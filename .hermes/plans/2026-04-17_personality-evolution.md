# Personality Evolution Plan — Hermes VTuber

> **Sister plan to** `2026-04-13_031400-hermes-avatar-platform-v2.md`.
> That plan is about the **body** (editor, rendering, rigging). This plan is
> about the **brain** (personality, memory, mood, voice).
>
> Both plans converge into the same shipping product. Neither blocks the other.

**Author:** Mike (Nous Research — Hermes Agent contributor / mod)
**Date:** April 17, 2026
**Status:** Approved direction, Phase 1 beginning

---

## Why this plan exists

On April 16–17, 2026, an unprompted comment from streamer **Leaflit**
(twitch.tv/Leaflit, founder of Angel's Sword Studios) surfaced the use case
we had been circling without a clear customer: _"I want my VTuber to live on
after I'm gone."_

That request cannot be served by a better editor alone. It requires a
persistent **personality**, not just a puppet. Whether Leaflit herself joins
the project or not (outreach is in motion, not contingent on this plan), the
gap she named is the same gap every VTuber, streamer, and long-form creator
using our stack will eventually hit: the avatar sounds the same in turn one
and turn one thousand. It does not grow. It does not remember. It does not
feel like a person you know.

This plan fixes that — universally, for every user of the skill, not just
for Leaflit.

---

## Credit where credit is due

Before a single line of new code: **this project does not exist without the
Open-LLM-VTuber team.** Everything we ship here — the WebSocket architecture,
the ASR/TTS/LLM abstraction, the Live2D integration, the character config
system, the MCP integration, the conversation handler — started with their
work. Our repo is a fork of theirs. Our `hermes_agent.py` plugs into their
`AgentInterface`. Our editor sits next to their server. Our motion research
was done on the `shizuku` model they ship.

Maintainers and contributors at `Open-LLM-VTuber/Open-LLM-VTuber` are
co-authors of this project in spirit, and their LICENSE and credits must
remain intact in every downstream release. When this personality pipeline
ships, the release notes will say so, out loud, on the first line.

Upstream: https://github.com/Open-LLM-VTuber/Open-LLM-VTuber

Other creators whose work is on our critical path:
 - **Cubism / Live2D Inc.** — the SDK our rendering depends on
 - **shizuku** model artists — the public model we used to learn rigging
 - **mao_pro** model artists — the second public model we validated on
 - **Cilphy** (if Leaflit collab lands) — Slime 2.0 rigger, Leaflit's model
 - **Kriss Sison** (if Leaflit collab lands) — original Leaflit slime art
 - **F5-TTS / XTTS / Coqui** teams — the voice cloning work we will lean on
   in a later sprint
 - **openai/whisper + faster-whisper** — the STT backbone we inherited from
   OLLV and keep using
 - **ElViejoByte** (if Leaflit collab lands) — directorial reference

A `CREDITS.md` will be created at repo root as part of Phase 1 closing tasks,
and the open-llm-vtuber Hermes skill SKILL.md will carry a `credits:` frontmatter
block listing everyone above.

---

## What this plan is NOT

- Not a replacement for the avatar platform plan (v2). That continues.
- Not voice cloning (that's a separate Sprint — deliberately excluded here).
- Not content ingestion (also separate — depends on a subject consenting).
- Not Leaflit-specific. If she joins, she consumes this pipeline. If she
  does not, every other VTuber who uses our skill consumes it instead.
- Not a product. It is an open-source module inside an open-source project.

---

## Scope — the five upgrades

In the execution order set by dependency, not by user preference order:

1. **G — Hermes IPC** (foundation; unblocks everything after)
2. **A — Persona Memory Layer** (3-tier: identity / biography / session)
3. **B — Mood State Machine** (persistent affect vector)
4. **E — Idle Behavior Brain** (mood-tagged idle pools, micro-behaviors)
5. **F — Continuous Expression** (sentence-affect → continuous blend)

Each phase below produces a shippable artifact. Nothing is merged to main
without working, testable output and a restart of the server proving it
still boots.

---

## Phase 1 — Hermes IPC (G)

**Problem today:** `hermes_agent.py` spawns `hermes chat -Q -q "prompt"` as
a fresh subprocess on every turn. This pays full startup cost per turn,
reloads skills/memory/config every time, and dumps CLI metadata into stdout
that we then strip with increasingly baroque regex in `_strip_thinking()`
and `_clean_response()`. The regex stack is ~100 lines and grows every time
the CLI output format shifts.

**Goal:** one long-lived hermes process per WebSocket session, clean message
boundaries, no per-turn startup cost, no banner stripping.

### Options considered

**(a) `--resume SESSION_ID` loop [CHOSEN for Phase 1]**
First turn: `hermes chat -Q -q "prompt" --source tool --pass-session-id`.
Capture the `session_id:` line from stdout. Every subsequent turn:
`hermes chat -Q -q "prompt" --resume <session_id> --source tool`.
Each call is still a subprocess, but hermes reuses the existing session —
memory, persona, and skills are already loaded on the hermes side.

 Pros: zero hermes code changes; `--source tool` keeps calls out of user
 session history; session persists across server restarts if we save the id.
 Cons: still one subprocess per turn. Not truly streaming.

**(b) ACP mode (`hermes acp`)**
Hermes already speaks Agent Client Protocol (JSON-RPC over stdio) for editor
integrations. We could spawn one long-lived `hermes acp` process per
WebSocket session and send JSON-RPC messages.

 Pros: true streaming; no subprocess-per-turn; structured responses (no
 regex stripping at all); proper cancellation.
 Cons: we have to implement an ACP client in Python. ACP spec is small but
 unfamiliar. Higher up-front cost. Better for Phase 1.5.

**(c) Python-level import of hermes internals**
 Rejected. Couples us tightly to hermes internals; version skew is a time bomb.

### Phase 1 deliverable

`src/open_llm_vtuber/agent/agents/hermes_agent.py` refactor:

- New field: `self._session_id: Optional[str] = None`
- First `_call_hermes()`: run with `--pass-session-id`, capture `session_id:`
  line, store in `self._session_id`, strip it from response as before.
- Subsequent calls: `hermes chat -Q -q "..." --resume <id> --source tool`
  — which short-circuits almost all banner output.
- `handle_interrupt()` now forwards an interrupt marker message into the
  resumed session instead of mutating a local list.
- `set_memory_from_history()` now maps an OLLV history_uid to a hermes
  session_id via a small `chat_history/hermes_sessions.json` index.
- Keep `_strip_thinking()` / `_clean_response()` as defense-in-depth —
  don't delete them, but they should fire on basically nothing after the fix.

Verification:
 - Run 10 consecutive turns, measure wall-clock time per turn. Target: first
   turn unchanged, subsequent turns under 50% of current time.
 - Log: exactly one `session_id:` observed on turn 1, zero thereafter.
 - `_clean_response()` hits counter: track how many lines it strips per
   turn. Target: ~0 after turn 1.

Out of scope for Phase 1: full ACP client. Filed as Phase 1.5 for later.

---

## Phase 2 — Persona Memory Layer (A)

**Problem today:** `persona_prompt` is one static string in `conf.yaml`.
Conversational memory is `self._memory[-10:]` — ten turns, then amnesia.
No awareness of anything the user told us a week ago.

**Goal:** three tiers of persona context, injected per turn, within a budget.

### The three tiers

**Tier 1 — IDENTITY** (static, 100% injected every turn, ~500 tokens max)
 What the character IS. Name, values, speech patterns, signature phrases,
 forbidden topics. This is basically today's `persona_prompt` but structured
 as a short YAML schema, not a wall of text.

**Tier 2 — BIOGRAPHY** (RAG, top-k 3–5 chunks per turn, ~800 tokens max)
 Episodic and semantic memory. Populated from:
  - prior conversation summaries (we generate these on session close)
  - any user-supplied lore documents (TTRPG writeups, wiki pages, etc.)
  - optional: VOD transcripts if/when content ingestion ships
 Storage: Chroma, per-character collection, persisted in `chat_history/rag/`.

**Tier 3 — SESSION** (volatile, full recent + summary of older, ~1500 tokens max)
 Last N turns raw (default 20). Older turns compressed into a running summary
 that hermes itself rewrites every 10 turns. Mood vector from Phase 3 lives
 here too.

### Injection order into the system prompt

```
[IDENTITY block]
[BIOGRAPHY: top 3-5 chunks from RAG, ordered by relevance]
[SESSION SUMMARY: rolling summary of older turns]
[SESSION RECENT: last 20 turns, raw]
[MOOD: current mood vector as natural language — Phase 3]
---
User: <new turn>
```

### Phase 2 deliverables

- `src/open_llm_vtuber/persona/__init__.py` — new subpackage
- `src/open_llm_vtuber/persona/identity.py` — loader + schema for Tier 1
- `src/open_llm_vtuber/persona/biography.py` — Chroma wrapper for Tier 2
- `src/open_llm_vtuber/persona/session_memory.py` — Tier 3 with rolling summary
- `src/open_llm_vtuber/persona/composer.py` — assembles the injection prompt
  with budget-aware truncation
- Integration in `hermes_agent.py._build_prompt()` — replaces current `self._system` + last-10 with the composer output
- Schema file `characters/_persona_schema.yaml` — the tier-1 shape
- Migration script `scripts/persona_migrate.py` — upgrades old flat persona_prompts into new schema

Verification:
 - Load an example character with 10 lore chunks in biography.
 - Converse for 50 turns about unrelated topics.
 - At turn 50, ask about something in chunk 3 — the character remembers.
 - Token count per turn must stay under the model's context minus 25%
   headroom. Composer enforces this.

---

## Phase 3 — Mood State Machine (B)

**Problem today:** the character has the same energy in turn 1 and turn 1000.
Users can feel it. It's the single biggest "this is an NPC not a person" signal.

**Goal:** a persistent, explainable mood vector that evolves with the
conversation and is surfaced to both the LLM (as natural language in the
system prompt) and the rigging layer (as a selection signal for idle
behaviors, Phase 4).

### The vector

Start small — four scalars, each `[-1.0, 1.0]`:

| Dim | Low end | High end |
|---|---|---|
| `valence` | sad / upset | happy / warm |
| `energy` | tired / sleepy | energetic / hyped |
| `social` | withdrawn / distant | open / chatty |
| `focus` | scattered / distracted | sharp / dialed-in |

Persisted in Tier 3 session memory (Phase 2). Updated after each assistant
turn by a cheap classifier (lightweight local model or a Hermes call with a
fixed format prompt). Decays toward a character-defined baseline over time
— each character has `mood_baseline: {valence: 0.3, energy: 0.0, ...}` in
their identity schema.

### Surfacing it

Every turn, the composer adds a natural-language mood line to the system
prompt:

```
Your current state: warm and open, a little tired tonight, focus is OK
but not peak. Let this color your responses subtly — not theatrically.
```

The _"subtly, not theatrically"_ clause is load-bearing. Without it, LLMs
play mood cues way too hard.

### Phase 3 deliverables

- `src/open_llm_vtuber/persona/mood.py` — the vector, update rules, decay, serialization
- `src/open_llm_vtuber/persona/mood_classifier.py` — one-shot affect classifier
- Mood baseline field in `_persona_schema.yaml`
- Composer integration (injects mood line into system prompt)
- Exported `get_mood()` API for Phase 4 and Phase 5 to consume

Verification:
 - Talk to the character about something sad for 5 turns. `valence` drops.
 - Switch to something exciting. `valence` recovers, `energy` rises.
 - Walk away 30 minutes, come back. Mood has decayed partway toward baseline.
 - Log of mood changes is human-readable for debugging.

---

## Phase 4 — Idle Behavior Brain (E)

**Problem today:** Live2D SDK plays one idle motion on loop. A real person
fidgets differently when bored vs curious vs tired. Our avatars don't.

**Goal:** pool-of-idles selection driven by Phase 3 mood + occasional
micro-behaviors (camera glances, sighs, stretches).

### Design

Each character's `model3.json` now defines **multiple idle pools**, tagged by
mood quadrant:

```json
"Motions": {
  "Idle_calm":    [{"File": "motion/idle_content.motion3.json"}],
  "Idle_tired":   [{"File": "motion/idle_slump.motion3.json"}],
  "Idle_excited": [{"File": "motion/idle_bouncy.motion3.json"}],
  "Idle_focused": [{"File": "motion/idle_leaning_in.motion3.json"}],
  "TapBody":      [...],
  "Talk":         [...]
}
```

A small frontend coordinator picks the pool based on mood, plays one random
motion from it, waits for it to finish, picks again. On a slower timer,
injects micro-behaviors (a single glance-away motion, a 200ms blink-heavy
frame, a head-tilt).

### Phase 4 deliverables

- Patch to `frontend/assets/main-*.js` (or a sidecar JS injected by our server):
  WebSocket message type `mood_update` with the vector → frontend changes
  idle pool selection strategy.
- New motion files for hermes_dark in each of 4 mood pools (we already have
  5 idle motions; re-tag them, author 1-2 more where the pool is thin)
- `src/open_llm_vtuber/persona/idle_coordinator.py` — server-side emits
  mood_update on every mood change
- Documentation update in skill SKILL.md with the new `Idle_*` model3.json convention

Verification:
 - Shift mood low/high-energy. Server logs show `mood_update` going out.
 - Frontend console logs pool switch. Idle motion visibly changes within 10s.

---

## Phase 5 — Continuous Expression (F)

**Problem today:** expressions are keyword tags the LLM types in its response,
like `[happy]`. Hard to tune, hard to modulate, cartoon-y. The keyword only
lets one expression be "on" at a time.

**Goal:** a continuous expression blend per sentence, driven by affect
inferred from the sentence text (not from LLM-emitted tags).

### Design

Each sentence goes through a lightweight affect classifier before it hits
TTS. Output is a blend weight vector over base expressions:

```
"Oh, I'm so sorry to hear that." →
  {compassion: 0.7, sadness: 0.3, smile: 0.0}
```

Feed that blend to the Live2D expression parameters directly — e.g.
`PARAM_BROW_Y = -0.3`, `PARAM_MOUTH_FORM = -0.2`, `PARAM_TERE = 0.4`.
The mood vector from Phase 3 biases the baseline — a sad-mood character's
"happy" never fully reaches 1.0.

### Phase 5 deliverables

- `src/open_llm_vtuber/persona/expression_inference.py` — sentence → blend vector
- `src/open_llm_vtuber/persona/expression_blender.py` — blend vector + mood → parameter deltas
- New WebSocket message type `param_set` — server pushes continuous parameter
  changes per sentence start
- Frontend patch — consume `param_set` and interpolate over sentence duration
- Deprecation path for the `[keyword]` style: still works (back-compat), but
  the new path is preferred and the `live2d_expression_prompt.txt` gets rewritten

Verification:
 - Say a sad sentence, observe brows drop and mouth curve down smoothly
   (not snap to a pose).
 - Overall expression strength bounded by current mood.

---

## What happens to moc3-wrangler?

The `moc3-wrangler/hermes-puppet-engine/` tree is a direct TypeScript .moc3
parser — a research spike that bypasses the Cubism SDK. It is **not** on
any critical path of this plan, but the work is real and worth keeping:
if Live2D ever ships a breaking SDK change, or we need to run in a context
where we can't distribute the Cubism blob, the wrangler becomes the path.

For now: leave it as-is, add a `moc3-wrangler/README.md` clarifying its
status as _"exploratory / reference implementation / not on main code path."_
No time spent polishing it this quarter.

---

## What this plan deliberately defers

- **C (Voice Cloning)** — separate sprint. Requires a consented voice donor
  to be useful. If Leaflit joins, this gets scheduled. If not, we add it as
  a "bring your own dataset" module later.
- **D (Content Ingestion)** — same gate as C. Harvesting public VODs without
  a subject's involvement is not a thing we do by default.
- **ACP client for Phase 1.5** — once all five phases are green, revisit IPC.
- **Group conversation mood** — phase 3's mood vector is per-session. Group
  conversations (OLLV supports these upstream) need per-participant mood;
  we deal with that after phase 5 lands.

---

## Rollout & Safety

Every phase:
 - ships behind a config flag in `conf.yaml` under `persona_v2:` so users
   can toggle the new pipeline off and fall back to today's behavior
 - lands in a feature branch, gets tested against the three public models
   (shizuku, mao_pro, hermes_dark) before merge
 - updates the open-llm-vtuber Hermes skill with new pitfalls and examples
 - adds its new failure modes to the "Troubleshooting" section of the skill

No Nous branding is shipped into public config defaults. The Nova persona
we use as our dev character is gated behind `character_name: Nova` — not
the default.

---

## Tracking

Each phase has its own branch: `persona/phase-1-ipc`, `persona/phase-2-memory`, etc.
Each merges to `main` only with a passing test run on all three public models.

Issues/discussion go in the Hermes Agent repo for community visibility.

---

## Sign-off

This plan has been read and approved by: Mike (author).
Awaiting: Teknium (for Nous-name usage and credit-line offer).
CC when drafted: Open-LLM-VTuber upstream, as a courtesy heads-up on the
direction we're taking the fork.
