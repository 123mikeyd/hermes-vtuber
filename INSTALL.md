# Installation Guide

## 1. Copy hermes_agent.py

```bash
cp hermes_agent.py /path/to/Open-LLM-VTuber/src/open_llm_vtuber/agent/agents/
```

## 2. Patch config_manager/agent.py

Add import at the top (after other agent imports):
```python
from .agents.hermes_agent import HermesAgent
```

Add HermesAgentConfig class (before AgentSettings class):
```python
class HermesAgentConfig(I18nMixin, BaseModel):
    hermes_path: str = Field("hermes", alias="hermes_path")
    faster_first_response: Optional[bool] = Field(True, alias="faster_first_response")
    segment_method: Literal["regex", "pysbd"] = Field("pysbd", alias="segment_method")
    model: str = Field("", alias="model")
    timeout: int = Field(120, alias="timeout")
```

Add to AgentSettings:
```python
hermes_agent: Optional[HermesAgentConfig] = Field(None, alias="hermes_agent")
```

Add to AgentConfig Literal:
```python
conversation_agent_choice: Literal[
    "basic_memory_agent", "mem0_agent", "hume_ai_agent", "letta_agent", "hermes_agent"
]
```

## 3. Patch agent_factory.py

Add import:
```python
from .agents.hermes_agent import HermesAgent
```

Add case in create_agent:
```python
elif conversation_agent_choice == "hermes_agent":
    settings = agent_settings.get("hermes_agent", {})
    return HermesAgent(
        hermes_path=settings.get("hermes_path", "hermes"),
        system=system_prompt,
        live2d_model=live2d_model,
        tts_preprocessor_config=tts_preprocessor_config,
        faster_first_response=settings.get("faster_first_response", True),
        segment_method=settings.get("segment_method", "pysbd"),
        model=settings.get("model", ""),
        timeout=settings.get("timeout", 120),
    )
```

## 4. Edit conf.yaml

```yaml
agent_config:
  conversation_agent_choice: 'hermes_agent'
  agent_settings:
    hermes_agent:
      hermes_path: '/home/mikeyd/.local/bin/hermes'
      faster_first_response: True
      segment_method: 'pysbd'
      model: ''
      timeout: 120
```

## 5. Run

```bash
cd Open-LLM-VTuber
python run_server.py
# Open http://localhost:12393
```
