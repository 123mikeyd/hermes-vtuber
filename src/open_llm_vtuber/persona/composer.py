"""
PersonaComposer — assembles Tier 1 + (Tier 2, later) + Tier 3 into a
budget-aware system prompt for injection on turn 1 of a new hermes session.

Budgets are expressed in estimated tokens (1 tok ≈ 4 chars). The composer
can't actually count model-specific tokens without loading a tokenizer,
so we deliberately over-estimate by rounding up, then leave 25% headroom
below the advertised context window.

On turn 2+ of a resumed session, we do NOT call the composer — hermes
already has identity + memory in its session state from turn 1. The
agent layer calls compose() only when starting a fresh session.

Part of: .hermes/plans/2026-04-17_personality-evolution.md (Phase 2a)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List
from loguru import logger

from .identity import Identity
from .session_memory import SessionMemory


# Default total budget for the composed system prompt. Tuned for common
# small-context models (8k). Callers with bigger models can bump this.
DEFAULT_TOTAL_BUDGET_TOKENS = 2500

# Per-tier soft caps. Composer enforces these BEFORE the total budget
# check, so no single tier can consume everything. Identity has no cap
# because if the character's core definition doesn't fit, nothing works.
TIER3_SUMMARY_CAP_TOKENS = 500
TIER3_RECENT_CAP_TOKENS = 1200


@dataclass
class ComposedPrompt:
    """The output of a compose() call. Carries the rendered text plus
    diagnostics so callers can log / debug budget usage.
    """

    text: str
    tokens_estimated: int
    tokens_budget: int
    tier1_tokens: int
    tier3_summary_tokens: int
    tier3_recent_tokens: int
    truncated: bool  # True if we had to cut content to fit budget

    def __str__(self) -> str:
        return self.text


class PersonaComposer:
    """Stateless composer. Construct once, call compose() per new session.

    The composer does not hold mutable state — identity and session
    memory are passed in on each call. This means a single composer
    instance can serve multiple concurrent sessions (OLLV creates one
    service context per WebSocket, but better safe than sorry).
    """

    def __init__(
        self,
        total_budget_tokens: int = DEFAULT_TOTAL_BUDGET_TOKENS,
        summary_cap: int = TIER3_SUMMARY_CAP_TOKENS,
        recent_cap: int = TIER3_RECENT_CAP_TOKENS,
    ):
        self.total_budget_tokens = total_budget_tokens
        self.summary_cap = summary_cap
        self.recent_cap = recent_cap

    def compose(
        self,
        identity: Identity,
        session_memory: Optional[SessionMemory] = None,
        biography_chunks: Optional[List[str]] = None,  # reserved for Phase 2b
    ) -> ComposedPrompt:
        """Compose the full system prompt for a new hermes session.

        Order of sections (top to bottom):
          1. Identity block (tier 1) — character definition
          2. Biography chunks (tier 2, optional, Phase 2b)
          3. Summary of older turns (tier 3, from prior sessions)
          4. Recent turns window (tier 3, from this or prior sessions)
          5. Mood line (Phase 3) — current emotional state in plain English

        If total token estimate exceeds budget, sections 3 and 4 are
        truncated from the OLDEST end — we keep the character intact
        and trim the memory window first. The mood line is ALWAYS kept
        (it's one sentence and the payoff is huge).
        """

        sections: List[str] = []
        tier1_tokens = identity.token_estimate()
        tier3_summary_tokens = 0
        tier3_recent_tokens = 0
        truncated = False

        # 1. Identity — always included, not truncated
        sections.append(identity.render())

        # 2. Biography (reserved — Phase 2b)
        if biography_chunks:
            bio_block = self._render_biography(biography_chunks)
            sections.append(bio_block)

        # 3 + 4. Session memory tier 3
        if session_memory is not None and session_memory.turns:
            # Summary of older turns
            summary_text = session_memory.rolling_summary.strip()
            if summary_text:
                capped_summary, summary_truncated = self._cap(
                    summary_text, self.summary_cap
                )
                truncated = truncated or summary_truncated
                tier3_summary_tokens = self._tok(capped_summary)
                sections.append(
                    "## Prior Context\n"
                    "(Summary of older conversation turns the character "
                    "should remember.)\n\n"
                    + capped_summary
                )

            # Recent turns — render all, then trim oldest if over cap
            recent_text = session_memory.render_recent()
            if recent_text:
                capped_recent, recent_truncated = self._cap_from_start(
                    recent_text, self.recent_cap
                )
                truncated = truncated or recent_truncated
                tier3_recent_tokens = self._tok(capped_recent)
                sections.append(
                    "## Recent Conversation\n"
                    "(The most recent turns, newest last.)\n\n"
                    + capped_recent
                )

        # 5. Mood line (Phase 3). Always append when mood exists —
        # one sentence, high leverage. We place it LAST so it's the
        # final note the LLM reads before generating.
        mood_tokens = 0
        if session_memory is not None and session_memory.mood is not None:
            session_memory.mood.decay_to_now()
            mood_line = session_memory.mood.describe()
            sections.append("## Current State\n" + mood_line)
            mood_tokens = self._tok(mood_line)

        composed = "\n\n---\n\n".join(sections)
        total_tokens = self._tok(composed)

        # Final safety net — if we are still over the total budget,
        # drop tier 3 recent (keeping identity + summary + mood). This
        # almost never fires because per-tier caps handle it, but
        # defense-in-depth.
        if total_tokens > self.total_budget_tokens and tier3_recent_tokens > 0:
            logger.warning(
                f"PersonaComposer total {total_tokens} > budget "
                f"{self.total_budget_tokens}; dropping recent turns entirely"
            )
            # Re-assemble without the recent section. Recent lives at a
            # known position (after summary, before mood) — find and drop.
            new_sections = [s for s in sections if not s.startswith("## Recent Conversation")]
            composed = "\n\n---\n\n".join(new_sections)
            total_tokens = self._tok(composed)
            tier3_recent_tokens = 0
            truncated = True

        result = ComposedPrompt(
            text=composed,
            tokens_estimated=total_tokens,
            tokens_budget=self.total_budget_tokens,
            tier1_tokens=tier1_tokens,
            tier3_summary_tokens=tier3_summary_tokens,
            tier3_recent_tokens=tier3_recent_tokens,
            truncated=truncated,
        )

        logger.debug(
            f"Composed prompt: {total_tokens}/{self.total_budget_tokens} tokens "
            f"(tier1={tier1_tokens}, summary={tier3_summary_tokens}, "
            f"recent={tier3_recent_tokens}, mood={mood_tokens}, "
            f"truncated={truncated})"
        )
        return result

    # --- Helpers ---

    @staticmethod
    def _tok(text: str) -> int:
        """Over-estimate tokens at 1 tok ≈ 4 chars, rounding up."""
        return (len(text) + 3) // 4

    @staticmethod
    def _cap(text: str, cap_tokens: int) -> tuple[str, bool]:
        """Truncate text from the END if it exceeds cap_tokens. Returns
        (possibly-truncated-text, was_truncated_bool).
        """
        if PersonaComposer._tok(text) <= cap_tokens:
            return text, False
        cap_chars = cap_tokens * 4
        return text[:cap_chars - 3] + "...", True

    @staticmethod
    def _cap_from_start(text: str, cap_tokens: int) -> tuple[str, bool]:
        """Truncate text from the BEGINNING if it exceeds cap_tokens —
        used for recent turns, where we want to keep the NEWEST messages
        and drop the oldest.
        """
        if PersonaComposer._tok(text) <= cap_tokens:
            return text, False
        cap_chars = cap_tokens * 4
        truncated = text[-(cap_chars - 3):]
        # Align to a line boundary so we don't chop a turn mid-word
        nl = truncated.find("\n")
        if 0 <= nl < 200:  # only realign if we land near a line break
            truncated = truncated[nl + 1:]
        return "[... earlier turns trimmed ...]\n" + truncated, True

    @staticmethod
    def _render_biography(chunks: List[str]) -> str:
        """Render biography RAG chunks (Phase 2b) as a labeled block."""
        lines = [
            "## Biography (retrieved context)",
            "(Relevant facts about the character, pulled from long-term memory.)",
            "",
        ]
        for i, chunk in enumerate(chunks, 1):
            lines.append(f"### Memory {i}")
            lines.append(chunk.strip())
            lines.append("")
        return "\n".join(lines).rstrip()
