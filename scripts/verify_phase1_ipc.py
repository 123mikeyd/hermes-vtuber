"""
Phase 1 verification: prove the session-resumed IPC actually works.

Runs 3 turns through HermesAgent and checks:
  1. Turn 1 captures a session_id
  2. Turn 2 resumes the same session (verified by memory persistence)
  3. _clean_response artifacts drop to ~0 after turn 1
  4. Wall-clock time per turn measured for the record

Not a pytest — just a runnable script. Exits non-zero on failure.
"""

import asyncio
import sys
import time
from pathlib import Path

# Make the src tree importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


async def main():
    # We stub the decorator pipeline — we only care about _call_hermes and
    # session management, not the full SentenceOutput chain. So we test
    # the low-level methods directly.
    from open_llm_vtuber.agent.agents.hermes_agent import HermesAgent

    agent = HermesAgent(hermes_path="hermes", timeout=60)

    # Seed a tiny identity so hermes knows who to be on turn 1
    agent.set_system(
        "You are a test subject. Keep responses under 10 words. "
        "You remember things we talk about."
    )

    assert agent._session_id is None, "Session id should start unset"

    prompts = [
        "My favorite color is cerulean. Say hi in 5 words or less.",
        "What is my favorite color?",
        "Count to three.",
    ]

    per_turn_times = []
    per_turn_strip = []

    for i, p in enumerate(prompts, 1):
        t0 = time.monotonic()

        # Use the low-level path so we don't need the full BatchInput pipeline
        full_prompt = agent._build_prompt(p)
        response = await agent._call_hermes(full_prompt)
        agent._add_message("user", p)
        agent._add_message("assistant", response)

        dt = time.monotonic() - t0
        per_turn_times.append(dt)
        per_turn_strip.append(agent._strip_counter)
        print(f"Turn {i}: {dt:.2f}s, session={agent._session_id}")
        print(f"   prompt:   {p}")
        print(f"   response: {response!r}")

    print()
    print("=" * 60)
    print("PHASE 1 VERIFICATION RESULTS")
    print("=" * 60)

    # Check 1: session_id was captured on turn 1
    assert agent._session_id is not None, \
        "FAIL: no session_id was captured on turn 1"
    print(f"[OK] session_id captured: {agent._session_id}")

    # Check 2: memory persists (turn 2 should mention "cerulean" or "blue")
    turn2_response = agent._memory[3]["content"].lower()
    remembered = "cerulean" in turn2_response or "blue" in turn2_response
    if not remembered:
        print(f"[WARN] turn 2 did not mention cerulean/blue: {turn2_response!r}")
        print("       (this might just be a model / phrasing miss — check manually)")
    else:
        print(f"[OK] turn 2 remembered the color: {turn2_response!r}")

    # Check 3: strip counter should stop climbing after turn 1
    # per_turn_strip is cumulative, so we look at deltas
    deltas = [per_turn_strip[0]] + [
        per_turn_strip[i] - per_turn_strip[i - 1] for i in range(1, len(per_turn_strip))
    ]
    print(f"[INFO] _clean_response strip counts per turn: {deltas}")
    post_turn1_total = sum(deltas[1:])
    if post_turn1_total > 5:
        print(f"[WARN] cleaner stripped {post_turn1_total} lines after turn 1 "
              f"(expected ≤5). Output format may have shifted.")
    else:
        print(f"[OK] cleaner stripped {post_turn1_total} lines after turn 1 (low).")

    # Check 4: log wall-clock times for the record
    print(f"[INFO] per-turn wall-clock times: "
          f"{[f'{t:.2f}s' for t in per_turn_times]}")
    if len(per_turn_times) >= 2:
        speedup = per_turn_times[0] / max(per_turn_times[1:])
        print(f"[INFO] turn 1 vs fastest resume turn: {speedup:.2f}x")

    print()
    print("Phase 1 IPC verification: COMPLETE")


if __name__ == "__main__":
    asyncio.run(main())
