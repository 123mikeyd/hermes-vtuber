"""
Hermes Agent for Open-LLM-VTuber

Calls Hermes Agent CLI directly to get responses.
Uses the decorator pipeline pattern like basic_memory_agent.
"""

import asyncio
import re
from typing import AsyncIterator, List, Dict, Any, Union, Literal, Callable
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


class HermesAgent(AgentInterface):
    """Agent that calls Hermes Agent CLI for responses."""

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
        self._memory: List[Dict[str, str]] = []

        logger.info(f"HermesAgent initialized with hermes at: {hermes_path}")

    def set_system(self, system: str):
        """Set the system prompt."""
        self._system = system
        logger.debug(f"HermesAgent system: {system[:100]}...")

    def _add_message(self, role: str, content: str):
        """Add message to conversation memory."""
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
        - XML-style think tags: <<think>>...</think>
        - Dash-style reasoning: lines starting with --- or ---
        - Colon-style reasoning: lines starting with ::
        - Bullet-style reasoning: lines starting with * or -
        """
        # Remove <<think>>...</think> blocks (case-insensitive, dotall)
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)

        # Remove standalone <think> or </think> tags
        text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE)

        # Remove horizontal rule patterns (---, ___, ***)
        text = re.sub(r"^[ \t]*[-_*]{3,}[ \t]*$", "", text, flags=re.MULTILINE)

        # Remove lines that are purely dash/colon formatting (reasoning artifacts)
        # Match lines like "---", "::", "--- ---", "::: Reasoning :::", etc.
        text = re.sub(
            r"^[ \t]*[-:]{2,}.*$", "", text, flags=re.MULTILINE
        )

        # Clean up excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()

    def _build_prompt(self, user_message: str) -> str:
        """Build prompt string for hermes CLI."""
        parts = []
        if self._system:
            parts.append(f"System: {self._system}")

        # Last 10 messages for context
        recent = self._memory[-10:] if len(self._memory) > 10 else self._memory
        for msg in recent:
            role = msg["role"].capitalize()
            parts.append(f"{role}: {msg['content']}")

        parts.append(f"User: {user_message}")
        parts.append("Assistant:")
        return "\n".join(parts)

    @staticmethod
    def _clean_response(text: str) -> str:
        """
        Strip CLI metadata artifacts from hermes output.

        Removes:
        - ASCII art banner (╭─╮ box drawing)
        - Tool/skill listings
        - Session info, duration, "Resume with:" lines
        - Separator lines (───, ===)
        - "Initializing agent..." and status lines
        - "Query:" prompt echo
        """
        lines = text.split("\n")
        cleaned = []
        in_banner = False

        for line in lines:
            stripped = line.strip()

            # Box drawing banner boundaries
            if stripped.startswith("╭") or stripped.startswith("╰"):
                in_banner = not stripped.startswith("╰")
                continue
            if stripped.startswith("│"):
                continue

            # Separator lines
            if re.match(r"^[─═\-]{10,}$", stripped):
                continue

            # Status/metadata lines
            if any(stripped.startswith(p) for p in [
                "Initializing agent",
                "Query:",
                "Resume this session",
                "Session:",
                "Duration:",
                "Messages:",
                "Hermes Agent v",
                "Available Tools",
                "Available Skills",
            ]):
                continue

            # Hermes separator with label
            if "Hermes" in stripped and "─" in stripped:
                continue

            # Empty lines at boundaries
            if not stripped and not cleaned:
                continue

            cleaned.append(line)

        # Strip trailing empty lines
        while cleaned and not cleaned[-1].strip():
            cleaned.pop()

        return "\n".join(cleaned)

    async def _call_hermes(self, prompt: str) -> str:
        """Call hermes CLI and return response."""
        cmd = [self._hermes_path, "chat", "-q", prompt, "-Q"]
        if self._model:
            cmd.extend(["--model", self._model])

        logger.debug(f"Calling hermes: {self._hermes_path} chat -q '...'")

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

            response = stdout.decode("utf-8", errors="replace").strip()

            # Strip thinking/reasoning content
            response = self._strip_thinking(response)

            # Strip CLI banner, metadata, session info
            response = self._clean_response(response)

            if not response:
                logger.warning("Hermes returned empty response after stripping thinking")
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
            # Extract user text
            user_text = ""
            for text_data in input_data.texts:
                if text_data.source == TextSource.INPUT:
                    user_text = text_data.content
                    break

            if not user_text:
                logger.warning("No input text received")
                return

            logger.info(f"HermesAgent received: {user_text[:100]}...")

            # Add to memory and build prompt
            self._add_message("user", user_text)
            prompt = self._build_prompt(user_text)

            # Call hermes (thinking already stripped)
            full_response = await self._call_hermes(prompt)

            # Add response to memory
            self._add_message("assistant", full_response)

            # Yield as individual tokens so sentence_divider can process properly
            # Split by spaces but keep punctuation attached
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
        """Handle user interruption."""
        logger.info(f"Interrupted. Heard: {heard_response[:50]}...")
        if heard_response:
            self._add_message("assistant", heard_response + "...")
        self._add_message("user", "[Interrupted by user]")

    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None:
        """Load memory from chat history."""
        logger.info(f"Loading history: {conf_uid}/{history_uid}")
        self._memory = []
