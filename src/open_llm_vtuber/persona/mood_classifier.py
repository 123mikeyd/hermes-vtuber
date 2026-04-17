"""
Phase 3 — Mood Classifier (heuristic).

Given the most recent user message and the character's last response,
produces a MoodDelta for mood.py to apply.

Why heuristic and not an LLM call:

 - Speed. This runs on every assistant turn. An extra hermes subprocess
   per turn would add 3-5s of latency for a one-dimensional improvement.
 - Explainability. When the character "seems sad for no reason" you can
   read the log line and see exactly which words tripped which axis.
 - Cost. A VTuber who might run for hours of stream time doesn't need to
   burn tokens on self-classification.
 - Zero deps. No model to download, no tokenizer to load.

The interface (`classify(user_text, assistant_text) -> MoodDelta`) is
stable. If someone wants to swap in a transformer-based classifier later,
they implement the same signature and pass the new instance to the
HermesAgent. The engine doesn't care.

Tuning:
 - Lexicons are intentionally small. False positives on a big lexicon
   feel worse than low recall. We'd rather miss a subtle mood shift than
   invent one that isn't there.
 - Each hit contributes +/- 0.1 on the relevant axis, clamped to [-1, 1].
 - Exclamation marks and question marks nudge arousal.
 - ALL CAPS words (len >= 3) nudge arousal up.
 - Expression-keyword tags like [happy], [angry] — if the LLM emitted
   them — count as explicit mood signals (strongest contribution).

Part of: .hermes/plans/2026-04-17_personality-evolution.md (Phase 3)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, Tuple

from loguru import logger

from .mood import MoodDelta


# --- Lexicons ---
# Each set is SMALL on purpose. Missing a word is cheaper than adding a
# word that fires on the wrong context. Add entries as you hit real
# false negatives in logs.

VALENCE_POSITIVE = {
    # Feelings
    "happy", "glad", "excited", "love", "loved", "loving", "great",
    "awesome", "wonderful", "amazing", "beautiful", "nice", "fun",
    "enjoy", "enjoyed", "enjoying", "thank", "thanks", "grateful",
    "appreciate", "proud", "pleased", "hopeful",
    # Social warmth
    "friend", "together", "welcome",
    # Achievement
    "won", "success", "finished", "finally", "yes",
}

VALENCE_NEGATIVE = {
    "sad", "hurt", "hurts", "pain", "painful", "tired", "exhausted",
    "angry", "mad", "frustrated", "frustrating", "annoyed", "annoying",
    "stupid", "awful", "terrible", "horrible", "worst", "worse",
    "hate", "hated", "hates", "hating", "broke", "broken", "failing",
    "failed", "fail", "lost", "loss", "lose", "miss", "missed",
    "sorry", "scared", "afraid", "worried", "worry", "stuck",
    "alone", "lonely", "cry", "cried", "crying", "dead", "die",
    "suck", "sucks", "sucked", "bad", "wrong",
}

AROUSAL_HIGH = {
    "wow", "whoa", "omg", "ahh", "oh", "yay", "yes", "let's",
    "let's go", "come on", "go", "fight", "rush", "quick", "fast",
    "now", "hurry", "instant", "immediate",
    # Intensity
    "absolutely", "totally", "completely", "insanely", "super",
    "so", "really", "extremely",
    # Conflict / urgency
    "danger", "danger!", "emergency", "alarm", "watch",
}

AROUSAL_LOW = {
    "tired", "exhausted", "sleepy", "boring", "bored", "slow",
    "quiet", "calm", "chill", "relax", "relaxed", "relaxing",
    "peaceful", "whatever", "meh", "eh", "yawn",
}

SOCIAL_POSITIVE = {
    "you", "your", "we", "us", "together", "friend", "friends",
    "team", "chat", "talk", "tell", "share",
}

SOCIAL_NEGATIVE = {
    "alone", "lonely", "quiet", "solo", "myself", "nobody", "shut",
    "leave", "go away", "stop",
}

FOCUS_HIGH = {
    "think", "thinking", "idea", "let's", "plan", "because", "reason",
    "specifically", "exactly", "precisely", "first", "second", "step",
    "steps", "build", "building", "figure", "solve", "solved", "solving",
    "focus", "focused", "details", "detail",
}

FOCUS_LOW = {
    "whatever", "idk", "dunno", "whatever", "random", "maybe",
    "something", "anyway", "confused", "confusing", "lost", "blank",
}

# Expression-keyword tags the LLM might emit (legacy pre-Phase-5 system).
# These contribute strong deltas because they're EXPLICIT signals, not
# keyword guesses.
EXPRESSION_TAGS: Dict[str, MoodDelta] = {
    "happy":     MoodDelta(valence=+0.5, arousal=+0.2, social=+0.2, reason="[happy] tag"),
    "smile":     MoodDelta(valence=+0.4, reason="[smile] tag"),
    "laugh":     MoodDelta(valence=+0.5, arousal=+0.4, social=+0.3, reason="[laugh] tag"),
    "excited":   MoodDelta(valence=+0.4, arousal=+0.6, reason="[excited] tag"),
    "sad":       MoodDelta(valence=-0.5, arousal=-0.2, reason="[sad] tag"),
    "angry":     MoodDelta(valence=-0.4, arousal=+0.5, social=-0.3, reason="[angry] tag"),
    "surprised": MoodDelta(arousal=+0.5, focus=+0.3, reason="[surprised] tag"),
    "tired":     MoodDelta(arousal=-0.6, reason="[tired] tag"),
    "bored":     MoodDelta(arousal=-0.4, focus=-0.3, reason="[bored] tag"),
    "calm":      MoodDelta(arousal=-0.2, valence=+0.1, reason="[calm] tag"),
    "thinking":  MoodDelta(focus=+0.5, arousal=-0.1, reason="[thinking] tag"),
    "confused":  MoodDelta(focus=-0.5, reason="[confused] tag"),
}

# Word boundary tokenizer — simple, fast, Unicode-aware enough for our
# lexicons which are all ASCII.
_WORD_RE = re.compile(r"\b[a-zA-Z']+\b")
_TAG_RE = re.compile(r"\[([a-zA-Z_]+)\]")


def _tokenize(text: str) -> Iterable[str]:
    """Lowercase word tokens from text."""
    for m in _WORD_RE.finditer(text.lower()):
        yield m.group(0)


def _count_hits(tokens: list[str], lexicon: set[str]) -> int:
    """Count how many tokens fall in the lexicon."""
    return sum(1 for t in tokens if t in lexicon)


def _extract_tags(text: str) -> list[str]:
    """Pull all [tag] strings from text, lowercase."""
    return [m.group(1).lower() for m in _TAG_RE.finditer(text)]


def _caps_word_count(text: str) -> int:
    """How many all-caps words (length >= 3) appear. "I'M" doesn't count.
    Rough arousal proxy.
    """
    return sum(
        1
        for w in re.findall(r"\b[A-Z][A-Z'A-Z]{2,}\b", text)
        if w.replace("'", "").isalpha()
    )


def classify(user_text: str, assistant_text: str) -> MoodDelta:
    """Compute a mood delta from this turn's exchange.

    The user's message gets 2x weight on valence/arousal (we track what
    the USER brought into the room) but 1x on focus (the ASSISTANT's
    focus state is more about how clearly they're thinking).

    Returns a MoodDelta the caller passes to MoodState.apply_delta().
    """
    user_text = user_text or ""
    assistant_text = assistant_text or ""

    # Tokenize once
    u_tokens = list(_tokenize(user_text))
    a_tokens = list(_tokenize(assistant_text))

    # --- Explicit expression tags from the assistant (strongest signal) ---
    explicit_delta = MoodDelta()
    explicit_reasons: list[str] = []
    for tag in _extract_tags(assistant_text):
        if tag in EXPRESSION_TAGS:
            d = EXPRESSION_TAGS[tag]
            explicit_delta = MoodDelta(
                valence=explicit_delta.valence + d.valence,
                arousal=explicit_delta.arousal + d.arousal,
                social=explicit_delta.social + d.social,
                focus=explicit_delta.focus + d.focus,
                reason=explicit_delta.reason,
            )
            explicit_reasons.append(f"[{tag}]")

    # --- Lexicon contributions ---
    def hits(tokens: list[str], lex: set[str]) -> int:
        return _count_hits(tokens, lex)

    STEP = 0.1

    # Valence: user 2x, assistant 1x
    valence = (
        +STEP * (2 * hits(u_tokens, VALENCE_POSITIVE) + hits(a_tokens, VALENCE_POSITIVE))
        - STEP * (2 * hits(u_tokens, VALENCE_NEGATIVE) + hits(a_tokens, VALENCE_NEGATIVE))
    )

    # Arousal: both streams equal. Add punctuation + caps contributions.
    arousal = (
        +STEP * (hits(u_tokens, AROUSAL_HIGH) + hits(a_tokens, AROUSAL_HIGH))
        - STEP * (hits(u_tokens, AROUSAL_LOW) + hits(a_tokens, AROUSAL_LOW))
    )
    # Exclamation marks
    arousal += 0.05 * min(4, user_text.count("!") + assistant_text.count("!"))
    # Questions from the user often increase engagement/arousal
    arousal += 0.03 * min(3, user_text.count("?"))
    # Caps shouting
    arousal += 0.08 * min(3, _caps_word_count(user_text) + _caps_word_count(assistant_text))

    # Social: weighted toward user (they're the one driving openness)
    social = (
        +STEP * (2 * hits(u_tokens, SOCIAL_POSITIVE) + hits(a_tokens, SOCIAL_POSITIVE))
        - STEP * (2 * hits(u_tokens, SOCIAL_NEGATIVE) + hits(a_tokens, SOCIAL_NEGATIVE))
    )

    # Focus: weighted toward assistant (it's about THEIR cognitive state)
    focus = (
        +STEP * (hits(u_tokens, FOCUS_HIGH) + 2 * hits(a_tokens, FOCUS_HIGH))
        - STEP * (hits(u_tokens, FOCUS_LOW) + 2 * hits(a_tokens, FOCUS_LOW))
    )

    # --- Combine heuristic + explicit (but scale heuristic so tags dominate) ---
    if explicit_delta.valence or explicit_delta.arousal or explicit_delta.social or explicit_delta.focus:
        # Explicit tag present — scale lexicon hits down, let the tag lead.
        valence = 0.5 * valence + explicit_delta.valence
        arousal = 0.5 * arousal + explicit_delta.arousal
        social = 0.5 * social + explicit_delta.social
        focus = 0.5 * focus + explicit_delta.focus

    # Build the reason string for logs — keep it compact
    reason_parts: list[str] = []
    if explicit_reasons:
        reason_parts.append("explicit:" + "+".join(explicit_reasons))
    # Summarize lexicon hits
    counts = {
        "v+": hits(u_tokens, VALENCE_POSITIVE) + hits(a_tokens, VALENCE_POSITIVE),
        "v-": hits(u_tokens, VALENCE_NEGATIVE) + hits(a_tokens, VALENCE_NEGATIVE),
        "a+": hits(u_tokens, AROUSAL_HIGH) + hits(a_tokens, AROUSAL_HIGH),
        "a-": hits(u_tokens, AROUSAL_LOW) + hits(a_tokens, AROUSAL_LOW),
    }
    nonzero = {k: v for k, v in counts.items() if v}
    if nonzero:
        reason_parts.append(",".join(f"{k}:{v}" for k, v in nonzero.items()))
    reason = " ".join(reason_parts) or "baseline-drift"

    delta = MoodDelta(
        valence=round(valence, 3),
        arousal=round(arousal, 3),
        social=round(social, 3),
        focus=round(focus, 3),
        reason=reason,
    )

    # Only log if the delta is meaningful
    if abs(delta.valence) + abs(delta.arousal) + abs(delta.social) + abs(delta.focus) > 0.0:
        logger.debug(
            f"MoodClassifier produced: "
            f"v={delta.valence:+.2f} a={delta.arousal:+.2f} "
            f"s={delta.social:+.2f} f={delta.focus:+.2f} ({reason})"
        )

    return delta
