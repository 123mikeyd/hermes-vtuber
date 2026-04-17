# Personality Evolution Session — Key Lessons

Reference notes from the April 2026 session that shipped Phases 1-5
of the personality evolution plan. Meant for future maintenance and
for anyone picking up this pipeline cold.

Treat this as an addendum to the `open-llm-vtuber` Hermes skill —
the skill has broader OLLV integration knowledge; this file has the
session-specific discoveries that didn't fit cleanly in a skill patch.

---

## The load-bearing gotchas

### 1. Hermes session_id emits on STDERR, not STDOUT

When `hermes chat -Q -q "..." --pass-session-id` runs, the clean
response goes to stdout and the `session_id: <id>` line goes to stderr.
A first-version agent that only reads stdout silently fails to capture
the id and stays in "fresh session forever" mode. Memory still appears
to work (fallback prompt building re-injects it each turn), but
`--resume` never fires and we pay full hermes startup cost every turn.

Fix: scan both streams, stderr first.

```python
stdout_text = stdout.decode("utf-8", errors="replace")
stderr_text = stderr.decode("utf-8", errors="replace")
self._extract_and_strip_session_id(stderr_text)
response = self._extract_and_strip_session_id(stdout_text).strip()
```

This cost about an hour to diagnose in Phase 1. Symptom: "memory
persists but server feels slow."

### 2. The `frontend-playback-complete` handshake

Upstream OLLV's `finalize_conversation_turn` calls
`wait_for_response(client_uid, "frontend-playback-complete")` with NO
timeout. Real browsers send this automatically after playing the TTS
audio. Python test harnesses that connect via `websockets.connect()`
without emulating it cause the server to:
 - block indefinitely on the wait
 - cancel the conversation task when the client eventually disconnects
 - never reach `store_message`
 - never emit `mood_update`

This burned two diagnostic iterations during Phase 4. Symptom: test
client sees `synth-complete` but no `mood_update` afterward.

Always emulate in test harnesses:

```python
if msg["type"] == "backend-synth-complete":
    await ws.send(json.dumps({"type": "frontend-playback-complete"}))
```

### 3. The `frontend/` submodule cannot hold our sidecar

OLLV's `frontend/` is a git submodule pointing at
`Open-LLM-VTuber/Open-LLM-VTuber-Web`. Files we drop into it aren't
tracked by our parent repo (mode 160000 — gitlink only) and would be
wiped on the next `git submodule update` if we could track them.

Solution (Phase 4):
 - Canonical sidecar source: `sidecars/mood-sidecar.js` (OUR repo)
 - index.html edit shipped as `patches/frontend-mood-sidecar.patch`
 - Installation instructions in docs: copy the JS, apply the patch

Always check `git ls-files --stage <path> | head -1` before committing
work inside a submodule-mounted directory. Mode `160000` = submodule.

### 4. Tree mirroring: OLLV runs from ITS OWN src/

OLLV's `run_server.py` imports `from src.open_llm_vtuber...` — it uses
the `src/` directory under its own repo root, not ours. Every code
change we make in hermes-vtuber MUST be copied over to
Open-LLM-VTuber/ manually or the running server uses the old code.

A `diff -q` loop across all touched files is the only reliable
sync-check. Run it after EVERY persona-layer edit.

### 5. Word choice in a public project — "arousal" → "energy"

The affect-psychology literature (Russell's circumplex, Mehrabian PAD)
uses "arousal" to mean activation/energy level. That's technically
correct but in everyday English the word carries sexual connotations.
For a public VTuber project with collaborators and stream viewers,
we renamed to `energy` across 185 occurrences. Backward-compat shim
in `MoodState.from_dict` accepts both keys so old saves still load.

Lesson: before shipping code whose variable names will be read by
non-specialists, say them out loud in the context they'll appear.
If it would make anyone pause, rename.

### 6. Defense in depth — speech must never fail because of cosmetics

Every persona code path (pre-turn classify, post-turn classify,
mood_update emit, expression_blend emit) is wrapped in try/except
with logger warnings. A classifier bug in an edge case must NEVER
silence Nova. Pattern:

```python
if self._identity is not None:
    try:
        # classify, apply_delta, save
    except Exception as _err:
        logger.warning(f"... failed (non-fatal): {_err}")
```

Audit caught two unguarded code paths during the session and fixed
them (`fix(safety): wrap pre/post-turn mood blocks in try/except`).

### 7. Adversarial input test matters for text classifiers

Phase 5 audit fed 13 adversarial inputs to `expression_infer`
including: None, null bytes, 5000-word repeats, regex-unfriendly
quotes, XSS strings, SQL-lookalike, ALL-CAPS. All passed.

Not because I wrote defensive code on day one — because the simple
lexicon+regex approach is genuinely hard to break. But running the
test is ~5 minutes of work and catches the one thing you didn't
think of.

### 8. Thermostat hysteresis beats single-threshold gates

Original quadrant logic: `if energy >= 0.15 return "excited"`.
Problem: a single strong sentence could cross that, and values
hovering at 0.14/0.16 flicker pools on every minor delta.

Fixed with separate ENTER and STAY thresholds:
```
excited:  enter @ energy >= 0.55,  stay while >= 0.25
```
Entry requires a strong signal; once in, you need sustained contrary
evidence to leave. `MoodState.current_quadrant` is now stateful and
persisted in the JSON so restarts don't re-evaluate from scratch.

User coined this as "thermostat hysteresis" after I used the jargon
without explaining it. Don't use specialist terms without defining
them in the same breath.

### 9. Visible vs. measurable mood drift

After first live test, user reported: "her mood changed but I
couldn't tell visually." Data said yes (valence +0.18, energy +0.21,
social MAXED at +1.00). Screen said "she looks the same."

Causes:
 - Hysteresis kept her in `calm` quadrant (correct) — pool didn't
   change, motions didn't change
 - Parameter deltas were ±0.3 max — being added on top of motions
   already moving the same parameters between ±0.6
 - Fixed 600ms envelope faded out before long sentences finished
 - Idle motions themselves didn't have mood-distinct baselines

Phase 4.5 fixed all four: doubled deltas, raised aggregate clamp to
±0.8, sentence-length-scaled envelope (up to 4s), and authored four
new idles with visibly different baseline poses (smile baked in for
calm, narrowed eyes for focused, heavy half-lids for tired, brows
UP for excited).

Lesson: perceptual tuning needs human eyes on screen. Numbers being
correct is not the same as a thing being visible.

### 10. Git hygiene under pressure

Twice in the session I had to recover from commit-sequence mistakes:
 - Phase 2a: `.gitignore` blocked a schema file; my --amend then
   squashed the new work into the wrong prior commit. Recovered via
   `git reset --soft origin/leaf` + clean re-commit.
 - Force-push was offered and user denied. The soft-reset path was
   available and better. Ask before destructive history rewrites.

Lesson: `git show --stat HEAD` any time a commit sequence feels off.
Check you committed what you THINK you committed before pushing.

---

## Useful commands we evolved

Motion file audit (check for four-arm-deity-style bugs):
```python
# See scripts/author_phase4_5_motions.py for the full 5-check suite
# 1. duration >= 8s, 2. critical params present, 3. neither arm side
# can vanish, 4. segment counts match meta, 5. opacity values in [0,1]
```

Tree sync check across hermes-vtuber and OLLV:
```bash
for f in src/open_llm_vtuber/persona/*.py \
         src/open_llm_vtuber/agent/agents/hermes_agent.py \
         src/open_llm_vtuber/agent/agent_factory.py \
         src/open_llm_vtuber/conversations/single_conversation.py \
         src/open_llm_vtuber/conversations/conversation_utils.py \
         src/open_llm_vtuber/websocket_handler.py; do
  diff -q /home/mikeyd/hermes-vtuber/$f \
          /home/mikeyd/Open-LLM-VTuber/$f 2>&1
done
```

Sidecar JS syntax-check (parses in node without executing):
```bash
node -e "const fs = require('fs'); new Function(fs.readFileSync('sidecars/mood-sidecar.js', 'utf-8'))"
```

Server-side live verification:
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:12393/
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:12393/mood-sidecar.js
curl -s http://127.0.0.1:12393/index.html | grep -c "mood-sidecar.js"
```

---

## Where to look for what

| Phase | Files | Doc |
|-------|-------|-----|
| 1 | `hermes_agent.py` | `docs/PHASE_1_IPC.md` |
| 2a | `persona/identity.py`, `session_memory.py`, `composer.py`, `agent_factory.py` | `docs/PHASE_2A_PERSONA.md` |
| 3 | `persona/mood.py`, `mood_classifier.py` | `docs/PHASE_3_MOOD.md` |
| 4 (server) | `persona/pool_map.py`, `single_conversation.py`, `websocket_handler.py` | `docs/PHASE_4_IDLE_POOLS.md` |
| 4 (frontend) | `sidecars/mood-sidecar.js`, `patches/frontend-mood-sidecar.patch` | `docs/PHASE_4_FRONTEND_SIDECAR.md` |
| 5 | `persona/expression_inference.py`, `conversation_utils.py` | `docs/PHASE_5_EXPRESSION.md` |
| 4.5 | `scripts/author_phase4_5_motions.py`, 4 new `idle_*_*.motion3.json` | (this file) |

Plan doc: `.hermes/plans/2026-04-17_personality-evolution.md`

Verify scripts: `scripts/verify_phase{1,2a,3,5}_*.py` — standalone,
run after any persona change.
