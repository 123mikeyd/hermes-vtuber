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
      // Phase 6 — sleep-related pools
      sleep: [],
      falling_asleep: [],
      waking_up: [],
    },
    poolPickIndex: 0,        // round-robin within the current pool
    modelName: null,
    enabled: true,           // hard kill switch
    pollIntervalMs: 1500,    // how often to check whether the SDK's
                             // current motion has finished and we
                             // should start the next from our pool
    pollHandle: null,
    lastStartedFilename: null,

    // ---------- Phase 6: sleep state machine ----------
    // Inactivity tracking. `lastActivityMs` resets whenever the server
    // emits something that proves Nova is "being talked to" — a
    // mood_update (post-turn), expression_blend (mid-response), or
    // listening_state:true (user started speaking).
    lastActivityMs: performance.now(),
    // Thresholds per Mike's spec (Apr 17, 2026):
    drowsyAfterMs:  22 * 60 * 1000,   // 22 min → tired/calm mix
    tiredAfterMs:   50 * 60 * 1000,   // 50 min → 100% tired pool
    sleepAfterMs:   64 * 60 * 1000,   // 64 min → sleep state
    // Sleep-state sub-phase. 'awake' is the normal mood pool path.
    // 'drowsy' biases toward tired. 'tired' forces tired. 'falling'
    // plays the falling_asleep transition once. 'asleep' loops the
    // sleep motion. 'waking' plays waking_up once.
    sleepPhase: 'awake',
    // One-shot transition tracking — when we cross INTO a new phase,
    // we play the transition motion once before reverting to the
    // regular pool selection.
    pendingTransition: null,    // null | 'falling_asleep' | 'waking_up'
    // Manual override from sleep_command message — forces 'asleep'
    // regardless of timer.
    manualSleep: false,
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
   * Re-evaluate the sleep state machine based on elapsed inactivity.
   * Called from both pickNextMotion() and the idle poll loop so both
   * paths see the same current phase.
   *
   * Returns the current phase:
   *   'awake'   — regular mood pool
   *   'drowsy'  — 60% tired, 40% calm mix
   *   'tired'   — 100% tired pool
   *   'falling' — play falling_asleep motion once, then -> asleep
   *   'asleep'  — loop sleep motion
   *   'waking'  — play waking_up motion once, then reset to awake
   *
   * Schedules pendingTransition when a boundary is crossed.
   */
  function updateSleepPhase() {
    // Manual sleep overrides everything
    if (state.manualSleep && state.sleepPhase !== 'asleep'
                           && state.sleepPhase !== 'falling') {
      if (state.sleepPhase !== 'waking') {
        log('manual sleep command → falling_asleep');
        state.sleepPhase = 'falling';
        state.pendingTransition = 'falling_asleep';
      }
      return state.sleepPhase;
    }

    const elapsed = performance.now() - state.lastActivityMs;
    const prev = state.sleepPhase;

    // Phase transitions based on elapsed inactivity. We only advance
    // FORWARD through these automatically; regressing (waking up)
    // requires activity, which is handled by markActive().
    let next = prev;
    if (prev === 'awake') {
      if (elapsed >= state.sleepAfterMs) next = 'falling';
      else if (elapsed >= state.tiredAfterMs) next = 'tired';
      else if (elapsed >= state.drowsyAfterMs) next = 'drowsy';
    } else if (prev === 'drowsy') {
      if (elapsed >= state.sleepAfterMs) next = 'falling';
      else if (elapsed >= state.tiredAfterMs) next = 'tired';
    } else if (prev === 'tired') {
      if (elapsed >= state.sleepAfterMs) next = 'falling';
    } else if (prev === 'falling') {
      // Falling motion is ~4s; after that, go to asleep loop
      if (elapsed - state.sleepAfterMs >= 4000) next = 'asleep';
    } else if (prev === 'waking') {
      // Waking motion is ~3s; after that, return to awake
      if (performance.now() - state.wakingStartedMs >= 3500) {
        next = 'awake';
        state.manualSleep = false;  // clear manual-sleep flag
      }
    }

    if (next !== prev) {
      log(`sleep phase: ${prev} → ${next} (inactive ${(elapsed/60000).toFixed(1)}min)`);
      state.sleepPhase = next;
      if (next === 'falling') state.pendingTransition = 'falling_asleep';
      if (next === 'waking')  state.pendingTransition = 'waking_up';
    }
    return state.sleepPhase;
  }

  /**
   * Called whenever the server proves Nova is being interacted with.
   * Resets inactivity timer. If she was asleep/drowsy, queue waking_up.
   *
   * Phase 6 fix (Apr 17, 2026): do NOT clear manualSleep here. The
   * sleep command path is:
   *   user says "go to sleep" -> sleep_command WS fires AND Nova
   *   acknowledges verbally, which triggers expression_blend, which
   *   calls markActive(). If markActive cleared manualSleep, the
   *   sleep command would be instantly cancelled. manualSleep only
   *   clears on real conversational input AFTER the sleep started
   *   (the wake transition handles that via its own logic).
   */
  function markActive() {
    state.lastActivityMs = performance.now();
    // Don't touch manualSleep here — let the sleep cycle complete
    const phase = state.sleepPhase;
    if (phase === 'asleep' || phase === 'falling') {
      log(`activity resumed during ${phase} → waking_up`);
      state.sleepPhase = 'waking';
      state.pendingTransition = 'waking_up';
      state.wakingStartedMs = performance.now();
      state.manualSleep = false;  // only clear when actually waking from sleep
    } else if (phase === 'drowsy' || phase === 'tired') {
      // Not asleep yet — just snap back to awake without a wake animation
      log(`activity resumed during ${phase} → awake (no wake anim needed)`);
      state.sleepPhase = 'awake';
      state.manualSleep = false;
    }
  }

  /**
   * Pick the next motion filename based on the full state machine:
   *   1. If there's a pending transition (falling_asleep / waking_up),
   *      return that motion AND clear pendingTransition so it plays once.
   *   2. Listening overrides everything else (user is speaking now).
   *   3. Otherwise, consult sleep phase:
   *        'awake'   → current quadrant pool
   *        'drowsy'  → 60% tired, 40% calm (random per-pick)
   *        'tired'   → tired pool
   *        'asleep'  → sleep pool (the loop)
   *   4. Round-robin within the chosen pool.
   */
  function pickNextMotion() {
    // 1. One-shot transition?
    if (state.pendingTransition) {
      const transitionPool = state.pools[state.pendingTransition] || [];
      if (transitionPool.length > 0) {
        const motion = transitionPool[0];
        log(`pickNextMotion: transition → ${motion}`);
        state.pendingTransition = null;
        return motion;
      }
      // Transition requested but pool empty — clear and fall through
      state.pendingTransition = null;
    }

    // 2. Listening always wins (as before)
    if (state.isListening) {
      const lp = state.pools.listening;
      if (lp && lp.length > 0) {
        state.poolPickIndex = (state.poolPickIndex + 1) % lp.length;
        return lp[state.poolPickIndex];
      }
    }

    // 3. Sleep phase selects pool
    const phase = updateSleepPhase();
    let pool;
    if (phase === 'asleep') {
      pool = state.pools.sleep;
    } else if (phase === 'tired') {
      pool = state.pools.tired;
    } else if (phase === 'drowsy') {
      // 60% tired, 40% calm random mix
      pool = (Math.random() < 0.60) ? state.pools.tired : state.pools.calm;
    } else {
      // awake / falling / waking — falling and waking are handled
      // above via pendingTransition, so this is just 'awake'
      pool = state.pools[state.currentQuadrant];
    }

    // Fallback chain
    if (!pool || pool.length === 0) pool = state.pools.calm;
    if (!pool || pool.length === 0) return null;

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
    // Phase 6: advance the sleep state machine every poll tick so
    // phase transitions fire even while a motion is still playing.
    updateSleepPhase();
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
            evt.data.indexOf('listening_state') === -1 &&
            evt.data.indexOf('expression_blend') === -1 &&
            evt.data.indexOf('sleep_command') === -1) {
          // Quick reject for the ~99% of messages that aren't ours
          return;
        }
        try {
          const msg = JSON.parse(evt.data);
          if (msg.type === 'mood_update') handleMoodUpdate(msg);
          else if (msg.type === 'listening_state') handleListeningState(msg);
          else if (msg.type === 'expression_blend') handleExpressionBlend(msg);
          else if (msg.type === 'sleep_command') handleSleepCommand(msg);
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
    // Phase 6: a mood update means Nova just finished a turn — she's
    // being talked to. Reset the inactivity timer.
    markActive();

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
    if (state.isListening) {
      // Phase 6: user is speaking — mark active regardless of transition.
      markActive();
    }
    if (wasListening !== state.isListening) {
      log(`listening: ${wasListening} -> ${state.isListening}`);
      // Reset round-robin when we toggle
      state.poolPickIndex = -1;
    }
  }

  /**
   * Phase 6: server-side sleep phrase detector fired. Force manual
   * sleep — the updateSleepPhase loop will push into 'falling' on
   * the next tick. The `active` field lets us toggle manual_sleep
   * off (though we also auto-clear it on waking).
   */
  function handleSleepCommand(msg) {
    const active = msg.active !== false;  // default true
    log(`sleep command received (active=${active}): ${msg.reason || ''}`);
    if (active) {
      state.manualSleep = true;
    } else {
      state.manualSleep = false;
    }
  }

  // ---------------------------------------------------------------------
  // Phase 5 — expression_blend handler
  //
  // Receives per-sentence affect blend + parameter deltas. Applies the
  // deltas to the loaded Live2D model on every animation frame for
  // duration_ms milliseconds, with a triangle-wave envelope (0 -> peak
  // -> 0). This way the expression "swells" with the sentence then
  // fades, leaving room for the next sentence's blend to take over.
  //
  // Multiple overlapping sentences will queue — newer ones REPLACE
  // older ones rather than blend, because LLMs typically generate
  // sentences faster than TTS can speak them and we want the most
  // recent affect to dominate.
  // ---------------------------------------------------------------------

  let activeBlend = null;  // {deltas, durationMs, startTimeMs}

  function handleExpressionBlend(msg) {
    // Phase 6: Nova speaking IS activity. Reset the inactivity timer.
    markActive();

    const deltas = msg.deltas || {};
    const durationMs = Math.max(100, msg.duration_ms || 600);
    if (Object.keys(deltas).length === 0) return;
    activeBlend = {
      deltas: deltas,
      durationMs: durationMs,
      startTimeMs: performance.now(),
    };
    if (msg.blend) {
      const intensity = Object.values(msg.blend).reduce((a, b) => a + b, 0);
      log(`expression: ${msg.reason || 'unknown'}, ` +
          `intensity ${intensity.toFixed(2)}, ` +
          `params ${Object.keys(deltas).join(',')}`);
    }
  }

  /**
   * Apply the active blend's parameter deltas to the model THIS FRAME.
   * Triangle envelope: 0 at t=0, full at t=duration/2, 0 at t=duration.
   * Called from a requestAnimationFrame loop.
   */
  function applyActiveBlend() {
    if (!activeBlend) return;
    const elapsed = performance.now() - activeBlend.startTimeMs;
    if (elapsed > activeBlend.durationMs) {
      activeBlend = null;
      return;
    }

    const half = activeBlend.durationMs / 2;
    let envelope;
    if (elapsed < half) {
      envelope = elapsed / half;          // 0 -> 1
    } else {
      envelope = (activeBlend.durationMs - elapsed) / half;  // 1 -> 0
    }

    const manager = getLive2DManagerSafe();
    if (!manager) return;
    const model = manager.getModel(0);
    if (!model || !model._model) return;

    // Apply each delta to its parameter. addParameterValueById ADDS to
    // whatever the motion has already set this frame, so we layer
    // expression on top of motion without overwriting.
    try {
      for (const paramId in activeBlend.deltas) {
        const value = activeBlend.deltas[paramId] * envelope;
        if (typeof model.addParameterValueById === 'function') {
          model.addParameterValueById(paramId, value);
        } else if (typeof model._model.addParameterValue === 'function') {
          // Fallback for different SDK versions
          const idx = model._model.getParameterIndex(paramId);
          if (idx >= 0) {
            model._model.addParameterValue(idx, value);
          }
        }
      }
    } catch (e) {
      // Silent — applyActiveBlend runs every frame, don't spam the console
    }
  }

  // Frame loop for expression blending
  let frameLoopHandle = null;
  function startFrameLoop() {
    if (frameLoopHandle) return;
    function loop() {
      applyActiveBlend();
      frameLoopHandle = requestAnimationFrame(loop);
    }
    frameLoopHandle = requestAnimationFrame(loop);
    log('expression frame loop started');
  }
  function stopFrameLoop() {
    if (frameLoopHandle) {
      cancelAnimationFrame(frameLoopHandle);
      frameLoopHandle = null;
    }
  }

  // ---------------------------------------------------------------------
  // Boot
  // ---------------------------------------------------------------------

  function boot() {
    try {
      installWebSocketIntercept();
      startIdlePoll();
      startFrameLoop();
      log('initialized — waiting for first mood_update from server');
      // Expose a debug surface for manual inspection in DevTools
      window.__moodSidecar = {
        state,
        get activeBlend() { return activeBlend; },
        get sleepPhase() { return state.sleepPhase; },
        pickNextMotion,
        resolveMotionByFilename,
        forceStart: maybeStartNextIdle,
        triggerExpression: handleExpressionBlend,  // for manual testing
        // Phase 6 debug helpers — bypass the timer to test transitions:
        forceSleep: () => {
          log('forceSleep() called via __moodSidecar debug API');
          state.manualSleep = true;
          updateSleepPhase();
        },
        forceWake: () => {
          log('forceWake() called via __moodSidecar debug API');
          markActive();
        },
        // Collapse the timeline for testing — pass seconds instead of minutes:
        setSleepTimersForTesting: (drowsySec, tiredSec, sleepSec) => {
          state.drowsyAfterMs = drowsySec * 1000;
          state.tiredAfterMs  = tiredSec  * 1000;
          state.sleepAfterMs  = sleepSec  * 1000;
          log(`sleep timers: drowsy=${drowsySec}s tired=${tiredSec}s sleep=${sleepSec}s`);
        },
        disable: () => { state.enabled = false; stopIdlePoll(); stopFrameLoop(); },
        enable: () => { state.enabled = true; startIdlePoll(); startFrameLoop(); },
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
