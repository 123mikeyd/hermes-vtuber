"""
Hermes Agent for Open-LLM-VTuber

Calls Hermes Agent CLI directly to get responses.
Hermes is a CLI tool, so we use subprocess to communicate with it.
"""

import asyncio
import subprocess
import json
import shlex
from typing import AsyncIterator, List, Dict, Any, Optional, Literal
from loguru import logger

from .agent_interface import AgentInterface
from ..output_types import SentenceOutput, DisplayText, Actions
from ..input_types import BatchInput, TextSource
from ..transformers import sentence_divider


class HermesAgent(AgentInterface):
    """Agent that calls Hermes Agent CLI for responses."""

    def __init__(
        self,
        hermes_path: str = "hermes",
        system: str = "",
        live2d_model=None,
        tts_preprocessor_config=None,
        faster_first_response: bool = True,
        segment_method: str = "pysbd",
        model: str = "",
        timeout: int = 120,
    ):
        """
        Initialize Hermes Agent.
        
        Args:
            hermes_path: Path to hermes CLI command
            system: System prompt for the character
            live2d_model: Live2D model for expression extraction
            tts_preprocessor_config: TTS preprocessing config
            faster_first_response: Start TTS as soon as first sentence arrives
            segment_method: Sentence segmentation method
            model: Model to use with hermes (optional)
            timeout: Timeout for hermes commands in seconds
        """
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
        logger.debug(f"HermesAgent system prompt set: {system[:100]}...")

    def _add_message(self, role: str, content: str):
        """Add message to conversation memory."""
        if not content:
            return
        # Don't add duplicate consecutive messages
        if self._memory and self._memory[-1]["role"] == role and self._memory[-1]["content"] == content:
            return
        self._memory.append({"role": role, "content": content})

    def _build_prompt(self, user_message: str) -> str:
        """
        Build a prompt string for hermes CLI.
        
        We format the conversation history + new message into a prompt.
        Hermes CLI typically takes a single prompt string.
        """
        parts = []
        
        # Add system prompt
        if self._system:
            parts.append(f"System: {self._system}")
        
        # Add conversation history (last 10 messages to keep it manageable)
        recent_history = self._memory[-10:] if len(self._memory) > 10 else self._memory
        for msg in recent_history:
            role = msg["role"].capitalize()
            parts.append(f"{role}: {msg['content']}")
        
        # Add current user message
        parts.append(f"User: {user_message}")
        parts.append("Assistant:")
        
        return "\n".join(parts)

    async def _call_hermes(self, prompt: str) -> str:
        """
        Call hermes CLI and return the response.
        
        Args:
            prompt: The formatted prompt string
            
        Returns:
            The response text from hermes
        """
        # Build the hermes command: hermes chat -q "message"
        cmd = [self._hermes_path, "chat", "-q", prompt]
        
        if self._model:
            cmd.extend(["--model", self._model])
        
        logger.debug(f"Calling hermes: {' '.join(cmd[:3])}...")
        
        try:
            # Run hermes as subprocess
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), 
                timeout=self._timeout
            )
            
            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="replace").strip()
                logger.error(f"Hermes CLI error (exit {process.returncode}): {error_msg}")
                return f"[Hermes error: {error_msg[:200]}]"
            
            response = stdout.decode("utf-8", errors="replace").strip()
            logger.debug(f"Hermes response length: {len(response)} chars")
            return response
            
        except asyncio.TimeoutError:
            logger.error(f"Hermes CLI timed out after {self._timeout}s")
            return "[Hermes timed out]"
        except FileNotFoundError:
            logger.error(f"Hermes CLI not found at: {self._hermes_path}")
            return "[Hermes not found - check hermes_path config]"
        except Exception as e:
            logger.error(f"Error calling hermes: {e}")
            return f"[Error: {str(e)[:200]}]"

    async def chat(self, input_data: BatchInput) -> AsyncIterator[SentenceOutput]:
        """
        Chat with Hermes Agent.
        
        Takes user input, sends to hermes CLI, yields sentences for TTS.
        """
        # Extract text from input
        user_text = ""
        for text_data in input_data.texts:
            if text_data.source == TextSource.INPUT:
                user_text = text_data.content
                break
        
        if not user_text:
            logger.warning("No input text received")
            return
        
        logger.info(f"HermesAgent received: {user_text[:100]}...")
        
        # Add user message to memory
        self._add_message("user", user_text)
        
        # Build prompt and call hermes
        prompt = self._build_prompt(user_text)
        full_response = await self._call_hermes(prompt)
        
        # Add response to memory
        self._add_message("assistant", full_response)
        
        # Split response into sentences for streaming TTS
        sentences = sentence_divider(full_response, method=self._segment_method)
        
        logger.info(f"Hermes response: {len(sentences)} sentences")
        
        # Yield each sentence as SentenceOutput
        for sentence in sentences:
            if not sentence.strip():
                continue
            
            # Extract Live2D expressions if model available
            actions = Actions()
            if self._live2d_model:
                try:
                    expressions = self._live2d_model.get_expression_keys_from_text(sentence)
                    if expressions:
                        actions = Actions(expressions=expressions)
                except Exception:
                    pass
            
            yield SentenceOutput(
                display_text=DisplayText(text=sentence, name="Hermes"),
                tts_text=sentence,
                actions=actions,
            )

    def handle_interrupt(self, heard_response: str) -> None:
        """Handle user interruption."""
        logger.info(f"User interrupted. Heard: {heard_response[:50]}...")
        # Add the partial response to memory
        if heard_response:
            self._add_message("assistant", heard_response + "...")
        self._add_message("user", "[Interrupted by user]")

    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None:
        """Load memory from chat history."""
        logger.info(f"Loading history for conf_uid={conf_uid}, history_uid={history_uid}")
        # For now, start fresh. Could integrate with hermes memory later.
        self._memory = []
