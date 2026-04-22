from typing import Union, List, Dict, Any, Optional
import asyncio
import json
from loguru import logger
import numpy as np

from .conversation_utils import (
    create_batch_input,
    process_agent_output,
    send_conversation_start_signals,
    process_user_input,
    finalize_conversation_turn,
    cleanup_conversation,
    EMOJI_LIST,
)
from .types import WebSocketSend
from .tts_manager import TTSTaskManager
from ..chat_history_manager import store_message
from ..service_context import ServiceContext

# Import necessary types from agent outputs
from ..agent.output_types import SentenceOutput, AudioOutput


async def process_single_conversation(
    context: ServiceContext,
    websocket_send: WebSocketSend,
    client_uid: str,
    user_input: Union[str, np.ndarray],
    images: Optional[List[Dict[str, Any]]] = None,
    session_emoji: str = np.random.choice(EMOJI_LIST),
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Process a single-user conversation turn

    Args:
        context: Service context containing all configurations and engines
        websocket_send: WebSocket send function
        client_uid: Client unique identifier
        user_input: Text or audio input from user
        images: Optional list of image data
        session_emoji: Emoji identifier for the conversation
        metadata: Optional metadata for special processing flags

    Returns:
        str: Complete response text
    """
    # Create TTSTaskManager for this conversation
    tts_manager = TTSTaskManager()
    full_response = ""  # Initialize full_response here

    try:
        # Send initial signals
        await send_conversation_start_signals(websocket_send)
        logger.info(f"New Conversation Chain {session_emoji} started!")

        # Process user input
        input_text = await process_user_input(
            user_input, context.asr_engine, websocket_send
        )

        # Create batch input
        batch_input = create_batch_input(
            input_text=input_text,
            images=images,
            from_name=context.character_config.human_name,
            metadata=metadata,
        )

        # Store user message (check if we should skip storing to history)
        skip_history = metadata and metadata.get("skip_history", False)
        if context.history_uid and not skip_history:
            store_message(
                conf_uid=context.character_config.conf_uid,
                history_uid=context.history_uid,
                role="human",
                content=input_text,
                name=context.character_config.human_name,
            )

        if skip_history:
            logger.debug("Skipping storing user input to history (proactive speak)")

        logger.info(f"User input: {input_text}")
        if images:
            logger.info(f"With {len(images)} images")

        # Phase 6 — sleep-command detection. If the user's input is a
        # standalone sleep instruction (not quoted, not buried in other
        # text), fire a `sleep_command` WebSocket message so the sidecar
        # puts Nova into the sleep state. The conversation still proceeds
        # normally — Nova gets to acknowledge the instruction before
        # falling asleep.
        try:
            from ..persona.sleep_detector import is_sleep_command
            if is_sleep_command(input_text):
                logger.info(
                    f"Phase 6: sleep command detected in user input — "
                    f"telling sidecar to start sleep cycle"
                )
                await websocket_send(
                    json.dumps({
                        "type": "sleep_command",
                        "active": True,
                        "reason": "user command",
                    })
                )
        except Exception as _sleep_err:
            # Best-effort — a detector bug must never break the turn
            logger.warning(f"sleep_command detect failed (non-fatal): {_sleep_err}")

        try:
            # agent.chat yields Union[SentenceOutput, Dict[str, Any]]
            agent_output_stream = context.agent_engine.chat(batch_input)

            async for output_item in agent_output_stream:
                if (
                    isinstance(output_item, dict)
                    and output_item.get("type") == "tool_call_status"
                ):
                    # Handle tool status event: send WebSocket message
                    output_item["name"] = context.character_config.character_name
                    logger.debug(f"Sending tool status update: {output_item}")

                    await websocket_send(json.dumps(output_item))

                elif isinstance(output_item, (SentenceOutput, AudioOutput)):
                    # Handle SentenceOutput or AudioOutput
                    response_part = await process_agent_output(
                        output=output_item,
                        character_config=context.character_config,
                        live2d_model=context.live2d_model,
                        tts_engine=context.tts_engine,
                        websocket_send=websocket_send,  # Pass websocket_send for audio/tts messages
                        tts_manager=tts_manager,
                        translate_engine=context.translate_engine,
                    )
                    # Ensure response_part is treated as a string before concatenation
                    response_part_str = (
                        str(response_part) if response_part is not None else ""
                    )
                    full_response += response_part_str  # Accumulate text response
                else:
                    logger.warning(
                        f"Received unexpected item type from agent chat stream: {type(output_item)}"
                    )
                    logger.debug(f"Unexpected item content: {output_item}")

        except Exception as e:
            logger.exception(
                f"Error processing agent response stream: {e}"
            )  # Log with stack trace
            await websocket_send(
                json.dumps(
                    {
                        "type": "error",
                        "message": f"Error processing agent response: {str(e)}",
                    }
                )
            )
            # full_response will contain partial response before error
        # --- End processing agent response ---

        # Wait for any pending TTS tasks
        if tts_manager.task_list:
            await asyncio.gather(*tts_manager.task_list)
            await websocket_send(json.dumps({"type": "backend-synth-complete"}))

        await finalize_conversation_turn(
            tts_manager=tts_manager,
            websocket_send=websocket_send,
            client_uid=client_uid,
        )

        if context.history_uid and full_response:  # Check full_response before storing
            store_message(
                conf_uid=context.character_config.conf_uid,
                history_uid=context.history_uid,
                role="ai",
                content=full_response,
                name=context.character_config.character_name,
                avatar=context.character_config.avatar,
            )
            logger.info(f"AI response: {full_response}")

        # Phase 4 — emit a mood_update WebSocket message so the frontend
        # can switch its idle motion pool to match the character's
        # current quadrant. Only fires when the agent is a HermesAgent
        # with persona v2 active (i.e., has a SessionMemory carrying a
        # MoodState). Silently no-ops for other agents.
        try:
            await _maybe_emit_mood_update(context, websocket_send)
        except Exception as _mood_err:
            # Best-effort; never break a turn over a cosmetic signal.
            logger.warning(f"mood_update emit failed (non-fatal): {_mood_err}")

        return full_response  # Return accumulated full_response

    except asyncio.CancelledError:
        logger.info(f"🤡👍 Conversation {session_emoji} cancelled because interrupted.")
        raise
    except Exception as e:
        logger.error(f"Error in conversation chain: {e}")
        await websocket_send(
            json.dumps({"type": "error", "message": f"Conversation error: {str(e)}"})
        )
        raise
    finally:
        cleanup_conversation(tts_manager, session_emoji)


# ---------------------------------------------------------------------------
# Phase 4 — mood_update emission
# ---------------------------------------------------------------------------

async def _maybe_emit_mood_update(
    context: ServiceContext,
    websocket_send: WebSocketSend,
) -> None:
    """If the agent carries a persona v2 mood vector, push a mood_update
    message to the frontend with the current quadrant, vector snapshot,
    and the pool of motion filenames the frontend should pick idles from.

    Silently no-ops when the agent lacks persona v2 (e.g., basic_memory
    or any non-hermes agent) or when mood hasn't been initialized yet.
    """
    agent = getattr(context, "agent_engine", None)
    if agent is None:
        return

    # SessionMemory is private on the agent, but we check with getattr
    # so we don't fail if the agent class doesn't have one.
    session_memory = getattr(agent, "_session_memory", None)
    if session_memory is None:
        return
    mood = getattr(session_memory, "mood", None)
    if mood is None:
        return

    # Snapshot the mood after any pending decay
    mood.decay_to_now()
    snapshot = mood.snapshot()
    quadrant = snapshot["quadrant"]

    # Resolve the motion pool for this character's loaded Live2D model
    from ..persona.pool_map import resolve_pool
    from pathlib import Path as _Path
    model_name = getattr(context.character_config, "live2d_model_name", None)
    if not model_name:
        return
    # Build a candidate model_dir so resolve_pool can auto-build if
    # no PoolMap is registered for this model
    model_dir = (
        _Path("live2d-models") / model_name / "runtime"
    )
    pool_map = resolve_pool(model_name, model_dir=model_dir)
    pool = pool_map.get(quadrant)

    message = {
        "type": "mood_update",
        "quadrant": quadrant,
        "pool": pool,                      # list of motion filenames
        "pools": pool_map.as_dict(),       # full mapping (frontend may cache)
        "snapshot": snapshot,              # v / e / s / f / description
        "model_name": model_name,
    }

    try:
        await websocket_send(json.dumps(message))
        logger.debug(
            f"mood_update sent: quadrant={quadrant}, "
            f"pool={len(pool)} motions, model={model_name}"
        )
    except Exception as e:
        logger.warning(f"mood_update websocket send failed: {e}")
