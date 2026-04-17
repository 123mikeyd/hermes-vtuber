# Phase 5 — Continuous Per-Sentence Expression

**Status:** Shipped on branch `leaf`
**Part of:** [Personality Evolution Plan](../.hermes/plans/2026-04-17_personality-evolution.md)
**Verification:** `scripts/verify_phase5_expression.py`

---

## What this phase delivers

Every sentence in Nova's response is now classified for affect IN
PARALLEL with the TTS pipeline, and the resulting "expression blend"
streams to the frontend BEFORE the audio plays. The sidecar interprets
the blend as parameter deltas and applies them with a triangle-wave
envelope (0 → peak → 0) over the sentence's duration. Result: Nova's
face moves WITH her speech, not as discrete pose snaps but as smooth
continuous parameter shifts riding on top of the motion playback.

This replaces the keyword-tag system (`[happy]`, `[sad]`) which only
allowed one hard pose at a time. The new path is multi-axis,
intensity-aware, and mood-modulated.

---

## How it works

### 1. Server-side: per-sentence inference

`src/open_llm_vtuber/persona/expression_inference.py`

5-axis affect blend, lexicon-driven (same philosophy as
`mood_classifier.py` — speed, explainability, zero deps):

  - `joy`        — positive emotion, smile mouth, raised brows
  - `sadness`    — drooped brows, downturned mouth, lower lids
  - `anger`      — lowered/sharp brows, slight pursed mouth
  - `surprise`   — raised brows, wider eyes, mouth open
  - `shy_blush`  — `PARAM_TERE` blush, gaze drops, soft mouth

Punctuation modifies axes: `!` boosts `surprise` plus whatever's
already firing, `?` adds curiosity-surprise, `...` adds
sadness/shyness, ALL-CAPS shouts add anger or excitement.

Each axis is capped at 0.9 individually (`SINGLE_AXIS_CAP`) and the
total magnitude across all 5 is L1-normalized to 1.2
(`TOTAL_BLEND_CAP`) so a sentence with words in many lexicons doesn't
saturate every parameter.

### 2. Server-side: blend → Live2D parameter map

`expression_inference.PARAM_MAP` is the lookup that turns each
affect axis into a list of `(param_id, max_delta)` tuples.
`blend_to_param_deltas()` aggregates them, supporting overlapping
axes (joy + surprise both lift brows → SUM, then clamp).

Final clamp is ±0.5 per parameter so even maxed-out aggregate blends
can't push the face off-model. Motions remain the dominant driver
of pose — expression deltas are layered on TOP via Cubism's
`addParameterValueById` (frontend side).

### 3. Server-side: emission per sentence

`src/open_llm_vtuber/conversations/conversation_utils.py`
(`handle_sentence_output`)

For every sentence yielded by the agent's `sentence_divider`, BEFORE
calling `tts_manager.speak()`:

```python
from ..persona import build_expression_message
blend_msg = build_expression_message(tts_text, valence=None)
if blend_msg.get("blend") and any(blend_msg["blend"].values()):
    await websocket_send(json.dumps(blend_msg))
```

Best-effort try/except like all other persona code paths — a
classifier hiccup never blocks Nova's actual speech.

Wire format:
```json
{
  "type": "expression_blend",
  "blend": {"joy": 0.3, "sadness": 0, "anger": 0, "surprise": 0.5, "shy_blush": 0},
  "deltas": {"PARAM_MOUTH_FORM": 0.27, "PARAM_BROW_L_Y": 0.21, ...},
  "duration_ms": 600,
  "reason": "j:1,u:1 !1"
}
```

### 4. Client-side: triangle envelope blending

`sidecars/mood-sidecar.js` (`handleExpressionBlend`,
`applyActiveBlend`, frame loop)

When an `expression_blend` arrives, the sidecar stores it as
`activeBlend` with start time. A `requestAnimationFrame` loop calls
`applyActiveBlend()` every frame, computing a triangle envelope:

```
t=0     -> envelope = 0
t=300ms -> envelope = 1.0  (full intensity)
t=600ms -> envelope = 0    (faded back out)
```

Each parameter is set via `model.addParameterValueById(paramId,
delta * envelope)`, which ADDS the value on top of whatever the
motion has already set this frame. Cubism handles the per-frame
parameter fight cleanly with this additive API.

If a NEW blend arrives mid-envelope (sentences are usually faster
than TTS), the new blend REPLACES the old one — most recent affect
wins. No queueing, no overlap.

---

## Mood baseline modulation

`blend_to_param_deltas(blend, valence=...)` accepts an optional
`valence` from MoodState in [-1, 1]. When provided:

  - **Joy** axis is scaled by `max(0, (1 + valence) / 2)`. A character
    at valence -1 cannot show joy at all (scale = 0). At valence 0,
    joy is half-strength. At valence +1, full joy.
  - **Sadness** axis is scaled inversely (capped at 1.0). High-valence
    Nova can still express sadness when context demands it — just not
    quite at full intensity. A low-valence Nova hits sadness hard.

This is the "sad-mood character's happy never reaches 1.0" rule from
the original plan, mechanized.

**NOTE for Phase 5.1**: the conversation_utils.py emission currently
passes `valence=None` because the mood vector lives on the agent
object and isn't easily accessible from that layer. Phase 5.1 would
plumb it through by adding a `mood_snapshot` field to the
SentenceOutput type. Not blocking — the inference and clamp logic
already work; we just don't yet bias by mood at the wire.

---

## Verification

```bash
cd /home/mikeyd/hermes-vtuber
python3 scripts/verify_phase5_expression.py
```

Seven tests, all must pass:

1. Lexicon hits in joy/sadness/anger/surprise/shy_blush sentences
2. Neutral sentences produce magnitude < 0.5
3. Punctuation modifiers fire the right axes (!, ?, ..., CAPS)
4. blend → params produces sensible Live2D deltas; aggregate clamps at ±0.5
5. Mood baseline modulates: valence -1.0 → joy delta = 0; valence +1.0 → full
6. `build_expression_message` returns wire-ready JSON
7. **LIVE**: server actually emits expression_blend per sentence over WebSocket

Live test confirmed: Nova's response "Why don't open-source developers
ever play hide and seek? Because good luck hiding when your whole commit
history is public." → 3 expression_blend messages, one per sentence.

Phase 1 + 2a + 3 verifications still pass — no regression.

---

## Browser debug surface

`window.__moodSidecar` extended with:

```js
window.__moodSidecar.activeBlend       // current blend or null
window.__moodSidecar.triggerExpression({  // manual fire for testing
  blend: {joy: 0.8},
  deltas: {PARAM_MOUTH_FORM: 0.3, PARAM_BROW_L_Y: 0.1},
  duration_ms: 1500,
  reason: 'manual test'
})
```

Open DevTools → Console while talking to Nova:
```
[mood-sidecar] expression: j:1,u:1 !1, intensity 0.62, params PARAM_MOUTH_FORM,PARAM_BROW_L_Y,PARAM_BROW_R_Y,PARAM_EYE_L_OPEN,PARAM_EYE_R_OPEN
```

---

## What this DOESN'T ship

1. **Expression keyword tags** (`[happy]`, `[sad]`, etc.) — still
   processed by the existing `live2d_expression_prompt.txt` system
   independently. Both layers coexist; neither blocks the other.
   Probably worth removing the old keyword tag prompt entirely in
   a follow-up since the new path covers the same use case better.

2. **Server passes valence to blend_to_param_deltas.** As noted above,
   the wire currently doesn't carry mood-modulated intensity. Tests
   prove the modulation works in-process; piping it through is a
   small Phase 5.1.

3. **Per-sentence translation interaction.** If a translation engine
   is configured, we infer expression on the TRANSLATED text, not the
   original. Lexicons are English-only. For non-English deployments,
   Phase 5 is essentially neutral. Noted for future.

4. **TTS prosody coupling.** TTS already varies speech pitch/speed
   somewhat by punctuation. Our visual expression doesn't synchronize
   to the actual audio waveform — it runs on a fixed 600ms triangle.
   Phase 5.1 could read TTS duration metadata and stretch the envelope
   to match; not blocking.

---

## Limitations and known gotchas

1. **English-only lexicons.** Documented. See above.

2. **Triangle envelope is fixed-width.** A 50-character sentence and
   a 5-character "Yeah." get the same 600ms envelope. This is fine
   in practice because the TTS audio is typically longer than 600ms
   anyway, so the envelope completes during the speech window.

3. **Frame loop runs always.** Even when no expression is active,
   the requestAnimationFrame loop ticks every frame and checks
   `activeBlend`. Cost: one function call + null check per frame. If
   you see CPU spikes in `__moodSidecar.activeBlend` reads, that's
   the cause; mitigation would be to start/stop the loop on demand,
   but for now the simplicity is worth the negligible cost.

4. **Param mapping is hermes_dark-tuned.** Other models (mao_pro,
   shizuku) use different parameter ID conventions. The deltas will
   silently no-op against a model that doesn't have these params,
   so nothing breaks — but the visual effect won't appear. Per-model
   `PARAM_MAP` overrides are a Phase 5.1 nicety.

---

## Credit

The 5-axis affect model is loosely inspired by Ekman's basic emotion
families (joy, sadness, anger, surprise — plus we add shy_blush which
isn't Ekman but is essential for anime-style avatars). The
triangle-wave envelope shape is the simplest non-snappy interpolation
that reads as "natural"; could be replaced by a cosine ease-in-out
later for slightly smoother transitions.

Live2D's `addParameterValueById` (the additive setter) is the
critical SDK API that lets motion + expression layer on the same
parameters without one stomping the other. Documented in the
Cubism Web Framework but rarely used in tutorials.
