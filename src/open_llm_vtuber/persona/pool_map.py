"""
Phase 4 — Mood-tagged idle motion pools.

Maps mood quadrants (from persona.mood.MoodState.quadrant()) to ordered
lists of motion filenames. The server sends these to the frontend via
the `mood_update` WebSocket message whenever mood changes; the frontend
filters its Idle randomizer by the current quadrant's pool.

Design principles:
 - PER-MODEL configuration. Different Live2D models have different
   motion files, so the pool mapping is keyed by model name. Pick up
   the right pool for whichever model is currently loaded.
 - FALLBACK IS EXPLICIT. If a quadrant's pool is empty or missing, fall
   through to the "calm" pool. If THAT's empty, return all available
   idle motions. Never leave the avatar without a pool to pick from.
 - "Listening" is a separate pool, not a quadrant. Plays while the user
   is speaking (VAD-triggered), regardless of mood.
 - Files referenced here must exist on disk in the model's motion/
   folder. The frontend is responsible for graceful failure if one
   doesn't load.

Part of: .hermes/plans/2026-04-17_personality-evolution.md (Phase 4)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger


# The four mood quadrants, the listening pool, and Phase 6 sleep/transition pools.
POOL_KEYS = ("calm", "tired", "excited", "focused", "listening",
             "sleep", "falling_asleep", "waking_up")


@dataclass
class PoolMap:
    """Per-quadrant motion-filename lists for a single model.

    Filenames are relative to the model's `runtime/` directory and use
    forward slashes, matching Cubism model3.json conventions
    (e.g., "motion/idle_calm.motion3.json").
    """

    model_name: str
    calm:           List[str] = field(default_factory=list)
    tired:          List[str] = field(default_factory=list)
    excited:        List[str] = field(default_factory=list)
    focused:        List[str] = field(default_factory=list)
    listening:      List[str] = field(default_factory=list)
    # Phase 6 — sleep states. `sleep` is the looping deep-sleep motion;
    # `falling_asleep` and `waking_up` are single-shot transitions the
    # sidecar plays once when crossing the sleep boundary.
    sleep:          List[str] = field(default_factory=list)
    falling_asleep: List[str] = field(default_factory=list)
    waking_up:      List[str] = field(default_factory=list)

    def get(self, quadrant: str) -> List[str]:
        """Lookup with graceful fallback.

        Primary: the exact quadrant's pool (if non-empty).
        Fallback 1: the "calm" pool (the neutral default).
        Fallback 2: everything non-empty across all pools.
        Fallback 3: an empty list (caller should log + let SDK pick).
        """
        primary = getattr(self, quadrant, None) or []
        if primary:
            return primary

        logger.debug(
            f"PoolMap[{self.model_name}]: '{quadrant}' pool empty, "
            f"falling back to 'calm'"
        )
        if self.calm:
            return self.calm

        # Last-ditch: flatten everything we have
        everything: List[str] = []
        for key in POOL_KEYS:
            everything.extend(getattr(self, key, []) or [])
        if everything:
            logger.warning(
                f"PoolMap[{self.model_name}]: all preferred pools empty, "
                f"returning flattened union ({len(everything)} motions)"
            )
        else:
            logger.warning(
                f"PoolMap[{self.model_name}]: NO motions in any pool — "
                f"frontend will fall back to SDK default"
            )
        return everything

    def as_dict(self) -> Dict[str, List[str]]:
        """Full dict of all pools for sending over WebSocket."""
        return {key: list(getattr(self, key)) for key in POOL_KEYS}


# ---------------------------------------------------------------------------
# Built-in pool mappings per model.
#
# Users can override by registering a PoolMap via register_pool() at
# startup or by editing this file. When a user loads a custom model
# we don't have a mapping for, get_pool_for_model() returns a best-effort
# auto-built map from whatever motions the model declares.
# ---------------------------------------------------------------------------

_REGISTRY: Dict[str, PoolMap] = {}


def register_pool(pool_map: PoolMap) -> None:
    """Register a PoolMap for a model. Overwrites any existing entry."""
    _REGISTRY[pool_map.model_name] = pool_map
    logger.info(
        f"Registered pool map for '{pool_map.model_name}': "
        f"calm={len(pool_map.calm)}, tired={len(pool_map.tired)}, "
        f"excited={len(pool_map.excited)}, focused={len(pool_map.focused)}, "
        f"listening={len(pool_map.listening)}"
    )


def get_pool_for_model(model_name: str) -> Optional[PoolMap]:
    """Return the registered PoolMap for a model, or None if none registered."""
    return _REGISTRY.get(model_name)


# ---------------------------------------------------------------------------
# hermes_dark — the primary model authored for this project.
#
# Assignments per user spec (Mike, Apr 17, 2026):
#   - creeper_! is the "sluggish one" -> tired
#   - Wonder / Wonder_full are the listening-phase motions
#   - Come on down is high-energy encouraging -> excited (NOT focused)
#
# All existing motion files are on disk at
# live2d-models/hermes_dark/runtime/motion/*.motion3.json
#
# GAPS (documented):
#   - tired pool has only creeper_! -> need 1-2 more authored motions
#   - focused pool has only idle_calm_02 -> need 1-2 more authored motions
# These gaps get filled by programmatically-authored motions shipped
# alongside this PoolMap (see motion_library in Phase 4 deliverable).
# ---------------------------------------------------------------------------

HERMES_DARK_POOL = PoolMap(
    model_name="hermes_dark",
    calm=[
        # Phase 6 — idle_wait is the most common background state
        # (16s, very subtle — breathing + blinking + tiny drift).
        # Lead the list so it plays first on quadrant entry.
        "motion/idle_wait.motion3.json",
        # Phase 4.5 warm baseline
        "motion/idle_calm_warm.motion3.json",
        # Phase 6 variety motions (short to long)
        "motion/idle_desk_check.motion3.json",     #  3s  quick notebook glance
        "motion/idle_look_around.motion3.json",    #  5s  people-watching
        "motion/idle_soft_stretch.motion3.json",   #  7s  stretch (tech-bro nag)
        "motion/idle_desk_rock.motion3.json",      #  9s  rummaging gag
        "motion/idle_hair_fidget.motion3.json",    # 12s  hand to hair
        # Legacy / fallbacks
        "motion/idle_arms_down.motion3.json",
        "motion/idle_calm.motion3.json",
        "motion/look_aside.motion3.json",
    ],
    tired=[
        # Phase 4.5 — new slump motion leads, followed by the
        # placeholder droop and the creeper fallback. These also serve
        # as the pre-sleep drowsy pool per Phase 6 design.
        "motion/idle_tired_slump.motion3.json",
        "motion/creeper_!.motion3.json",
        "motion/idle_tired_droop.motion3.json",
    ],
    excited=[
        # Phase 4.5 — bouncy is the primary excited; Laughing_Test
        # stays as a strong alternate; Come on down for variety
        "motion/idle_excited_bouncy.motion3.json",
        "motion/Laughing_Test.motion3.json",
        "motion/Come on down.motion3.json",
    ],
    focused=[
        # Phase 4.5 — intent is the primary; old lean + calm_02 as
        # alternates
        "motion/idle_focused_intent.motion3.json",
        "motion/idle_calm_02.motion3.json",
        "motion/idle_focused_lean.motion3.json",
    ],
    listening=[
        "motion/Wonder.motion3.json",
        "motion/Wonder_full.motion3.json",
    ],
    # Phase 6 — sleep state pools. Sidecar plays `falling_asleep` once
    # when entering sleep, loops `sleep` until woken, then plays
    # `waking_up` once on wake.
    sleep=[
        "motion/sleep_head_down.motion3.json",
    ],
    falling_asleep=[
        "motion/falling_asleep.motion3.json",
    ],
    waking_up=[
        "motion/waking_up.motion3.json",
    ],
)
register_pool(HERMES_DARK_POOL)


# ---------------------------------------------------------------------------
# Automatic fallback for models without a registered PoolMap.
# ---------------------------------------------------------------------------

def auto_pool_from_model3(model3_path: Path, model_name: str) -> PoolMap:
    """Build a minimal PoolMap by reading the model3.json's Idle group.

    Every motion in the Idle group gets placed in the "calm" pool. Other
    pools stay empty. The model will never visually change on mood
    transitions — but nothing breaks, either. Users can register a
    proper mapping later.

    This is the zero-configuration fallback for brand-new models someone
    drops in without editing our registry.
    """
    import json

    pool = PoolMap(model_name=model_name)
    try:
        with open(model3_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        idle_items = (
            data.get("FileReferences", {})
                .get("Motions", {})
                .get("Idle", [])
        )
        pool.calm = [item.get("File", "") for item in idle_items if item.get("File")]
        logger.info(
            f"auto_pool_from_model3('{model_name}'): "
            f"extracted {len(pool.calm)} motions into calm pool; "
            f"other pools empty"
        )
    except Exception as e:
        logger.warning(f"auto_pool_from_model3 failed for {model3_path}: {e}")
    return pool


def resolve_pool(model_name: str, model_dir: Optional[Path] = None) -> PoolMap:
    """Get the pool map for a model, falling back to auto-build if needed.

    Primary: registered PoolMap.
    Secondary: auto-build from model3.json Idle group.
    Tertiary: empty PoolMap (frontend will use SDK default).
    """
    registered = get_pool_for_model(model_name)
    if registered is not None:
        return registered

    if model_dir is not None:
        candidates = list(model_dir.glob(f"{model_name}.model3.json"))
        if candidates:
            return auto_pool_from_model3(candidates[0], model_name)

    logger.warning(
        f"resolve_pool: no registered pool and no model3.json found "
        f"for '{model_name}', returning empty PoolMap"
    )
    return PoolMap(model_name=model_name)
