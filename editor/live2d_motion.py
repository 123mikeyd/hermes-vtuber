#!/usr/bin/env python3
"""
Live2D Motion Authoring Library

Generate motion3.json files programmatically from pose descriptions.
Works without the renderer — reads model metadata, writes motion JSON.

Usage:
    from live2d_motion import ModelInspector, MotionBuilder, PosePresets

    model = ModelInspector("/path/to/model/runtime/")
    builder = MotionBuilder(model)

    # Build a motion from pose keyframes
    builder.pose(0.0, PosePresets.CALM_IDLE)
    builder.pose(5.0, PosePresets.LOOK_LEFT)
    builder.pose(10.0, PosePresets.CALM_IDLE)
    builder.save("motion/my_motion.motion3.json", loop=True)

    # Or from natural language descriptions
    builder.pose(0.0, model.describe_to_params("looking right, smiling, hand raised"))
"""

import json
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


# ============================================================
#  Model Inspector — understand a model's parameter space
# ============================================================

class ModelInspector:
    """Read and understand a Live2D model without rendering it."""

    def __init__(self, runtime_dir: str):
        self.runtime_dir = Path(runtime_dir)
        self._load_model()

    def _load_model(self):
        """Load all model metadata files."""
        # Find model3.json
        model3_files = list(self.runtime_dir.glob("*.model3.json"))
        if not model3_files:
            raise FileNotFoundError(f"No .model3.json in {self.runtime_dir}")

        with open(model3_files[0]) as f:
            self.model3 = json.load(f)
        self.model_name = model3_files[0].stem.replace('.model3', '')

        # Parameter display names from cdi3.json
        self.param_names = {}
        cdi3_files = list(self.runtime_dir.glob("*.cdi3.json"))
        if cdi3_files:
            with open(cdi3_files[0]) as f:
                cdi3 = json.load(f)
            for p in cdi3.get('Parameters', []):
                self.param_names[p['Id']] = p.get('Name', p['Id'])
            self.parts = {p['Id']: p.get('Name', p['Id'])
                          for p in cdi3.get('Parts', [])}

        # Physics — know what's auto-driven
        self.physics_inputs = set()
        self.physics_outputs = set()
        physics_files = list(self.runtime_dir.glob("*.physics3.json"))
        if physics_files:
            with open(physics_files[0]) as f:
                physics = json.load(f)
            for setting in physics.get('PhysicsSettings', []):
                for inp in setting.get('Input', []):
                    self.physics_inputs.add(inp.get('Source', {}).get('Id', ''))
                for out in setting.get('Output', []):
                    self.physics_outputs.add(out.get('Destination', {}).get('Id', ''))

        # Pose groups — mutually exclusive parts
        self.pose_groups = []
        pose_files = list(self.runtime_dir.glob("*.pose3.json"))
        if pose_files:
            with open(pose_files[0]) as f:
                pose = json.load(f)
            for group in pose.get('Groups', []):
                self.pose_groups.append([item['Id'] for item in group])

        # Learn from existing motions
        self.param_ranges = {}
        self._analyze_motions()

    def _analyze_motions(self):
        """Extract parameter usage from existing motion files."""
        motion_dir = self.runtime_dir / "motion"
        if not motion_dir.exists():
            return

        for fname in motion_dir.glob("*.motion3.json"):
            if 'backup' in fname.name:
                continue
            try:
                with open(fname) as f:
                    motion = json.load(f)
            except (json.JSONDecodeError, IOError):
                continue

            for curve in motion.get('Curves', []):
                pid = curve['Id']
                target = curve['Target']
                values = self._extract_values(curve['Segments'])

                key = pid if target == 'Parameter' else f"part:{pid}"
                if key not in self.param_ranges:
                    self.param_ranges[key] = {'min': float('inf'), 'max': float('-inf')}
                if values:
                    self.param_ranges[key]['min'] = min(self.param_ranges[key]['min'], min(values))
                    self.param_ranges[key]['max'] = max(self.param_ranges[key]['max'], max(values))

    @staticmethod
    def _extract_values(segments):
        """Pull all keyframe values from a segment array."""
        values = []
        i = 0
        while i < len(segments):
            if i == 0:
                if len(segments) > 1:
                    values.append(segments[1])
                i = 2
            else:
                seg_type = int(segments[i])
                if seg_type == 0:  # linear
                    values.append(segments[i + 2])
                    i += 3
                elif seg_type == 1:  # bezier
                    values.append(segments[i + 6])
                    i += 7
                elif seg_type in (2, 3):  # stepped/inverse stepped
                    values.append(segments[i + 2])
                    i += 3
                else:
                    i += 1
        return values

    def is_physics_driven(self, param_id: str) -> bool:
        """Is this param auto-animated by physics? Don't hardcode it."""
        return param_id in self.physics_outputs

    def get_motion_groups(self):
        """Get motion groups from model3.json."""
        refs = self.model3.get('FileReferences', {})
        return refs.get('Motions', {})

    def describe_params(self) -> str:
        """Human-readable parameter catalog."""
        lines = []
        for pid, name in sorted(self.param_names.items()):
            flags = []
            if pid in self.physics_inputs:
                flags.append("drives-physics")
            if pid in self.physics_outputs:
                flags.append("PHYSICS-DRIVEN")
            r = self.param_ranges.get(pid, {})
            range_str = f"[{r.get('min', '?'):.2f}..{r.get('max', '?'):.2f}]" if r else "[unused]"
            lines.append(f"  {pid} ({name}) {range_str} {' '.join(flags)}")
        return '\n'.join(lines)


# ============================================================
#  Pose Presets — named parameter sets for common poses
# ============================================================

class PosePresets:
    """
    Common pose configurations for hermes_dark/shizuku-type models.

    Each preset is a dict of {param_id: value}.
    Params not listed keep their default or previous value.

    CONVENTIONS:
    - Eyes: 0=closed, 0.85=relaxed open, 1.0=normal, 1.6=wide
    - Mouth form: -1.0=sad/pout, -0.2=neutral, 0.5=smile, 1.0=big smile
    - Mouth open: 0=closed, 1.0=half, 2.0=wide
    - Head angle X: -30=look right, 0=center, +30=look left
    - Head angle Y: -30=look down, 0=center, +30=look up
    - Body Y: -0.7 to +0.7 (breathing range)
    - Tere (blush): 0=none, 0.5=light, 1.0=full
    - Arm 02 R/L 01: -1=raised(face), 0=rest, +1=extended
    """

    # === Base defaults (MUST set or eyes close, mouth goes weird) ===
    DEFAULTS = {
        'PARAM_EYE_L_OPEN': 0.85,
        'PARAM_EYE_R_OPEN': 0.85,
        'PARAM_EYE_BALL_X': 0.0,
        'PARAM_EYE_BALL_Y': 0.0,
        'PARAM_MOUTH_OPEN_Y': 0.0,
        'PARAM_MOUTH_FORM': -0.2,
        'PARAM_ANGLE_X': 0.0,
        'PARAM_ANGLE_Y': 0.0,
        'PARAM_ANGLE_Z': 0.0,
        'PARAM_BODY_X': 0.0,
        'PARAM_BODY_Y': 0.0,
        'PARAM_BODY_Z': 0.0,
        'PARAM_BROW_L_Y': 0.0,
        'PARAM_BROW_R_Y': 0.0,
        'PARAM_BROW_L_ANGLE': 0.0,
        'PARAM_BROW_R_ANGLE': 0.0,
        'PARAM_BROW_L_FORM': 0.0,
        'PARAM_BROW_R_FORM': 0.0,
        'PARAM_TERE': 0.0,
        # ARM VALUES: learned from working idle motions (Apr 12 2026)
        # Right arm: -1.0 = resting/hand at face position
        # Left arm: 0.0 = resting on desk
        # Using WRONG values (e.g. 0.0 for right) makes both hands fly up!
        'PARAM_ARM_02_L_01': 0.0,
        'PARAM_ARM_02_L_02': 0.0,
        'PARAM_ARM_02_R_01': -1.0,
        'PARAM_ARM_02_R_02': -1.0,
        'PARAM_HAND_02_L': 0.0,
        'PARAM_HAND_02_R': -1.0,
    }

    # Part opacity for B-layer arms (default pose)
    PARTS_B_ARMS = {
        'PARTS_01_ARM_L_02': 1.0,
        'PARTS_01_ARM_L_01': 0.0,
        'PARTS_01_ARM_R_02': 1.0,
        'PARTS_01_ARM_R_01': 0.0,
    }

    # === Idle Poses ===

    CALM_IDLE = {
        **DEFAULTS,
        **PARTS_B_ARMS,
        'PARAM_ANGLE_X': 24.0,
        'PARAM_ANGLE_Y': 3.0,
        'PARAM_ANGLE_Z': -5.0,
        'PARAM_EYE_L_OPEN': 0.85,
        'PARAM_EYE_R_OPEN': 0.85,
        'PARAM_EYE_BALL_X': -0.3,
        'PARAM_MOUTH_FORM': -0.2,
        'PARAM_BODY_X': 0.2,
        'PARAM_BODY_Z': -0.4,
        'PARAM_ARM_02_L_01': -0.5,
        'PARAM_ARM_02_L_02': -0.5,
        'PARAM_HAND_02_L': -0.5,
    }

    DREAMY = {
        **DEFAULTS,
        **PARTS_B_ARMS,
        'PARAM_ANGLE_X': 20.0,
        'PARAM_ANGLE_Y': -8.0,
        'PARAM_ANGLE_Z': -8.0,
        'PARAM_EYE_L_OPEN': 0.55,
        'PARAM_EYE_R_OPEN': 0.55,
        'PARAM_EYE_BALL_X': -0.5,
        'PARAM_EYE_BALL_Y': -0.3,
        'PARAM_MOUTH_FORM': -0.3,
        'PARAM_BODY_Z': -0.5,
    }

    # === Emotion Poses ===

    HAPPY = {
        **DEFAULTS,
        **PARTS_B_ARMS,
        'PARAM_ANGLE_X': 15.0,
        'PARAM_ANGLE_Y': 5.0,
        'PARAM_ANGLE_Z': -3.0,
        'PARAM_EYE_L_OPEN': 0.6,
        'PARAM_EYE_R_OPEN': 0.6,
        'PARAM_EYE_BALL_X': 0.0,
        'PARAM_MOUTH_FORM': 0.5,
        'PARAM_MOUTH_OPEN_Y': 0.3,
        'PARAM_BROW_L_Y': 0.3,
        'PARAM_BROW_R_Y': 0.3,
        'PARAM_TERE': 0.3,
    }

    EXCITED = {
        **DEFAULTS,
        **PARTS_B_ARMS,
        'PARAM_ANGLE_X': 5.0,
        'PARAM_ANGLE_Y': 10.0,
        'PARAM_EYE_L_OPEN': 1.3,
        'PARAM_EYE_R_OPEN': 1.3,
        'PARAM_MOUTH_FORM': 0.8,
        'PARAM_MOUTH_OPEN_Y': 1.0,
        'PARAM_BROW_L_Y': 0.4,
        'PARAM_BROW_R_Y': 0.4,
        'PARAM_TERE': 0.5,
        'PARAM_ARM_02_R_01': -0.7,  # right arm raised
        'PARAM_ARM_02_R_02': -0.5,
    }

    THINKING = {
        **DEFAULTS,
        **PARTS_B_ARMS,
        'PARAM_ANGLE_X': -15.0,
        'PARAM_ANGLE_Y': 8.0,
        'PARAM_ANGLE_Z': 5.0,
        'PARAM_EYE_L_OPEN': 0.7,
        'PARAM_EYE_R_OPEN': 0.7,
        'PARAM_EYE_BALL_X': 0.5,
        'PARAM_EYE_BALL_Y': -0.3,
        'PARAM_MOUTH_FORM': -0.1,
        'PARAM_BROW_L_ANGLE': 0.3,
        'PARAM_BROW_R_ANGLE': 0.3,
    }

    SAD = {
        **DEFAULTS,
        **PARTS_B_ARMS,
        'PARAM_ANGLE_X': 20.0,
        'PARAM_ANGLE_Y': -15.0,
        'PARAM_ANGLE_Z': -10.0,
        'PARAM_EYE_L_OPEN': 0.5,
        'PARAM_EYE_R_OPEN': 0.5,
        'PARAM_EYE_BALL_Y': -0.5,
        'PARAM_MOUTH_FORM': -0.8,
        'PARAM_BROW_L_Y': -0.5,
        'PARAM_BROW_R_Y': -0.5,
        'PARAM_BROW_L_FORM': -0.4,
        'PARAM_BROW_R_FORM': -0.4,
        'PARAM_TERE': 0.0,
    }

    SURPRISED = {
        **DEFAULTS,
        **PARTS_B_ARMS,
        'PARAM_ANGLE_Y': 5.0,
        'PARAM_EYE_L_OPEN': 1.6,
        'PARAM_EYE_R_OPEN': 1.6,
        'PARAM_MOUTH_OPEN_Y': 1.5,
        'PARAM_MOUTH_FORM': 0.0,
        'PARAM_BROW_L_Y': 0.4,
        'PARAM_BROW_R_Y': 0.4,
    }

    SHY = {
        **DEFAULTS,
        **PARTS_B_ARMS,
        'PARAM_ANGLE_X': 25.0,
        'PARAM_ANGLE_Y': -10.0,
        'PARAM_ANGLE_Z': -8.0,
        'PARAM_EYE_L_OPEN': 0.6,
        'PARAM_EYE_R_OPEN': 0.6,
        'PARAM_EYE_BALL_X': -0.5,
        'PARAM_EYE_BALL_Y': -0.4,
        'PARAM_MOUTH_FORM': -0.1,
        'PARAM_TERE': 0.8,
        'PARAM_BROW_L_FORM': -0.3,
        'PARAM_BROW_R_FORM': -0.3,
    }

    # === Direction Poses ===

    LOOK_LEFT = {
        **DEFAULTS,
        'PARAM_ANGLE_X': 25.0,
        'PARAM_EYE_BALL_X': -0.6,
        'PARAM_BODY_X': 0.3,
    }

    LOOK_RIGHT = {
        **DEFAULTS,
        'PARAM_ANGLE_X': -25.0,
        'PARAM_EYE_BALL_X': 0.6,
        'PARAM_BODY_X': -0.3,
    }

    LOOK_UP = {
        **DEFAULTS,
        'PARAM_ANGLE_Y': 20.0,
        'PARAM_EYE_BALL_Y': 0.1,
        'PARAM_EYE_L_OPEN': 1.1,
        'PARAM_EYE_R_OPEN': 1.1,
    }

    LOOK_DOWN = {
        **DEFAULTS,
        'PARAM_ANGLE_Y': -20.0,
        'PARAM_EYE_BALL_Y': -0.5,
        'PARAM_EYE_L_OPEN': 0.5,
        'PARAM_EYE_R_OPEN': 0.5,
    }

    # === Speaking Poses ===

    SPEAKING_ENGAGED = {
        **DEFAULTS,
        **PARTS_B_ARMS,
        'PARAM_ANGLE_X': 10.0,
        'PARAM_ANGLE_Y': 5.0,
        'PARAM_EYE_L_OPEN': 1.0,
        'PARAM_EYE_R_OPEN': 1.0,
        'PARAM_MOUTH_FORM': 0.3,
        'PARAM_MOUTH_OPEN_Y': 0.5,
        'PARAM_BROW_L_Y': 0.2,
        'PARAM_BROW_R_Y': 0.2,
    }

    SPEAKING_EMPHATIC = {
        **DEFAULTS,
        **PARTS_B_ARMS,
        'PARAM_ANGLE_X': -10.0,
        'PARAM_ANGLE_Y': 8.0,
        'PARAM_EYE_L_OPEN': 1.2,
        'PARAM_EYE_R_OPEN': 1.2,
        'PARAM_MOUTH_FORM': 0.5,
        'PARAM_MOUTH_OPEN_Y': 1.0,
        'PARAM_BROW_L_Y': 0.3,
        'PARAM_BROW_R_Y': 0.3,
        'PARAM_ARM_02_R_01': -0.5,  # gesture with right arm
    }

    # === Action Poses ===

    WAVE = {
        **DEFAULTS,
        'PARTS_01_ARM_R_02': 1.0,
        'PARTS_01_ARM_R_01': 0.0,
        'PARAM_ARM_02_R_01': -1.0,   # arm fully raised
        'PARAM_ARM_02_R_02': -0.5,
        'PARAM_HAND_02_R': -1.0,
        'PARAM_MOUTH_FORM': 0.6,     # smile
        'PARAM_EYE_L_OPEN': 0.8,
        'PARAM_EYE_R_OPEN': 0.8,
    }

    HAND_TO_FACE = {
        **DEFAULTS,
        'PARTS_01_ARM_R_02': 1.0,
        'PARTS_01_ARM_R_01': 0.0,
        'PARAM_ARM_02_R_01': -1.0,   # arm at face
        'PARAM_ARM_02_R_02': -1.0,
        'PARAM_HAND_02_R': -1.0,
        'PARAM_ANGLE_X': 20.0,       # head tilted toward hand
        'PARAM_ANGLE_Z': -5.0,
    }

    # === Blink (use as overlay) ===
    BLINK = {
        'PARAM_EYE_L_OPEN': 0.0,
        'PARAM_EYE_R_OPEN': 0.0,
    }

    WINK_LEFT = {
        'PARAM_EYE_L_OPEN': 0.0,
        'PARAM_EYE_R_OPEN': 0.85,
        'PARAM_MOUTH_FORM': 0.5,
    }

    @classmethod
    def list_presets(cls) -> list:
        """List all available preset names."""
        return [name for name in dir(cls)
                if not name.startswith('_') and isinstance(getattr(cls, name), dict)
                and name != 'list_presets']

    @classmethod
    def get(cls, name: str) -> dict:
        """Get a preset by name (case-insensitive)."""
        name_upper = name.upper().replace(' ', '_').replace('-', '_')
        if hasattr(cls, name_upper):
            return getattr(cls, name_upper)
        raise ValueError(f"Unknown preset '{name}'. Available: {cls.list_presets()}")


# ============================================================
#  Motion Builder — create motion3.json from pose keyframes
# ============================================================

@dataclass
class Keyframe:
    time: float
    params: dict  # {param_id: value}
    parts: dict = field(default_factory=dict)  # {part_id: opacity}


class MotionBuilder:
    """
    Build motion files from a sequence of poses.

    Usage:
        builder = MotionBuilder(model)
        builder.pose(0.0, PosePresets.CALM_IDLE)
        builder.pose(3.0, PosePresets.HAPPY)
        builder.pose(6.0, PosePresets.CALM_IDLE)
        builder.save("motion/happy_moment.motion3.json")
    """

    def __init__(self, model: Optional[ModelInspector] = None):
        self.model = model
        self.keyframes: list[Keyframe] = []

    def clear(self):
        """Clear all keyframes."""
        self.keyframes = []
        return self

    def pose(self, time: float, params: dict) -> 'MotionBuilder':
        """
        Add a pose keyframe at the given time.

        params: dict of {param_id: value} — can include both
                Parameter targets and PartOpacity targets.
                Part IDs (starting with PARTS_) are auto-detected.
        """
        regular = {}
        parts = {}
        for k, v in params.items():
            if k.startswith('PARTS_'):
                parts[k] = v
            else:
                regular[k] = v

        self.keyframes.append(Keyframe(time=time, params=regular, parts=parts))
        return self

    def blink_at(self, time: float, duration: float = 0.3) -> 'MotionBuilder':
        """Insert a blink at the given time. Opens eyes before and after."""
        self.pose(time, {'PARAM_EYE_L_OPEN': 0.85, 'PARAM_EYE_R_OPEN': 0.85})
        self.pose(time + duration * 0.3, {'PARAM_EYE_L_OPEN': 0.0, 'PARAM_EYE_R_OPEN': 0.0})
        self.pose(time + duration, {'PARAM_EYE_L_OPEN': 0.85, 'PARAM_EYE_R_OPEN': 0.85})
        return self

    def breathing(self, start: float, end: float, cycle: float = 3.0,
                  amplitude: float = 0.15) -> 'MotionBuilder':
        """Add breathing oscillation to PARAM_BODY_Y."""
        t = start
        phase = 0
        while t < end:
            # Sine wave approximated by keyframes
            val = -amplitude * (1 if phase % 2 == 0 else -1)
            self.pose(t, {'PARAM_BODY_Y': val * 0.5})
            t += cycle / 2
            phase += 1
        return self

    def build(self, duration: Optional[float] = None, loop: bool = True,
              fps: float = 30.0) -> dict:
        """
        Build the motion3.json dict from accumulated keyframes.

        Merges all keyframes into per-parameter bezier curves.
        Physics-driven params are excluded if model is provided.
        """
        if not self.keyframes:
            raise ValueError("No keyframes added. Use .pose() first.")

        self.keyframes.sort(key=lambda k: k.time)

        if duration is None:
            duration = max(k.time for k in self.keyframes)
            if duration == 0:
                duration = 10.0  # static pose default

        # Collect all parameter values across keyframes
        param_times = {}  # {param_id: [(time, value), ...]}
        part_times = {}   # {part_id: [(time, value), ...]}

        for kf in self.keyframes:
            for pid, val in kf.params.items():
                # Skip physics-driven params
                if self.model and self.model.is_physics_driven(pid):
                    continue
                if pid not in param_times:
                    param_times[pid] = []
                param_times[pid].append((kf.time, val))

            for pid, val in kf.parts.items():
                if pid not in part_times:
                    part_times[pid] = []
                part_times[pid].append((kf.time, val))

        # Build curves
        curves = []

        for pid, points in sorted(param_times.items()):
            # Deduplicate and ensure we have start and end
            points = self._ensure_endpoints(points, duration)
            segments = self._make_bezier_segments(points)
            curves.append({
                'Target': 'Parameter',
                'Id': pid,
                'Segments': segments,
            })

        for pid, points in sorted(part_times.items()):
            points = self._ensure_endpoints(points, duration)
            # Parts use stepped interpolation (instant switch)
            segments = self._make_stepped_segments(points)
            curves.append({
                'Target': 'PartOpacity',
                'Id': pid,
                'Segments': segments,
            })

        motion = {
            'Version': 3,
            'Meta': {
                'Duration': round(duration, 4),
                'Fps': fps,
                'Loop': loop,
                'AreBeziersRestricted': True,
                'CurveCount': len(curves),
                'TotalSegmentCount': sum(len(c['Segments']) for c in curves),
                'TotalPointCount': sum(len(c['Segments']) for c in curves),
                'UserDataCount': 0,
                'TotalUserDataSize': 0,
            },
            'Curves': curves,
        }

        return motion

    def save(self, path: str, duration: Optional[float] = None,
             loop: bool = True, fps: float = 30.0) -> str:
        """Build and save to file. Returns the path."""
        motion = self.build(duration=duration, loop=loop, fps=fps)

        # Resolve relative to model runtime dir if model is set
        if self.model and not os.path.isabs(path):
            path = str(self.model.runtime_dir / path)

        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(motion, f, indent=2)

        return path

    @staticmethod
    def _ensure_endpoints(points, duration):
        """Ensure we have points at t=0 and t=duration."""
        points = sorted(set(points), key=lambda p: p[0])

        # If no point at t=0, copy first value
        if points[0][0] > 0:
            points.insert(0, (0.0, points[0][1]))

        # If no point at end, copy last value
        if points[-1][0] < duration:
            points.append((duration, points[-1][1]))

        return points

    @staticmethod
    def _make_bezier_segments(points):
        """
        Create bezier segments from keyframe points.
        Smooth ease-in-out between each pair.
        """
        segments = []
        for i, (t, v) in enumerate(points):
            if i == 0:
                segments.extend([round(t, 4), round(v, 6)])
            else:
                prev_t, prev_v = points[i - 1]
                dt = t - prev_t
                # Bezier control points for smooth ease
                segments.extend([
                    1,  # bezier type
                    round(prev_t + dt * 0.4, 4), round(prev_v, 6),  # cp1
                    round(prev_t + dt * 0.6, 4), round(v, 6),       # cp2
                    round(t, 4), round(v, 6),                        # end
                ])
        return segments

    @staticmethod
    def _make_stepped_segments(points):
        """Create stepped segments (instant transitions)."""
        segments = []
        for i, (t, v) in enumerate(points):
            if i == 0:
                segments.extend([round(t, 4), round(v, 6)])
            else:
                segments.extend([
                    2,  # stepped type
                    round(t, 4), round(v, 6),
                ])
        return segments


# ============================================================
#  Convenience Functions
# ============================================================

def inspect_model(runtime_dir: str) -> str:
    """Inspect a model and return a human-readable summary."""
    model = ModelInspector(runtime_dir)
    lines = [
        f"Model: {model.model_name}",
        f"Parameters: {len(model.param_names)}",
        f"Physics outputs (auto-driven): {sorted(model.physics_outputs)}",
        f"Pose groups: {model.pose_groups}",
        "",
        "Parameter catalog:",
        model.describe_params(),
        "",
        "Motion groups:",
    ]
    for group, items in model.get_motion_groups().items():
        for item in items:
            lines.append(f"  {group}: {item['File']}")
    return '\n'.join(lines)


def make_idle_motion(model: ModelInspector, name: str = "idle_custom",
                     duration: float = 10.0) -> str:
    """Create a calm idle motion and save it."""
    builder = MotionBuilder(model)

    # Start and end at calm idle
    builder.pose(0.0, PosePresets.CALM_IDLE)

    # Gentle drift to slightly different pose at midpoint
    mid = {**PosePresets.CALM_IDLE}
    mid['PARAM_ANGLE_X'] = mid['PARAM_ANGLE_X'] + 3
    mid['PARAM_EYE_BALL_X'] = mid['PARAM_EYE_BALL_X'] + 0.15
    mid['PARAM_BODY_X'] = mid['PARAM_BODY_X'] + 0.1
    builder.pose(duration / 2, mid)

    # Back to start
    builder.pose(duration, PosePresets.CALM_IDLE)

    # Add a blink
    builder.blink_at(duration * 0.3)
    builder.blink_at(duration * 0.75)

    path = builder.save(f"motion/{name}.motion3.json", duration=duration, loop=True)
    return path


def make_speaking_motion(model: ModelInspector, name: str = "speak_custom",
                         emotion: str = "engaged", duration: float = 3.0) -> str:
    """Create a speaking motion with the given emotion."""
    builder = MotionBuilder(model)

    presets = {
        'engaged': PosePresets.SPEAKING_ENGAGED,
        'emphatic': PosePresets.SPEAKING_EMPHATIC,
        'happy': PosePresets.HAPPY,
        'excited': PosePresets.EXCITED,
        'thinking': PosePresets.THINKING,
        'shy': PosePresets.SHY,
    }

    base_pose = presets.get(emotion, PosePresets.SPEAKING_ENGAGED)

    # Start at the emotion
    builder.pose(0.0, base_pose)

    # Slight movement at 1/3 and 2/3
    shifted = {**base_pose}
    shifted['PARAM_ANGLE_X'] = shifted.get('PARAM_ANGLE_X', 0) - 5
    shifted['PARAM_BODY_X'] = shifted.get('PARAM_BODY_X', 0) + 0.15
    builder.pose(duration / 3, shifted)

    shifted2 = {**base_pose}
    shifted2['PARAM_ANGLE_X'] = shifted2.get('PARAM_ANGLE_X', 0) + 3
    builder.pose(duration * 2 / 3, shifted2)

    # End at base
    builder.pose(duration, base_pose)

    path = builder.save(f"motion/{name}.motion3.json", duration=duration, loop=True)
    return path


# ============================================================
#  CLI Interface
# ============================================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Live2D Motion Authoring Tool')
    parser.add_argument('command', choices=['inspect', 'presets', 'idle', 'speak', 'sequence'],
                        help='Command to run')
    parser.add_argument('--model', '-m', default=None,
                        help='Path to model runtime directory')
    parser.add_argument('--name', '-n', default=None, help='Output motion name')
    parser.add_argument('--emotion', '-e', default='engaged', help='Emotion for speaking motion')
    parser.add_argument('--duration', '-d', type=float, default=None, help='Motion duration')
    parser.add_argument('--poses', '-p', nargs='+', help='Pose names for sequence command')

    args = parser.parse_args()

    # Default model path
    model_dir = args.model or os.path.expanduser(
        "~/Open-LLM-VTuber/live2d-models/hermes_dark/runtime"
    )

    if args.command == 'inspect':
        print(inspect_model(model_dir))

    elif args.command == 'presets':
        for name in PosePresets.list_presets():
            params = getattr(PosePresets, name)
            print(f"\n{name} ({len(params)} params):")
            for k, v in sorted(params.items()):
                if k.startswith('PARTS_'):
                    print(f"  [{k}] = {v}")
                else:
                    print(f"  {k} = {v}")

    elif args.command == 'idle':
        model = ModelInspector(model_dir)
        name = args.name or 'idle_custom'
        dur = args.duration or 10.0
        path = make_idle_motion(model, name, dur)
        print(f"Saved: {path}")

    elif args.command == 'speak':
        model = ModelInspector(model_dir)
        name = args.name or f'speak_{args.emotion}'
        dur = args.duration or 3.0
        path = make_speaking_motion(model, name, args.emotion, dur)
        print(f"Saved: {path}")

    elif args.command == 'sequence':
        if not args.poses:
            print("Error: --poses required for sequence command")
            print(f"Available: {PosePresets.list_presets()}")
            exit(1)

        model = ModelInspector(model_dir)
        builder = MotionBuilder(model)
        dur = args.duration or (len(args.poses) * 3.0)
        interval = dur / max(len(args.poses) - 1, 1)

        for i, pose_name in enumerate(args.poses):
            try:
                pose = PosePresets.get(pose_name)
            except ValueError as e:
                print(f"Error: {e}")
                exit(1)
            builder.pose(i * interval, pose)

        name = args.name or 'sequence'
        path = builder.save(f"motion/{name}.motion3.json", duration=dur, loop=True)
        print(f"Saved: {path} ({len(args.poses)} poses, {dur}s)")
