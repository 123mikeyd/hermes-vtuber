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
# ~2 minutes means: a spike from a one-off sad sentence fades by the
# time you've had three more exchanges, but a sustained sad conversation
# keeps topping the mood up and it stays there.
MOOD_HALFLIFE_SECONDS = 120.0

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
    arousal: float = 0.0
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
    arousal: float = 0.0
    social: float = 0.0
    focus: float = 0.0

    # Wall-clock seconds since epoch of the last delta application OR
    # decay step. `None` means "never applied" — first apply_delta()
    # starts the clock.
    last_update: Optional[float] = None

    def __post_init__(self) -> None:
        # Initialize to baseline on first construction — more natural
        # than starting at all-zeros if the baseline was specified.
        if self.valence == self.arousal == self.social == self.focus == 0.0:
            self.valence = self.baseline.valence
            self.arousal = self.baseline.arousal
            self.social = self.baseline.social
            self.focus = self.baseline.focus
        # Hard-clamp in case something handed us garbage.
        self._clamp()

    # --- State math ---

    def _clamp(self) -> None:
        """Hard-clamp every dimension to [MOOD_MIN, MOOD_MAX]."""
        self.valence = max(MOOD_MIN, min(MOOD_MAX, self.valence))
        self.arousal = max(MOOD_MIN, min(MOOD_MAX, self.arousal))
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
        self.arousal = self.baseline.arousal + (self.arousal - self.baseline.arousal) * factor
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
        self.arousal += w * delta.arousal
        self.social += w * delta.social
        self.focus += w * delta.focus
        self._clamp()

        if delta.reason:
            logger.debug(
                f"Mood delta applied ({delta.reason}): "
                f"v={delta.valence:+.2f} a={delta.arousal:+.2f} "
                f"s={delta.social:+.2f} f={delta.focus:+.2f} -> "
                f"v={self.valence:+.2f} a={self.arousal:+.2f} "
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

        # Arousal word
        if self.arousal > 0.5:
            parts.append("buzzing with energy")
        elif self.arousal > 0.15:
            parts.append("alert")
        elif self.arousal < -0.5:
            parts.append("tired")
        elif self.arousal < -0.15:
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

            "calm"     — low arousal, non-negative valence
            "tired"    — low arousal, negative valence
            "excited"  — high arousal, non-negative valence
            "focused"  — high arousal, high focus (overrides excited)

        These map 1:1 to the Idle_calm / Idle_tired / Idle_excited /
        Idle_focused motion groups Phase 4 will introduce in model3.json.
        """
        if self.arousal >= 0.15:
            if self.focus >= 0.4:
                return "focused"
            return "excited"
        # Low-ish arousal
        if self.valence < -0.1:
            return "tired"
        return "calm"

    # --- Serialization ---

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe dict for persistence inside SessionMemory."""
        return {
            "baseline": asdict(self.baseline),
            "valence": round(self.valence, 4),
            "arousal": round(self.arousal, 4),
            "social": round(self.social, 4),
            "focus": round(self.focus, 4),
            "last_update": self.last_update,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MoodState":
        """Load from the dict shape emitted by to_dict(). Tolerates
        missing fields for forward-compat (old saves, new fields).
        """
        bline_raw = data.get("baseline") or {}
        baseline = MoodBaseline(
            valence=float(bline_raw.get("valence", 0.0)),
            arousal=float(bline_raw.get("arousal", 0.0)),
            social=float(bline_raw.get("social", 0.0)),
            focus=float(bline_raw.get("focus", 0.0)),
        )
        return cls(
            baseline=baseline,
            valence=float(data.get("valence", baseline.valence)),
            arousal=float(data.get("arousal", baseline.arousal)),
            social=float(data.get("social", baseline.social)),
            focus=float(data.get("focus", baseline.focus)),
            last_update=data.get("last_update"),
        )

    def snapshot(self) -> Dict[str, Any]:
        """Compact live snapshot for WebSocket push / frontend consumption.

        Different from to_dict(): no baseline echo, includes quadrant +
        describe() for the frontend that doesn't want to re-run the
        threshold logic.
        """
        return {
            "valence": round(self.valence, 3),
            "arousal": round(self.arousal, 3),
            "social": round(self.social, 3),
            "focus": round(self.focus, 3),
            "quadrant": self.quadrant(),
            "description": self.describe(),
        }
