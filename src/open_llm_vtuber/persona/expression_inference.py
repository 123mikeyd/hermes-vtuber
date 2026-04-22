"""
Phase 5 — Sentence-level affect inference and parameter blending.

This module turns each spoken sentence (the assistant's response,
broken into sentences by sentence_divider) into a 5-dim affect blend
vector, then maps that blend onto the Live2D parameter axes the
frontend will subtly nudge while the sentence plays.

Design:
 - HEURISTIC, lexicon-based, like mood_classifier. Same reasons as
   Phase 3: speed, explainability, zero deps, swappable interface.
 - The output is TWO things: a high-level affect blend (for logs,
   debugging, future ML upgrade) AND a parameter-value dict
   (for the sidecar to actually consume).
 - Mood baseline modulates intensity: a tired character's "joy"
   never reaches full strength. The composer/agent passes the
   current MoodState to compute_blend so that bias can be applied.
 - Output values are SMALL DELTAS, not absolute parameter sets.
   Max ±0.3 on any single param. Motions remain the dominant
   driver of pose — we only color the edges.

Five affect dimensions:
   joy        — smile mouth, raised brows, soft eye
   sadness    — drooped brows, downturned mouth, lower eye lids
   anger      — lowered/sharp brows, slightly pursed mouth
   surprise   — raised brows, wider eyes, mouth slightly open
   shy_blush  — blush, slight downward eye, soft mouth

Each dim is 0.0..1.0 (no negatives — opposites are separate dimensions).
The blend is L1-normalized so the total "expression intensity" is
bounded, regardless of how many dimensions hit.

Part of: .hermes/plans/2026-04-17_personality-evolution.md (Phase 5)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

from loguru import logger

# Optional — if mood is available, we modulate blend intensity by it.
# Imported lazily to avoid circular imports at module top.


# ---------------------------------------------------------------------------
# Lexicons — small on purpose. Same tuning philosophy as mood_classifier.
# ---------------------------------------------------------------------------

JOY_WORDS = {
    "happy", "glad", "love", "loved", "loving", "great", "awesome",
    "wonderful", "amazing", "yay", "yes", "haha", "lol", "fun",
    "enjoy", "enjoyed", "smile", "smiling", "laugh", "laughing",
    "delighted", "thrilled", "excited", "fantastic", "perfect",
    "beautiful", "thank", "thanks", "appreciate", "honored",
}

SADNESS_WORDS = {
    "sad", "sorry", "miss", "missed", "lonely", "alone", "cry", "crying",
    "tears", "hurt", "hurts", "pain", "ache", "broken", "lost",
    "grief", "regret", "wish", "unfortunate", "unfortunately",
    "shame", "ashamed", "disappointed", "tragic", "heartbreaking",
    "rip", "goodbye", "bittersweet",
}

ANGER_WORDS = {
    "angry", "mad", "furious", "rage", "hate", "hated", "hates",
    "annoyed", "annoying", "frustrated", "frustrating", "irritated",
    "stupid", "ridiculous", "absurd", "outrage", "unfair",
    "garbage", "trash", "bullshit", "damn", "hell",
}

SURPRISE_WORDS = {
    "wow", "whoa", "oh", "huh", "really", "honestly", "actually",
    "wait", "what", "no way", "seriously", "incredible", "unbelievable",
    "shocked", "surprised", "stunned", "speechless",
    "did you know", "turns out", "apparently",
}

SHY_BLUSH_WORDS = {
    "shy", "embarrassed", "blush", "blushing", "flustered",
    "stammered", "stutter", "um", "uh", "well", "i mean",
    "compliment", "complimented", "sweet", "kind", "thoughtful",
    "endearing", "cute",
}

# ---------------------------------------------------------------------------
# Punctuation/casing modifiers
# ---------------------------------------------------------------------------

def _exclamation_count(text: str) -> int:
    return text.count("!")

def _question_count(text: str) -> int:
    return text.count("?")

def _ellipsis_count(text: str) -> int:
    # "..." or "…" — both common in TTS-input transcripts
    return text.count("...") + text.count("…")

def _caps_word_count(text: str) -> int:
    return sum(1 for w in re.findall(r"\b[A-Z][A-Z'A-Z]{2,}\b", text)
               if w.replace("'", "").isalpha())


# ---------------------------------------------------------------------------
# Tokenizer (same shape as mood_classifier — kept independent so neither
# module breaks if the other changes its tokenization)
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"\b[a-zA-Z']+\b")

def _tokenize(text: str) -> List[str]:
    return [m.group(0).lower() for m in _WORD_RE.finditer(text)]


def _hits(tokens: List[str], lex: set) -> int:
    return sum(1 for t in tokens if t in lex)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass
class AffectBlend:
    """Per-sentence affect vector. All fields in [0.0, 1.0]."""
    joy: float = 0.0
    sadness: float = 0.0
    anger: float = 0.0
    surprise: float = 0.0
    shy_blush: float = 0.0

    # Audit string for logs — what triggered this blend?
    reason: str = ""

    def magnitude(self) -> float:
        return self.joy + self.sadness + self.anger + self.surprise + self.shy_blush

    def to_dict(self) -> Dict[str, float]:
        # Round for log/wire compactness
        return {
            "joy": round(self.joy, 3),
            "sadness": round(self.sadness, 3),
            "anger": round(self.anger, 3),
            "surprise": round(self.surprise, 3),
            "shy_blush": round(self.shy_blush, 3),
        }


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

# How much each lexicon hit contributes to its affect axis
PER_HIT_WEIGHT = 0.25
# Max value any single affect axis can reach from word hits alone
SINGLE_AXIS_CAP = 0.9
# Per-sentence total expression intensity cap (after normalization)
TOTAL_BLEND_CAP = 1.2


def infer(sentence: str) -> AffectBlend:
    """Read one sentence, return its 5-dim affect blend.

    Pure function — no side effects, deterministic for a given input.
    Safe to call in the request hot path; runs in microseconds.
    """
    if not sentence or not sentence.strip():
        return AffectBlend(reason="empty")

    tokens = _tokenize(sentence)

    # Lexicon hits → axis contributions
    joy = _hits(tokens, JOY_WORDS) * PER_HIT_WEIGHT
    sadness = _hits(tokens, SADNESS_WORDS) * PER_HIT_WEIGHT
    anger = _hits(tokens, ANGER_WORDS) * PER_HIT_WEIGHT
    surprise = _hits(tokens, SURPRISE_WORDS) * PER_HIT_WEIGHT
    shy_blush = _hits(tokens, SHY_BLUSH_WORDS) * PER_HIT_WEIGHT

    # Punctuation modifiers
    exc = _exclamation_count(sentence)
    qst = _question_count(sentence)
    ell = _ellipsis_count(sentence)
    caps = _caps_word_count(sentence)

    # Each ! adds a little surprise + boosts joy/anger if those are present
    if exc > 0:
        bump = min(0.4, 0.15 * exc)
        surprise += bump * 0.5
        if joy > 0:
            joy += bump * 0.3
        if anger > 0:
            anger += bump * 0.3

    # Each ? adds a touch of surprise (curiosity)
    if qst > 0:
        surprise += min(0.3, 0.1 * qst)

    # Ellipsis adds sadness/shyness (trailing off)
    if ell > 0:
        bump = min(0.3, 0.15 * ell)
        sadness += bump * 0.4
        shy_blush += bump * 0.3

    # ALL-CAPS shouting = anger or excitement, not sadness
    if caps > 0:
        bump = min(0.4, 0.2 * caps)
        if anger > 0:
            anger += bump
        else:
            joy += bump * 0.5
        surprise += bump * 0.3

    # Cap each axis at SINGLE_AXIS_CAP
    joy = min(SINGLE_AXIS_CAP, joy)
    sadness = min(SINGLE_AXIS_CAP, sadness)
    anger = min(SINGLE_AXIS_CAP, anger)
    surprise = min(SINGLE_AXIS_CAP, surprise)
    shy_blush = min(SINGLE_AXIS_CAP, shy_blush)

    # Normalize total magnitude if it exceeds cap
    blend = AffectBlend(
        joy=joy, sadness=sadness, anger=anger,
        surprise=surprise, shy_blush=shy_blush,
    )
    mag = blend.magnitude()
    if mag > TOTAL_BLEND_CAP:
        scale = TOTAL_BLEND_CAP / mag
        blend = AffectBlend(
            joy=joy * scale,
            sadness=sadness * scale,
            anger=anger * scale,
            surprise=surprise * scale,
            shy_blush=shy_blush * scale,
        )

    # Build reason string for logs
    parts: List[str] = []
    counts = {
        "j": _hits(tokens, JOY_WORDS),
        "s": _hits(tokens, SADNESS_WORDS),
        "a": _hits(tokens, ANGER_WORDS),
        "u": _hits(tokens, SURPRISE_WORDS),
        "b": _hits(tokens, SHY_BLUSH_WORDS),
    }
    nonzero = {k: v for k, v in counts.items() if v}
    if nonzero:
        parts.append(",".join(f"{k}:{v}" for k, v in nonzero.items()))
    if exc: parts.append(f"!{exc}")
    if qst: parts.append(f"?{qst}")
    if ell: parts.append(f"…{ell}")
    if caps: parts.append(f"CAPS{caps}")
    blend.reason = " ".join(parts) or "neutral"

    return blend


# ---------------------------------------------------------------------------
# Affect blend → Live2D parameter deltas
# ---------------------------------------------------------------------------

# Parameter weights per affect axis. Each entry is (param_id, max_delta).
# Positive max_delta means parameter goes UP at full axis value;
# negative means it goes DOWN.
#
# Max delta tuned to ±0.3 so motions remain dominant.

PARAM_MAP: Dict[str, List[Tuple[str, float]]] = {
    "joy": [
        ("PARAM_MOUTH_FORM", +0.50),    # smile, visible
        ("PARAM_BROW_L_Y", +0.20),      # brows lift
        ("PARAM_BROW_R_Y", +0.20),
        ("PARAM_EYE_L_OPEN", +0.10),    # eyes widen a touch
        ("PARAM_EYE_R_OPEN", +0.10),
        ("PARAM_TERE", +0.15),          # soft blush on strong joy
    ],
    "sadness": [
        ("PARAM_MOUTH_FORM", -0.45),    # clear frown
        ("PARAM_BROW_L_Y", -0.35),      # brows down
        ("PARAM_BROW_R_Y", -0.35),
        ("PARAM_BROW_L_ANGLE", +0.35),  # inner-brow up (sad face)
        ("PARAM_BROW_R_ANGLE", -0.35),
        ("PARAM_EYE_L_OPEN", -0.25),    # lids droop
        ("PARAM_EYE_R_OPEN", -0.25),
    ],
    "anger": [
        ("PARAM_BROW_L_Y", -0.50),      # brows SLAM down
        ("PARAM_BROW_R_Y", -0.50),
        ("PARAM_BROW_L_ANGLE", -0.35),  # inner-brow down (angry V)
        ("PARAM_BROW_R_ANGLE", +0.35),
        ("PARAM_MOUTH_FORM", -0.25),    # downturn
    ],
    "surprise": [
        ("PARAM_BROW_L_Y", +0.55),      # brows fly up, hard
        ("PARAM_BROW_R_Y", +0.55),
        ("PARAM_EYE_L_OPEN", +0.50),    # eyes SAUCERS
        ("PARAM_EYE_R_OPEN", +0.50),
        ("PARAM_MOUTH_OPEN_Y", +0.30),  # mouth opens visibly
    ],
    "shy_blush": [
        ("PARAM_TERE", +0.55),          # full blush
        ("PARAM_EYE_BALL_Y", -0.25),    # gaze drops
        ("PARAM_MOUTH_FORM", +0.15),    # shy smile
        ("PARAM_BROW_L_Y", -0.10),      # brows soften
        ("PARAM_BROW_R_Y", -0.10),
    ],
}


def blend_to_param_deltas(
    blend: AffectBlend,
    valence: Optional[float] = None,
) -> Dict[str, float]:
    """Convert an AffectBlend into a {param_id: delta_value} dict.

    Each delta is a SIGNED FLOAT in roughly [-0.3, +0.3], to be ADDED
    to whatever the motion is currently driving the parameter to.
    The frontend sidecar uses Cubism's per-frame parameter setter;
    if it sets the same param multiple times per frame (motion +
    expression), the SDK averages or adds depending on the parameter's
    `bridge` flag. For PartOpacity this won't matter because expression
    deltas only touch face params, not arms.

    Mood-baseline modulation: if valence is provided in [-1, 1], the
    joy axis is scaled by max(0.5, (1 + valence) / 2). A character
    with very low valence (-1) caps joy intensity at 0.0 (totally
    blocked); valence 0 caps at 0.5 (half intensity); valence +1 keeps
    joy at full strength. Sadness axis gets the opposite treatment
    (high-valence character can still express sadness, but it's
    capped at half).
    """
    deltas: Dict[str, float] = {}

    # Modulate by mood baseline if provided
    joy_scale = 1.0
    sadness_scale = 1.0
    if valence is not None:
        # Joy: high valence boosts, low valence dampens
        joy_scale = max(0.0, (1.0 + valence) / 2.0)
        # Sadness: low valence boosts, high valence dampens
        sadness_scale = max(0.0, (1.0 - valence) / 2.0 + 0.5)
        sadness_scale = min(1.0, sadness_scale)  # cap at 1.0

    scaled = {
        "joy": blend.joy * joy_scale,
        "sadness": blend.sadness * sadness_scale,
        "anger": blend.anger,
        "surprise": blend.surprise,
        "shy_blush": blend.shy_blush,
    }

    for axis, intensity in scaled.items():
        if intensity <= 0.0:
            continue
        for param_id, max_delta in PARAM_MAP[axis]:
            contribution = max_delta * intensity
            deltas[param_id] = deltas.get(param_id, 0.0) + contribution

    # Final clamp on aggregated deltas — overlapping axes can stack
    # (e.g. both joy+surprise want PARAM_BROW up). Cap at ±0.8 per
    # parameter so that simultaneous-axis stacking stays visible while
    # still preventing the face going fully off-model.
    return {pid: max(-0.8, min(0.8, v)) for pid, v in deltas.items()}


def build_expression_message(
    sentence: str,
    valence: Optional[float] = None,
    duration_ms: Optional[int] = None,
) -> Dict:
    """Build the full WebSocket message the frontend will receive.

    If duration_ms is None, we estimate from sentence length — roughly
    80ms per character, clamped to [600ms, 4000ms]. This keeps the
    envelope active for long-form content (sea shanty verses,
    storytelling) where the old fixed 600ms faded out 3 seconds
    before TTS finished. Short exclamations still get a short window.
    """
    blend = infer(sentence)
    deltas = blend_to_param_deltas(blend, valence=valence)
    if duration_ms is None:
        est = 80 * max(1, len(sentence or ""))
        duration_ms = max(600, min(4000, est))
    return {
        "type": "expression_blend",
        "blend": blend.to_dict(),
        "deltas": deltas,
        "duration_ms": duration_ms,
        "reason": blend.reason,
    }
