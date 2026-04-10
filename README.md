# hermes-vtuber

Hermes Agent integration for Open-LLM-VTuber. Voice-interactive AI avatar that speaks Hermes responses.

## Quick Start

```bash
# 1. Clone Open-LLM-VTuber
git clone https://github.com/Open-LLM-VTuber/Open-LLM-VTuber.git
cd Open-LLM-VTuber

# 2. Copy hermes agent
cp ../hermes-vtuber/hermes_agent.py src/open_llm_vtuber/agent/agents/

# 3. Edit agent_factory.py - add import and case
# 4. Edit conf.yaml - set conversation_agent_choice: 'hermes_agent'
# 5. Run
python run_server.py
```

## Configuration

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

## How It Works

```
You speak → STT → hermes chat -q "..." → Edge-TTS → Live2D avatar talks
```
