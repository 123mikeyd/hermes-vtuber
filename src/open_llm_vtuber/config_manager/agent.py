"""
This module contains the pydantic model for the configurations of
different types of agents.
"""

from pydantic import BaseModel, Field
from typing import Dict, ClassVar, Optional, Literal, List, Any
from .i18n import I18nMixin, Description
from .stateless_llm import StatelessLLMConfigs

# ======== Configurations for different Agents ========


class BasicMemoryAgentConfig(I18nMixin, BaseModel):
    """Configuration for the basic memory agent."""

    llm_provider: Literal[
        "stateless_llm_with_template",
        "openai_compatible_llm",
        "claude_llm",
        "llama_cpp_llm",
        "ollama_llm",
        "lmstudio_llm",
        "openai_llm",
        "gemini_llm",
        "zhipu_llm",
        "deepseek_llm",
        "groq_llm",
        "mistral_llm",
    ] = Field(..., alias="llm_provider")

    faster_first_response: Optional[bool] = Field(True, alias="faster_first_response")
    segment_method: Literal["regex", "pysbd"] = Field("pysbd", alias="segment_method")
    use_mcpp: Optional[bool] = Field(False, alias="use_mcpp")
    mcp_enabled_servers: Optional[List[str]] = Field([], alias="mcp_enabled_servers")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "llm_provider": Description(
            en="LLM provider to use for this agent",
        ),
        "faster_first_response": Description(
            en="Whether to respond as soon as encountering a comma in the first sentence to reduce latency (default: True)",
        ),
        "segment_method": Description(
            en="Method for segmenting sentences: 'regex' or 'pysbd' (default: 'pysbd')",
        ),
        "use_mcpp": Description(
            en="Whether to use MCP (Model Context Protocol) for the agent (default: True)",
        ),
        "mcp_enabled_servers": Description(
            en="List of MCP servers to enable for the agent",
        ),
    }


class Mem0VectorStoreConfig(I18nMixin, BaseModel):
    """Configuration for Mem0 vector store."""

    provider: str = Field(..., alias="provider")
    config: Dict = Field(..., alias="config")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "provider": Description(
            en="Vector store provider (e.g., qdrant)"
        ),
        "config": Description(
            en="Provider-specific configuration"
        ),
    }


class Mem0LLMConfig(I18nMixin, BaseModel):
    """Configuration for Mem0 LLM."""

    provider: str = Field(..., alias="provider")
    config: Dict = Field(..., alias="config")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "provider": Description(en="LLM provider name"),
        "config": Description(
            en="Provider-specific configuration"
        ),
    }


class Mem0EmbedderConfig(I18nMixin, BaseModel):
    """Configuration for Mem0 embedder."""

    provider: str = Field(..., alias="provider")
    config: Dict = Field(..., alias="config")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "provider": Description(en="Embedder provider name"),
        "config": Description(
            en="Provider-specific configuration"
        ),
    }


class Mem0Config(I18nMixin, BaseModel):
    """Configuration for Mem0."""

    vector_store: Mem0VectorStoreConfig = Field(..., alias="vector_store")
    llm: Mem0LLMConfig = Field(..., alias="llm")
    embedder: Mem0EmbedderConfig = Field(..., alias="embedder")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "vector_store": Description(en="Vector store configuration"),
        "llm": Description(en="LLM configuration"),
        "embedder": Description(en="Embedder configuration"),
    }


# =================================


class HumeAIConfig(I18nMixin, BaseModel):
    """Configuration for the Hume AI agent."""

    api_key: str = Field(..., alias="api_key")
    host: str = Field("api.hume.ai", alias="host")
    config_id: Optional[str] = Field(None, alias="config_id")
    idle_timeout: int = Field(15, alias="idle_timeout")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "api_key": Description(
            en="API key for Hume AI service"
        ),
        "host": Description(
            en="Host URL for Hume AI service (default: api.hume.ai)"
        ),
        "config_id": Description(
            en="Configuration ID for EVI settings"
        ),
        "idle_timeout": Description(
            en="Idle timeout in seconds before disconnecting (default: 15)"
        ),
    }


# =================================


class LettaConfig(I18nMixin, BaseModel):
    """Configuration for the Letta agent."""

    host: str = Field("localhost", alias="host")
    port: int = Field(8283, alias="port")
    id: str = Field(..., alias="id")
    faster_first_response: Optional[bool] = Field(True, alias="faster_first_response")
    segment_method: Literal["regex", "pysbd"] = Field("pysbd", alias="segment_method")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "host": Description(
            en="Host address for the Letta server"
        ),
        "port": Description(
            en="Port number for the Letta server (default: 8283)"
        ),
        "id": Description(
            en="Agent instance ID running on the Letta server"
        ),
    }


class HermesAgentConfig(I18nMixin, BaseModel):
    """Configuration for the Hermes Agent."""

    hermes_path: str = Field("hermes", alias="hermes_path")
    faster_first_response: Optional[bool] = Field(True, alias="faster_first_response")
    segment_method: Literal["regex", "pysbd"] = Field("pysbd", alias="segment_method")
    model: str = Field("", alias="model")
    timeout: int = Field(120, alias="timeout")

    # Phase 2a — persona memory layer (all optional).
    # Two ways to supply an identity:
    #   1. persona_v2_identity_path: path to a YAML file (preferred)
    #   2. persona_v2_identity: inline dict with the same schema
    # Leave both unset to disable persona v2 and use the classic system
    # prompt path — full backward compatibility.
    persona_v2_identity_path: Optional[str] = Field(
        None, alias="persona_v2_identity_path"
    )
    persona_v2_identity: Optional[Dict[str, Any]] = Field(
        None, alias="persona_v2_identity"
    )
    # Where session memory (turns + rolling summary) persists between
    # server restarts. Relative paths resolve under chat_history/.
    # Default: chat_history/persona_sessions/<character>.json
    persona_v2_memory_path: Optional[str] = Field(
        None, alias="persona_v2_memory_path"
    )
    # Composer total budget in estimated tokens. Override for bigger
    # context models; default 2500 fits 8k-context comfortably.
    persona_v2_budget_tokens: int = Field(
        2500, alias="persona_v2_budget_tokens"
    )

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "hermes_path": Description(
            en="Path to hermes CLI binary"
        ),
        "model": Description(
            en="Model override for hermes (leave empty for default)"
        ),
        "timeout": Description(
            en="Timeout in seconds for hermes response (default: 120)"
        ),
        "persona_v2_identity_path": Description(
            en="Path to a Tier-1 persona YAML (characters/_persona_schema.yaml for reference). Enables persona v2 memory layer."
        ),
        "persona_v2_identity": Description(
            en="Inline persona identity dict. Alternative to persona_v2_identity_path."
        ),
        "persona_v2_memory_path": Description(
            en="Where session memory persists (default: chat_history/persona_sessions/<character>.json)"
        ),
        "persona_v2_budget_tokens": Description(
            en="Composer total token budget for the system prompt (default: 2500)"
        ),
    }


class AgentSettings(I18nMixin, BaseModel):
    """Settings for different types of agents."""

    basic_memory_agent: Optional[BasicMemoryAgentConfig] = Field(
        None, alias="basic_memory_agent"
    )
    mem0_agent: Optional[Mem0Config] = Field(None, alias="mem0_agent")
    hume_ai_agent: Optional[HumeAIConfig] = Field(None, alias="hume_ai_agent")
    letta_agent: Optional[LettaConfig] = Field(None, alias="letta_agent")
    hermes_agent: Optional[HermesAgentConfig] = Field(None, alias="hermes_agent")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "basic_memory_agent": Description(
            en="Configuration for basic memory agent"
        ),
        "mem0_agent": Description(en="Configuration for Mem0 agent"),
        "hume_ai_agent": Description(
            en="Configuration for Hume AI agent"
        ),
        "letta_agent": Description(
            en="Configuration for Letta agent"
        ),
        "hermes_agent": Description(
            en="Configuration for Hermes Agent integration"
        ),
    }


class AgentConfig(I18nMixin, BaseModel):
    """This class contains all of the configurations related to agent."""

    conversation_agent_choice: Literal[
        "basic_memory_agent", "mem0_agent", "hume_ai_agent", "letta_agent", "hermes_agent"
    ] = Field(..., alias="conversation_agent_choice")
    agent_settings: AgentSettings = Field(..., alias="agent_settings")
    llm_configs: StatelessLLMConfigs = Field(..., alias="llm_configs")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "conversation_agent_choice": Description(
            en="Type of conversation agent to use"
        ),
        "agent_settings": Description(
            en="Settings for different agent types"
        ),
        "llm_configs": Description(
            en="Pool of LLM provider configurations"
        ),
        "faster_first_response": Description(
            en="Whether to respond as soon as encountering a comma in the first sentence to reduce latency (default: True)"
        ),
        "segment_method": Description(
            en="Method for segmenting sentences: 'regex' or 'pysbd' (default: 'pysbd')"
        ),
    }
