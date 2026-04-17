# OLLV + Persona v2 — Integration Lessons Learned

Session-level gotchas from the Phase 1-4 implementation of the
persona-memory + mood pipeline. Skill update was blocked by a
security scanner on pre-existing (unrelated) files in the skill
directory — documenting here so future work doesn't re-learn these.

---

## `frontend-playback-complete` handshake IS REQUIRED

**Wasted time:** ~45 minutes debugging why `mood_update` WebSocket
messages never arrived during headless integration tests.

**Root cause:** `conversation_utils.finalize_conversation_turn()`
blocks waiting for the client to echo back a
`frontend-playback-complete` message after the `backend-synth-complete`
signal:

```python
# single_conversation.py line ~145
await finalize_conversation_turn(
    tts_manager=tts_manager,
    websocket_send=websocket_send,
    client_uid=client_uid,
)

# conversation_utils.py ~line 60
response = await message_handler.wait_for_response(
    client_uid, "frontend-playback-complete"
)
```

Real browsers send this automatically after audio playback completes.
Python test scripts MUST emulate it or the server blocks forever and
then cancels the whole conversation chain when the client disconnects.

**Symptom:** conversation appears finished (`backend-synth-complete`
observed in client), but no further messages arrive, and server log
shows `🤡👍 Conversation cancelled because interrupted` even though
no real interrupt occurred.

**Fix in test harness:**

```python
async for raw in ws:
    parsed = json.loads(raw)
    mt = parsed.get("type")
    if mt == "backend-synth-complete":
        # Emulate what the browser's audio-element onended does
        await ws.send(json.dumps({"type": "frontend-playback-complete"}))
    elif mt == "mood_update":
        # Now this will actually arrive
        ...
```

**Lesson:** Any WebSocket emission added AFTER the final TTS audio in
the conversation chain — `store_message`, `mood_update`, future
`listening_state` confirmations, etc. — needs this handshake or test
harnesses will silently fail.

---

## Motion3.json Segment Parsing — Type Matters

**Wasted time:** ~15 minutes chasing a false-positive "opacity > 1.0"
bug that didn't exist.

**Root cause:** Cubism motion3.json `Curves[].Segments` is a flat
array of floats where each segment's byte-size depends on its type
code:

```
Segment type codes:
  0 = linear       [type, time, value]                         — 3 floats
  1 = bezier       [type, cp1_t, cp1_v, cp2_t, cp2_v, end_t, end_v] — 7 floats
  2 = stepped      [type, time, value]                         — 3 floats
  3 = inv-stepped  [type, time, value]                         — 3 floats
```

The FIRST point of every curve is `[time, value]` — 2 floats, no type
code. Type codes start at index 2.

**Naive scanner that bites you:**

```python
# WRONG — assumes every 7 floats is bezier
vals = [segments[i+1] for i in range(0, len(segments), 7) if i+1 < len(segments)]
```

This reads the TIME values of stepped segments as opacity values and
produces alarming output like "max opacity = 13.0" — the 13.0 is a
time in seconds, not an opacity.

**Correct scanner:**

```python
def extract_values(segments):
    vals = [segments[1]]  # first value (no type code)
    i = 2
    while i < len(segments):
        seg_type = int(segments[i])
        if seg_type == 0 or seg_type in (2, 3):
            vals.append(segments[i+2])
            i += 3
        elif seg_type == 1:  # bezier
            vals.extend([segments[i+2], segments[i+4], segments[i+6]])
            i += 7
        else:
            i += 1  # unknown type, skip cautiously
    return vals
```

**Real malformed-motion indicator:** segments whose tail length doesn't
match the declared type's expected float count. Example:

```
PARTS_01_ARM_R_01: Segments=[0, 1.0, 1, 0, 1.0, 16.0, 1.0]
                            └first─┘  └── bezier? type=1 but only 5 more floats, needs 6
```

This IS a real bug — SDK may leave part opacities in an inconsistent
state between motion-loops, causing arm-visibility glitches. Found in
`four_arm_deity_dance.motion3.json` during Phase 4 debugging. Fix:
remove from Idle pool or repair the curve.

---

## Arm-Invisibility Debugging Checklist

When a hermes_dark / shizuku arm disappears mid-idle:

1. Identify the motion file PLAYING when the arm vanishes. Watch the
   network tab in DevTools; server GET log also shows it.
2. Parse its Segments with the correct-type walker above.
3. Look for moments where BOTH `PARTS_01_ARM_{L,R}_01` AND
   `PARTS_01_ARM_{L,R}_02` simultaneously hit opacity 0 — if yes,
   the arm has no visible layer, it vanishes.
4. Check for malformed bezier segments (tail length wrong).
5. Check for opacity > 1.0 authoring errors. WebGL usually clamps
   but some drivers render weirdly. Rarely the root cause but worth
   noting in an audit.
6. **Fast fix:** remove the motion from `FileReferences.Motions.Idle`
   in model3.json. File stays on disk for future re-use, SDK stops
   picking it. Always backup first:
   ```
   cp model.json model.backup_$(date +%Y%m%d_%H%M%S).json
   ```

---

## "Arousal" → "Energy" Naming

**Context:** The psychology-correct term for the activation/energy
axis in Russell's circumplex model of affect is "arousal." It appears
in every textbook. In code it's semantically correct.

**Problem:** Everyday English usage of "arousal" is heavily sexually
coded. For a public-facing VTuber project that will be seen by
collaborators, stream viewers, and anyone reading the repo, there's
zero upside to using a word that may be misread.

**Fix:** rename the field to `energy` or equivalent. Backward-compat
shim in `MoodState.from_dict` and `load_identity`:

```python
baseline = MoodBaseline(
    energy=float(data.get("energy", data.get("arousal", 0.0))),
    ...
)
```

This way, old JSON saves and YAMLs with `arousal` keys still load
correctly. Next save writes the new key; old one quietly drops.

**Lesson:** Even semantically-correct jargon from adjacent fields
needs a public-facing review. User called this out in commit review;
renamed 185 occurrences across both repo trees in one sweep.

---

## Persona v2 Architecture Summary

`src/open_llm_vtuber/persona/` subpackage shipped across Phases 1-4:

- `identity.py` — Tier 1 structured YAML (name, core, directives,
  voice, taboos, mood_baseline, relationship). Validated on load.
- `session_memory.py` — Tier 3 turns + rolling summary + mood state,
  atomic JSON persistence at `chat_history/persona_sessions/<name>.json`
- `composer.py` — budget-aware system-prompt assembly, per-tier soft
  caps; budget overshoot drops recent-turns first, keeps Identity.
- `mood.py` — four-dim vector (valence/energy/social/focus), expo
  decay (240s half-life), thermostat-hysteresis quadrant transitions.
- `mood_classifier.py` — heuristic lexicon-based affect classifier,
  microseconds per call, no subprocess.
- `pool_map.py` — mood-quadrant → Live2D motion filenames mapping
  with fallback chain (explicit → calm → flattened → empty + log).

Wiring:
- `agent_factory.py` loads Identity from config, constructs
  SessionMemory + PersonaComposer, passes them to HermesAgent.
- `hermes_agent.py` pre-turn classifies user input at half weight
  (so hermes "reads the room" before responding), post-turn
  classifies full exchange at full weight, touches `quadrant()`
  BEFORE `save()` so hysteresis resolves before persisting.
- `conversations/single_conversation.py` emits `mood_update` over
  WebSocket after `store_message` completes — best-effort, never
  blocks a turn on cosmetic signals.

Activate via `conf.yaml`:

```yaml
agent_config:
  agent_settings:
    hermes_agent:
      persona_v2_identity_path: characters/_persona_schema.yaml
      persona_v2_memory_path: ''  # auto
      persona_v2_budget_tokens: 2500
```

Fully backward-compat: omit those keys and the agent falls back to
the classic `persona_prompt` string path.
