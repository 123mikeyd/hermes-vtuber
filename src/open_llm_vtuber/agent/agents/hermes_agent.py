"""
Hermes Agent for Open-LLM-VTuber

Calls Hermes Agent CLI directly to get responses.
Uses the decorator pipeline pattern like basic_memory_agent.

Phase 1 — Session-Resumed IPC (Apr 17, 2026)
--------------------------------------------
Turn 1: spawn `hermes chat -Q -q "..." --pass-session-id --source tool`,
        capture the session_id from the first stdout line matching
        `session_id: <id>`.
Turn 2+: spawn `hermes chat -Q -q "..." --resume <id> --source tool`.
        Hermes reuses the existing session — skills, memory, provider config
        are already loaded. The per-turn subprocess still exists (this is
        not true streaming IPC yet — that's Phase 1.5 via ACP), but startup
        cost per turn drops dramatically after turn 1.

Why --source tool:
    Keeps our vtuber calls out of the user's `hermes chat --continue` recent
    session list. Without it, every vtuber interaction would clutter the
    user's own session history.

Why --pass-session-id:
    Forces hermes to include the `session_id:` line even in quiet mode, so
    we can parse the id for resuming.

GOTCHA — session_id is on STDERR, not STDOUT.
    Hermes in -Q mode writes the clean response to stdout and the
    `session_id: <id>` line to stderr. Old code read only stdout and silently
    fell through to the always-fresh-session fallback path. We now read both
    streams and scan stderr first for the session id. If hermes changes and
    starts emitting session_id on stdout again, the scanner still works
    because it checks both streams.

The resume banner "↻ Resumed session <id> ..." IS emitted on stdout even
in -Q mode, so _clean_response() strips it (the line can have \r\n line
endings — the regex handles that).
"""

import asyncio
import re
from typing import AsyncIterator, List, Dict, Any, Union, Optional, Callable
from loguru import logger

from .agent_interface import AgentInterface
from ..output_types import SentenceOutput, DisplayText, Actions
from ..transformers import (
    sentence_divider,
    actions_extractor,
    tts_filter,
    display_processor,
)
from ...config_manager import TTSPreprocessorConfig
from ..input_types import BatchInput, TextSource

# Persona v2 (Phase 2a). Optional — agent still works with plain `system` string.
from ...persona import Identity, SessionMemory, PersonaComposer


# Matches the session_id line hermes emits when --pass-session-id is set.
# Example: "session_id: 20260417_014722_742a04"
SESSION_ID_RE = re.compile(r"^session_id:\s*(\S+)\s*$", re.MULTILINE)

# Matches the resume banner that appears on every --resume call, even with -Q.
# Example: "↻ Resumed session 20260417_014722_742a04 (1 user message, 2 total messages)"
# Note: hermes emits this line with \r\n on some platforms, so \r is tolerated.
RESUME_BANNER_RE = re.compile(r"^[↻↩↪]\s*Resumed session\s+\S+.*?\r?$", re.MULTILINE)


class HermesAgent(AgentInterface):
    """Agent that calls Hermes Agent CLI for responses.

    Maintains one hermes session per agent instance, resuming it on each
    turn to avoid per-turn startup cost and skill-reload overhead.
    """

    def __init__(
        self,
        hermes_path: str = "hermes",
        system: str = "",
        live2d_model=None,
        tts_preprocessor_config: TTSPreprocessorConfig = None,
        faster_first_response: bool = True,
        segment_method: str = "pysbd",
        model: str = "",
        timeout: int = 120,
        # Phase 2a — persona memory layer (all optional for backward compat)
        identity: Optional[Identity] = None,
        session_memory: Optional[SessionMemory] = None,
        composer: Optional[PersonaComposer] = None,
    ):
        super().__init__()
        self._hermes_path = hermes_path
        self._system = system
        self._live2d_model = live2d_model
        self._tts_preprocessor_config = tts_preprocessor_config
        self._faster_first_response = faster_first_response
        self._segment_method = segment_method
        self._model = model
        self._timeout = timeout

        # Phase 2a: identity is injected by the composer on turn 1.
        # session_memory records every turn and provides the recent window +
        # rolling summary. composer assembles everything with budget caps.
        # If identity is None, we fall back to the classic `system` path —
        # persona v2 is fully optional.
        self._identity = identity
        self._session_memory = session_memory or SessionMemory()
        self._composer = composer or PersonaComposer()

        # In-agent memory is now a fallback. Hermes holds the real conversation.
        # We keep this only for handle_interrupt() and for the first-turn
        # system prompt injection.
        self._memory: List[Dict[str, str]] = []

        # THE Phase 1 change: persistent session id across turns.
        self._session_id: Optional[str] = None

        # Counter — how many lines did _clean_response strip? For debugging
        # and to confirm the IPC improvement is actually reducing artifacts.
        self._strip_counter = 0

        logger.info(f"HermesAgent initialized with hermes at: {hermes_path}")

    def set_system(self, system: str):
        """Set the system prompt. Used only on the FIRST turn (turn 1 of a
        fresh session), because hermes carries system context forward on
        resume. If the caller re-sets system mid-session, we have a decision
        to make — for now, log a warning and honor it for the NEXT turn only.
        """
        if self._session_id and system != self._system:
            logger.warning(
                "set_system() called on an already-established hermes session. "
                "Hermes carries its own system context forward on resume, so this "
                "change only affects the per-turn prompt prefix we prepend, not "
                "the resumed hermes session itself."
            )
        self._system = system
        logger.debug(f"HermesAgent system: {system[:100]}...")

    def _add_message(self, role: str, content: str):
        """Add message to conversation memory (fallback / interrupt handling).

        Note: hermes itself tracks the full conversation in the resumed
        session. This list is kept only to reconstruct a prompt prefix on
        the very first turn, and to record interruption markers.
        """
        if not content:
            return
        if (
            self._memory
            and self._memory[-1]["role"] == role
            and self._memory[-1]["content"] == content
        ):
            return
        self._memory.append({"role": role, "content": content})

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """
        Remove thinking/reasoning content from model output.

        Handles:
        - XML-style think tags: <think>...</think>
        - Standalone <think> or </think> tags
        - Horizontal rule patterns (---, ___, ***)
        - Lines of pure dash/colon reasoning artifacts
        """
        # Remove <think>...</think> blocks (case-insensitive, dotall)
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)

        # Remove standalone <think> or </think> tags
        text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE)

        # Remove horizontal rule patterns
        text = re.sub(r"^[ \t]*[-_*]{3,}[ \t]*$", "", text, flags=re.MULTILINE)

        # Remove pure dash/colon formatting lines
        text = re.sub(r"^[ \t]*[-:]{2,}.*$", "", text, flags=re.MULTILINE)

        # Collapse excess blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()

    def _build_prompt(self, user_message: str) -> str:
        """Build the prompt passed to `hermes chat -q`.

        On turn 1 (no session yet): include system + memory prefix so
        hermes starts the new session with our persona context.

        On turn 2+: just the user's new message. Hermes already has the
        persona + prior turns in the resumed session's state.

        Phase 2a: when an Identity is attached, use PersonaComposer to
        build the tier 1 + tier 3 system block. Otherwise fall back to
        the classic `self._system` string for backward compatibility.
        """
        if self._session_id is None:
            # First turn — prime hermes with the full composed system prompt
            if self._identity is not None:
                composed = self._composer.compose(
                    identity=self._identity,
                    session_memory=self._session_memory,
                )
                logger.info(
                    f"First-turn system prompt: {composed.tokens_estimated} est. tokens "
                    f"(budget {composed.tokens_budget}, truncated={composed.truncated})"
                )
                return f"System: {composed.text}\n\nUser: {user_message}\n\nAssistant:"

            # Legacy path — plain system string + ad-hoc memory list
            parts = []
            if self._system:
                parts.append(f"System: {self._system}")
            recent = self._memory[-10:] if len(self._memory) > 10 else self._memory
            for msg in recent:
                role = msg["role"].capitalize()
                parts.append(f"{role}: {msg['content']}")
            parts.append(f"User: {user_message}")
            parts.append("Assistant:")
            return "\n".join(parts)

        # Resume path — hermes remembers. Just send the new turn.
        return user_message

    def _clean_response(self, text: str) -> str:
        """
        Strip CLI metadata artifacts from hermes output.

        Removes:
        - ASCII art banner (╭─╮ box drawing)
        - Tool/skill listings
        - Session info, duration, "Resume with:" lines
        - Separator lines (───, ===)
        - "Initializing agent..." and status lines
        - "Query:" prompt echo
        - Resume banner from --resume calls ("↻ Resumed session <id>...")
        """
        # Strip the resume banner (one line, preserves everything else)
        text, n_resume = RESUME_BANNER_RE.subn("", text)

        lines = text.split("\n")
        cleaned = []
        in_banner = False
        stripped_count = n_resume

        for line in lines:
            stripped = line.strip()

            # Box drawing banner boundaries
            if stripped.startswith("╭") or stripped.startswith("╰"):
                in_banner = not stripped.startswith("╰")
                stripped_count += 1
                continue
            if stripped.startswith("│"):
                stripped_count += 1
                continue

            # Separator lines of dashes / equals
            if re.match(r"^[─═\-]{10,}$", stripped):
                stripped_count += 1
                continue

            # Known status/metadata line prefixes
            if any(
                stripped.startswith(p)
                for p in [
                    "Initializing agent",
                    "Query:",
                    "Resume this session",
                    "Session:",
                    "Duration:",
                    "Messages:",
                    "Hermes Agent v",
                    "Available Tools",
                    "Available Skills",
                ]
            ):
                stripped_count += 1
                continue

            # Hermes labeled separator
            if "Hermes" in stripped and "─" in stripped:
                stripped_count += 1
                continue

            # Empty lines at boundaries
            if not stripped and not cleaned:
                continue

            cleaned.append(line)

        # Strip trailing empty lines
        while cleaned and not cleaned[-1].strip():
            cleaned.pop()

        self._strip_counter += stripped_count
        if stripped_count and self._session_id:
            # After turn 1, this should be near zero. Log it if it isn't.
            logger.debug(
                f"_clean_response stripped {stripped_count} lines "
                f"(session {self._session_id[:20]}...)"
            )

        return "\n".join(cleaned)

    def _extract_and_strip_session_id(self, text: str) -> str:
        """Pull out session_id from hermes output, update state, return
        the text with session_id lines removed.
        """
        match = SESSION_ID_RE.search(text)
        if match and not self._session_id:
            self._session_id = match.group(1)
            logger.info(f"HermesAgent pinned session: {self._session_id}")
        elif match and match.group(1) != self._session_id:
            # Hermes gave us a different session id — this shouldn't happen
            # on --resume, but log if it does.
            logger.warning(
                f"Session id changed mid-life: {self._session_id} -> "
                f"{match.group(1)}. Pinning the new one."
            )
            self._session_id = match.group(1)

        # Remove ALL session_id: lines from the text
        return SESSION_ID_RE.sub("", text)

    def _build_cmd(self, prompt: str) -> List[str]:
        """Build the hermes chat command. First turn starts a fresh session
        with --pass-session-id so we can capture the id. Later turns resume.
        """
        cmd = [self._hermes_path, "chat", "-Q", "-q", prompt, "--source", "tool"]

        if self._session_id is None:
            cmd.append("--pass-session-id")
        else:
            cmd.extend(["--resume", self._session_id])

        if self._model:
            cmd.extend(["--model", self._model])

        return cmd

    async def _call_hermes(self, prompt: str) -> str:
        """Call hermes CLI and return response.

        First call: starts a fresh session, captures session_id.
        Subsequent calls: resumes the pinned session.
        """
        cmd = self._build_cmd(prompt)
        is_first = self._session_id is None
        logger.debug(
            f"Calling hermes ({'fresh' if is_first else 'resume ' + self._session_id[:20]}): "
            f"{' '.join(cmd[:5])}..."
        )

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self._timeout
            )

            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="replace").strip()
                logger.error(f"Hermes error (exit {process.returncode}): {error_msg}")
                return f"[Hermes error: {error_msg[:200]}]"

            stdout_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")

            # session_id emits to STDERR in quiet mode, not stdout.
            # Scan both streams — stderr first (where --pass-session-id puts it),
            # stdout second (where older hermes versions emitted it and where
            # the --resume banner also lives).
            self._extract_and_strip_session_id(stderr_text)
            response = self._extract_and_strip_session_id(stdout_text).strip()

            # Strip thinking/reasoning content
            response = self._strip_thinking(response)

            # Strip CLI banner, metadata, resume banner, session info
            response = self._clean_response(response)

            response = response.strip()
            if not response:
                logger.warning("Hermes returned empty response after stripping")
                return "[No response]"

            logger.info(f"Hermes response: {len(response)} chars")
            return response

        except asyncio.TimeoutError:
            logger.error(f"Hermes timed out after {self._timeout}s")
            return "[Hermes timed out]"
        except FileNotFoundError:
            logger.error(f"Hermes not found at: {self._hermes_path}")
            return "[Hermes not found]"
        except Exception as e:
            logger.error(f"Error calling hermes: {e}")
            return f"[Error: {str(e)[:200]}]"

    async def _refresh_summary(self) -> None:
        """Background task: regenerate the rolling summary of older turns.

        Runs out-of-band from the user's active turn. Uses a SEPARATE
        hermes session (no --resume) so we don't contaminate the
        character's own conversation state with summarization prompts.

        Failures are logged and swallowed — summarization is best-effort,
        never blocks the user, and stale summaries degrade gracefully.
        """
        from ...persona.session_memory import build_summary_prompt
        try:
            older = self._session_memory.older_than_recent()
            if not older:
                return
            prompt = build_summary_prompt(
                older, prior_summary=self._session_memory.rolling_summary
            )
            logger.debug(
                f"Refreshing rolling summary over {len(older)} older turns "
                f"({len(prompt)} prompt chars)"
            )
            # Call hermes with a FRESH session — intentionally no --resume.
            cmd = [
                self._hermes_path, "chat", "-Q", "-q", prompt,
                "--source", "tool",
            ]
            if self._model:
                cmd.extend(["--model", self._model])
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout
            )
            if proc.returncode != 0:
                logger.warning(
                    f"Summary refresh exited {proc.returncode}: "
                    f"{stderr.decode('utf-8', errors='replace')[:200]}"
                )
                return
            summary_text = self._clean_response(
                self._strip_thinking(stdout.decode("utf-8", errors="replace").strip())
            ).strip()
            if summary_text:
                self._session_memory.set_summary(summary_text)
        except Exception as e:
            logger.warning(f"Summary refresh failed (non-fatal): {e}")

    def _chat_function_factory(
        self,
    ) -> Callable[[BatchInput], AsyncIterator[Union[SentenceOutput, Dict[str, Any]]]]:
        """Create the decorated chat pipeline."""

        @tts_filter(self._tts_preprocessor_config)
        @display_processor()
        @actions_extractor(self._live2d_model)
        @sentence_divider(
            faster_first_response=self._faster_first_response,
            segment_method=self._segment_method,
            valid_tags=["think"],
        )
        async def chat_with_hermes(
            input_data: BatchInput,
        ) -> AsyncIterator[Union[str, Dict[str, Any]]]:
            """Process chat through hermes CLI."""
            user_text = ""
            for text_data in input_data.texts:
                if text_data.source == TextSource.INPUT:
                    user_text = text_data.content
                    break

            if not user_text:
                logger.warning("No input text received")
                return

            logger.info(f"HermesAgent received: {user_text[:100]}...")

            # Build prompt (differs for first turn vs resume)
            prompt = self._build_prompt(user_text)

            # Call hermes. After this, self._session_id is set (if it wasn't already).
            full_response = await self._call_hermes(prompt)

            # Track the user + assistant turns in our fallback memory too.
            # We don't feed these back in later prompts (hermes has them),
            # but interrupt handling reads this list.
            self._add_message("user", user_text)
            self._add_message("assistant", full_response)

            # Phase 2a: also record into SessionMemory for the tier-3 window
            # and future rolling summary. Separate from self._memory because
            # SessionMemory carries timestamps, persists to disk, and is what
            # the composer reads on the NEXT new session to remember context.
            self._session_memory.add_turn("user", user_text)
            self._session_memory.add_turn("assistant", full_response)
            if self._session_memory.needs_summary():
                # Fire-and-forget: schedule summarization but don't await.
                # The refreshed summary will be in place for any NEW session
                # we start later; mid-session hermes has its own memory.
                asyncio.create_task(self._refresh_summary())

            # Yield tokens so sentence_divider can process them
            tokens = full_response.split()
            for token in tokens:
                yield token + " "

        return chat_with_hermes

    async def chat(
        self,
        input_data: BatchInput,
    ) -> AsyncIterator[Union[SentenceOutput, Dict[str, Any]]]:
        """Run chat pipeline through hermes."""
        chat_func = self._chat_function_factory()
        async for output in chat_func(input_data):
            yield output

    def handle_interrupt(self, heard_response: str) -> None:
        """Handle user interruption.

        We record the interruption in our fallback memory. On the next turn,
        hermes's session still contains the FULL (unfinished) response it
        generated — we can't easily tell hermes "the user only heard X" from
        here, but we can log it for later. Phase 1.5 (ACP) will allow us to
        properly cancel mid-generation.
        """
        logger.info(f"Interrupted. Heard: {heard_response[:50]}...")
        if heard_response:
            self._add_message("assistant", heard_response + "...")
        self._add_message("user", "[Interrupted by user]")

    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None:
        """Load memory from chat history.

        Phase 1 behavior: if an existing hermes session was pinned for this
        (conf_uid, history_uid) pair, resume it. Otherwise start fresh.

        Index mapping is stored in chat_history/hermes_sessions.json and is
        managed by the session_memory module (coming in Phase 2). For now,
        we simply reset — the first hermes call will mint a new session.
        """
        logger.info(f"Loading history: {conf_uid}/{history_uid}")
        # TODO (Phase 2): load pinned session_id from hermes_sessions.json
        self._memory = []
        self._session_id = None
        self._strip_counter = 0
