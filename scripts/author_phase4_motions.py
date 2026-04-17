"""
Author two idle motions for hermes_dark to fill Phase 4 pool gaps:

  - motion/idle_tired_droop.motion3.json
        Low energy, slight head droop, slow blinks, quiet body.
        Target: the "tired" quadrant pool (pairs with creeper_!).

  - motion/idle_focused_lean.motion3.json
        Forward-leaning engaged focus, subtle head tilt, slightly
        narrower eyes. Target: the "focused" quadrant pool
        (pairs with idle_calm_02).

Both motions use the B-layer arm pose (PARTS_01_ARM_*_02 = 1.0) so
they're compatible with the rest of the hermes_dark idles and won't
switch arm artwork mid-pool. Duration 10s each, looping, gentle bezier
interpolation. Deliberately SIMPLE — anyone with the Cubism Editor can
replace them later with hand-rigged motions.

Run this once to generate the files. Idempotent — overwrites existing
files of the same name each run.
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


def bezier_curve(
    param_id: str,
    keyframes: Sequence[Tuple[float, float]],
    target: str = "Parameter",
) -> dict:
    """Build a Cubism motion3.json curve with bezier segments.

    keyframes is [(time_seconds, value), ...] strictly ascending by time.
    Each segment between consecutive keyframes uses bezier type 1 with
    control points at 33% and 66% of the time interval — smooth ease
    in/out without overshoot.
    """
    if len(keyframes) < 2:
        raise ValueError("Need at least 2 keyframes")

    segments: List[float] = []
    # First point is just [time, value]
    t0, v0 = keyframes[0]
    segments.extend([float(t0), float(v0)])

    for (prev_t, prev_v), (t, v) in zip(keyframes, keyframes[1:]):
        # Bezier segment: type=1, cp1_t, cp1_v, cp2_t, cp2_v, end_t, end_v
        dt = t - prev_t
        cp1_t = prev_t + dt * 0.33
        cp2_t = prev_t + dt * 0.66
        segments.extend([
            1,              # bezier
            float(cp1_t), float(prev_v),
            float(cp2_t), float(v),
            float(t), float(v),
        ])

    return {
        "Target": target,
        "Id": param_id,
        "Segments": segments,
    }


def stepped_hold(param_id: str, value: float, duration: float,
                 target: str = "Parameter") -> dict:
    """Hold a parameter at a constant value for the full duration."""
    return bezier_curve(param_id, [(0.0, value), (duration, value)], target)


def build_motion(curves: Sequence[dict], duration: float,
                 fps: float = 30.0, loop: bool = True) -> dict:
    """Wrap a list of curves in a full motion3.json document."""
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


# ---------------------------------------------------------------------------
# idle_tired_droop — LOW energy, slight head droop, slow blinks
# ---------------------------------------------------------------------------

def author_tired_droop(duration: float = 10.0) -> dict:
    """Tired-quadrant idle. Head drifts down gently. Eyes half-lidded
    most of the time with a slow blink at 4.5s. Slight slump — body
    position slightly lower than default, no blush, neutral mouth.

    All parameter ranges are SMALL on purpose. We want "barely moving"
    not dramatic slumping — that would read as sad, not tired.
    """
    curves = [
        # --- Head: small droop pattern ---
        # ANGLE_X slight aside (-5 to +5 degrees range), lazy drift
        bezier_curve("PARAM_ANGLE_X", [
            (0.0, -3.0),
            (3.0, -5.0),
            (6.0, -2.0),
            (duration, -3.0),
        ]),
        # ANGLE_Y DOWN a few degrees (head droop)
        bezier_curve("PARAM_ANGLE_Y", [
            (0.0, -4.0),
            (5.0, -6.0),
            (duration, -4.0),
        ]),
        # ANGLE_Z very slight roll
        bezier_curve("PARAM_ANGLE_Z", [
            (0.0, 0.0),
            (duration, -2.0),
        ]),

        # --- Eyes: half-lidded most of the time, one slow blink ---
        bezier_curve("PARAM_EYE_L_OPEN", [
            (0.0, 0.55),     # half-lidded
            (4.0, 0.55),
            (4.3, 0.0),      # blink begins
            (4.5, 0.0),      # eyes closed briefly
            (4.8, 0.55),     # reopen to half-lidded
            (duration, 0.55),
        ]),
        bezier_curve("PARAM_EYE_R_OPEN", [
            (0.0, 0.55),
            (4.0, 0.55),
            (4.3, 0.0),
            (4.5, 0.0),
            (4.8, 0.55),
            (duration, 0.55),
        ]),
        # Eyes drift slightly downward
        bezier_curve("PARAM_EYE_BALL_X", [
            (0.0, 0.0),
            (5.0, -0.2),
            (duration, 0.0),
        ]),
        bezier_curve("PARAM_EYE_BALL_Y", [
            (0.0, -0.3),
            (duration, -0.3),
        ]),

        # --- Brows: slightly lowered (tired brows, not angry) ---
        stepped_hold("PARAM_BROW_L_Y", -0.2, duration),
        stepped_hold("PARAM_BROW_R_Y", -0.2, duration),

        # --- Mouth: neutral-closed, no expression ---
        stepped_hold("PARAM_MOUTH_OPEN_Y", 0.0, duration),
        stepped_hold("PARAM_MOUTH_FORM", -0.2, duration),

        # --- Body: slightly lower position (slumpy), slow breathing ---
        bezier_curve("PARAM_BODY_Y", [
            (0.0, -0.4),
            (3.0, -0.45),
            (6.0, -0.4),
            (duration, -0.4),
        ]),

        # --- B-arm layer (hands up, resting pose), very still ---
        stepped_hold("PARAM_ARM_02_L", 0.0, duration),
        stepped_hold("PARAM_ARM_02_R", 0.0, duration),

        # --- Part opacity: B-arm layer ON, A-arm layer OFF ---
        stepped_hold("PARTS_01_ARM_L_02", 1.0, duration, target="PartOpacity"),
        stepped_hold("PARTS_01_ARM_R_02", 1.0, duration, target="PartOpacity"),
        stepped_hold("PARTS_01_ARM_L_01", 0.0, duration, target="PartOpacity"),
        stepped_hold("PARTS_01_ARM_R_01", 0.0, duration, target="PartOpacity"),

        # --- No blush ---
        stepped_hold("PARAM_TERE", 0.0, duration),
    ]
    return build_motion(curves, duration=duration, loop=True)


# ---------------------------------------------------------------------------
# idle_focused_lean — ENGAGED, slight forward lean, dialed in
# ---------------------------------------------------------------------------

def author_focused_lean(duration: float = 10.0) -> dict:
    """Focused-quadrant idle. Head tilts slightly forward and to one
    side (classic "listening intently" pose). Eyes slightly narrowed
    (reading-something concentration). One blink mid-loop. No blush.
    Body forward a bit.
    """
    curves = [
        # --- Head: slight tilt + forward lean ---
        bezier_curve("PARAM_ANGLE_X", [
            (0.0, 2.0),
            (4.0, 5.0),
            (7.0, 2.0),
            (duration, 2.0),
        ]),
        bezier_curve("PARAM_ANGLE_Y", [
            (0.0, 2.0),    # head slightly UP (forward, not slumped)
            (5.0, 3.0),
            (duration, 2.0),
        ]),
        bezier_curve("PARAM_ANGLE_Z", [
            (0.0, 3.0),    # slight tilt (engaged listener)
            (duration, 3.0),
        ]),

        # --- Eyes: slightly narrowed, alert, one crisp blink ---
        bezier_curve("PARAM_EYE_L_OPEN", [
            (0.0, 0.85),
            (5.0, 0.85),
            (5.15, 0.0),     # fast blink
            (5.3, 0.85),
            (duration, 0.85),
        ]),
        bezier_curve("PARAM_EYE_R_OPEN", [
            (0.0, 0.85),
            (5.0, 0.85),
            (5.15, 0.0),
            (5.3, 0.85),
            (duration, 0.85),
        ]),
        # Gaze slightly off-center (looking at user's eyes / at screen)
        bezier_curve("PARAM_EYE_BALL_X", [
            (0.0, 0.1),
            (4.0, 0.05),
            (duration, 0.1),
        ]),
        stepped_hold("PARAM_EYE_BALL_Y", 0.1, duration),

        # --- Brows: neutral-to-slightly-raised (interested) ---
        stepped_hold("PARAM_BROW_L_Y", 0.1, duration),
        stepped_hold("PARAM_BROW_R_Y", 0.1, duration),

        # --- Mouth: slight closed smile, engaged ---
        stepped_hold("PARAM_MOUTH_OPEN_Y", 0.0, duration),
        stepped_hold("PARAM_MOUTH_FORM", 0.15, duration),

        # --- Body: forward (lean in), subtle breathing ---
        bezier_curve("PARAM_BODY_Y", [
            (0.0, -0.1),
            (4.0, -0.05),
            (8.0, -0.1),
            (duration, -0.1),
        ]),

        # --- B-arm layer, still ---
        stepped_hold("PARAM_ARM_02_L", 0.0, duration),
        stepped_hold("PARAM_ARM_02_R", 0.0, duration),

        # --- Part opacity: B-arm ON, A-arm OFF ---
        stepped_hold("PARTS_01_ARM_L_02", 1.0, duration, target="PartOpacity"),
        stepped_hold("PARTS_01_ARM_R_02", 1.0, duration, target="PartOpacity"),
        stepped_hold("PARTS_01_ARM_L_01", 0.0, duration, target="PartOpacity"),
        stepped_hold("PARTS_01_ARM_R_01", 0.0, duration, target="PartOpacity"),

        # --- No blush ---
        stepped_hold("PARAM_TERE", 0.0, duration),
    ]
    return build_motion(curves, duration=duration, loop=True)


# ---------------------------------------------------------------------------
# Write out
# ---------------------------------------------------------------------------

def main() -> None:
    outputs = [
        ("idle_tired_droop.motion3.json", author_tired_droop()),
        ("idle_focused_lean.motion3.json", author_focused_lean()),
    ]

    for filename, motion in outputs:
        for target_dir in [MODEL_DIR, *MIRROR_DIRS]:
            target_dir.mkdir(parents=True, exist_ok=True)
            out_path = target_dir / filename
            with out_path.open("w", encoding="utf-8") as f:
                json.dump(motion, f, indent=2)
            meta = motion["Meta"]
            print(
                f"  wrote {out_path}  "
                f"({meta['Duration']:.1f}s, {meta['CurveCount']} curves, "
                f"{meta['TotalSegmentCount']} segment-floats)"
            )


if __name__ == "__main__":
    main()
