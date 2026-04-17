"""
Tier 1 — Identity.

Static character definition loaded from a YAML file. This is the "who is
this character" block injected into the system prompt on turn 1 of every
new session. Once hermes has the identity in its session, it carries it
forward on `--resume` calls, so we don't need to re-inject on later turns.

Design notes:
 - Everything except `name` and `core` is optional. Missing fields render
   as empty sections that are simply omitted from the composed prompt.
 - The schema is intentionally narrow: name, core, directives, voice,
   taboos, mood_baseline, relationship. Adding new fields later is a
   non-breaking change; the composer just ignores unknown keys.
 - Free-text fields preserve their YAML whitespace. Authors can use
   multi-line block scalars (`|`) for prose without worrying about how
   YAML will fold it.

Part of: .hermes/plans/2026-04-17_personality-evolution.md (Phase 2a)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any, Union

import yaml
from loguru import logger


# Bounds for each mood dimension. Enforced at load time so bad YAML
# doesn't silently corrupt Phase 3 mood math later.
MOOD_MIN = -1.0
MOOD_MAX = 1.0


@dataclass(frozen=True)
class MoodBaseline:
    """The mood vector the character decays toward in the absence of
    conversational stimulus. All four dimensions are in [-1.0, 1.0].

    Phase 3 (mood state machine) will consume this; Phase 2 only loads
    and validates it.
    """

    valence: float = 0.0  # sad/upset (-1) ↔ happy/warm (+1)
    arousal: float = 0.0  # tired/sleepy (-1) ↔ energetic/hyped (+1)
    social: float = 0.0   # withdrawn (-1) ↔ open/chatty (+1)
    focus: float = 0.0    # scattered (-1) ↔ sharp/dialed-in (+1)

    def __post_init__(self) -> None:
        for name, value in (
            ("valence", self.valence),
            ("arousal", self.arousal),
            ("social", self.social),
            ("focus", self.focus),
        ):
            if not (MOOD_MIN <= value <= MOOD_MAX):
                raise ValueError(
                    f"mood_baseline.{name}={value} out of range "
                    f"[{MOOD_MIN}, {MOOD_MAX}]"
                )


@dataclass(frozen=True)
class Identity:
    """Tier 1 persona data — the static "who is this character" block.

    Construct via `load_identity()` from a YAML file, or directly from
    Python for testing.
    """

    # Required
    name: str
    core: str

    # Optional — all default to empty / neutral
    directives: List[str] = field(default_factory=list)
    voice: str = ""
    taboos: List[str] = field(default_factory=list)
    mood_baseline: MoodBaseline = field(default_factory=MoodBaseline)
    relationship: str = ""

    def render(self) -> str:
        """Render this identity as a system-prompt block.

        The shape is deterministic — each section is labeled and
        separated by a single blank line. Sections with empty content
        are omitted entirely (not rendered as empty headers).

        Returns a multi-line string suitable for direct inclusion in
        the system prompt.
        """
        sections: List[str] = []

        # CORE is always present
        sections.append(f"# {self.name}\n{self.core.strip()}")

        if self.directives:
            lines = ["## Directives"]
            lines.extend(f"- {d.strip()}" for d in self.directives if d.strip())
            if len(lines) > 1:  # only emit if we have non-empty entries
                sections.append("\n".join(lines))

        if self.voice.strip():
            sections.append(f"## Voice\n{self.voice.strip()}")

        if self.taboos:
            lines = ["## Avoid"]
            lines.extend(f"- {t.strip()}" for t in self.taboos if t.strip())
            if len(lines) > 1:
                sections.append("\n".join(lines))

        if self.relationship.strip():
            sections.append(f"## Relationship\n{self.relationship.strip()}")

        return "\n\n".join(sections)

    def token_estimate(self) -> int:
        """Rough token estimate (1 token ≈ 4 chars). For composer budgeting.

        We deliberately over-estimate by rounding up so callers don't
        overflow their context window.
        """
        rendered = self.render()
        return (len(rendered) + 3) // 4


def load_identity(source: Union[str, Path, Dict[str, Any]]) -> Identity:
    """Load an Identity from a YAML file path OR a pre-parsed dict.

    Passing a dict is useful for tests and for in-line character configs
    where the identity block lives inside conf.yaml.
    """
    if isinstance(source, (str, Path)):
        path = Path(source).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Identity file not found: {path}")
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        logger.debug(f"Loaded identity from {path}")
    elif isinstance(source, dict):
        data = source
    else:
        raise TypeError(
            f"load_identity expects a path or dict, got {type(source).__name__}"
        )

    # Required fields
    name = data.get("name")
    core = data.get("core")
    if not name or not isinstance(name, str):
        raise ValueError("Identity YAML is missing required string field 'name'")
    if not core or not isinstance(core, str):
        raise ValueError("Identity YAML is missing required string field 'core'")

    # Optional fields with type coercion
    directives_raw = data.get("directives") or []
    if not isinstance(directives_raw, list):
        raise ValueError("'directives' must be a list of strings")
    directives = [str(d) for d in directives_raw]

    voice = str(data.get("voice") or "")

    taboos_raw = data.get("taboos") or []
    if not isinstance(taboos_raw, list):
        raise ValueError("'taboos' must be a list of strings")
    taboos = [str(t) for t in taboos_raw]

    relationship = str(data.get("relationship") or "")

    # Mood baseline — defaults to all zeros if unspecified
    mood_raw: Optional[Dict[str, Any]] = data.get("mood_baseline")
    if mood_raw is None:
        mood = MoodBaseline()
    elif isinstance(mood_raw, dict):
        mood = MoodBaseline(
            valence=float(mood_raw.get("valence", 0.0)),
            arousal=float(mood_raw.get("arousal", 0.0)),
            social=float(mood_raw.get("social", 0.0)),
            focus=float(mood_raw.get("focus", 0.0)),
        )
    else:
        raise ValueError("'mood_baseline' must be a mapping")

    identity = Identity(
        name=name.strip(),
        core=core.strip(),
        directives=directives,
        voice=voice,
        taboos=taboos,
        mood_baseline=mood,
        relationship=relationship,
    )

    logger.info(
        f"Identity loaded: name={identity.name!r}, "
        f"core={len(identity.core)} chars, "
        f"directives={len(identity.directives)}, "
        f"taboos={len(identity.taboos)}, "
        f"est_tokens={identity.token_estimate()}"
    )
    return identity
