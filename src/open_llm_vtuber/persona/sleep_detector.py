"""
Phase 6 — sleep command detector.

Returns True only when the user's input is a STANDALONE, DIRECT command
to take a nap. Per Mike's strict rules (Apr 17, 2026):

  FIRES on:
    "go to sleep"
    "Nova, take a nap."
    "Hey Nova, get some rest please"
    "tap a nap"
    "rest up"
    "go to sleep, please"

  DOES NOT fire on:
    I told my brother "go to sleep" last night    (quoted speech)
    why would someone say go to sleep             (the phrase isn't the command)
    I'm going to take a nap myself                (subject is I, not Nova)
    Nova, remind me to go to sleep in 20 minutes  (too long, phrase embedded)

Rules in code:
  1. Message has >0 chars after whitespace strip
  2. If message contains quote marks around the trigger phrase → reject
  3. Strip direct-address prefixes ('nova,', 'hey nova,', 'hey nova')
     and polite suffixes ('please', '.', '!', '?') and trailing punctuation
  4. The REMAINING string must BE a trigger phrase exactly (case-insensitive),
     not merely contain one
  5. Total original message must be ≤ 8 words (commands are short)

The detector is a pure function — no side effects, no I/O, microsecond
runtime, trivial to unit-test.
"""

from __future__ import annotations

import re
from typing import Iterable


# --- The accepted trigger phrases (lowercase, exact, whitespace-normalized) ---

SLEEP_PHRASES: set[str] = {
    "go to sleep",
    "take a nap",
    "get some rest",
    "rest up",
    "tap a nap",          # Mike's typo made canonical
    "take a rest",
    "get some sleep",
    "sleep now",
    "nap time",
    "time to sleep",
}

# Direct-address prefixes we strip before testing the phrase.
# Keys are normalized (lowercase, single spaces).
_ADDRESS_PREFIXES = (
    "nova",
    "nova,",
    "nova:",
    "hey",
    "hey,",
    "hey nova",
    "hey nova,",
    "hey nova:",
    "ok nova",
    "ok nova,",
    "nova please",
    "nova, please",
    "nova could you",
    "nova would you",
    "nova can you",
    "could you",
    "would you",
    "can you",
    "please",
)

# Polite / punctuation suffixes to strip.
# Note: "now" was tempting to include but it's part of canonical
# phrases ("sleep now", "nap time") so we keep it in the message.
_POLITE_SUFFIXES = (
    "please",
    "thanks",
    "thank you",
)

# Maximum word count for what we'll consider a command
MAX_COMMAND_WORDS = 8


def _normalize(text: str) -> str:
    """Lowercase, collapse whitespace, strip surrounding whitespace."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _strip_trailing_punctuation(text: str) -> str:
    """Drop trailing . ! ? , ; : and whitespace."""
    return re.sub(r"[\s.!?,:;]+$", "", text).strip()


def _has_quoted_phrase(text: str, phrases: Iterable[str]) -> bool:
    """True if any trigger phrase appears inside quote marks (straight or
    smart quotes). That indicates reported speech, not a direct command.
    """
    lower = text.lower()
    # Find quoted spans — single or double, straight or curly
    quote_pattern = re.compile(
        r"""
        "([^"]*)"       |  # "..."
        '([^']*)'       |  # '...'
        [\u201c\u201d]([^\u201c\u201d]*)[\u201c\u201d] |  # smart double
        [\u2018\u2019]([^\u2018\u2019]*)[\u2018\u2019]    # smart single
        """,
        re.VERBOSE,
    )
    for match in quote_pattern.finditer(lower):
        inside = next((g for g in match.groups() if g is not None), "")
        if any(p in inside for p in phrases):
            return True
    return False


def _strip_address_and_polite(text: str) -> str:
    """Peel direct-address prefixes and polite suffixes from `text`.
    Operates iteratively — removing one layer may expose another.
    """
    # Prefer longer prefixes first so "hey nova," doesn't get consumed
    # as just "hey".
    prefixes_sorted = sorted(_ADDRESS_PREFIXES, key=len, reverse=True)
    suffixes_sorted = sorted(_POLITE_SUFFIXES, key=len, reverse=True)

    changed = True
    while changed:
        changed = False
        t = text.strip()
        for p in prefixes_sorted:
            if t == p:
                return ""
            if t.startswith(p + " ") or t.startswith(p + ","):
                t = t[len(p):].lstrip(" ,")
                changed = True
                break
        for s in suffixes_sorted:
            if t.endswith(" " + s) or t.endswith("," + s):
                t = t[:-len(s)].rstrip(" ,")
                changed = True
                break
        text = t
    return _strip_trailing_punctuation(text)


def is_sleep_command(text: str | None) -> bool:
    """Apply all four rules. Return True only for standalone commands."""
    if not text or not text.strip():
        return False

    # Rule 5: word-count gate (cheap, do first)
    if len(text.split()) > MAX_COMMAND_WORDS:
        return False

    normalized = _normalize(text)

    # Rule 2: quote-marked trigger → reported speech, not a command
    if _has_quoted_phrase(normalized, SLEEP_PHRASES):
        return False

    # Rule 3 + 4: strip address/politeness, then the remainder must
    # EQUAL one of the phrases (not just contain it)
    core = _strip_address_and_polite(normalized)
    core = _strip_trailing_punctuation(core)
    if core in SLEEP_PHRASES:
        return True

    # Also: if the WHOLE normalized+depunctuated message IS a phrase,
    # accept it (covers the no-politeness case)
    full_stripped = _strip_trailing_punctuation(normalized)
    if full_stripped in SLEEP_PHRASES:
        return True

    return False
