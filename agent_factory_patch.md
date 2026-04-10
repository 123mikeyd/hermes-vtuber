# Patch for agent_factory.py

## Add import (after other imports):
```python
from .agents.hermes_agent import HermesAgent
```

## Add case (in create_agent method, before the else clause):
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
