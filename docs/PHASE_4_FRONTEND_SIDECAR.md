# Phase 4 (Part 2) — Frontend Sidecar + Listening State

**Status:** SHIPPED. Phase 4 is now complete end-to-end.
**Part of:** [Personality Evolution Plan](../.hermes/plans/2026-04-17_personality-evolution.md)
**Files:**
 - `sidecars/mood-sidecar.js` — the sidecar source of truth
 - `patches/frontend-mood-sidecar.patch` — index.html patch
 - `src/open_llm_vtuber/websocket_handler.py` — listening_state emission

---

## What landed in Part 2

Phase 4 Part 1 (already shipped) gave the server side: `mood_update`
messages with quadrant + pool emitted after each turn. Part 2 wires
the frontend to ACT on those messages, plus adds the `listening_state`
signal so the avatar plays Listening motions while the user is talking.

### 1. The sidecar (`sidecars/mood-sidecar.js`)

A standalone vanilla-JS file that loads BEFORE the React bundle. It:

 1. Monkey-patches `window.WebSocket` so it observes inbound messages
    on whatever connection React opens.
 2. Tracks current quadrant + listening state + per-quadrant motion
    pools (with full-mapping cache so quadrant flips don't need
    server round-trips).
 3. Polls the loaded Live2D model every 1.5 seconds. When the SDK's
    current motion finishes, it picks the next motion from the
    active pool (listening overrides quadrant when listening is on)
    and starts it directly via `model.startMotion(group, index, 2)`.
 4. Round-robins within the pool so all motions get airtime.
 5. Logs every state change with a `[mood-sidecar]` console badge.

**Failure mode:** if anything goes wrong, the SDK's default Idle
randomizer keeps running. Nova never freezes or goes silent because
of the sidecar. Defense-in-depth: try/catches around all model access,
graceful degradation when the model isn't loaded yet.

### 2. The index.html patch (`patches/frontend-mood-sidecar.patch`)

The `frontend/` directory in OLLV is a git submodule pointing at
`Open-LLM-VTuber/Open-LLM-VTuber-Web`. We can't commit changes
directly to it — they would be wiped on the next `git submodule update`.

Solution: ship the surgical edit as a `.patch` file in our repo.
Users (or our installer) apply it with:

```bash
cd ${OLLV_DIR}/frontend && \
  patch -p1 < ${HERMES_VTUBER}/patches/frontend-mood-sidecar.patch
cp ${HERMES_VTUBER}/sidecars/mood-sidecar.js \
   ${OLLV_DIR}/frontend/mood-sidecar.js
```

The patch adds one `<script src="./mood-sidecar.js"></script>` tag
in the head of `index.html`, BEFORE the main bundle script. That
ordering is load-bearing — the sidecar's WebSocket intercept must
be installed by the time React opens its connection.

### 3. `listening_state` server emission

Two new emissions in `websocket_handler._handle_raw_audio_data()`:

 - When VAD detects voice activity (audio_bytes > 1024 threshold),
   send `{type: "listening_state", active: true}` BEFORE the existing
   `mic-audio-end` control message, then `{active: false}` AFTER.
 - When VAD detects an interrupt (`<|PAUSE|>`), also send
   `{type: "listening_state", active: true}` so the avatar reacts
   immediately to the user starting to talk over Nova.

The sidecar de-dupes redundant signals on its end, so the server can
emit liberally without flooding the frontend with motion changes.

---

## How it all fits together

```
USER speaks -----------------------------+
                                         v
SERVER VAD detects voice -> WebSocket: listening_state(true)
                                         v
SIDECAR: switch active pool to "listening"
SIDECAR: next idle pick will come from listening pool (Wonder, Wonder_full)
                                         v
USER stops speaking -> mic-audio-end -> listening_state(false)
                                         v
SIDECAR: revert to quadrant pool
                                         v
SERVER: hermes generates response, mood classifier updates vector
SERVER: TTS streams audio chunks
SERVER: backend-synth-complete + frontend-playback-complete handshake
SERVER: store_message() -> _maybe_emit_mood_update -> WebSocket: mood_update
                                         v
SIDECAR: receives new pool list, updates state.pools, logs transition
SIDECAR: when current Talk motion finishes, next idle picked from new pool
```

End-to-end:
 - User speech → Listening pool plays (engaged "I hear you" motions)
 - Nova response → Talk motion plays (SDK auto)
 - After Nova finishes → idle from current quadrant pool
 - Mood drifts over conversation → quadrant changes → next idle from
   new pool

---

## Verification

Server-side (already covered in Phase 4 Part 1 docs):
```bash
cd /home/mikeyd/Open-LLM-VTuber && python3 -u run_server.py
# Then run the WebSocket test from PHASE_4_IDLE_POOLS.md
```

Sidecar JS parsing:
```bash
node -e "const fs = require('fs'); new Function(fs.readFileSync('sidecars/mood-sidecar.js', 'utf-8'))"
```

Sidecar served correctly:
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:12393/mood-sidecar.js
# Expect: 200
curl -s http://localhost:12393/index.html | grep -c "mood-sidecar.js"
# Expect: 1
```

In a real browser: open DevTools → Console. Expect to see:
```
[mood-sidecar] WebSocket intercept installed
[mood-sidecar] idle override polling started (every 1500ms)
[mood-sidecar] initialized — waiting for first mood_update from server
```
After the first turn:
```
[mood-sidecar] mood update (no quadrant change, still calm) "Your current state: ..."
[mood-sidecar] started Idle[1] = motion/idle_calm.motion3.json (quadrant=calm)
```

`window.__moodSidecar` is exposed for live debugging:
```js
window.__moodSidecar.state           // current quadrant, pools, etc
window.__moodSidecar.pickNextMotion()  // dry-run pool selection
window.__moodSidecar.forceStart()      // immediately try to swap
window.__moodSidecar.disable()         // kill switch
window.__moodSidecar.enable()          // resume
```

---

## Known limitations

1. **Polling, not event-driven.** The sidecar polls every 1.5s for
   motion-finished state because the SDK doesn't expose an
   `onFinished` event we can subscribe to from outside. Worst-case
   latency between SDK finishing and us starting the next is 1.5s.
   Cheap to dial down if it feels laggy.

2. **No mid-motion override.** We let the current motion finish before
   picking the next from the (possibly new) pool. Mood transitions
   therefore cross-fade across ~5-10 second idle boundaries, not
   instantly. This is INTENTIONAL — interrupting mid-motion looks
   jarring.

3. **Talk motions still come from the SDK.** When TTS audio plays,
   the SDK fires `startRandomMotion("Talk", PriorityNormal)` from
   the model3.json's Talk group. The sidecar doesn't override Talk
   motions — those continue to be picked by the existing logic.
   Phase 5 (continuous expression) would be the place to add
   mood-aware Talk motion selection if we want it.

4. **`listening_state` signal can be noisy.** VAD fires the voice-
   activity threshold on every chunk that exceeds the audio level,
   not once per utterance. The sidecar de-dupes on its end (only
   logs when `isListening` actually changes) so the perceptual
   behavior is correct, but the wire traffic is chattier than
   strictly necessary. Could be optimized later by adding a
   debouncer in the server.

---

## Credit

The sidecar approach (load BEFORE the main bundle, monkey-patch
`window.WebSocket`) is borrowed from a long line of browser-extension
and analytics-injection patterns. Specifically the `WebSocket`
prototype intercept idiom shows up in performance-monitoring tools
and Chrome extension wrappers. Nothing novel — just wiring a known
pattern into our stack.

The Cubism SDK's `getLive2DManager().getModel(0)` debug surface is
documented in the OLLV skill notes (which we wrote in earlier
sessions when building the editor). That's what makes direct
`startMotion` calls possible without forking the bundle.
