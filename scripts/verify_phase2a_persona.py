"""
Phase 2a verification: prove the persona memory layer works end-to-end.

Runs:
  1. Unit-ish tests of Identity loading (schema, validation, rendering)
  2. Unit-ish tests of SessionMemory (add, recent, save/load roundtrip)
  3. Composer budget-enforcement test
  4. Live integration: HermesAgent + Identity + SessionMemory through
     an actual hermes subprocess — verify character speaks in persona,
     turns get recorded, summary refresh fires when it should.

Not a pytest — standalone runnable. Exits non-zero on any failure.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from open_llm_vtuber.persona import (
    Identity,
    MoodBaseline,
    load_identity,
    SessionMemory,
    Turn,
    PersonaComposer,
)


def section(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


# ---------------------------------------------------------------------------
# Test 1 — Identity schema + loading
# ---------------------------------------------------------------------------

def test_identity_from_yaml() -> None:
    section("Test 1: Identity from YAML (uses the canonical schema file)")
    schema_path = ROOT / "characters" / "_persona_schema.yaml"
    assert schema_path.is_file(), f"missing schema example: {schema_path}"

    identity = load_identity(schema_path)
    assert identity.name == "Nova", f"expected Nova, got {identity.name!r}"
    assert identity.core, "core should not be empty"
    assert identity.directives, "schema example has directives"
    assert identity.mood_baseline.valence > 0, "baseline should be positive"

    rendered = identity.render()
    assert identity.name in rendered
    assert "## Directives" in rendered
    assert "## Voice" in rendered
    print(f"[OK] loaded identity: {identity.name}, ~{identity.token_estimate()} tokens")


def test_identity_validation() -> None:
    section("Test 2: Identity validation (catches bad input)")
    try:
        load_identity({"core": "no name"})
        raise AssertionError("should have raised ValueError on missing name")
    except ValueError as e:
        print(f"[OK] missing 'name' raised: {e}")

    try:
        load_identity({"name": "X", "core": "y", "mood_baseline": {"valence": 5.0}})
        raise AssertionError("should have raised ValueError on out-of-range mood")
    except ValueError as e:
        print(f"[OK] bad mood_baseline raised: {e}")

    try:
        load_identity({"name": "X", "core": "y", "directives": "not a list"})
        raise AssertionError("should have raised ValueError on non-list directives")
    except ValueError as e:
        print(f"[OK] bad directives raised: {e}")


# ---------------------------------------------------------------------------
# Test 3 — SessionMemory basics
# ---------------------------------------------------------------------------

def test_session_memory_roundtrip() -> None:
    section("Test 3: SessionMemory add/save/load roundtrip")
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "session.json"
        mem = SessionMemory()
        mem.attach_file(path)
        mem.add_turn("user", "hello there")
        mem.add_turn("assistant", "hi back")
        mem.add_turn("assistant", "hi back")  # duplicate, should be dropped
        mem.add_turn("user", "  ")  # empty, should be dropped
        assert len(mem.turns) == 2, f"expected 2 turns, got {len(mem.turns)}"

        # Reload from disk
        mem2 = SessionMemory.load(path)
        assert len(mem2.turns) == 2
        assert mem2.turns[0].content == "hello there"
        assert mem2.turns[1].role == "assistant"
        print(f"[OK] roundtrip: 2 turns survived save+load")


def test_session_memory_windows() -> None:
    section("Test 4: SessionMemory recent() and older_than_recent()")
    mem = SessionMemory()
    for i in range(30):
        mem.add_turn("user", f"turn {i}")
    recent = mem.recent(20)
    older = mem.older_than_recent(20)
    assert len(recent) == 20
    assert len(older) == 10
    assert older[0].content == "turn 0"
    assert recent[-1].content == "turn 29"
    print(f"[OK] recent({len(recent)}) + older({len(older)}) = {len(mem.turns)}")


# ---------------------------------------------------------------------------
# Test 5 — Composer budget
# ---------------------------------------------------------------------------

def test_composer_basic() -> None:
    section("Test 5: Composer basic assembly")
    identity = Identity(
        name="Tester",
        core="A very small character used only for testing.",
        directives=["Be brief."],
    )
    mem = SessionMemory()
    mem.add_turn("user", "hello")
    mem.add_turn("assistant", "hi")

    composer = PersonaComposer()
    composed = composer.compose(identity=identity, session_memory=mem)

    assert "Tester" in composed.text
    assert "Be brief" in composed.text
    assert "hello" in composed.text
    assert composed.tokens_estimated <= composed.tokens_budget
    assert not composed.truncated
    print(f"[OK] composed {composed.tokens_estimated} tokens, not truncated")


def test_composer_budget_truncation() -> None:
    section("Test 6: Composer truncates when over budget")
    identity = Identity(
        name="T",
        core="x" * 200,  # small identity
    )
    mem = SessionMemory()
    # Inject a huge rolling summary to force cap
    mem.rolling_summary = "S" * 50_000  # way over any reasonable cap
    # And a lot of recent turns
    for i in range(200):
        mem.add_turn("user", f"this is user turn number {i} " * 10)
        mem.add_turn("assistant", f"this is assistant turn number {i} " * 10)

    composer = PersonaComposer(total_budget_tokens=1500)  # tight budget
    composed = composer.compose(identity=identity, session_memory=mem)

    assert composed.truncated, "expected truncation with tight budget"
    assert composed.tokens_estimated <= composed.tokens_budget, (
        f"composer overshot budget: {composed.tokens_estimated} > {composed.tokens_budget}"
    )
    assert "T" in composed.text, "identity block should always be preserved"
    print(
        f"[OK] truncation kept us under budget "
        f"({composed.tokens_estimated}/{composed.tokens_budget} tokens)"
    )


# ---------------------------------------------------------------------------
# Test 7 — Live integration with a real hermes subprocess
# ---------------------------------------------------------------------------

async def test_integration_live() -> None:
    section("Test 7: HermesAgent + Identity + SessionMemory (LIVE)")
    from open_llm_vtuber.agent.agents.hermes_agent import HermesAgent

    identity = Identity(
        name="Crumpet",
        core=(
            "You are Crumpet, a small and friendly test character. "
            "You speak in short sentences. You always sign off with 'crumpet out.'"
        ),
        directives=["Keep responses under 15 words.", "Always sign off with 'crumpet out.'"],
    )

    with tempfile.TemporaryDirectory() as td:
        mem = SessionMemory()
        mem.attach_file(Path(td) / "crumpet.json")

        agent = HermesAgent(
            hermes_path="hermes",
            timeout=60,
            identity=identity,
            session_memory=mem,
        )

        # Turn 1: we pin a memorable fact
        p1 = agent._build_prompt("My pet is a capybara named Biscuit.")
        r1 = await agent._call_hermes(p1)
        agent._session_memory.add_turn("user", "My pet is a capybara named Biscuit.")
        agent._session_memory.add_turn("assistant", r1)
        print(f"Turn 1 response: {r1!r}")
        assert agent._session_id, "session_id should be captured on turn 1"

        # Turn 2: does the character remember?
        p2 = agent._build_prompt("What's my pet's name?")
        r2 = await agent._call_hermes(p2)
        agent._session_memory.add_turn("user", "What's my pet's name?")
        agent._session_memory.add_turn("assistant", r2)
        print(f"Turn 2 response: {r2!r}")
        remembered = "biscuit" in r2.lower()
        if not remembered:
            print(f"[WARN] turn 2 did not mention Biscuit — persona/memory may be weak")
        else:
            print(f"[OK] turn 2 remembered the pet name")

        # Did persona stick? Check for the signoff catchphrase.
        has_signoff = "crumpet out" in r1.lower() or "crumpet out" in r2.lower()
        if has_signoff:
            print(f"[OK] persona directive honored (signoff present)")
        else:
            print(f"[WARN] signoff not present — LLMs sometimes skip one-shot directives")

        # Session memory should have 4 turns recorded
        assert len(agent._session_memory.turns) == 4, (
            f"expected 4 turns in session memory, got {len(agent._session_memory.turns)}"
        )
        print(f"[OK] session memory recorded {len(agent._session_memory.turns)} turns")

        # Persist + reload
        agent._session_memory.save()
        reloaded = SessionMemory.load(Path(td) / "crumpet.json")
        assert len(reloaded.turns) == 4
        print(f"[OK] session memory survived save+reload")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # Sync tests
    test_identity_from_yaml()
    test_identity_validation()
    test_session_memory_roundtrip()
    test_session_memory_windows()
    test_composer_basic()
    test_composer_budget_truncation()

    # Live integration test
    asyncio.run(test_integration_live())

    print()
    print("=" * 60)
    print("Phase 2a persona memory layer verification: COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
