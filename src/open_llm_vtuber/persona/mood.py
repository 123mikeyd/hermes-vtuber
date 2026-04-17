"""
Phase 3 — Mood State Machine.

Holds a persistent four-dimensional mood vector for a character session.
Each dimension is in [-1.0, 1.0]. The vector updates after each assistant
turn based on conversation affect (see mood_classifier.py), and decays
gently toward a character-defined baseline between updates — so a sad
conversation lingers but doesn't trap the character there forever.

The vector is surfaced TWO places:

  1. Into the system prompt, as a natural-language mood line composed by
     describe(). The LLM reads it like any other context hint and colors
     its response subtly (composer ships this in Phase 3.1).

  2. Out over the WebSocket as a `mood_update` message for the frontend
     to consume (Phase 4 — idle pool selection is driven by mood).

Design principles:

 - EXPLAINABLE. Every state transition is readable in logs. No opaque
   black-box mood engines.
 - BOUNDED. Every dimension is hard-clamped to [-1, 1] after every update.
 - PERSISTENT. Serialized into SessionMemory's JSON so it survives
   server restarts.
 - DECAYING. Conversations fade. Without new input, mood half-lifes toward
   baseline so the character doesn't drift forever.

Part of: .hermes/plans/2026-04-17_personality-evolution.md (Phase 3)
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, asdict, replace
from typing import Dict, Any, Optional, Tuple

from loguru import logger

from .identity import MoodBaseline


# How many seconds it takes for mood to decay halfway back to baseline
# when no new input arrives. Tuned for conversational pacing — half-life
# ~4 minutes means: a spike survives a short break (bathroom, sip of
# coffee) and still colors the next exchange, but eventually fades if
# the conversation truly stops. Adjust up for more persistent mood,
# down for more volatile.
MOOD_HALFLIFE_SECONDS = 240.0

# Hysteresis thresholds — thermostat-style two-level gates on quadrant
# transitions. Crossing INTO a quadrant requires a stronger signal than
# staying in it, which prevents flicker when energy hovers near the
# boundary. Based on MOOD_UPDATE_WEIGHT=0.3 and MoodClassifier's typical
# +/-0.9 delta per strongly-worded sentence:
#   - Nova's baseline energy is 0.1; one strong turn nudges ~+0.27
#     (to ~0.37), still below 0.55, so it takes a SECOND strong turn
#     (~+0.27 to 0.64) to flip to excited. Two-sentence minimum.
#   - Stay-in thresholds are lower, so a calm reply mid-excited-run
#     doesn't instantly kick her back to calm.
MOOD_ENTER_EXCITED_ENERGY = 0.55
MOOD_STAY_EXCITED_ENERGY  = 0.25

MOOD_ENTER_FOCUSED_ENERGY = 0.55   # focused also needs high energy
MOOD_ENTER_FOCUSED_FOCUS  = 0.50   # AND high focus
MOOD_STAY_FOCUSED_ENERGY  = 0.25
MOOD_STAY_FOCUSED_FOCUS   = 0.25

MOOD_ENTER_TIRED_ENERGY   = -0.35
MOOD_ENTER_TIRED_VALENCE  = -0.10
MOOD_STAY_TIRED_ENERGY    = -0.10
MOOD_STAY_TIRED_VALENCE   = 0.05    # slight positive valence still counts as tired

# How much influence a single classifier delta has on the current mood.
# Conversations should nudge mood, not yank it. 0.3 = a strongly sad
# sentence shifts valence by at most ~0.3 toward -1.
MOOD_UPDATE_WEIGHT = 0.3

# Hard clamp for every dimension.
MOOD_MIN = -1.0
MOOD_MAX = 1.0


@dataclass
class MoodDelta:
    """An update proposed by a classifier. Added to the current Mood
    (weighted, clamped) by MoodState.apply_delta().

    Classifiers return these; they never mutate state directly. Keeps
    the mood engine testable and the classifier swappable.
    """

    valence: float = 0.0
    energy: float = 0.0
    social: float = 0.0
    focus: float = 0.0

    # Optional human-readable reason — shown in logs and debug UIs.
    # Keep under ~80 chars; this ends up in log lines.
    reason: str = ""


@dataclass
class MoodState:
    """Four-dim mood vector plus its baseline and last-update time.

    Call `apply_delta()` when a classifier gives you an update.
    Call `decay_to_now()` anytime before READING the vector so decay
    catches up to wall-clock time.

    This object is stored INSIDE SessionMemory (composition, not
    inheritance) so persistence is handled through the same JSON file.
    """

    baseline: MoodBaseline = field(default_factory=MoodBaseline)

    valence: float = 0.0
    energy: float = 0.0
    social: float = 0.0
    focus: float = 0.0

    # Wall-clock seconds since epoch of the last delta application OR
    # decay step. `None` means "never applied" — first apply_delta()
    # starts the clock.
    last_update: Optional[float] = None

    # Current quadrant label. Stateful because hysteresis needs to know
    # where we ARE to decide whether to leave. Starts at "calm" and
    # updates whenever quadrant() is called.
    current_quadrant: str = "calm"

    def __post_init__(self) -> None:
        # Initialize to baseline on first construction — more natural
        # than starting at all-zeros if the baseline was specified.
        if self.valence == self.energy == self.social == self.focus == 0.0:
            self.valence = self.baseline.valence
            self.energy = self.baseline.energy
            self.social = self.baseline.social
            self.focus = self.baseline.focus
        # Hard-clamp in case something handed us garbage.
        self._clamp()

    # --- State math ---

    def _clamp(self) -> None:
        """Hard-clamp every dimension to [MOOD_MIN, MOOD_MAX]."""
        self.valence = max(MOOD_MIN, min(MOOD_MAX, self.valence))
        self.energy = max(MOOD_MIN, min(MOOD_MAX, self.energy))
        self.social = max(MOOD_MIN, min(MOOD_MAX, self.social))
        self.focus = max(MOOD_MIN, min(MOOD_MAX, self.focus))

    def decay_to_now(self, now: Optional[float] = None) -> None:
        """Decay every dimension toward its baseline by the elapsed time
        since last_update, using an exponential half-life of
        MOOD_HALFLIFE_SECONDS.

        Safe to call repeatedly — it's a no-op if last_update is None
        (fresh state) or if no time has passed. Always safe to call
        before reading any mood value.
        """
        if self.last_update is None:
            self.last_update = now if now is not None else time.time()
            return

        now = now if now is not None else time.time()
        elapsed = max(0.0, now - self.last_update)
        if elapsed <= 0.0:
            return

        # Exponential decay: after one half-life, the distance to
        # baseline is halved. factor = (1/2) ** (elapsed / halflife)
        factor = math.pow(0.5, elapsed / MOOD_HALFLIFE_SECONDS)

        self.valence = self.baseline.valence + (self.valence - self.baseline.valence) * factor
        self.energy = self.baseline.energy + (self.energy - self.baseline.energy) * factor
        self.social = self.baseline.social + (self.social - self.baseline.social) * factor
        self.focus = self.baseline.focus + (self.focus - self.baseline.focus) * factor

        self.last_update = now
        self._clamp()

    def apply_delta(self, delta: MoodDelta, now: Optional[float] = None) -> None:
        """Pull mood toward the delta, weighted by MOOD_UPDATE_WEIGHT.

        Decays FIRST (so elapsed time is accounted for), then moves the
        vector by `weight * delta_value` on each axis, then re-clamps.
        """
        self.decay_to_now(now=now)

        w = MOOD_UPDATE_WEIGHT
        self.valence += w * delta.valence
        self.energy += w * delta.energy
        self.social += w * delta.social
        self.focus += w * delta.focus
        self._clamp()

        if delta.reason:
            logger.debug(
                f"Mood delta applied ({delta.reason}): "
                f"v={delta.valence:+.2f} e={delta.energy:+.2f} "
                f"s={delta.social:+.2f} f={delta.focus:+.2f} -> "
                f"v={self.valence:+.2f} e={self.energy:+.2f} "
                f"s={self.social:+.2f} f={self.focus:+.2f}"
            )

    # --- Presentation ---

    def describe(self) -> str:
        """Render the current vector as a single natural-language line
        suitable for injection into the system prompt.

        The _"subtly, not theatrically"_ clause is load-bearing — without
        it, LLMs play mood cues way too hard. Do not remove.

        Examples:
          "You're feeling warm and quite dialed-in tonight."
          "A little tired and pulled-back; not in a rough spot, just quiet."
          "Buzzing — upbeat, energetic, and wide open."
        """
        parts: list[str] = []

        # Valence word
        if self.valence > 0.5:
            parts.append("warm and upbeat")
        elif self.valence > 0.15:
            parts.append("in a good mood")
        elif self.valence < -0.5:
            parts.append("low / down")
        elif self.valence < -0.15:
            parts.append("a little blue")
        else:
            parts.append("even-keeled")

        # Energy word
        if self.energy > 0.5:
            parts.append("buzzing with energy")
        elif self.energy > 0.15:
            parts.append("alert")
        elif self.energy < -0.5:
            parts.append("tired")
        elif self.energy < -0.15:
            parts.append("slow-paced")

        # Social word
        if self.social > 0.5:
            parts.append("very open and chatty")
        elif self.social < -0.5:
            parts.append("withdrawn")
        elif self.social < -0.15:
            parts.append("pulled-back")

        # Focus word
        if self.focus > 0.5:
            parts.append("sharp and dialed-in")
        elif self.focus < -0.5:
            parts.append("scattered")
        elif self.focus < -0.15:
            parts.append("a bit unfocused")

        joined = ", ".join(parts)
        return (
            f"Your current state: {joined}. "
            f"Let this color your responses subtly — not theatrically."
        )

    def quadrant(self) -> str:
        """Return one of the four idle-pool labels for Phase 4 frontend
        consumption:

            "calm"     — low energy, non-negative valence (default)
            "tired"    — low energy, negative valence
            "excited"  — high energy, non-negative valence
            "focused"  — high energy, high focus (overrides excited)

        THERMOSTAT HYSTERESIS: this method is stateful. The thresholds
        to ENTER a quadrant are higher than the thresholds to STAY in
        one. This prevents flicker when the mood vector hovers right
        at a boundary. See the MOOD_ENTER_* / MOOD_STAY_* constants
        at the top of this module for exact numbers.

        These map 1:1 to the Idle_calm / Idle_tired / Idle_excited /
        Idle_focused motion groups Phase 4 introduces.
        """
        q = self.current_quadrant

        # --- Stay-in check first (asks: do we STILL qualify for our
        #     current quadrant?). If yes, don't move.
        if q == "excited":
            if self.energy >= MOOD_STAY_EXCITED_ENERGY:
                return q
        elif q == "focused":
            if (self.energy >= MOOD_STAY_FOCUSED_ENERGY
                    and self.focus >= MOOD_STAY_FOCUSED_FOCUS):
                return q
        elif q == "tired":
            if (self.energy <= MOOD_STAY_TIRED_ENERGY
                    and self.valence <= MOOD_STAY_TIRED_VALENCE):
                return q
        # "calm" always re-evaluates since it's the fallback

        # --- Enter check: do we qualify to enter a non-calm quadrant?
        #     Focused takes priority over excited if both qualify.
        new_q = "calm"
        if (self.energy >= MOOD_ENTER_FOCUSED_ENERGY
                and self.focus >= MOOD_ENTER_FOCUSED_FOCUS):
            new_q = "focused"
        elif self.energy >= MOOD_ENTER_EXCITED_ENERGY:
            new_q = "excited"
        elif (self.energy <= MOOD_ENTER_TIRED_ENERGY
                and self.valence <= MOOD_ENTER_TIRED_VALENCE):
            new_q = "tired"

        if new_q != q:
            logger.info(
                f"Mood quadrant transition: {q} -> {new_q} "
                f"(v={self.valence:+.2f} e={self.energy:+.2f} "
                f"s={self.social:+.2f} f={self.focus:+.2f})"
            )
            self.current_quadrant = new_q

        return self.current_quadrant

    # --- Serialization ---

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe dict for persistence inside SessionMemory."""
        return {
            "baseline": asdict(self.baseline),
            "valence": round(self.valence, 4),
            "energy": round(self.energy, 4),
            "social": round(self.social, 4),
            "focus": round(self.focus, 4),
            "last_update": self.last_update,
            "current_quadrant": self.current_quadrant,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MoodState":
        """Load from the dict shape emitted by to_dict(). Tolerates
        missing fields for forward-compat (old saves, new fields).

        Backward-compat: older saves used "arousal" for what is now
        called "energy". We accept both keys on load and quietly
        migrate — next save() writes the new key, old one dropped.
        """
        bline_raw = data.get("baseline") or {}
        baseline = MoodBaseline(
            valence=float(bline_raw.get("valence", 0.0)),
            energy=float(bline_raw.get("energy", bline_raw.get("arousal", 0.0))),
            social=float(bline_raw.get("social", 0.0)),
            focus=float(bline_raw.get("focus", 0.0)),
        )
        return cls(
            baseline=baseline,
            valence=float(data.get("valence", baseline.valence)),
            energy=float(data.get("energy", data.get("arousal", baseline.energy))),
            social=float(data.get("social", baseline.social)),
            focus=float(data.get("focus", baseline.focus)),
            last_update=data.get("last_update"),
            current_quadrant=str(data.get("current_quadrant", "calm")),
        )

    def snapshot(self) -> Dict[str, Any]:
        """Compact live snapshot for WebSocket push / frontend consumption.

        Different from to_dict(): no baseline echo, includes quadrant +
        describe() for the frontend that doesn't want to re-run the
        threshold logic.
        """
        return {
            "valence": round(self.valence, 3),
            "energy": round(self.energy, 3),
            "social": round(self.social, 3),
            "focus": round(self.focus, 3),
            "quadrant": self.quadrant(),
            "description": self.describe(),
        }
