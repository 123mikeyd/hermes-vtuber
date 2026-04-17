# Phase 1 — Session-Resumed Hermes IPC

**Status:** Shipped on branch `persona/phase-1-ipc`
**Part of:** [Personality Evolution Plan](../.hermes/plans/2026-04-17_personality-evolution.md)
**Commit:** `0de37ea` — feat(phase-1): session-resumed hermes IPC
**Verification:** `scripts/verify_phase1_ipc.py`

---

## What changed

`src/open_llm_vtuber/agent/agents/hermes_agent.py` now maintains one
long-lived hermes session per agent instance:

- **Turn 1**: `hermes chat -Q -q <prompt> --source tool --pass-session-id`
  captures the `session_id:` line from hermes's output.
- **Turn 2+**: `hermes chat -Q -q <prompt> --source tool --resume <id>`
  reuses the same session. Hermes already has memory, skills, persona,
  and conversation state loaded — we just send the new user turn.

The agent still spawns a subprocess per turn (Phase 1.5 via ACP will
eliminate that too), but the subprocess is now orders of magnitude
cheaper because it resumes existing state instead of bootstrapping.

---

## Why the change

Before Phase 1, every VTuber turn paid:
- Full hermes startup cost (~0.5-2s)
- Skill graph reload
- Memory reload from disk
- Model / provider / config reload
- Banner + metadata output that we then stripped with ~100 lines of regex

After Phase 1:
- Full startup cost on turn 1 only
- Subsequent turns resume instantly on the hermes side
- Output is just: response + resume banner (1 line we strip)

Measured on the verification script (3 turns, short prompts):
- Turn 1 (fresh): 6.27s
- Turn 2 (resume): 4.06s
- Turn 3 (resume): 3.96s
- ~35% per-turn speedup after session is pinned

`_clean_response()` strip counter dropped from many per turn to exactly 1.

---

## The gotcha that cost an hour

**`session_id` emits on STDERR, not STDOUT.**

Hermes in `-Q` mode writes the clean assistant response to stdout and
the `session_id: <id>` line to stderr. The first version of this code
read only stdout, silently fell through to the fresh-session fallback
path (which still works because `_build_prompt()` re-injects system +
memory when `_session_id is None`), and ran with zero actual IPC
improvement while appearing to function.

Symptom: memory appeared to persist across turns (because the fallback
was re-sending the full context every turn), but `_session_id` stayed
`None`, wall-clock time stayed at fresh-session levels, and
`_strip_counter` climbed on every turn.

Fix: read both streams, scan stderr first.

```python
stdout_text = stdout.decode("utf-8", errors="replace")
stderr_text = stderr.decode("utf-8", errors="replace")

# stderr first — that's where hermes -Q puts session_id
self._extract_and_strip_session_id(stderr_text)
response = self._extract_and_strip_session_id(stdout_text).strip()
```

Defense-in-depth: scanning stdout too means if hermes ever moves
session_id back to stdout (as older versions did), we still work.

---

## Other quirks encountered

- **Resume banner on stdout**: `↻ Resumed session <id> (N messages)`
  is emitted on every `--resume` call even in `-Q` mode. We strip
  it in `_clean_response()`.
- **Windows line endings**: the resume banner sometimes ends `\r\n`.
  The stripping regex uses `\r?$` to handle both.
- **`--source tool` is mandatory**: without it, every VTuber call
  clutters the user's personal `hermes chat --continue` recent-session
  list. Always set it for programmatic / integration use.
- **`--pass-session-id` is mandatory** on turn 1: without it, hermes
  prints nothing but the response in `-Q` mode, and we have no way
  to capture the session id.

---

## Interface unchanged

`HermesAgent` still satisfies the OLLV `AgentInterface` contract:
- `chat(input_data) -> AsyncIterator[SentenceOutput]`
- `handle_interrupt(heard_response)`
- `set_memory_from_history(conf_uid, history_uid)`
- `set_system(system)`

No caller changes are required. Existing `conf.yaml` files keep working.

---

## What this unblocks

Phase 2 (persona memory layer — 3-tier identity/biography/session) now has
a clean prompt-injection point. Before Phase 1, every turn was already
stuffing the system prompt + last-10 messages into a fresh hermes process,
so adding RAG on top would have compounded the reload cost. Now: inject
the tier-2 RAG chunks only when relevance changes, and hermes holds onto
tier-3 session memory natively.

Phase 1.5 (ACP-based IPC) is filed for after all five planned phases
land. That upgrade would eliminate the per-turn subprocess entirely and
give us proper streaming + cancellation, but it's not blocking anything
today.

---

## Verification

```bash
cd /home/mikeyd/hermes-vtuber
python3 scripts/verify_phase1_ipc.py
```

Expected output:
- `[OK] session_id captured: <id>`
- `[OK] turn 2 remembered the color: 'cerulean.'`
- `[OK] cleaner stripped N lines after turn 1 (low)`
- Per-turn wall-clock times logged

Exits non-zero if any assertion fails. Safe to re-run.

---

## Credit

This work lives inside the Open-LLM-VTuber `AgentInterface` contract —
the upstream team's architectural decision to keep the agent layer
pluggable is what lets us slot this in without touching their core.

Upstream: https://github.com/Open-LLM-VTuber/Open-LLM-VTuber
