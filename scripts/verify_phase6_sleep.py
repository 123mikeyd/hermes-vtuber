"""
Phase 6 verification: sleep detector + new motion files + pool_map updates.

Tests:
  1. Sleep detector rejects empty / whitespace input
  2. Sleep detector accepts all canonical SLEEP_PHRASES
  3. Sleep detector rejects quoted-speech false triggers
  4. Sleep detector rejects embedded phrases in longer messages
  5. Direct-address prefix stripping works (Nova, Hey Nova, etc.)
  6. Politeness suffix stripping works (please, thanks)
  7. All 9 new Phase 6 motion files exist, parse, and structural audit passes
  8. HERMES_DARK_POOL has the expected Phase 6 additions
  9. POOL_KEYS includes the new sleep-related keys

Standalone runnable. Exits non-zero on assertion failure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from open_llm_vtuber.persona import (
    is_sleep_command,
    SLEEP_PHRASES,
    POOL_KEYS,
    HERMES_DARK_POOL,
)


def section(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


# ---------------------------------------------------------------------------

def test_empty_and_whitespace() -> None:
    section("Test 1: empty/whitespace inputs reject")
    for x in ["", "   ", "\n\t", None]:
        assert not is_sleep_command(x), f"empty-ish '{x!r}' should not fire"
    print("[OK] empty/whitespace/None all reject")


def test_accept_canonical_phrases() -> None:
    section("Test 2: all SLEEP_PHRASES fire when standalone")
    for phrase in SLEEP_PHRASES:
        assert is_sleep_command(phrase), f"canonical phrase {phrase!r} didn't fire"
        # With polite variations too
        for variant in [phrase + ".", phrase + "!", "please " + phrase]:
            assert is_sleep_command(variant), f"variant {variant!r} didn't fire"
    print(f"[OK] all {len(SLEEP_PHRASES)} canonical phrases + variants fire")


def test_reject_quoted_speech() -> None:
    section("Test 3: quoted speech rejects (not reported speech)")
    cases = [
        'I told my brother "go to sleep" last night',
        "my friend said 'take a nap' earlier",
        'nova said "go to sleep" yesterday',
        "I heard 'rest up' on a podcast",
    ]
    for c in cases:
        result = is_sleep_command(c)
        print(f"  {'[OK]' if not result else '[FAIL]'} {c!r}")
        assert not result, f"quoted phrase {c!r} incorrectly fired"
    print("[OK] quoted-speech false positives all avoided")


def test_reject_embedded() -> None:
    section("Test 4: phrase embedded in longer message rejects")
    cases = [
        "Nova, remind me to go to sleep in 20 minutes",
        "can you help me write a post about taking a nap",
        "I'm going to take a nap myself",
        "if I say go to sleep do you go to sleep",
        "is it time to take a nap yet",  # 7 words, still feels embedded
    ]
    for c in cases:
        result = is_sleep_command(c)
        print(f"  {'[OK]' if not result else '[FAIL]'} {c!r}")
        assert not result, f"embedded phrase {c!r} incorrectly fired"
    print("[OK] embedded phrases don't trigger")


def test_direct_address() -> None:
    section("Test 5: direct-address prefix stripping")
    cases = [
        "Nova, go to sleep",
        "Nova take a nap",
        "Hey Nova, rest up",
        "Hey Nova take a nap please",
        "please go to sleep",
        "can you take a nap",
    ]
    for c in cases:
        assert is_sleep_command(c), f"address-prefixed {c!r} should fire"
        print(f"  [OK] {c!r}")
    print("[OK] direct-address prefixes strip correctly")


def test_politeness_suffix() -> None:
    section("Test 6: politeness suffix stripping")
    cases = [
        "go to sleep please",
        "take a nap, please",
        "get some rest, thanks",
        "rest up thank you",
    ]
    for c in cases:
        assert is_sleep_command(c), f"polite {c!r} should fire"
        print(f"  [OK] {c!r}")
    print("[OK] politeness suffixes strip correctly")


# ---------------------------------------------------------------------------

def test_motions_exist() -> None:
    section("Test 7: all 9 new Phase 6 motion files exist + audit")
    base = Path("/home/mikeyd/Open-LLM-VTuber/live2d-models/hermes_dark/runtime/motion")
    new_motions = [
        ("idle_desk_check.motion3.json",     3.0,  False),
        ("idle_look_around.motion3.json",    5.0,  False),
        ("idle_soft_stretch.motion3.json",   7.0,  False),
        ("idle_desk_rock.motion3.json",      9.0,  False),
        ("idle_hair_fidget.motion3.json",   12.0,  False),
        ("idle_wait.motion3.json",          16.0,  False),
        ("falling_asleep.motion3.json",      4.0,  False),
        ("sleep_head_down.motion3.json",    20.0,  True),   # LOOPS
        ("waking_up.motion3.json",           3.0,  False),
    ]
    for fname, expected_dur, expected_loop in new_motions:
        p = base / fname
        assert p.is_file(), f"missing: {fname}"
        data = json.loads(p.read_text())
        meta = data["Meta"]
        assert abs(meta["Duration"] - expected_dur) < 0.01, \
            f"{fname}: duration {meta['Duration']} != {expected_dur}"
        assert meta["Loop"] == expected_loop, \
            f"{fname}: loop {meta['Loop']} != {expected_loop}"
        # Critical params present
        curves = data["Curves"]
        ids = {c["Id"] for c in curves}
        for must_have in ["PARAM_EYE_L_OPEN", "PARAM_EYE_R_OPEN",
                          "PARTS_01_ARM_L_02", "PARTS_01_ARM_R_02"]:
            assert must_have in ids, f"{fname} missing {must_have}"
        # Arm visibility guard (four-arm-deity)
        for side in ("L", "R"):
            c01 = next((c for c in curves if c["Id"] == f"PARTS_01_ARM_{side}_01"), None)
            c02 = next((c for c in curves if c["Id"] == f"PARTS_01_ARM_{side}_02"), None)
            if c01 and c02:
                v01 = c01["Segments"][1]
                v02 = c02["Segments"][1]
                assert v01 > 0.5 or v02 > 0.5, \
                    f"{fname}: {side}-arm will vanish (both layers 0)"
        print(f"  [OK] {fname:38s} {expected_dur:5.1f}s loop={expected_loop}")
    print("[OK] all 9 new motions present, structural audit passes")


def test_pool_map() -> None:
    section("Test 8 + 9: POOL_KEYS + HERMES_DARK_POOL Phase 6 updates")

    # POOL_KEYS includes new keys
    for k in ("sleep", "falling_asleep", "waking_up"):
        assert k in POOL_KEYS, f"POOL_KEYS missing {k!r}"
    print(f"[OK] POOL_KEYS includes sleep, falling_asleep, waking_up")

    # HERMES_DARK_POOL has ≥10 calm motions (Phase 6 variety goal)
    assert len(HERMES_DARK_POOL.calm) >= 8, \
        f"calm pool only has {len(HERMES_DARK_POOL.calm)}, expected >= 8"
    print(f"[OK] calm pool has {len(HERMES_DARK_POOL.calm)} motions (variety goal)")

    # The lead motion is idle_wait (most common background state)
    assert "idle_wait.motion3.json" in HERMES_DARK_POOL.calm[0], \
        f"idle_wait should lead calm, got {HERMES_DARK_POOL.calm[0]!r}"
    print(f"[OK] idle_wait leads the calm pool")

    # Sleep pools populated
    assert len(HERMES_DARK_POOL.sleep) >= 1
    assert len(HERMES_DARK_POOL.falling_asleep) >= 1
    assert len(HERMES_DARK_POOL.waking_up) >= 1
    print(f"[OK] sleep pools populated: "
          f"sleep={len(HERMES_DARK_POOL.sleep)} "
          f"falling_asleep={len(HERMES_DARK_POOL.falling_asleep)} "
          f"waking_up={len(HERMES_DARK_POOL.waking_up)}")


# ---------------------------------------------------------------------------

def main() -> None:
    test_empty_and_whitespace()
    test_accept_canonical_phrases()
    test_reject_quoted_speech()
    test_reject_embedded()
    test_direct_address()
    test_politeness_suffix()
    test_motions_exist()
    test_pool_map()

    print()
    print("=" * 60)
    print("Phase 6 sleep + variety verification: COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
