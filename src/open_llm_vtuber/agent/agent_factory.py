from typing import Type, Literal
from pathlib import Path
from loguru import logger

from .agents.agent_interface import AgentInterface
from .agents.basic_memory_agent import BasicMemoryAgent
from .stateless_llm_factory import LLMFactory as StatelessLLMFactory
from .agents.hume_ai import HumeAIAgent
from .agents.letta_agent import LettaAgent
from .agents.hermes_agent import HermesAgent

# Phase 2a — persona memory layer. Imported lazily per-call so import
# failures don't kill the factory for other agent types.
from ..persona import Identity, SessionMemory, PersonaComposer, load_identity

from ..mcpp.tool_manager import ToolManager
from ..mcpp.tool_executor import ToolExecutor
from typing import Optional


class AgentFactory:
    @staticmethod
    def create_agent(
        conversation_agent_choice: str,
        agent_settings: dict,
        llm_configs: dict,
        system_prompt: str,
        live2d_model=None,
        tts_preprocessor_config=None,
        **kwargs,
    ) -> Type[AgentInterface]:
        """Create an agent based on the configuration.

        Args:
            conversation_agent_choice: The type of agent to create
            agent_settings: Settings for different types of agents
            llm_configs: Pool of LLM configurations
            system_prompt: The system prompt to use
            live2d_model: Live2D model instance for expression extraction
            tts_preprocessor_config: Configuration for TTS preprocessing
            **kwargs: Additional arguments
        """
        logger.info(f"Initializing agent: {conversation_agent_choice}")

        if conversation_agent_choice == "basic_memory_agent":
            # Get the LLM provider choice from agent settings
            basic_memory_settings: dict = agent_settings.get("basic_memory_agent", {})
            llm_provider: str = basic_memory_settings.get("llm_provider")

            if not llm_provider:
                raise ValueError("LLM provider not specified for basic memory agent")

            # Get the LLM config for this provider
            llm_config: dict = llm_configs.get(llm_provider)
            interrupt_method: Literal["system", "user"] = llm_config.pop(
                "interrupt_method", "user"
            )

            if not llm_config:
                raise ValueError(
                    f"Configuration not found for LLM provider: {llm_provider}"
                )

            # Create the stateless LLM
            llm = StatelessLLMFactory.create_llm(
                llm_provider=llm_provider, system_prompt=system_prompt, **llm_config
            )

            tool_prompts = kwargs.get("system_config", {}).get("tool_prompts", {})

            # Extract MCP components/data needed by BasicMemoryAgent from kwargs
            tool_manager: Optional[ToolManager] = kwargs.get("tool_manager")
            tool_executor: Optional[ToolExecutor] = kwargs.get("tool_executor")
            mcp_prompt_string: str = kwargs.get("mcp_prompt_string", "")

            # Create the agent with the LLM and live2d_model
            return BasicMemoryAgent(
                llm=llm,
                system=system_prompt,
                live2d_model=live2d_model,
                tts_preprocessor_config=tts_preprocessor_config,
                faster_first_response=basic_memory_settings.get(
                    "faster_first_response", True
                ),
                segment_method=basic_memory_settings.get("segment_method", "pysbd"),
                use_mcpp=basic_memory_settings.get("use_mcpp", False),
                interrupt_method=interrupt_method,
                tool_prompts=tool_prompts,
                tool_manager=tool_manager,
                tool_executor=tool_executor,
                mcp_prompt_string=mcp_prompt_string,
            )

        elif conversation_agent_choice == "mem0_agent":
            from .agents.mem0_llm import LLM as Mem0LLM

            mem0_settings = agent_settings.get("mem0_agent", {})
            if not mem0_settings:
                raise ValueError("Mem0 agent settings not found")

            # Validate required settings
            required_fields = ["base_url", "model", "mem0_config"]
            for field in required_fields:
                if field not in mem0_settings:
                    raise ValueError(
                        f"Missing required field '{field}' in mem0_agent settings"
                    )

            return Mem0LLM(
                user_id=kwargs.get("user_id", "default"),
                system=system_prompt,
                live2d_model=live2d_model,
                **mem0_settings,
            )

        elif conversation_agent_choice == "hume_ai_agent":
            settings = agent_settings.get("hume_ai_agent", {})
            return HumeAIAgent(
                api_key=settings.get("api_key"),
                host=settings.get("host", "api.hume.ai"),
                config_id=settings.get("config_id"),
                idle_timeout=settings.get("idle_timeout", 15),
            )

        elif conversation_agent_choice == "letta_agent":
            settings = agent_settings.get("letta_agent", {})
            return LettaAgent(
                live2d_model=live2d_model,
                id=settings.get("id"),
                tts_preprocessor_config=tts_preprocessor_config,
                faster_first_response=settings.get("faster_first_response"),
                segment_method=settings.get("segment_method"),
                host=settings.get("host"),
                port=settings.get("port"),
            )

        elif conversation_agent_choice == "hermes_agent":
            settings = agent_settings.get("hermes_agent", {})

            # Phase 2a — persona memory layer (optional).
            # Attempt to load an Identity from either a path or an inline
            # dict. If neither is configured, we pass None and HermesAgent
            # falls back to the classic `system` string path.
            identity: Optional[Identity] = None
            session_memory: Optional[SessionMemory] = None
            composer: Optional[PersonaComposer] = None

            identity_path = settings.get("persona_v2_identity_path")
            identity_inline = settings.get("persona_v2_identity")
            try:
                if identity_path:
                    identity = load_identity(identity_path)
                    logger.info(
                        f"Persona v2 enabled from path: {identity_path} "
                        f"({identity.name!r}, ~{identity.token_estimate()} est. tokens)"
                    )
                elif identity_inline:
                    identity = load_identity(identity_inline)
                    logger.info(
                        f"Persona v2 enabled from inline dict: "
                        f"{identity.name!r} (~{identity.token_estimate()} est. tokens)"
                    )
            except Exception as e:
                # Don't fail the whole factory if persona config is bad —
                # log loudly, keep going with the classic system path.
                logger.error(
                    f"Persona v2 identity failed to load ({e}). "
                    f"Falling back to classic system prompt path."
                )
                identity = None

            if identity is not None:
                # Resolve persistence path for session memory. Relative
                # paths land under chat_history/ (OLLV's convention).
                mem_path_raw = settings.get("persona_v2_memory_path")
                if mem_path_raw:
                    mem_path = Path(mem_path_raw).expanduser()
                    if not mem_path.is_absolute():
                        mem_path = Path("chat_history") / mem_path
                else:
                    safe_name = "".join(
                        c if c.isalnum() or c in "-_" else "_"
                        for c in identity.name.lower()
                    )
                    mem_path = Path("chat_history") / "persona_sessions" / f"{safe_name}.json"

                session_memory = SessionMemory.load(mem_path)
                composer = PersonaComposer(
                    total_budget_tokens=settings.get("persona_v2_budget_tokens", 2500),
                )

            return HermesAgent(
                hermes_path=settings.get("hermes_path", "hermes"),
                system=system_prompt,
                live2d_model=live2d_model,
                tts_preprocessor_config=tts_preprocessor_config,
                faster_first_response=settings.get("faster_first_response", True),
                segment_method=settings.get("segment_method", "pysbd"),
                model=settings.get("model", ""),
                timeout=settings.get("timeout", 120),
                # Phase 2a — these are all None if persona v2 is not configured
                identity=identity,
                session_memory=session_memory,
                composer=composer,
            )

        else:
            raise ValueError(f"Unsupported agent type: {conversation_agent_choice}")
