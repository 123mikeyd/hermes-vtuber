"""
Phase 4.5 — author richer, clearly-distinct idle motions per quadrant.

Each motion has a baseline facial expression that's visibly different
from the others even before any per-sentence blend lands on top. The
goal: you can tell Nova's mood at a glance from her idle pose alone.

All motions use the B-layer arm pose (PARTS_01_ARM_*_02 = 1.0) so
they compose cleanly with the rest of hermes_dark's idle pool and
don't switch arm artwork mid-motion.

Authored motions:

  calm/    idle_calm_warm.motion3.json
    Small warm smile baked in, eyes softly focused on camera, gentle
    head sway, occasional slow blink. Reads as 'content and present'.

  excited/ idle_excited_bouncy.motion3.json
    Eyes wider at baseline, brows slightly up, bigger head bob,
    faster blink cadence. Reads as 'amped, engaged, loving this'.

  focused/ idle_focused_intent.motion3.json
    Head forward tilt, eyes NARROWED (not closed — just intense),
    brows slightly drawn, minimal sway. Reads as 'locked in'.

  tired/   idle_tired_slump.motion3.json
    Head droop, heavy half-lids, LONG slow blinks, slightly lower
    body position. Very little movement. Reads as 'running on fumes'.

All are 12 seconds, looping, restricted-bezier — well above the 8-9s
loop-boundary floor you specified earlier.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Sequence, Tuple


MODEL_DIR = Path(
    "/home/mikeyd/Open-LLM-VTuber/live2d-models/hermes_dark/runtime/motion"
)
MIRROR_DIRS = [
    Path(
        "/home/mikeyd/hermes-vtuber/live2d-models/hermes_dark/runtime/motion"
    ),
]


# --------------------------------------------------------------------------
# Motion3.json helpers (same format as author_phase4_motions.py, kept
# local so this file stays self-contained).
# --------------------------------------------------------------------------

def bezier_curve(param_id: str,
                 keyframes: Sequence[Tuple[float, float]],
                 target: str = "Parameter") -> dict:
    if len(keyframes) < 2:
        raise ValueError("Need at least 2 keyframes")
    segments: List[float] = []
    t0, v0 = keyframes[0]
    segments.extend([float(t0), float(v0)])
    for (prev_t, prev_v), (t, v) in zip(keyframes, keyframes[1:]):
        dt = t - prev_t
        cp1_t = prev_t + dt * 0.33
        cp2_t = prev_t + dt * 0.66
        segments.extend([
            1,
            float(cp1_t), float(prev_v),
            float(cp2_t), float(v),
            float(t), float(v),
        ])
    return {"Target": target, "Id": param_id, "Segments": segments}


def hold(param_id: str, value: float, duration: float,
         target: str = "Parameter") -> dict:
    return bezier_curve(param_id, [(0.0, value), (duration, value)], target)


def build_motion(curves: Sequence[dict], duration: float,
                 fps: float = 30.0, loop: bool = True) -> dict:
    total_segments = sum(len(c["Segments"]) for c in curves)
    return {
        "Version": 3,
        "Meta": {
            "Duration": float(duration),
            "Fps": float(fps),
            "Loop": bool(loop),
            "AreBeziersRestricted": True,
            "CurveCount": len(curves),
            "TotalSegmentCount": total_segments,
            "TotalPointCount": total_segments,
            "UserDataCount": 0,
            "TotalUserDataSize": 0,
        },
        "Curves": list(curves),
    }


# B-layer arm pose curves — same for every idle so layer stays consistent.
def arm_layer_b(duration: float) -> List[dict]:
    return [
        hold("PARTS_01_ARM_L_02", 1.0, duration, target="PartOpacity"),
        hold("PARTS_01_ARM_R_02", 1.0, duration, target="PartOpacity"),
        hold("PARTS_01_ARM_L_01", 0.0, duration, target="PartOpacity"),
        hold("PARTS_01_ARM_R_01", 0.0, duration, target="PartOpacity"),
        hold("PARAM_ARM_02_L", 0.0, duration),
        hold("PARAM_ARM_02_R", 0.0, duration),
    ]


# --------------------------------------------------------------------------
# CALM — warm, content, softly present
# --------------------------------------------------------------------------

def author_calm_warm(duration: float = 12.0) -> dict:
    """Baseline warm Nova. Visible small smile, soft eyes, gentle sway."""
    curves = [
        # Head: gentle sway, slight nod
        bezier_curve("PARAM_ANGLE_X", [
            (0.0, 0.0),
            (4.0, 3.0),
            (8.0, -2.0),
            (duration, 0.0),
        ]),
        bezier_curve("PARAM_ANGLE_Y", [
            (0.0, 2.0),
            (6.0, 0.0),
            (duration, 2.0),
        ]),
        bezier_curve("PARAM_ANGLE_Z", [
            (0.0, 0.0),
            (5.0, 1.5),
            (duration, 0.0),
        ]),

        # Eyes: open, soft. One slow blink mid-loop, one quick near end.
        bezier_curve("PARAM_EYE_L_OPEN", [
            (0.0, 0.85),
            (4.0, 0.85),
            (4.3, 0.0),          # slow blink
            (4.7, 0.85),
            (9.0, 0.85),
            (9.15, 0.0),         # quick blink
            (9.3, 0.85),
            (duration, 0.85),
        ]),
        bezier_curve("PARAM_EYE_R_OPEN", [
            (0.0, 0.85),
            (4.0, 0.85),
            (4.3, 0.0),
            (4.7, 0.85),
            (9.0, 0.85),
            (9.15, 0.0),
            (9.3, 0.85),
            (duration, 0.85),
        ]),
        hold("PARAM_EYE_BALL_X", 0.0, duration),
        hold("PARAM_EYE_BALL_Y", 0.0, duration),

        # Brows: neutral, slight lift (friendly)
        hold("PARAM_BROW_L_Y", 0.1, duration),
        hold("PARAM_BROW_R_Y", 0.1, duration),

        # Mouth: BAKED-IN SMALL SMILE (this is the visible "warm" cue)
        hold("PARAM_MOUTH_OPEN_Y", 0.0, duration),
        hold("PARAM_MOUTH_FORM", 0.30, duration),

        # Body: soft breathing
        bezier_curve("PARAM_BODY_Y", [
            (0.0, -0.15),
            (3.0, -0.10),
            (6.0, -0.15),
            (9.0, -0.10),
            (duration, -0.15),
        ]),

        # Light blush — she's in a good mood
        hold("PARAM_TERE", 0.15, duration),
    ]
    curves.extend(arm_layer_b(duration))
    return build_motion(curves, duration=duration, loop=True)


# --------------------------------------------------------------------------
# EXCITED — amped, eyes bright, bigger motion
# --------------------------------------------------------------------------

def author_excited_bouncy(duration: float = 12.0) -> dict:
    """Visibly more energy. Wider eyes, brows up, bigger head bob."""
    curves = [
        # Head: bigger sway, more bob — like she's vibing
        bezier_curve("PARAM_ANGLE_X", [
            (0.0, 0.0),
            (2.0, 6.0),
            (4.0, -3.0),
            (6.0, 6.0),
            (8.0, -3.0),
            (10.0, 5.0),
            (duration, 0.0),
        ]),
        bezier_curve("PARAM_ANGLE_Y", [
            (0.0, 3.0),       # head more upright (proud/engaged)
            (3.0, 5.0),
            (6.0, 3.0),
            (9.0, 5.0),
            (duration, 3.0),
        ]),
        bezier_curve("PARAM_ANGLE_Z", [
            (0.0, 0.0),
            (2.0, 3.0),
            (4.0, -2.0),
            (6.0, 3.0),
            (8.0, -2.0),
            (duration, 0.0),
        ]),

        # Eyes: wider at baseline. Faster blinks.
        bezier_curve("PARAM_EYE_L_OPEN", [
            (0.0, 1.0),
            (3.0, 1.0),
            (3.1, 0.0),
            (3.2, 1.0),
            (7.0, 1.0),
            (7.1, 0.0),
            (7.2, 1.0),
            (duration, 1.0),
        ]),
        bezier_curve("PARAM_EYE_R_OPEN", [
            (0.0, 1.0),
            (3.0, 1.0),
            (3.1, 0.0),
            (3.2, 1.0),
            (7.0, 1.0),
            (7.1, 0.0),
            (7.2, 1.0),
            (duration, 1.0),
        ]),

        # Eyeballs: a little darty (excitement)
        bezier_curve("PARAM_EYE_BALL_X", [
            (0.0, 0.0),
            (3.0, 0.2),
            (6.0, -0.15),
            (9.0, 0.2),
            (duration, 0.0),
        ]),
        hold("PARAM_EYE_BALL_Y", 0.1, duration),

        # Brows: raised at baseline (that surprised-delighted look)
        hold("PARAM_BROW_L_Y", 0.35, duration),
        hold("PARAM_BROW_R_Y", 0.35, duration),

        # Mouth: open smile baked in
        hold("PARAM_MOUTH_OPEN_Y", 0.20, duration),
        hold("PARAM_MOUTH_FORM", 0.60, duration),

        # Body: bouncier breathing
        bezier_curve("PARAM_BODY_Y", [
            (0.0, -0.05),
            (2.0, 0.05),
            (4.0, -0.05),
            (6.0, 0.05),
            (8.0, -0.05),
            (10.0, 0.05),
            (duration, -0.05),
        ]),

        # Noticeable blush — flushed with enjoyment
        hold("PARAM_TERE", 0.40, duration),
    ]
    curves.extend(arm_layer_b(duration))
    return build_motion(curves, duration=duration, loop=True)


# --------------------------------------------------------------------------
# FOCUSED — locked in, less motion, narrower eyes
# --------------------------------------------------------------------------

def author_focused_intent(duration: float = 12.0) -> dict:
    """Leaning in, eyes narrowed (not closed, just intent), brows drawn."""
    curves = [
        # Head: forward tilt, barely moves
        bezier_curve("PARAM_ANGLE_X", [
            (0.0, 1.0),
            (6.0, -1.0),
            (duration, 1.0),
        ]),
        bezier_curve("PARAM_ANGLE_Y", [
            (0.0, 4.0),          # head forward (reading something)
            (6.0, 5.0),
            (duration, 4.0),
        ]),
        bezier_curve("PARAM_ANGLE_Z", [
            (0.0, 2.0),          # slight tilt, "listening"
            (duration, 2.0),
        ]),

        # Eyes: NARROWED (0.55, not closed). Single sharp blink.
        bezier_curve("PARAM_EYE_L_OPEN", [
            (0.0, 0.55),
            (6.0, 0.55),
            (6.15, 0.0),
            (6.3, 0.55),
            (duration, 0.55),
        ]),
        bezier_curve("PARAM_EYE_R_OPEN", [
            (0.0, 0.55),
            (6.0, 0.55),
            (6.15, 0.0),
            (6.3, 0.55),
            (duration, 0.55),
        ]),

        # Eyeballs: locked on center (she's looking AT you)
        hold("PARAM_EYE_BALL_X", 0.0, duration),
        hold("PARAM_EYE_BALL_Y", 0.0, duration),

        # Brows: slightly drawn-together (concentrating look)
        hold("PARAM_BROW_L_Y", -0.10, duration),
        hold("PARAM_BROW_R_Y", -0.10, duration),
        hold("PARAM_BROW_L_ANGLE", -0.15, duration),
        hold("PARAM_BROW_R_ANGLE", 0.15, duration),

        # Mouth: neutral, very slight firm-line
        hold("PARAM_MOUTH_OPEN_Y", 0.0, duration),
        hold("PARAM_MOUTH_FORM", 0.05, duration),

        # Body: still, shallow breathing
        bezier_curve("PARAM_BODY_Y", [
            (0.0, -0.08),
            (6.0, -0.05),
            (duration, -0.08),
        ]),

        # No blush
        hold("PARAM_TERE", 0.0, duration),
    ]
    curves.extend(arm_layer_b(duration))
    return build_motion(curves, duration=duration, loop=True)


# --------------------------------------------------------------------------
# TIRED — slumpy, heavy lids, minimal motion
# --------------------------------------------------------------------------

def author_tired_slump(duration: float = 12.0) -> dict:
    """Very low energy read. Big slow blinks, drooped head, slight sag."""
    curves = [
        # Head: droops down and slightly aside, barely moves
        bezier_curve("PARAM_ANGLE_X", [
            (0.0, -4.0),
            (7.0, -6.0),
            (duration, -4.0),
        ]),
        bezier_curve("PARAM_ANGLE_Y", [
            (0.0, -7.0),         # head down
            (6.0, -9.0),
            (duration, -7.0),
        ]),
        bezier_curve("PARAM_ANGLE_Z", [
            (0.0, -3.0),         # head tilted over, tired
            (duration, -3.0),
        ]),

        # Eyes: HEAVY half-lids most of the time, TWO long slow blinks
        bezier_curve("PARAM_EYE_L_OPEN", [
            (0.0, 0.40),
            (3.0, 0.40),
            (3.5, 0.0),          # long blink 1
            (4.2, 0.0),
            (4.6, 0.40),
            (8.0, 0.40),
            (8.5, 0.0),          # long blink 2
            (9.2, 0.0),
            (9.6, 0.40),
            (duration, 0.40),
        ]),
        bezier_curve("PARAM_EYE_R_OPEN", [
            (0.0, 0.40),
            (3.0, 0.40),
            (3.5, 0.0),
            (4.2, 0.0),
            (4.6, 0.40),
            (8.0, 0.40),
            (8.5, 0.0),
            (9.2, 0.0),
            (9.6, 0.40),
            (duration, 0.40),
        ]),

        # Gaze drifts down
        hold("PARAM_EYE_BALL_X", -0.1, duration),
        hold("PARAM_EYE_BALL_Y", -0.4, duration),

        # Brows: lowered, tired (not angry — just down)
        hold("PARAM_BROW_L_Y", -0.3, duration),
        hold("PARAM_BROW_R_Y", -0.3, duration),

        # Mouth: neutral-to-slightly-downturned
        hold("PARAM_MOUTH_OPEN_Y", 0.0, duration),
        hold("PARAM_MOUTH_FORM", -0.20, duration),

        # Body: slumped, slow shallow breathing
        bezier_curve("PARAM_BODY_Y", [
            (0.0, -0.50),
            (4.0, -0.55),
            (8.0, -0.50),
            (duration, -0.55),
        ]),

        # No blush (not flushed, just drained)
        hold("PARAM_TERE", 0.0, duration),
    ]
    curves.extend(arm_layer_b(duration))
    return build_motion(curves, duration=duration, loop=True)


# --------------------------------------------------------------------------
# Write
# --------------------------------------------------------------------------

def main() -> None:
    outputs = [
        ("idle_calm_warm.motion3.json",       author_calm_warm()),
        ("idle_excited_bouncy.motion3.json",  author_excited_bouncy()),
        ("idle_focused_intent.motion3.json",  author_focused_intent()),
        ("idle_tired_slump.motion3.json",     author_tired_slump()),
    ]
    for filename, motion in outputs:
        for d in [MODEL_DIR, *MIRROR_DIRS]:
            d.mkdir(parents=True, exist_ok=True)
            p = d / filename
            with p.open("w", encoding="utf-8") as f:
                json.dump(motion, f, indent=2)
            meta = motion["Meta"]
            print(
                f"  wrote {p}  "
                f"({meta['Duration']:.1f}s, {meta['CurveCount']} curves)"
            )


if __name__ == "__main__":
    main()
