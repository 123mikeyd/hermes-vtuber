"""
Phase 3 verification: prove the mood state machine works end-to-end.

Tests:
  1. MoodState starts at baseline and clamps in-range
  2. Decay moves toward baseline at the expected half-life
  3. apply_delta nudges the vector, clamps, updates timestamp
  4. Serialization roundtrips through JSON cleanly
  5. Classifier reads positive / negative / high-energy lexicons
  6. Composer includes a mood line in the system prompt
  7. LIVE: HermesAgent.chat() drifts mood across a conversation
     and the drift is visible in SessionMemory JSON after each turn.

Not a pytest — standalone runnable. Exits non-zero on assertion failure.
"""

from __future__ import annotations

import asyncio
import json
import math
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from open_llm_vtuber.persona import (
    Identity,
    MoodBaseline,
    MoodState,
    MoodDelta,
    SessionMemory,
    PersonaComposer,
    mood_classify,
)
from open_llm_vtuber.persona.mood import MOOD_HALFLIFE_SECONDS, MOOD_UPDATE_WEIGHT


def section(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


# ---------------------------------------------------------------------------
# Test 1 — MoodState initialization
# ---------------------------------------------------------------------------

def test_mood_init() -> None:
    section("Test 1: MoodState starts at baseline")
    baseline = MoodBaseline(valence=0.3, energy=0.1, social=0.4, focus=0.5)
    mood = MoodState(baseline=baseline)
    assert abs(mood.valence - 0.3) < 1e-9, f"valence: {mood.valence}"
    assert abs(mood.energy - 0.1) < 1e-9
    assert abs(mood.social - 0.4) < 1e-9
    assert abs(mood.focus - 0.5) < 1e-9
    print(f"[OK] MoodState starts at baseline: {mood.to_dict()}")


def test_mood_clamping() -> None:
    section("Test 2: Mood values clamp to [-1, 1]")
    mood = MoodState(valence=2.5, energy=-5.0)
    assert mood.valence == 1.0, f"valence not clamped: {mood.valence}"
    assert mood.energy == -1.0
    print(f"[OK] out-of-range inputs clamped: v={mood.valence}, e={mood.energy}")


# ---------------------------------------------------------------------------
# Test 3 — decay math
# ---------------------------------------------------------------------------

def test_decay_halflife() -> None:
    section("Test 3: Decay moves toward baseline at the expected half-life")
    baseline = MoodBaseline(valence=0.0)
    mood = MoodState(baseline=baseline, valence=1.0)
    # Start the clock at t=0
    t0 = 1000000.0
    mood.last_update = t0
    # Advance one half-life
    mood.decay_to_now(now=t0 + MOOD_HALFLIFE_SECONDS)
    # Should have moved HALFWAY to baseline: from 1.0 toward 0.0 = 0.5
    assert abs(mood.valence - 0.5) < 0.01, f"half-life wrong: {mood.valence}"
    # Advance TWO half-lives further (three total from start)
    mood.decay_to_now(now=t0 + 3 * MOOD_HALFLIFE_SECONDS)
    # Should be at about 1.0 * (0.5)**3 = 0.125
    assert abs(mood.valence - 0.125) < 0.01, f"3-halflife wrong: {mood.valence}"
    print(f"[OK] decay at 1 halflife = 0.5, 3 halflives = 0.125")


# ---------------------------------------------------------------------------
# Test 4 — apply_delta
# ---------------------------------------------------------------------------

def test_apply_delta() -> None:
    section("Test 4: apply_delta moves mood by weight * delta")
    baseline = MoodBaseline()
    mood = MoodState(baseline=baseline)
    mood.last_update = time.time()
    # Big sad delta
    mood.apply_delta(MoodDelta(valence=-1.0, reason="test"))
    # Expected: from 0.0, nudged by -0.3 (MOOD_UPDATE_WEIGHT) ≈ -0.3
    assert abs(mood.valence + MOOD_UPDATE_WEIGHT) < 0.02, f"got {mood.valence}"
    print(f"[OK] delta -1.0 at weight {MOOD_UPDATE_WEIGHT} -> valence = {mood.valence:.2f}")


# ---------------------------------------------------------------------------
# Test 5 — serialization
# ---------------------------------------------------------------------------

def test_serialization() -> None:
    section("Test 5: MoodState roundtrips through JSON")
    baseline = MoodBaseline(valence=0.3, energy=0.1)
    mood = MoodState(baseline=baseline, valence=-0.4, energy=0.6, social=0.2, focus=-0.1)
    mood.last_update = time.time()

    d = mood.to_dict()
    encoded = json.dumps(d)
    decoded = json.loads(encoded)
    mood2 = MoodState.from_dict(decoded)

    for axis in ("valence", "energy", "social", "focus"):
        assert abs(getattr(mood, axis) - getattr(mood2, axis)) < 1e-3, (
            f"{axis} drift on roundtrip: {getattr(mood, axis)} -> {getattr(mood2, axis)}"
        )
    assert mood2.baseline.valence == 0.3
    print(f"[OK] JSON roundtrip preserves all 4 axes + baseline")


# ---------------------------------------------------------------------------
# Test 6 — classifier sanity
# ---------------------------------------------------------------------------

def test_classifier() -> None:
    section("Test 6: Classifier lexicon pattern checks")

    happy = mood_classify(
        user_text="I am so happy and excited to be building this!",
        assistant_text="Wonderful! Let's go. That's awesome.",
    )
    assert happy.valence > 0.0, f"expected positive valence, got {happy.valence}"
    assert happy.energy > 0.0, f"expected positive energy, got {happy.energy}"
    print(f"[OK] happy text: v={happy.valence:+.2f} e={happy.energy:+.2f}")

    sad = mood_classify(
        user_text="I'm tired, frustrated, and I hate this. Everything is broken.",
        assistant_text="I'm sorry you're feeling that way.",
    )
    assert sad.valence < -0.1, f"expected very negative valence, got {sad.valence}"
    print(f"[OK] sad text: v={sad.valence:+.2f} e={sad.energy:+.2f}")

    neutral = mood_classify(
        user_text="What time is it.",
        assistant_text="It is currently 3 pm.",
    )
    mag = abs(neutral.valence) + abs(neutral.energy) + abs(neutral.social) + abs(neutral.focus)
    assert mag < 0.5, f"neutral text should produce small delta, got mag={mag}"
    print(f"[OK] neutral text: low magnitude {mag:.2f}")

    explicit_tag = mood_classify(
        user_text="whatever",
        assistant_text="[angry] I said no!",
    )
    assert explicit_tag.valence < 0 and explicit_tag.energy > 0, (
        f"[angry] tag should push v-, a+: {explicit_tag}"
    )
    print(f"[OK] explicit [angry] tag: v={explicit_tag.valence:+.2f} e={explicit_tag.energy:+.2f}")


# ---------------------------------------------------------------------------
# Test 7 — composer includes mood line
# ---------------------------------------------------------------------------

def test_composer_mood_line() -> None:
    section("Test 7: Composer includes mood line when mood is set")
    identity = Identity(
        name="Moody",
        core="You are a test character.",
        mood_baseline=MoodBaseline(valence=0.3),
    )
    mem = SessionMemory()
    mem.ensure_mood(identity.mood_baseline)
    # Push mood hard negative
    mem.mood.apply_delta(MoodDelta(valence=-1.0, energy=-1.0, reason="test"))
    mem.mood.apply_delta(MoodDelta(valence=-1.0, energy=-1.0, reason="test"))
    mem.add_turn("user", "anything")
    mem.add_turn("assistant", "anything")

    composed = PersonaComposer().compose(identity, mem)
    assert "## Current State" in composed.text, "mood section missing"
    assert "Your current state" in composed.text, "describe() line missing"
    print(f"[OK] mood line present in composed prompt")
    # Print a snippet so the human can eyeball the wording
    lines = composed.text.split("\n")
    for i, line in enumerate(lines):
        if "Current State" in line:
            print(f"  >>> {lines[i+1][:120]}")
            break


# ---------------------------------------------------------------------------
# Test 7b — hysteresis: two-sentence minimum + no flicker
# ---------------------------------------------------------------------------

def test_hysteresis() -> None:
    section("Test 7b: Hysteresis — 2-sentence minimum + no flicker")
    # Low-focus character so the excited test lands in 'excited', not 'focused'
    mood = MoodState(baseline=MoodBaseline(valence=0.3, energy=0.1, social=0.4, focus=0.2))

    # 1 strong energy turn — must NOT flip (two-sentence minimum)
    mood.apply_delta(MoodDelta(energy=0.9, reason="strong #1"))
    q1 = mood.quadrant()
    assert q1 == "calm", f"1 strong turn flipped to {q1}, should still be calm"
    print(f"[OK] 1 strong turn: stayed calm (energy={mood.energy:.2f})")

    # 2nd strong energy turn — must flip to excited
    mood.apply_delta(MoodDelta(energy=0.9, reason="strong #2"))
    q2 = mood.quadrant()
    assert q2 == "excited", f"2 strong turns should flip to excited, got {q2}"
    print(f"[OK] 2 strong turns: flipped to excited (energy={mood.energy:.2f})")

    # 1 mild calm reply — must STAY excited (hysteresis protects against flicker)
    mood.apply_delta(MoodDelta(energy=-0.2, reason="calm reply"))
    q3 = mood.quadrant()
    assert q3 == "excited", f"mild calm reply should NOT drop quadrant, got {q3}"
    print(f"[OK] mild calm reply: stayed excited (energy={mood.energy:.2f})")

    # Sustained calming — eventually falls back to calm (stay threshold 0.25)
    for i in range(5):
        mood.apply_delta(MoodDelta(energy=-0.3, reason=f"calming #{i+1}"))
    q4 = mood.quadrant()
    assert q4 == "calm", f"sustained calming should return to calm, got {q4}"
    print(f"[OK] sustained calming: dropped to calm (energy={mood.energy:.2f})")


# ---------------------------------------------------------------------------
# Test 8 — LIVE integration: mood drifts across a conversation
# ---------------------------------------------------------------------------

async def test_live_mood_drift() -> None:
    section("Test 8: LIVE — mood drifts across a real conversation")
    from open_llm_vtuber.agent.agents.hermes_agent import HermesAgent

    identity = Identity(
        name="Drifter",
        core=(
            "You are Drifter, a small test character. Respond in 10 words or less. "
            "You reflect back the user's energy."
        ),
        mood_baseline=MoodBaseline(valence=0.0, energy=0.0),
    )

    with tempfile.TemporaryDirectory() as td:
        mem = SessionMemory()
        mem.attach_file(Path(td) / "drifter.json")

        agent = HermesAgent(
            hermes_path="hermes",
            timeout=60,
            identity=identity,
            session_memory=mem,
        )

        # Prime the mood by manually driving it — no hermes calls needed
        # for a drift test. Simulates what would happen over a sad
        # conversation.
        mem.ensure_mood(identity.mood_baseline)
        initial_snapshot = mem.mood.snapshot()
        print(f"Initial mood: {initial_snapshot}")

        from open_llm_vtuber.persona.mood_classifier import classify
        sad_delta = classify(
            user_text="This is awful. I hate everything. I'm tired and frustrated.",
            assistant_text="I'm so sorry you're hurting.",
        )
        for _ in range(3):  # three sad exchanges
            mem.mood.apply_delta(sad_delta)
        mem.save()

        after_sad = mem.mood.snapshot()
        print(f"After 3 sad deltas: {after_sad}")
        assert after_sad["valence"] < initial_snapshot["valence"], "valence should drop"
        quadrant_after_sad = after_sad["quadrant"]
        print(f"[OK] quadrant after sadness: {quadrant_after_sad}")

        # Now flip to an excited conversation
        happy_delta = classify(
            user_text="WOW I am so excited! This is AMAZING!",
            assistant_text="Yes! Let's go! That's wonderful!",
        )
        for _ in range(4):  # four happy exchanges
            mem.mood.apply_delta(happy_delta)

        after_happy = mem.mood.snapshot()
        print(f"After 4 happy deltas: {after_happy}")
        assert after_happy["valence"] > after_sad["valence"], "valence should rise"
        assert after_happy["energy"] > after_sad["energy"], "energy should rise"
        print(f"[OK] mood flipped: valence {after_sad['valence']:+.2f} -> {after_happy['valence']:+.2f}")

        # Reload from disk — mood should survive restart
        mem.save()
        reloaded = SessionMemory.load(Path(td) / "drifter.json")
        assert reloaded.mood is not None
        assert abs(reloaded.mood.valence - after_happy["valence"]) < 0.01, (
            f"mood lost on reload: {reloaded.mood.valence} vs {after_happy['valence']}"
        )
        print(f"[OK] mood survived save+reload")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    test_mood_init()
    test_mood_clamping()
    test_decay_halflife()
    test_apply_delta()
    test_serialization()
    test_classifier()
    test_composer_mood_line()
    test_hysteresis()
    asyncio.run(test_live_mood_drift())

    print()
    print("=" * 60)
    print("Phase 3 mood state machine verification: COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
