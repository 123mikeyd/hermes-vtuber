# Phase 3 — Mood State Machine

**Status:** Shipped on branch `leaf`
**Part of:** [Personality Evolution Plan](../.hermes/plans/2026-04-17_personality-evolution.md)
**Verification:** `scripts/verify_phase3_mood.py`

---

## What this is

A persistent four-dimensional mood vector that rides along with each
character's session, updates after every conversational turn based on
affect, and decays back toward a character-defined baseline between
updates. Surfaces in two places:

1. **Into the LLM system prompt** as a natural-language line
   ("Your current state: warm and upbeat, alert, very open and chatty.
   Let this color your responses subtly — not theatrically.")
2. **Out over the WebSocket (Phase 4 upcoming)** as a `mood_update`
   message — the frontend will use the `quadrant` field to pick the
   right idle-motion pool (`Idle_calm`, `Idle_tired`, `Idle_excited`,
   `Idle_focused`).

---

## The vector

Four scalars, each bounded to `[-1.0, 1.0]`:

| Dim | Low (-1) | High (+1) |
|---|---|---|
| `valence` | sad / hurt | happy / warm |
| `arousal` | tired / sleepy | energetic / buzzing |
| `social` | withdrawn / pulled-back | open / chatty |
| `focus` | scattered / lost | sharp / dialed-in |

The `mood_baseline` already defined in `characters/_persona_schema.yaml`
is what the character decays toward when nothing is stimulating them.
Nova's baseline: `valence=0.3, arousal=0.1, social=0.4, focus=0.5` —
so her default resting state is warm, moderately open, and dialed-in.

---

## Decay

Exponential, half-life of `MOOD_HALFLIFE_SECONDS = 120` (two minutes).
Practical meaning:

- A one-off sad sentence pushes valence down, then fades ~75% back
  toward baseline within four minutes of no further stimulus.
- A sustained sad conversation (one nudge every 30 seconds or so)
  keeps topping the mood up and it stays there.
- Walking away for ten minutes returns the character to near-baseline.

Implementation: `MoodState.decay_to_now(now=None)` computes
`factor = (1/2) ** (elapsed / halflife)` and linearly interpolates
every dimension from its current value toward the baseline value.

---

## Updates — how mood actually changes

After every assistant turn, the agent calls `mood_classify(user_text,
assistant_text)` which returns a `MoodDelta`. That delta gets fed into
`MoodState.apply_delta()`, which:

1. Decays mood first (catch up to wall-clock)
2. Adds `MOOD_UPDATE_WEIGHT * delta` to each axis (weight = 0.3)
3. Clamps to [-1, 1]
4. Updates `last_update` timestamp

So a full-magnitude sad delta `(valence=-1.0)` shifts valence by
-0.3 per turn, not -1.0. Conversations nudge, they don't yank.

---

## Why a heuristic classifier (for now)

The plan doc mentioned "cheap classifier (lightweight local model or
a Hermes call)." We chose heuristic for Phase 3 because:

- **Speed**: runs in microseconds, no subprocess per turn
- **Explainability**: every log line shows which words hit which lexicon
- **Zero dependencies**: no transformer, no tokenizer, no model download
- **Swappable**: interface is `classify(user_text, assistant_text) -> MoodDelta`.
  If this proves too noisy in practice, we drop in a transformer-based
  classifier later without touching anything else.

Lexicons are intentionally small. Adding words on false negatives is
cheap; a big lexicon with false positives is miserable. See
`mood_classifier.py` for the full tuning strategy.

Explicit expression-keyword tags that the LLM might emit (`[happy]`,
`[sad]`, `[angry]` etc.) get STRONGER deltas than lexicon hits —
they're explicit signals, not guesses. The classifier respects them.

---

## What the LLM actually sees

The composer appends a `## Current State` section to the system prompt
on turn 1 of each new hermes session. Example output after three sad
exchanges with Nova's baseline:

```
...
## Current State
Your current state: low / down, tired. Let this color your responses
subtly — not theatrically.
```

The "subtly, not theatrically" clause is load-bearing. Without it,
LLMs play mood cues WAY too hard and sound melodramatic. Tested both
ways, kept the clause.

---

## Quadrants → Phase 4 idle pools

`MoodState.quadrant()` collapses the four-dim vector to one of:

- `"calm"`     — low-ish arousal, non-negative valence → `Idle_calm`
- `"tired"`    — low arousal, negative valence        → `Idle_tired`
- `"excited"`  — high arousal, non-negative valence   → `Idle_excited`
- `"focused"`  — high arousal AND high focus          → `Idle_focused`

Phase 4 will push these labels over WebSocket and the frontend will
switch motion pools based on them.

---

## Persistence

Mood lives INSIDE the existing `SessionMemory` JSON (no new file).
Serialized field:

```json
{
  "turns": [...],
  "rolling_summary": "...",
  "turns_since_summary": 2,
  "mood": {
    "baseline": {"valence": 0.3, "arousal": 0.1, ...},
    "valence": -0.81,
    "arousal": 0.0,
    "social": 0.0,
    "focus": 0.0,
    "last_update": 1776423456.78
  }
}
```

Loading is forward-compatible — existing JSON files from Phase 2a
(no `mood` field) load cleanly and `ensure_mood(baseline)` creates
a fresh vector on first agent turn.

---

## Verification

```bash
cd /home/mikeyd/hermes-vtuber
python3 scripts/verify_phase3_mood.py
```

Eight tests, all must pass:

1. MoodState starts at baseline
2. Values clamp to [-1, 1] if given out-of-range input
3. Decay math: 1 half-life = halfway, 3 half-lives = 1/8th distance
4. `apply_delta` moves by `weight * delta`, clamps, timestamps
5. JSON roundtrip preserves all 4 axes + baseline
6. Classifier: happy text gets +valence/+arousal, sad text gets
   -valence, neutral text stays near zero, `[angry]` tag gets
   -valence/+arousal
7. Composer includes mood line in the prompt when mood is set
8. LIVE: sad deltas drop valence, happy deltas raise it, quadrant
   transitions from `calm` → `tired` → `excited`, and mood survives
   save+reload

Phase 1 (`verify_phase1_ipc.py`) and Phase 2a (`verify_phase2a_persona.py`)
both still pass. No regressions.

---

## What this does NOT do yet

- **Frontend consumption**: `mood_update` WebSocket message is not
  emitted yet. Will be added in Phase 4 alongside the idle pool
  selector on the frontend.
- **Expression continuous blend**: sentence-level affect analysis
  driving Live2D parameters in real time is Phase 5 (F).
- **Group conversations**: mood is per-session, not per-participant.
  OLLV's group conversation support is untouched for now.

---

## Credit

The exponential-decay-toward-baseline pattern comes directly from
the affect dynamics literature — Russell's circumplex model of
affect (1980) defines the valence + arousal plane we extend here;
Mehrabian's PAD (Pleasure/Arousal/Dominance) model also uses
decay-to-baseline. Nothing novel — disciplined engineering on top
of forty-year-old psych research, wired into the persona pipeline
Phase 2a built.

The classifier is pure heuristic, inspired loosely by VADER sentiment
(Hutto & Gilbert 2014) but simpler — small lexicons, explicit
boosters, no negation handling yet.
