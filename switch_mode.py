#!/usr/bin/env python3
"""
Switch Nova VTuber between Hermes Agent (remote) and Local LLM (Ollama).

Usage:
  python3 switch_mode.py hermes    # Use Hermes Agent (remote API)
  python3 switch_mode.py local     # Use local Ollama (qwen2.5:7b)
  python3 switch_mode.py           # Show current mode
"""

import yaml
import sys
from pathlib import Path

CONF = Path(__file__).parent / "conf.yaml"

def get_mode(conf):
    return conf['character_config']['agent_config']['conversation_agent_choice']

def main():
    if not CONF.exists():
        print(f"Config not found: {CONF}")
        sys.exit(1)

    with open(CONF) as f:
        conf = yaml.safe_load(f)

    current = get_mode(conf)

    if len(sys.argv) < 2:
        print(f"Current mode: {current}")
        print(f"  hermes → Hermes Agent (remote API, costs money)")
        print(f"  local  → Ollama qwen2.5:7b (runs on your GPU, free)")
        print(f"\nUsage: python3 {sys.argv[0]} [hermes|local]")
        return

    target = sys.argv[1].lower()
    if target not in ('hermes', 'local'):
        print(f"Unknown mode: {target}. Use 'hermes' or 'local'.")
        sys.exit(1)

    if target == current:
        print(f"Already in {target} mode.")
        return

    if target == 'local':
        conf['character_config']['agent_config']['conversation_agent_choice'] = 'basic_memory_agent'
        print("Switched to LOCAL mode (Ollama qwen2.5:7b)")
    else:
        conf['character_config']['agent_config']['conversation_agent_choice'] = 'hermes_agent'
        print("Switched to HERMES mode (remote API)")

    with open(CONF, 'w') as f:
        yaml.dump(conf, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print("  Restart the VTuber server for changes to take effect:")
    print("  python3 run_server.py")

if __name__ == '__main__':
    main()
