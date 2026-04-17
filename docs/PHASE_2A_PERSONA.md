# Phase 2a — Persona Memory Layer (Tiers 1 + 3)

**Status:** Shipped on branch `leaf`
**Part of:** [Personality Evolution Plan](../.hermes/plans/2026-04-17_personality-evolution.md)
**Verification:** `scripts/verify_phase2a_persona.py`

---

## What changed

A new `src/open_llm_vtuber/persona/` subpackage holding three modules:

- **`identity.py`** — Tier 1 identity schema + loader. Structured
  dataclass (`Identity`) with `name`, `core`, `directives`, `voice`,
  `taboos`, `mood_baseline`, `relationship`. Validation: out-of-range
  mood values, missing required fields, and bad types all raise at load.
- **`session_memory.py`** — Tier 3 session state. `SessionMemory`
  holds a timestamped list of `Turn` objects, exposes `recent()` and
  `older_than_recent()` windows, carries a `rolling_summary` string,
  atomically persists to JSON on disk.
- **`composer.py`** — `PersonaComposer` assembles Tier 1 + Tier 3 into
  a system prompt with per-tier soft caps and a total-budget enforcer.
  If over budget, drops summary-then-recent-turns, preserves Identity.
- **`__init__.py`** — public surface: `Identity`, `MoodBaseline`,
  `load_identity`, `SessionMemory`, `Turn`, `PersonaComposer`,
  `ComposedPrompt`.

A new schema example at `characters/_persona_schema.yaml` documents
the Tier 1 YAML shape with the Nova persona filled in as a working
reference.

`src/open_llm_vtuber/agent/agents/hermes_agent.py` grew three optional
constructor arguments (`identity`, `session_memory`, `composer`) — all
default to `None` / sensible defaults, so existing configs that pass only
`system="..."` keep working unchanged. When `identity` is provided,
`_build_prompt()` on turn 1 calls the composer instead of the legacy
string concatenation path.

Each turn (user + assistant) is recorded into `SessionMemory`. When
enough turns accumulate (default: 10 beyond the recent window of 20),
`_refresh_summary()` fires as an `asyncio.create_task` — a background
hermes call that generates a rolling summary without blocking the user.
Summarization failures are swallowed with a warning; stale summaries
degrade gracefully.

---

## Tier 2 (biography RAG) is NOT in this commit

Phase 2b will add `biography.py` with a Chroma-backed RAG module,
behind an optional dependency. Keeping 2a dependency-free means this
ships without forcing every OLLV install to pull Chroma.

The composer already accepts a `biography_chunks: List[str]` argument
for Phase 2b — passing an empty list or None skips the biography
section cleanly.

---

## Backward compatibility

Every caller that built a `HermesAgent` before this commit still works
identically. The persona v2 path is opt-in: pass `identity=...` and
the new pipeline activates. No config changes required for existing
character YAMLs.

---

## Verification

```bash
cd /home/mikeyd/hermes-vtuber
python3 scripts/verify_phase2a_persona.py
```

Seven tests, all must pass:

1. Identity loads from `_persona_schema.yaml`, fields populated, render
   produces labeled sections.
2. Identity validation rejects missing `name`, out-of-range mood values,
   and non-list directives.
3. `SessionMemory` roundtrips cleanly to JSON — 2 turns in, 2 turns out,
   duplicates and empty-content turns dropped.
4. `recent()` + `older_than_recent()` partition turns correctly.
5. Composer assembles identity + memory into a prompt under budget.
6. Composer truncates when over budget but preserves the Identity block.
7. **LIVE integration:** `HermesAgent` with an Identity + SessionMemory
   carries persona ("crumpet out" signoff) AND remembers facts (the
   user's pet "Biscuit the capybara") across a session resume.

Phase 1 verification (`verify_phase1_ipc.py`) still passes — Phase 2a
did not regress session-resumed IPC.

---

## Budget numbers

The canonical schema example composes to ~299 tokens. With `DEFAULT_TOTAL_BUDGET_TOKENS=2500`, that leaves ~2200 tokens for tier-3 summary
+ recent window + tier-2 biography chunks once that lands.

If you need more headroom for a big model (32k+ context), construct
`PersonaComposer(total_budget_tokens=...)` and pass it to the agent.

---

## What this unblocks

- **Phase 3 (Mood State Machine):** now has a persistent, per-session
  home for the mood vector. `SessionMemory` is where the affect
  classifier writes, the composer injects mood as natural language
  into the system block, and the frontend reads it to pick idle pools.
- **Phase 5 (Continuous Expression):** baseline mood from
  `Identity.mood_baseline` lets a sad-mood character's "happy"
  never reach full intensity — the anchor point was needed.
- **Phase 2b (biography RAG):** the composer's `biography_chunks`
  arg is already the injection point. A Chroma-backed module drops
  in as a pluggable backend.

---

## Credit

The overall pattern (agent holds a per-session state object, composer
assembles a system prompt with caps) is the standard architecture that
LangChain, LlamaIndex, and several OLLV-upstream agents use in
different flavors. The specific 3-tier split (identity/biography/session)
is adapted from the MemGPT paper and the Letta project's sensibilities,
both of which OLLV already has integrations for.

Nothing in this phase is novel research — it's disciplined engineering
on top of well-understood ideas, wired to work with the Open-LLM-VTuber
agent contract and the Hermes Agent session-resume IPC from Phase 1.
