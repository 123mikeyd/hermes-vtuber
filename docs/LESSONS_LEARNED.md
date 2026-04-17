# Lessons Learned — Persona v2 Pipeline (Phases 1-5)

**Compiled:** April 17, 2026
**Scope:** Every gotcha, bad assumption, and painful detour from
building Phases 1-5 of the Open-LLM-VTuber personality evolution.

This file exists because the Hermes skill system security scanner
blocked updating the `open-llm-vtuber` skill with this material
(pre-existing scripts in the skill dir triggered the scanner, not
anything in this content). It's a better home for it anyway — lives
with the code it describes.

---

## 1. `hermes chat` session_id emits on STDERR, not stdout

**Phase 1.** In `-Q` (quiet) mode with `--pass-session-id`, hermes
writes the assistant response to stdout and the `session_id: <id>`
line to STDERR. Our first implementation read only stdout and
silently fell through to the "fresh session" fallback path forever
— memory APPEARED to work (the fallback re-injects context) but
`_session_id` never captured, wall-clock time never improved, and
the strip counter climbed on every turn.

**Fix:** read BOTH streams:

```python
stdout_text = stdout.decode("utf-8", errors="replace")
stderr_text = stderr.decode("utf-8", errors="replace")
self._extract_and_strip_session_id(stderr_text)  # stderr first
response = self._extract_and_strip_session_id(stdout_text).strip()
```

Defense-in-depth: scanning both means if hermes ever moves the line
back to stdout (as older versions did), we still work.

Cost: ~1 hour of confused debugging.

---

## 2. Always use `--source tool` for programmatic hermes calls

Without it, every VTuber turn clutters the user's
`hermes chat --continue` recent-session list. The user eventually
opens a chat expecting their most recent work and sees a hundred
VTuber exchanges.

```python
cmd = [self._hermes_path, "chat", "-Q", "-q", prompt, "--source", "tool"]
```

Make it mandatory for any integration code that calls hermes.

---

## 3. The resume banner has `\r\n` line endings on some systems

`↻ Resumed session <id> (N user message(s), M total messages)` is
emitted on stdout with `\r\n` endings. Our first regex used `$` which
matches `\n` only. Strip worked for fresh Linux, broke on other setups.

**Fix:** `\r?$` in the anchor.

```python
RESUME_BANNER_RE = re.compile(
    r"^[↻↩↪]\s*Resumed session\s+\S+.*?\r?$",
    re.MULTILINE
)
```

---

## 4. `mood.quadrant()` has a stateful side effect — call it before `save()`

Phase 3's `quadrant()` method is STATEFUL: it reads the hysteresis
thresholds AND updates `self.current_quadrant` as a side effect
(persisting the transition to disk on next save). Original code path:

```python
mood.apply_delta(delta)    # updates vector
mem.save()                 # saves — but current_quadrant is STALE
# quadrant() never called -> transition not logged, WebSocket sends OLD label
```

The `mood_update` WebSocket message picked up the old quadrant label
because `current_quadrant` on disk was from the previous turn.

**Fix:** always call `quadrant()` between `apply_delta()` and
`save()`:

```python
mood.apply_delta(delta)
mood.quadrant()            # evaluate hysteresis, update current_quadrant
mem.save()                 # now current_quadrant reflects this turn
```

Symptom before the fix: `mood_update` sent `calm` while logs showed
`Mood quadrant transition: calm -> focused`.

---

## 5. The OLLV frontend is a git submodule

`frontend/` in the OLLV tree is a submodule pointing at
`Open-LLM-VTuber/Open-LLM-VTuber-Web`. You cannot commit changes to
it in our fork — they would be wiped on the next
`git submodule update`.

**The sidecar pattern that works:**

```
hermes-vtuber/
├── sidecars/mood-sidecar.js       # source of truth (OUTSIDE submodule)
├── patches/frontend-mood-sidecar.patch  # surgical index.html edit
└── ... rest of repo ...

Open-LLM-VTuber/
└── frontend/            # submodule
    ├── index.html       # patched at install time
    └── mood-sidecar.js  # copied from our sidecars/ at install time
```

Install:

```bash
cd ${OLLV_DIR}/frontend && \
  patch -p1 < ${HERMES_VTUBER}/patches/frontend-mood-sidecar.patch
cp ${HERMES_VTUBER}/sidecars/mood-sidecar.js \
   ${OLLV_DIR}/frontend/mood-sidecar.js
```

The patch adds one `<script src="./mood-sidecar.js"></script>` tag
BEFORE the main bundle. Load order is critical — the sidecar's
WebSocket prototype intercept must be installed by the time React
opens its connection.

---

## 6. Tree mirroring: hermes-vtuber and OLLV both have `src/` trees

The OLLV server runs out of `~/Open-LLM-VTuber/src/`, NOT our fork's
`src/`. Every Python file you edit in the fork must be manually
mirrored to take effect on the running server:

```bash
# After edits in ~/hermes-vtuber/ run:
cp hermes-vtuber/src/open_llm_vtuber/persona/*.py \
   Open-LLM-VTuber/src/open_llm_vtuber/persona/
cp hermes-vtuber/src/open_llm_vtuber/agent/agents/hermes_agent.py \
   Open-LLM-VTuber/src/open_llm_vtuber/agent/agents/
cp hermes-vtuber/src/open_llm_vtuber/conversations/conversation_utils.py \
   Open-LLM-VTuber/src/open_llm_vtuber/conversations/
cp hermes-vtuber/src/open_llm_vtuber/agent/agent_factory.py \
   Open-LLM-VTuber/src/open_llm_vtuber/agent/
cp hermes-vtuber/src/open_llm_vtuber/websocket_handler.py \
   Open-LLM-VTuber/src/open_llm_vtuber/
```

Also mirror the sidecar:

```bash
cp hermes-vtuber/sidecars/mood-sidecar.js \
   Open-LLM-VTuber/frontend/mood-sidecar.js
```

**After every edit**, verify sync:

```bash
for f in persona/mood.py persona/pool_map.py \
         agent/agents/hermes_agent.py \
         conversations/conversation_utils.py; do
  diff -q hermes-vtuber/src/open_llm_vtuber/$f \
          Open-LLM-VTuber/src/open_llm_vtuber/$f || echo "DIVERGED: $f"
done
```

Silence is good.

---

## 7. `frontend-playback-complete` handshake is REQUIRED for mood_update

`finalize_conversation_turn()` in `conversation_utils.py` blocks on
`message_handler.wait_for_response("frontend-playback-complete")`
with NO timeout. Headless test clients that connect, send a message,
and then close without sending this reply will hang the conversation
chain. On disconnect the chain is cancelled, `asyncio.CancelledError`
is raised, `store_message()` is skipped, and `_maybe_emit_mood_update`
NEVER EXECUTES.

Symptom: test sees synth-complete fire but no mood_update ever
arrives, even with 180-second waits.

Real browsers send `frontend-playback-complete` automatically when
audio playback finishes. Test harnesses MUST emulate:

```python
if msg["type"] == "backend-synth-complete":
    await ws.send(json.dumps({"type": "frontend-playback-complete"}))
```

This is upstream OLLV code (not ours to "fix"), but we discovered it
during Phase 4 and it now affects every test script we write.

---

## 8. All persona code paths wrap their work in try/except

During the post-Phase-4 audit we found TWO unguarded code blocks
(pre-turn and post-turn mood classification) that could have
silenced Nova mid-response if the classifier ever threw. Mood is
best-effort cosmetic; the user MUST always get the speech.

The pattern, applied everywhere:

```python
if self._identity is not None:
    try:
        # ... mood classification, apply_delta, save ...
    except Exception as err:
        logger.warning(f"... failed (non-fatal): {err}")
```

Audit checklist for any new persona integration:

1. Dynamic execution (eval/exec/Function/__import__): must be zero
2. Hardcoded secrets / Bearer / sk-... / api_key=: must be zero
3. New outbound URLs: must be zero (only local hermes subprocess)
4. Bare `except:` blocks: must be zero
5. Model-touching JS must use `getLive2DManagerSafe()` (null-guards)
6. Every persona-layer code block must be in try/except
7. WebSocket intercept preserves `OriginalWS.prototype`, `OPEN`,
   `CLOSED`, `CONNECTING`, `CLOSING`
8. Adversarial input test: empty, whitespace, only-punct, long
   repeats, unicode, emoji, SQL/XSS lookalikes, None, null bytes —
   zero crashes

---

## 9. Rename `arousal` to `energy`

The mood vector axis originally called `arousal` (standard psych
term, Russell's circumplex model) was renamed to `energy` because
"arousal" reads sexualized in everyday English. For a public VTuber
project that will appear in READMEs, stream chat, and collaborator
emails, there's no reason to ship a word that makes anyone pause.

Backward-compat shim in `MoodState.from_dict`:

```python
energy=float(data.get("energy", data.get("arousal", baseline.energy))),
```

Old nova.json saves with `"arousal"` key load cleanly. Next save
writes the new key. All new code uses `energy`.

---

## 10. Four-arm-deity bug pattern

If a motion3.json file sets BOTH arm layers
(`PARTS_01_ARM_L_01` AND `PARTS_01_ARM_L_02`) at `PartOpacity = 0.0`
at the same timestamp, the arm visually vanishes. The A-layer and
B-layer are mutually exclusive — exactly ONE should be 1.0 at any
keyframe.

`four_arm_deity_dance.motion3.json` had malformed bezier segments
that produced this visually. Pulled from the Idle pool.

Audit check when authoring new motions:

```python
for side in ("L", "R"):
    l1 = next(c for c in curves if c["Id"] == f"PARTS_01_ARM_{side}_01")
    l2 = next(c for c in curves if c["Id"] == f"PARTS_01_ARM_{side}_02")
    # At every keyframe, l1 OR l2 must be 1.0, and they must not both be 0
```

Full implementation in the Phase 4 audit section — reuse when
authoring motions.

---

## 11. Verify-script discipline

All four verify scripts must pass green before EVERY commit:

```bash
cd hermes-vtuber
python3 scripts/verify_phase1_ipc.py        # session resume + banner strip
python3 scripts/verify_phase2a_persona.py   # identity + session memory
python3 scripts/verify_phase3_mood.py       # mood math + hysteresis + live drift
python3 scripts/verify_phase5_expression.py # affect blend + param deltas
# Phase 4 verified by live WebSocket test (manual)
```

Run them AGAINST A CLEAN CHECKOUT BEFORE starting work too. Sets a
baseline and confirms the test harnesses still work against your
local hermes CLI version. Multiple times the harness worked but
revealed the LIVE integration was broken (bug #1 was caught exactly
this way).

---

## 12. The server's log goes to a DIFFERENT FILE than the background process output

`/tmp/ollv_server.log` — only if you redirected to it manually.
OLLV's own debug log: `~/Open-LLM-VTuber/logs/debug_YYYY-MM-DD.log`.
The Hermes background process watcher captures stdout only.

When investigating "why didn't X fire" always check ALL THREE:

```bash
# 1. Hermes background-process captured output
process(action="log", session_id=...)

# 2. OLLV's own debug log
tail -200 ~/Open-LLM-VTuber/logs/debug_2026-*.log

# 3. Stale /tmp log from earlier runs
tail -200 /tmp/ollv_server.log
```

The server's startup banner shows in (1) and (2). Individual DEBUG
lines (per-turn mood classifier output, expression_blend payloads)
only show in (2) — they don't appear in (1) because loguru's file
sink and the stdout sink are configured independently.

---

## 13. Git workflow: NEVER force-push without user confirmation

During Phase 2a I accidentally squashed two unrelated commits by
using `git commit --amend` after a gitignore hiccup. Tried to
force-push the "clean" history. User blocked it.

**The right recovery is `git reset --soft origin/<branch>` and
replay commits cleanly, not force-push.** That's non-destructive,
preserves the pushed history, and produces the same end state.

If you find yourself reaching for `git push --force` on a branch
that's already on GitHub, stop and ask. Even on a feature branch
that "nobody else is using."

---

## 14. Personality hardens conversation quality — hysteresis thresholds

The user asked for "at least two strongly worded sentences" to flip
quadrants, and "no flicker at boundaries." The math that satisfies
both:

```
MOOD_UPDATE_WEIGHT = 0.3     # per-turn nudge cap
MOOD_ENTER_EXCITED_ENERGY = 0.55   # thermostat "on" temp
MOOD_STAY_EXCITED_ENERGY  = 0.25   # thermostat "off" temp
```

Baseline energy 0.1 + 0.3 * 0.9 (strong delta) = 0.37 — below 0.55,
so one strong turn stays calm. Two strong turns reach 0.64 — cross
the threshold. Once in, stays in until energy drops below 0.25.

Decay half-life 240s (4 min) so short breaks don't wipe mood.

**Document this math in the mood.py header.** Future changes to
`MOOD_UPDATE_WEIGHT` or the thresholds will invalidate the
"2 sentences minimum" guarantee; the comment is what keeps future
maintainers from breaking the contract.

---

## 15. Frame-loop cost: one null check per frame is fine

The Phase 5 sidecar runs `requestAnimationFrame(applyActiveBlend)`
always, even when no blend is active. First instinct: start/stop the
loop on demand for "performance."

Real measurement: one null check at 60fps is ~60 ops/sec. Negligible.
The complexity of start/stop logic vastly outweighs the cost of the
always-on loop. Left it always-on.

Lesson: measure before optimizing. JavaScript null checks are cheap.
RAF callbacks that early-exit are cheaper than the code that would
gate the RAF itself.

---

## Credits

The upstream Open-LLM-VTuber team built the entire agent/ASR/TTS/
WebSocket/Live2D foundation this work sits on top of. Their
`AgentInterface` contract, the `conversation_handler` mediation
layer, and the `sentence_divider` pipeline are what let persona v2
slot in without touching anything they own.

Upstream: https://github.com/Open-LLM-VTuber/Open-LLM-VTuber

Nothing in this work is novel research — it's disciplined engineering
on top of known patterns (thermostat hysteresis from control theory,
exponential decay from affect dynamics literature, sidecar pattern
from browser extensions, Cubism's additive parameter setter from the
Live2D SDK).
