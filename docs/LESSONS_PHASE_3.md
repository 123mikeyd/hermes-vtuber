# Phase 3 Lessons — Naming Matters; Tree Mirroring; Motion Parsing

**Status:** Lessons from the Phase 3 implementation, April 17 2026
**Context:** The arousal→energy rename, the hermes_dark four_arm_deity_dance
bug, and the OLLV-vs-fork tree divergence issue.

These are captured here (not in the main skill file) because the
skill security scanner has a standing flag on older scripts and
re-patching it requires confirmation. This doc carries the lesson
text permanently in the repo, where it will be found by the next
person doing related work.

---

## Naming: "arousal" is a terminology landmine for AI projects

Russell's circumplex model of affect (1980) and Mehrabian's PAD model
both use "arousal" to mean activation / energy level / physiological
alertness. It's correct psychology terminology. Use it in an academic
paper and reviewers nod.

Use it in a VTuber project's system prompt, config YAML, log lines,
commit messages, or README and the EVERYDAY ENGLISH reading dominates.
Your code will be read by:
 - Streamers
 - Chat moderators
 - Potential collaborators who are not ML researchers
 - Casual contributors reading GitHub issues

All of whom will parse "arousal" as sex-adjacent first and ask questions
later. For a project meant to be shared — especially one involving
anime-styled characters — this is a trust cost with no upside.

**Rule:** For any AI character / persona / companion project going
public, run terminology through the "how does this read to someone
with zero psychology background" filter.

Flagged terms to avoid or rename:
  arousal → **energy** (what we landed on)
  stimulation → engagement
  drive → motivation
  excitation → activation (ironically clearer)

Mike (user) flagged this on Phase 3 ship night. I had shipped
`MoodBaseline(arousal=0.1)` straight from Russell's paper without
thinking about the reading room. 185 occurrences to rename. Not the
kind of mistake to repeat.

---

## Backward-compat rename pattern

When renaming a persisted field, accept BOTH keys on load:

```python
@classmethod
def from_dict(cls, data: Dict[str, Any]) -> "MoodState":
    # New key takes priority; fall back to old key; then default.
    energy = float(data.get("energy", data.get("arousal", default)))
```

Next `save()` writes only the new key. Old key quietly disappears
from disk on first write after upgrade. No migration script needed.
Tested against live nova.json with 14 accumulated turns — all
values preserved.

Same shim in two places:
 - `MoodState.from_dict` (per-session JSON)
 - `load_identity` YAML loader (character config files)

---

## OLLV tree ≠ hermes-vtuber repo — manually mirror or the server doesn't see your edits

The live server runs `run_server.py` from `~/Open-LLM-VTuber/` which
imports from its own `src/open_llm_vtuber/` tree. The fork at
`~/hermes-vtuber/` is a SEPARATE clone.

If you edit only in `~/hermes-vtuber/`, the server will not pick it up.
You MUST mirror every touched file:

```bash
# After editing in ~/hermes-vtuber/, sync to OLLV:
cp ~/hermes-vtuber/src/open_llm_vtuber/persona/*.py \
   ~/Open-LLM-VTuber/src/open_llm_vtuber/persona/

cp ~/hermes-vtuber/src/open_llm_vtuber/agent/agents/hermes_agent.py \
   ~/Open-LLM-VTuber/src/open_llm_vtuber/agent/agents/

cp ~/hermes-vtuber/src/open_llm_vtuber/agent/agent_factory.py \
   ~/Open-LLM-VTuber/src/open_llm_vtuber/agent/

cp ~/hermes-vtuber/characters/_persona_schema.yaml \
   ~/Open-LLM-VTuber/characters/

# Verify sync before restarting server:
diff -r ~/hermes-vtuber/src/open_llm_vtuber/persona \
        ~/Open-LLM-VTuber/src/open_llm_vtuber/persona
```

**Pitfall I hit:** a prior session had already mirrored `agent_factory.py`
and edited `conf.yaml` into OLLV. Coming back fresh, I assumed the
integration code was missing from `leaf` (true) AND from the live
server (false). Spent time "wiring" integration that was already live.
Always diff BOTH trees before planning work.

---

## Live2D motion3.json segment parser

Curves in `.motion3.json` use typed segments. Three types:

```
0 = linear:  [type, time, value]                           (3 floats per segment)
1 = bezier:  [type, c1t, c1v, c2t, c2v, endt, endv]        (7 floats per segment)
2 = stepped: [type, time, value]                           (3 floats per segment)
3 = inverse-stepped: [type, time, value]                   (3 floats per segment)
```

First keyframe is ALWAYS `[time, value]` (2 floats), not a typed segment.
Subsequent keyframes ARE typed segments.

Naive parser that assumes "every 3 floats is time/value" will:
 - Misread bezier control-point times as keyframe times
 - Produce spurious "max values" by including time coordinates
 - Report "opacity 13.0" when the file actually has opacity 1.0 at t=13s

Correct walker:

```python
def extract_values(segments):
    """Extract just the VALUE coordinates (not times) from a curve."""
    vals = []
    if not segments or len(segments) < 2:
        return vals
    vals.append(segments[1])  # first keyframe is [time, value]
    i = 2
    while i < len(segments):
        seg_type = int(segments[i])
        try:
            if seg_type == 0:
                vals.append(segments[i + 2]); i += 3
            elif seg_type == 1:
                # bezier: end-value only (the real keyframe)
                vals.append(segments[i + 6]); i += 7
            elif seg_type in (2, 3):
                vals.append(segments[i + 2]); i += 3
            else:
                i += 1
        except IndexError:
            # File is malformed (truncated bezier, etc.). Bail safely.
            break
    return vals
```

**Real-world caveat:** authoring tools DO produce malformed bezier
segments with truncated float groups (found `four_arm_deity_dance.motion3.json`
with an incomplete 7-float group at the tail). The Cubism SDK silently
tolerates this (it may just skip the curve). Your audit code must too.

**Use case: arm-disappearance audit**

```python
# Check if a motion ever leaves both arm layers at opacity 0 simultaneously
for side in ("L", "R"):
    if "01" in layers and "02" in layers:
        min_01, _ = layers["01"]
        min_02, _ = layers["02"]
        if min_01 < 0.05 and min_02 < 0.05:
            print(f"BUG: {side}-arm — both layers hit 0 → arm disappears")
```

Found `four_arm_deity_dance.motion3.json` in hermes_dark's Idle pool
with malformed bezier + all 4 arm layers at opacity 1.0 (intended
"four-arm deity" effect, never completed). Caused random arm-vanish
during idle. Pulled from pool, file preserved on disk for later
repurposing as a refusal/poor-taste-trigger motion.

---

## Git recovery without force-push

When a commit goes sideways (gitignore blocks part of staged set,
accidental `--amend` squashes files into the wrong commit, etc.),
recover without force-push:

```bash
# Rewind to match origin — keeps working tree intact, restages everything
git reset --soft origin/BRANCH

# Everything that was in bad commits is now staged.
# Re-split and re-commit cleanly:
git reset HEAD <files>               # un-stage what belongs elsewhere
git commit -m "clean commit 1"

git add <other files>
git commit -m "clean commit 2"

# Push normally. No --force needed. No --force-with-lease needed.
git push origin BRANCH
```

Why this works: `reset --soft` moves only HEAD. Index and working
tree are untouched. You get to redo the commit sequence with
hindsight but no state loss.

When a user blocks `git push --force` (which is the safe default
posture), this is the clean fallback. Tested Apr 17 2026 during
Phase 2a commit recovery — worked on first try.

---

## Cross-reference

Main skill: `autonomous-ai-agents/open-llm-vtuber`
Plan doc: `.hermes/plans/2026-04-17_personality-evolution.md`
Prior lessons: `docs/PHASE_1_IPC.md`, `docs/PHASE_2A_PERSONA.md`,
              `docs/PHASE_3_MOOD.md`
