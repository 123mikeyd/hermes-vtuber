# Phase 4 (Part 1) — Mood-Tagged Idle Motion Pools

**Status:** Server-side pool mapping + `mood_update` WebSocket emission SHIPPED.
**Remaining for Phase 4:** Frontend handler (intercept `mood_update`,
swap idle pool); `listening_state` emission (VAD-triggered); basic
frontend integration testing.

**Part of:** [Personality Evolution Plan](../.hermes/plans/2026-04-17_personality-evolution.md)
**Verification:** Live WebSocket test shows `mood_update` arriving
correctly with quadrant, snapshot, and motion pool per turn.

---

## What this phase delivers

After every assistant turn, if persona v2 is active, the server now
emits a `mood_update` WebSocket message. The message carries:

- `quadrant`: current mood quadrant (`calm` / `tired` / `excited` /
  `focused` / `listening`)
- `pool`: ordered list of motion filenames the frontend should draw
  random idles from while in this quadrant
- `pools`: full mapping of all five quadrants → motion lists (frontend
  can cache locally to switch quadrants without round-trips)
- `snapshot`: full 4-dim mood vector plus the plain-English description
- `model_name`: which Live2D model the pools apply to

Plus mood is now classified TWICE per turn: once from the user's
message alone BEFORE hermes fires (so the character "reads the room"
and has updated mood in its system prompt), and again from the full
exchange AFTER the response. Pre-turn delta is applied at half weight
so it doesn't saturate the vector.

---

## Pool mapping (hermes_dark, per user direction)

| quadrant  | motions                                                                     |
|-----------|-----------------------------------------------------------------------------|
| calm      | idle_arms_down, idle_calm, look_aside                                        |
| tired     | creeper_!, **idle_tired_droop (new, authored)**                              |
| excited   | Laughing_Test, Come on down                                                  |
| focused   | idle_calm_02, **idle_focused_lean (new, authored)**                          |
| listening | Wonder, Wonder_full                                                          |

- `creeper_!` was classified as `tired` ("the sluggish one" per user)
- `Wonder` / `Wonder_full` reserved for `listening`, NOT used as idle
- `Come on down` classified as `excited` (high energy gesture)
- Every pool has ≥2 motions and ≥8 seconds of unique looping material
- **2 new motions authored programmatically** to round out thin pools
  (`idle_tired_droop.motion3.json`, `idle_focused_lean.motion3.json`)
  — see `scripts/author_phase4_motions.py`. Both are simple 10-second
  loops with no arm-layer changes, designed to be replaced by
  hand-rigged motions later without breaking any interfaces.

---

## Hysteresis thresholds (shipped in earlier Phase 3 fix-up)

Two-level gates prevent quadrant flicker:

```
excited:  enter @ energy >= 0.55,  stay while >= 0.25
focused:  enter @ energy >= 0.55 AND focus >= 0.5,  stay lower
tired:    enter @ energy <= -0.35 AND valence <= -0.10,  stay lower
calm:     default fallback
```

With `MOOD_UPDATE_WEIGHT = 0.3` and per-sentence deltas capped at about
±0.9, a single strong sentence can't flip quadrants (baseline 0.1 + 0.27
= 0.37 < 0.55 enter threshold). Takes two strong sentences minimum.

Decay half-life is 240 seconds (4 minutes), so mood persists into the
next exchange after short breaks but fades if the conversation stops.

---

## Files

| path                                                         | role                                                   |
|--------------------------------------------------------------|--------------------------------------------------------|
| `src/open_llm_vtuber/persona/pool_map.py`                    | `PoolMap` dataclass, registry, resolve fallback logic. |
| `src/open_llm_vtuber/persona/mood.py`                        | Added hysteresis constants + stateful `quadrant()`.    |
| `src/open_llm_vtuber/agent/agents/hermes_agent.py`           | Added pre-turn classification; post-turn calls `quadrant()` before save. |
| `src/open_llm_vtuber/conversations/single_conversation.py`   | Added `_maybe_emit_mood_update` helper; invoked after `store_message`. |
| `live2d-models/hermes_dark/runtime/motion/idle_tired_droop.motion3.json` | New programmatic motion — tired pool.  |
| `live2d-models/hermes_dark/runtime/motion/idle_focused_lean.motion3.json` | New programmatic motion — focused pool. |
| `scripts/author_phase4_motions.py`                           | Motion authoring helper (idempotent, overwrites).      |

---

## How to verify

```bash
cd /home/mikeyd/Open-LLM-VTuber
python3 -u run_server.py
```

Then connect a WebSocket client and send a `text-input` message. After
the server synthesizes Nova's response, **and after the client replies
with `frontend-playback-complete`**, the server emits a `mood_update`.

Observed live test:
```
-> Tell me a joke.
[+9.8s] synth complete
[+9.8s] MOOD_UPDATE:
  quadrant: focused
  snapshot: v=+0.45 e=+0.30 s=+0.56 f=+0.59
  description: "in a good mood, alert, very open and chatty,
                sharp and dialed-in"
  pool (2):
    - motion/idle_calm_02.motion3.json
    - motion/idle_focused_lean.motion3.json
```

---

## Gotcha discovered during testing

Test harnesses that connect with `websockets.connect()` and don't send
`frontend-playback-complete` back after `backend-synth-complete` will
cause the server to block waiting forever in `finalize_conversation_turn`,
then cancel the whole chain when the client disconnects. When that
happens, `mood_update` never fires because `store_message` never gets
called.

Real browsers handle this automatically. Test scripts must emulate it:

```python
if msg["type"] == "backend-synth-complete":
    await ws.send(json.dumps({"type": "frontend-playback-complete"}))
```

Documented in `scripts/verify_phase1_ipc.py` style test files for
future phases.

---

## What's NOT shipped yet in Phase 4

1. **Frontend handler** — the frontend currently receives `mood_update`
   messages but does nothing with them (no log, no pool swap). Needs
   JavaScript patch to the compiled frontend (or source rebuild of the
   frontend submodule) to intercept the message and override the idle
   randomizer.
2. **Listening state emission** — VAD already detects user speech
   start/end in the server; we just haven't wired it to emit a
   `listening_state` WebSocket message yet.
3. **Micro-behaviors** — deferred to Phase 4.5 per plan.

These will land in a follow-up commit. The server-side foundation is
complete; the remaining work is frontend consumption.

---

## Credit

`creeper_!`, `Wonder`, `Wonder_full`, `Come on down` are motion files
authored by the user for the hermes_dark model. `idle_tired_droop` and
`idle_focused_lean` are placeholders authored programmatically by
Hermes Agent using the motion3.json bezier format; they're expected to
be replaced by hand-rigged versions later.
