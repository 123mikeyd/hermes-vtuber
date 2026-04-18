"""
Phase 6 — Rich idle variety + sleep/drowsy states.

10 new motion files authored per Mike's spec (Apr 17, 2026):

  CALM POOL additions (varied durations, subtle background life):
    idle_desk_check.motion3.json       3s   quick glance down at notebook
    idle_look_around.motion3.json      5s   slow head swivel, people-watching
    idle_soft_stretch.motion3.json     7s   forward lean stretch (tech-bro nag)
    idle_desk_rock.motion3.json        9s   rummaging, body rocks desk (gag beat)
    idle_hair_fidget.motion3.json     12s   hand to face/hair, tidy, settle
    idle_wait.motion3.json            16s   mostly breathing + blinking, tiny drift

  SLEEP states (new pool, triggered by inactivity timer or command):
    falling_asleep.motion3.json        4s   head droops, eyes close, body settles
    sleep_head_down.motion3.json      20s   looping: head on desk, slow breathing
    waking_up.motion3.json             3s   head rises, eyes open, back to normal

Design rules honored:
  - B-arm layer for all hand-near-face motions (matches hermes_dark default)
  - Full range of body params explored for desk_rock (BODY_X/Y/Z near limits)
  - Subtle motions stay well inside safe ranges
  - Eye-open values EXPLICITLY set in every motion (skill pitfall: param defaults to 0 = closed if not set)
  - Neither arm side ever goes both-layers-zero (four-arm-deity bug preventer)
  - Loop=False so the sidecar can swap between them reliably
  - Sleep loop is Loop=True because we want it to stay until woken

Run with:
  python3 scripts/author_phase6_sleep_motions.py

Writes to both the OLLV install and the hermes-vtuber mirror.
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


# -------------------------------------------------------------------------
# Motion3.json helpers
# -------------------------------------------------------------------------

def bezier_curve(param_id: str,
                 keyframes: Sequence[Tuple[float, float]],
                 target: str = "Parameter") -> dict:
    """keyframes = [(time_s, value), ...] strictly ascending by time."""
    if len(keyframes) < 2:
        raise ValueError(f"curve {param_id} needs >= 2 keyframes")
    segments: List[float] = []
    t0, v0 = keyframes[0]
    segments.extend([float(t0), float(v0)])
    for (prev_t, prev_v), (t, v) in zip(keyframes, keyframes[1:]):
        dt = t - prev_t
        cp1_t = prev_t + dt * 0.33
        cp2_t = prev_t + dt * 0.66
        segments.extend([
            1,                       # bezier type
            float(cp1_t), float(prev_v),
            float(cp2_t), float(v),
            float(t), float(v),
        ])
    return {"Target": target, "Id": param_id, "Segments": segments}


def hold(param_id: str, value: float, duration: float,
         target: str = "Parameter") -> dict:
    return bezier_curve(param_id, [(0.0, value), (duration, value)], target)


def build_motion(curves: Sequence[dict], duration: float,
                 fps: float = 30.0, loop: bool = False) -> dict:
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


def arm_layer_b(duration: float) -> List[dict]:
    """Standard B-arm layer (hands up at face). Used for most motions."""
    return [
        hold("PARTS_01_ARM_L_02", 1.0, duration, target="PartOpacity"),
        hold("PARTS_01_ARM_R_02", 1.0, duration, target="PartOpacity"),
        hold("PARTS_01_ARM_L_01", 0.0, duration, target="PartOpacity"),
        hold("PARTS_01_ARM_R_01", 0.0, duration, target="PartOpacity"),
        hold("PARAM_ARM_02_L", 0.0, duration),
        hold("PARAM_ARM_02_R", 0.0, duration),
    ]


def eye_defaults(duration: float, openness: float = 0.85,
                 blink_at: List[float] = None) -> List[dict]:
    """Eye open/blink curves. Pass blink_at=[4.0, 8.0] for two blinks."""
    if blink_at is None:
        blink_at = []
    keys_l = [(0.0, openness)]
    for t in blink_at:
        keys_l.extend([
            (t, openness),
            (t + 0.12, 0.0),       # close fast
            (t + 0.25, openness),  # open fast
        ])
    keys_l.append((duration, openness))
    return [
        bezier_curve("PARAM_EYE_L_OPEN", keys_l),
        bezier_curve("PARAM_EYE_R_OPEN", list(keys_l)),  # mirror
    ]


# =========================================================================
# CALM POOL MOTIONS
# =========================================================================

def author_desk_check(duration: float = 3.0) -> dict:
    """Quick glance DOWN at the notebook, then back up. ~3s total."""
    curves = [
        bezier_curve("PARAM_ANGLE_X", [
            (0.0, 0.0), (1.2, 2.0), (duration, 0.0),
        ]),
        bezier_curve("PARAM_ANGLE_Y", [
            (0.0, 0.0),
            (1.0, -18.0),     # head DOWN, checking notebook
            (1.8, -18.0),     # pause to read
            (duration, 0.0),  # back up
        ]),
        bezier_curve("PARAM_ANGLE_Z", [
            (0.0, 0.0), (duration, 0.0),
        ]),
        *eye_defaults(duration, openness=0.85, blink_at=[1.4]),
        bezier_curve("PARAM_EYE_BALL_X", [
            (0.0, 0.0), (1.0, -0.1), (duration, 0.0),
        ]),
        bezier_curve("PARAM_EYE_BALL_Y", [
            (0.0, 0.0),
            (1.0, -0.8),     # eyes down too
            (1.8, -0.8),
            (duration, 0.0),
        ]),
        hold("PARAM_BROW_L_Y", 0.0, duration),
        hold("PARAM_BROW_R_Y", 0.0, duration),
        hold("PARAM_MOUTH_OPEN_Y", 0.0, duration),
        hold("PARAM_MOUTH_FORM", 0.10, duration),
        bezier_curve("PARAM_BODY_Y", [
            (0.0, -0.10),
            (1.0, -0.25),    # slight lean forward
            (duration, -0.10),
        ]),
        hold("PARAM_TERE", 0.10, duration),
    ]
    curves.extend(arm_layer_b(duration))
    return build_motion(curves, duration=duration, loop=False)


def author_look_around(duration: float = 5.0) -> dict:
    """Slow head swivel — people watching. ~5s."""
    curves = [
        bezier_curve("PARAM_ANGLE_X", [
            (0.0, 0.0),
            (1.2, 18.0),     # look LEFT (viewer's right)
            (2.5, 18.0),     # linger
            (3.8, -18.0),    # swing RIGHT
            (duration, 0.0),
        ]),
        bezier_curve("PARAM_ANGLE_Y", [
            (0.0, 2.0),
            (2.5, 4.0),      # slight up-tilt curious
            (duration, 2.0),
        ]),
        bezier_curve("PARAM_ANGLE_Z", [
            (0.0, 0.0),
            (2.0, 3.0),
            (4.0, -3.0),
            (duration, 0.0),
        ]),
        *eye_defaults(duration, openness=0.9, blink_at=[2.8]),
        bezier_curve("PARAM_EYE_BALL_X", [
            (0.0, 0.0),
            (1.0, 0.8),      # eyes also look
            (2.5, 0.8),
            (3.8, -0.8),
            (duration, 0.0),
        ]),
        hold("PARAM_EYE_BALL_Y", 0.1, duration),
        hold("PARAM_BROW_L_Y", 0.15, duration),
        hold("PARAM_BROW_R_Y", 0.15, duration),
        hold("PARAM_MOUTH_OPEN_Y", 0.0, duration),
        hold("PARAM_MOUTH_FORM", 0.20, duration),
        bezier_curve("PARAM_BODY_X", [
            (0.0, 0.0),
            (2.5, 3.0),
            (duration, 0.0),
        ]),
        hold("PARAM_TERE", 0.10, duration),
    ]
    curves.extend(arm_layer_b(duration))
    return build_motion(curves, duration=duration, loop=False)


def author_soft_stretch(duration: float = 7.0) -> dict:
    """Forward lean stretch — gentle reminder for tech folks. ~7s."""
    curves = [
        bezier_curve("PARAM_ANGLE_X", [
            (0.0, 0.0),
            (2.5, -4.0),
            (5.0, 4.0),
            (duration, 0.0),
        ]),
        bezier_curve("PARAM_ANGLE_Y", [
            (0.0, 0.0),
            (2.0, 12.0),      # head TILTS BACK (stretch)
            (3.5, 12.0),      # hold
            (4.5, -3.0),      # slight forward release
            (duration, 0.0),
        ]),
        bezier_curve("PARAM_ANGLE_Z", [
            (0.0, 0.0),
            (3.5, 5.0),       # slight tilt
            (duration, 0.0),
        ]),
        *eye_defaults(duration, openness=0.85, blink_at=[2.2, 5.5]),
        hold("PARAM_EYE_BALL_X", 0.0, duration),
        bezier_curve("PARAM_EYE_BALL_Y", [
            (0.0, 0.0),
            (2.0, 0.4),       # eyes follow head up
            (3.5, 0.4),
            (duration, 0.0),
        ]),
        bezier_curve("PARAM_BROW_L_Y", [
            (0.0, 0.0), (3.0, 0.25), (duration, 0.0),
        ]),
        bezier_curve("PARAM_BROW_R_Y", [
            (0.0, 0.0), (3.0, 0.25), (duration, 0.0),
        ]),
        bezier_curve("PARAM_MOUTH_OPEN_Y", [
            (0.0, 0.0), (2.5, 0.3), (3.5, 0.3), (4.5, 0.0),
            (duration, 0.0),
        ]),
        bezier_curve("PARAM_MOUTH_FORM", [
            (0.0, 0.20), (3.0, 0.10), (5.0, 0.30), (duration, 0.20),
        ]),
        bezier_curve("PARAM_BODY_Y", [
            (0.0, -0.10),
            (2.5, 0.30),      # body leans back
            (5.0, -0.15),     # settle forward
            (duration, -0.10),
        ]),
        hold("PARAM_TERE", 0.15, duration),
    ]
    curves.extend(arm_layer_b(duration))
    return build_motion(curves, duration=duration, loop=False)


def author_desk_rock(duration: float = 9.0) -> dict:
    """Gag beat — searching the desk, body rocks. Exploring full BODY range.
    Nova is rummaging for something. Her body sways hard (the hermes_dark
    rig translates body sway into the desk seeming to shift), and she
    glances around with a slightly annoyed/confused expression.
    """
    curves = [
        bezier_curve("PARAM_ANGLE_X", [
            (0.0, 0.0),
            (1.5, -25.0),     # sharp left
            (3.5, 20.0),      # sharp right
            (5.5, -15.0),
            (7.5, 10.0),
            (duration, 0.0),
        ]),
        bezier_curve("PARAM_ANGLE_Y", [
            (0.0, 0.0),
            (2.0, -20.0),     # head DOWN searching
            (4.0, -5.0),
            (6.0, -20.0),     # back down searching
            (duration, 0.0),
        ]),
        bezier_curve("PARAM_ANGLE_Z", [
            (0.0, 0.0),
            (2.0, -10.0),
            (5.0, 10.0),
            (duration, 0.0),
        ]),
        *eye_defaults(duration, openness=1.0, blink_at=[3.5, 7.0]),
        bezier_curve("PARAM_EYE_BALL_X", [
            (0.0, 0.0),
            (1.5, -0.9),
            (3.5, 0.9),
            (5.5, -0.6),
            (duration, 0.0),
        ]),
        bezier_curve("PARAM_EYE_BALL_Y", [
            (0.0, 0.0),
            (2.0, -0.9),
            (4.0, -0.3),
            (6.0, -0.9),
            (duration, 0.0),
        ]),
        bezier_curve("PARAM_BROW_L_Y", [
            (0.0, 0.0), (3.0, -0.4), (6.0, -0.4), (duration, 0.0),
        ]),
        bezier_curve("PARAM_BROW_R_Y", [
            (0.0, 0.0), (3.0, -0.4), (6.0, -0.4), (duration, 0.0),
        ]),
        bezier_curve("PARAM_BROW_L_ANGLE", [
            (0.0, 0.0), (3.0, -0.35), (duration, 0.0),
        ]),
        bezier_curve("PARAM_BROW_R_ANGLE", [
            (0.0, 0.0), (3.0, 0.35), (duration, 0.0),
        ]),
        bezier_curve("PARAM_MOUTH_FORM", [
            (0.0, 0.0), (3.0, -0.35), (6.0, -0.20), (duration, 0.0),
        ]),
        hold("PARAM_MOUTH_OPEN_Y", 0.0, duration),
        # BODY rocking — full range exploration
        bezier_curve("PARAM_BODY_X", [
            (0.0, 0.0),
            (1.5, -9.0),       # rock LEFT hard
            (3.5, 9.0),        # rock RIGHT hard
            (5.5, -7.0),
            (7.5, 6.0),
            (duration, 0.0),
        ]),
        bezier_curve("PARAM_BODY_Y", [
            (0.0, -0.10),
            (2.0, -0.50),      # lean forward searching
            (4.0, -0.10),
            (6.0, -0.50),
            (duration, -0.10),
        ]),
        bezier_curve("PARAM_BODY_Z", [
            (0.0, 0.0),
            (2.0, -4.0),
            (5.0, 4.0),
            (duration, 0.0),
        ]),
        hold("PARAM_TERE", 0.0, duration),
    ]
    curves.extend(arm_layer_b(duration))
    return build_motion(curves, duration=duration, loop=False)


def author_hair_fidget(duration: float = 12.0) -> dict:
    """Hand-to-face/hair adjustment. Longer, relaxed. ~12s."""
    curves = [
        bezier_curve("PARAM_ANGLE_X", [
            (0.0, 0.0),
            (3.0, 5.0),
            (6.0, -3.0),
            (9.0, 2.0),
            (duration, 0.0),
        ]),
        bezier_curve("PARAM_ANGLE_Y", [
            (0.0, 2.0),
            (4.0, 5.0),
            (8.0, 1.0),
            (duration, 2.0),
        ]),
        bezier_curve("PARAM_ANGLE_Z", [
            (0.0, 0.0),
            (3.0, 6.0),       # tilt head to one side (hand to hair)
            (9.0, -2.0),
            (duration, 0.0),
        ]),
        *eye_defaults(duration, openness=0.85, blink_at=[3.5, 8.5]),
        bezier_curve("PARAM_EYE_BALL_X", [
            (0.0, 0.0), (3.0, 0.3), (9.0, -0.2), (duration, 0.0),
        ]),
        hold("PARAM_EYE_BALL_Y", 0.0, duration),
        hold("PARAM_BROW_L_Y", 0.1, duration),
        hold("PARAM_BROW_R_Y", 0.1, duration),
        hold("PARAM_MOUTH_OPEN_Y", 0.0, duration),
        hold("PARAM_MOUTH_FORM", 0.25, duration),
        bezier_curve("PARAM_BODY_Y", [
            (0.0, -0.10),
            (3.0, -0.05),
            (6.0, -0.15),
            (9.0, -0.05),
            (duration, -0.10),
        ]),
        bezier_curve("PARAM_BODY_X", [
            (0.0, 0.0),
            (5.0, 2.0),
            (duration, 0.0),
        ]),
        # Slight arm motion — hand moves in toward face
        bezier_curve("PARAM_ARM_02_R", [
            (0.0, 0.0),
            (3.0, -0.30),     # hand up to face
            (7.0, -0.30),
            (duration, 0.0),
        ]),
        hold("PARAM_TERE", 0.20, duration),
    ]
    # Rebuild arm layer without the held PARAM_ARM_02_R (we set it above)
    arm_curves = [
        hold("PARTS_01_ARM_L_02", 1.0, duration, target="PartOpacity"),
        hold("PARTS_01_ARM_R_02", 1.0, duration, target="PartOpacity"),
        hold("PARTS_01_ARM_L_01", 0.0, duration, target="PartOpacity"),
        hold("PARTS_01_ARM_R_01", 0.0, duration, target="PartOpacity"),
        hold("PARAM_ARM_02_L", 0.0, duration),
        # PARAM_ARM_02_R already added with motion above
    ]
    curves.extend(arm_curves)
    return build_motion(curves, duration=duration, loop=False)


def author_idle_wait(duration: float = 16.0) -> dict:
    """The longest, subtlest motion — just breathing + blinking + tiny drift.
    This is what plays MOST of the time when she's "just waiting".
    """
    curves = [
        bezier_curve("PARAM_ANGLE_X", [
            (0.0, 0.0),
            (5.0, 2.0),
            (10.0, -2.0),
            (duration, 0.0),
        ]),
        bezier_curve("PARAM_ANGLE_Y", [
            (0.0, 2.0),
            (8.0, 3.0),
            (duration, 2.0),
        ]),
        bezier_curve("PARAM_ANGLE_Z", [
            (0.0, 0.0),
            (6.0, 1.5),
            (12.0, -1.0),
            (duration, 0.0),
        ]),
        # Three subtle blinks over 16s
        *eye_defaults(duration, openness=0.85, blink_at=[3.5, 9.0, 14.0]),
        bezier_curve("PARAM_EYE_BALL_X", [
            (0.0, 0.0), (7.0, 0.1), (duration, 0.0),
        ]),
        hold("PARAM_EYE_BALL_Y", 0.0, duration),
        hold("PARAM_BROW_L_Y", 0.05, duration),
        hold("PARAM_BROW_R_Y", 0.05, duration),
        hold("PARAM_MOUTH_OPEN_Y", 0.0, duration),
        hold("PARAM_MOUTH_FORM", 0.20, duration),
        # Gentle breathing — slow oscillation
        bezier_curve("PARAM_BODY_Y", [
            (0.0, -0.15),
            (3.0, -0.10),
            (6.0, -0.15),
            (9.0, -0.10),
            (12.0, -0.15),
            (duration, -0.12),
        ]),
        hold("PARAM_TERE", 0.15, duration),
    ]
    curves.extend(arm_layer_b(duration))
    return build_motion(curves, duration=duration, loop=False)


# =========================================================================
# SLEEP STATE MOTIONS
# =========================================================================

def author_falling_asleep(duration: float = 4.0) -> dict:
    """Transitions INTO sleep. Head droops, eyes close gradually."""
    curves = [
        bezier_curve("PARAM_ANGLE_X", [
            (0.0, 0.0), (duration, -3.0),
        ]),
        bezier_curve("PARAM_ANGLE_Y", [
            (0.0, 0.0), (1.5, -8.0), (duration, -25.0),  # head drops hard
        ]),
        bezier_curve("PARAM_ANGLE_Z", [
            (0.0, 0.0), (duration, -5.0),
        ]),
        # Eyes slowly close
        bezier_curve("PARAM_EYE_L_OPEN", [
            (0.0, 0.85),
            (1.0, 0.60),
            (2.0, 0.30),
            (3.0, 0.10),
            (duration, 0.0),
        ]),
        bezier_curve("PARAM_EYE_R_OPEN", [
            (0.0, 0.85),
            (1.0, 0.60),
            (2.0, 0.30),
            (3.0, 0.10),
            (duration, 0.0),
        ]),
        bezier_curve("PARAM_EYE_BALL_Y", [
            (0.0, 0.0), (duration, -0.8),
        ]),
        hold("PARAM_EYE_BALL_X", 0.0, duration),
        # Brows relax
        bezier_curve("PARAM_BROW_L_Y", [
            (0.0, 0.0), (duration, -0.15),
        ]),
        bezier_curve("PARAM_BROW_R_Y", [
            (0.0, 0.0), (duration, -0.15),
        ]),
        bezier_curve("PARAM_MOUTH_OPEN_Y", [
            (0.0, 0.0), (2.0, 0.10), (duration, 0.05),
        ]),
        bezier_curve("PARAM_MOUTH_FORM", [
            (0.0, 0.10), (duration, -0.10),
        ]),
        bezier_curve("PARAM_BODY_Y", [
            (0.0, -0.15), (duration, -0.80),   # body slumps forward
        ]),
        hold("PARAM_TERE", 0.0, duration),
    ]
    curves.extend(arm_layer_b(duration))
    return build_motion(curves, duration=duration, loop=False)


def author_sleep_head_down(duration: float = 20.0) -> dict:
    """Deep sleep — head fully on desk. Loops until awoken.
    Slow breathing (body rising/falling every ~5s).
    Occasional subtle mouth movement.
    """
    # Critical: eyes MUST be held closed. The default is 0 (closed) but
    # explicit is safer, especially since sidecar may interleave.
    curves = [
        # Head fully dropped, slight sway
        hold("PARAM_ANGLE_X", -3.0, duration),
        bezier_curve("PARAM_ANGLE_Y", [
            (0.0, -25.0),
            (10.0, -27.0),
            (duration, -25.0),
        ]),
        bezier_curve("PARAM_ANGLE_Z", [
            (0.0, -5.0),
            (10.0, -3.0),
            (duration, -5.0),
        ]),
        # Eyes CLOSED (both must be 0 — defensive)
        hold("PARAM_EYE_L_OPEN", 0.0, duration),
        hold("PARAM_EYE_R_OPEN", 0.0, duration),
        hold("PARAM_EYE_BALL_X", 0.0, duration),
        hold("PARAM_EYE_BALL_Y", -0.8, duration),
        hold("PARAM_BROW_L_Y", -0.15, duration),
        hold("PARAM_BROW_R_Y", -0.15, duration),
        # Subtle mouth twitch (barely open, twice across loop)
        bezier_curve("PARAM_MOUTH_OPEN_Y", [
            (0.0, 0.05),
            (6.0, 0.15),
            (7.0, 0.05),
            (14.0, 0.12),
            (15.0, 0.05),
            (duration, 0.05),
        ]),
        hold("PARAM_MOUTH_FORM", -0.10, duration),
        # SLOW breathing oscillation
        bezier_curve("PARAM_BODY_Y", [
            (0.0, -0.80),
            (5.0, -0.75),     # inhale
            (10.0, -0.80),    # exhale
            (15.0, -0.75),    # inhale
            (duration, -0.80),
        ]),
        hold("PARAM_TERE", 0.0, duration),
    ]
    curves.extend(arm_layer_b(duration))
    return build_motion(curves, duration=duration, loop=True)


def author_waking_up(duration: float = 3.0) -> dict:
    """Short wake animation. Head lifts, eyes blink open to normal."""
    curves = [
        bezier_curve("PARAM_ANGLE_X", [
            (0.0, -3.0), (duration, 0.0),
        ]),
        bezier_curve("PARAM_ANGLE_Y", [
            (0.0, -25.0),     # starts head-down (continues from sleep)
            (1.5, -10.0),     # rising
            (duration, 0.0),  # back to neutral
        ]),
        bezier_curve("PARAM_ANGLE_Z", [
            (0.0, -5.0), (duration, 0.0),
        ]),
        # Eyes open gradually with a "just waking" flutter
        bezier_curve("PARAM_EYE_L_OPEN", [
            (0.0, 0.0),
            (0.8, 0.30),
            (1.2, 0.20),       # flutter back
            (2.0, 0.60),
            (duration, 0.85),
        ]),
        bezier_curve("PARAM_EYE_R_OPEN", [
            (0.0, 0.0),
            (0.8, 0.30),
            (1.2, 0.20),
            (2.0, 0.60),
            (duration, 0.85),
        ]),
        bezier_curve("PARAM_EYE_BALL_Y", [
            (0.0, -0.8), (1.5, -0.3), (duration, 0.0),
        ]),
        hold("PARAM_EYE_BALL_X", 0.0, duration),
        bezier_curve("PARAM_BROW_L_Y", [
            (0.0, -0.15), (duration, 0.05),
        ]),
        bezier_curve("PARAM_BROW_R_Y", [
            (0.0, -0.15), (duration, 0.05),
        ]),
        # Small surprised mouth-open as she wakes, then closes
        bezier_curve("PARAM_MOUTH_OPEN_Y", [
            (0.0, 0.05), (1.0, 0.25), (2.0, 0.10), (duration, 0.0),
        ]),
        bezier_curve("PARAM_MOUTH_FORM", [
            (0.0, -0.10), (duration, 0.15),
        ]),
        bezier_curve("PARAM_BODY_Y", [
            (0.0, -0.80), (1.5, -0.40), (duration, -0.10),
        ]),
        # Slight blush from being caught sleeping
        bezier_curve("PARAM_TERE", [
            (0.0, 0.0), (1.5, 0.25), (duration, 0.15),
        ]),
    ]
    curves.extend(arm_layer_b(duration))
    return build_motion(curves, duration=duration, loop=False)


# =========================================================================
# Write all motions to disk
# =========================================================================

def main() -> None:
    outputs = [
        # Calm pool variety
        ("idle_desk_check.motion3.json",     author_desk_check()),
        ("idle_look_around.motion3.json",    author_look_around()),
        ("idle_soft_stretch.motion3.json",   author_soft_stretch()),
        ("idle_desk_rock.motion3.json",      author_desk_rock()),
        ("idle_hair_fidget.motion3.json",    author_hair_fidget()),
        ("idle_wait.motion3.json",           author_idle_wait()),
        # Sleep states
        ("falling_asleep.motion3.json",      author_falling_asleep()),
        ("sleep_head_down.motion3.json",     author_sleep_head_down()),
        ("waking_up.motion3.json",           author_waking_up()),
    ]

    for filename, motion in outputs:
        for d in [MODEL_DIR, *MIRROR_DIRS]:
            d.mkdir(parents=True, exist_ok=True)
            p = d / filename
            with p.open("w", encoding="utf-8") as f:
                json.dump(motion, f, indent=2)
            meta = motion["Meta"]
            print(
                f"  wrote {filename:40s} "
                f"{meta['Duration']:5.1f}s  "
                f"loop={meta['Loop']!s:5s} "
                f"curves={meta['CurveCount']}"
            )


if __name__ == "__main__":
    main()
