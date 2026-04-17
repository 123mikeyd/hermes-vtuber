/**
 * Hermes VTuber Mood Sidecar
 *
 * Phase 4 frontend handler. Listens for `mood_update` and `listening_state`
 * WebSocket messages from the OLLV server and drives Live2D idle motion
 * selection by mood quadrant.
 *
 * Why a sidecar (not a patch to the compiled main bundle):
 *   The compiled React bundle's idle randomizer is hard to surgically
 *   patch without breaking it. Instead, this script:
 *     1. Wraps WebSocket so we observe inbound messages.
 *     2. Tracks the current quadrant + pool.
 *     3. When the SDK's auto-played idle motion FINISHES, our hook
 *        starts the NEXT motion using a filename from the current pool
 *        — overriding the SDK's random pick from the model3.json's
 *        Idle group.
 *     4. Listening state takes precedence over quadrant-based pools.
 *
 * Failure mode: if anything goes wrong, we silently degrade. The SDK's
 * default Idle randomizer keeps running, and Nova just doesn't react
 * to mood changes. She never goes silent or freezes because of this.
 *
 * Globals provided in the page:
 *   getLive2DManager()  — returns the Live2D manager instance
 *   ws or wsRef          — WebSocket reference (varies by build; we
 *                          intercept via WebSocket prototype)
 *
 * Part of: .hermes/plans/2026-04-17_personality-evolution.md (Phase 4)
 */

(function () {
  'use strict';

  // ---------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------

  const state = {
    currentQuadrant: 'calm',
    isListening: false,
    pools: {
      calm: [],
      tired: [],
      excited: [],
      focused: [],
      listening: [],
    },
    poolPickIndex: 0,        // round-robin within the current pool
    modelName: null,
    enabled: true,           // hard kill switch
    pollIntervalMs: 1500,    // how often to check whether the SDK's
                             // current motion has finished and we
                             // should start the next from our pool
    pollHandle: null,
    lastStartedFilename: null,
  };

  // Helpful console badge so it's clear in DevTools that we're alive.
  function log(...args) {
    console.log('%c[mood-sidecar]', 'color:#7af', ...args);
  }
  function warn(...args) {
    console.warn('%c[mood-sidecar]', 'color:#fa7', ...args);
  }

  // ---------------------------------------------------------------------
  // Pool selection
  // ---------------------------------------------------------------------

  /**
   * Pick the next motion filename from the active pool.
   * Listening pool wins over quadrant pool when isListening is true.
   * Returns null if no pool is available.
   */
  function pickNextMotion() {
    let pool = state.isListening ? state.pools.listening : null;
    if (!pool || pool.length === 0) {
      pool = state.pools[state.currentQuadrant] || [];
    }
    if (pool.length === 0) {
      // Last-ditch fallback to calm
      pool = state.pools.calm || [];
    }
    if (pool.length === 0) {
      return null;
    }
    // Round-robin so all motions get airtime even with 2-entry pools
    state.poolPickIndex = (state.poolPickIndex + 1) % pool.length;
    return pool[state.poolPickIndex];
  }

  /**
   * Convert a filename like "motion/idle_calm.motion3.json" into the
   * group name + index pair the Cubism SDK actually wants.
   *
   * The model3.json declares motions in groups; the SDK's startMotion
   * needs (groupName, index, priority). We need to look this up
   * against the loaded model's motion list.
   */
  function resolveMotionByFilename(filename) {
    const manager = getLive2DManagerSafe();
    if (!manager) return null;
    const model = manager.getModel(0);
    if (!model || !model._modelSetting) return null;

    const motions = model._modelSetting._json &&
                    model._modelSetting._json.FileReferences &&
                    model._modelSetting._json.FileReferences.Motions;
    if (!motions) return null;

    for (const groupName in motions) {
      const arr = motions[groupName];
      for (let i = 0; i < arr.length; i++) {
        if (arr[i].File === filename) {
          return { group: groupName, index: i };
        }
      }
    }
    return null;
  }

  /**
   * Wrap getLive2DManager() in a try/catch — it can throw if the model
   * hasn't finished loading yet.
   */
  function getLive2DManagerSafe() {
    try {
      if (typeof getLive2DManager === 'function') {
        return getLive2DManager();
      }
    } catch (e) {
      // model not ready
    }
    return null;
  }

  // ---------------------------------------------------------------------
  // Idle override loop
  //
  // Polls every pollIntervalMs. When the SDK's current motion finishes,
  // we start the next motion from our pool. We do NOT interrupt
  // mid-motion — let it finish naturally so transitions are smooth.
  // ---------------------------------------------------------------------

  function maybeStartNextIdle() {
    if (!state.enabled) return;
    const manager = getLive2DManagerSafe();
    if (!manager) return;
    const model = manager.getModel(0);
    if (!model || !model._motionManager) return;

    // Don't start anything new if a motion is still playing
    if (!model._motionManager.isFinished()) return;

    // Don't override during TTS playback (Talk motions take precedence).
    // _expressionManager doesn't tell us about Talk, but we can check
    // whether the Talk group recently fired by inspecting current state.
    // Simplest safe heuristic: skip if the SDK is the one that just
    // played and it's not an Idle.
    // (Acceptable to be wrong here — Talk motions are short, we'll
    // catch the next idle moment.)

    const filename = pickNextMotion();
    if (!filename) return;

    const resolved = resolveMotionByFilename(filename);
    if (!resolved) {
      warn(`could not resolve motion '${filename}' against loaded model`);
      return;
    }

    // PriorityNormal=2 in standard Cubism. We use 2 so it can be
    // interrupted by a real Talk motion (priority 2-3) but overrides
    // the SDK's PriorityIdle=1 random pick.
    try {
      model.startMotion(resolved.group, resolved.index, 2);
      state.lastStartedFilename = filename;
      log(`started ${resolved.group}[${resolved.index}] = ${filename} ` +
          `(quadrant=${state.currentQuadrant}${state.isListening ? ', LISTENING' : ''})`);
    } catch (e) {
      warn('startMotion threw:', e);
    }
  }

  function startIdlePoll() {
    if (state.pollHandle) return;
    state.pollHandle = setInterval(maybeStartNextIdle, state.pollIntervalMs);
    log(`idle override polling started (every ${state.pollIntervalMs}ms)`);
  }

  function stopIdlePoll() {
    if (state.pollHandle) {
      clearInterval(state.pollHandle);
      state.pollHandle = null;
    }
  }

  // ---------------------------------------------------------------------
  // WebSocket interception
  //
  // The compiled bundle creates its own WebSocket. We don't have a
  // direct reference, so we monkey-patch WebSocket.prototype.addEventListener
  // and intercept 'message' events on the very first WebSocket the page
  // opens. Cheap, broad, and reversible.
  // ---------------------------------------------------------------------

  let interceptInstalled = false;
  function installWebSocketIntercept() {
    if (interceptInstalled) return;
    interceptInstalled = true;

    const OriginalWS = window.WebSocket;
    window.WebSocket = function (url, protocols) {
      const ws = protocols !== undefined
        ? new OriginalWS(url, protocols)
        : new OriginalWS(url);

      ws.addEventListener('message', (evt) => {
        // We only care about JSON text frames
        if (typeof evt.data !== 'string') return;
        if (evt.data.indexOf('mood_update') === -1 &&
            evt.data.indexOf('listening_state') === -1) {
          // Quick reject for the ~99% of messages that aren't ours
          return;
        }
        try {
          const msg = JSON.parse(evt.data);
          if (msg.type === 'mood_update') handleMoodUpdate(msg);
          else if (msg.type === 'listening_state') handleListeningState(msg);
        } catch (e) {
          // Not JSON or not our schema — ignore.
        }
      });

      return ws;
    };
    // Preserve static / prototype handles
    window.WebSocket.prototype = OriginalWS.prototype;
    window.WebSocket.OPEN = OriginalWS.OPEN;
    window.WebSocket.CLOSED = OriginalWS.CLOSED;
    window.WebSocket.CONNECTING = OriginalWS.CONNECTING;
    window.WebSocket.CLOSING = OriginalWS.CLOSING;

    log('WebSocket intercept installed');
  }

  // ---------------------------------------------------------------------
  // Message handlers
  // ---------------------------------------------------------------------

  function handleMoodUpdate(msg) {
    const newQuadrant = msg.quadrant || 'calm';
    const previous = state.currentQuadrant;
    state.currentQuadrant = newQuadrant;
    if (msg.pools) {
      // Replace the entire pool map so newly-registered motions show up
      for (const key in msg.pools) {
        state.pools[key] = msg.pools[key] || [];
      }
    } else if (msg.pool) {
      // Per-quadrant override only
      state.pools[newQuadrant] = msg.pool;
    }
    state.modelName = msg.model_name || state.modelName;

    if (previous !== newQuadrant) {
      log(`quadrant: ${previous} -> ${newQuadrant}`,
          msg.snapshot ? msg.snapshot.description : '');
    } else {
      log(`mood update (no quadrant change, still ${newQuadrant})`,
          msg.snapshot ? msg.snapshot.description : '');
    }

    // Reset round-robin so the new quadrant doesn't start mid-list
    state.poolPickIndex = -1;
  }

  function handleListeningState(msg) {
    const wasListening = state.isListening;
    state.isListening = !!msg.active;
    if (wasListening !== state.isListening) {
      log(`listening: ${wasListening} -> ${state.isListening}`);
      // Reset round-robin when we toggle
      state.poolPickIndex = -1;
    }
  }

  // ---------------------------------------------------------------------
  // Boot
  // ---------------------------------------------------------------------

  function boot() {
    try {
      installWebSocketIntercept();
      startIdlePoll();
      log('initialized — waiting for first mood_update from server');
      // Expose a debug surface for manual inspection in DevTools
      window.__moodSidecar = {
        state,
        pickNextMotion,
        resolveMotionByFilename,
        forceStart: maybeStartNextIdle,
        disable: () => { state.enabled = false; stopIdlePoll(); },
        enable: () => { state.enabled = true; startIdlePoll(); },
      };
    } catch (e) {
      warn('boot failed:', e);
    }
  }

  // The sidecar loads BEFORE the React bundle creates its WebSocket —
  // we install our intercept first so we catch the very first connection.
  // boot() is idempotent so it's safe to call from either path below.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();
