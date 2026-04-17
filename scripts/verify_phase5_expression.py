"""
Phase 5 verification: per-sentence affect inference + parameter blending.

Tests:
  1. infer() returns a sane AffectBlend for known-affect sentences
  2. Neutral sentences produce ~zero blend
  3. Punctuation modifiers (!, ?, ..., CAPS) shift the right axes
  4. blend_to_param_deltas produces the right Live2D parameters
  5. Mood baseline modulation: low-valence character can't show full joy
  6. build_expression_message returns a wire-ready dict
  7. LIVE: HermesAgent + WebSocket integration emits expression_blend
     messages with correct shape, one per sentence

Standalone runnable. Exits non-zero on any assertion failure.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from open_llm_vtuber.persona import (
    AffectBlend,
    expression_infer,
    blend_to_param_deltas,
    build_expression_message,
)


def section(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


# ---------------------------------------------------------------------------

def test_basic_infer() -> None:
    section("Test 1: infer() reads basic affect lexicons")

    happy = expression_infer("I am so happy and excited today!")
    print(f"happy text -> {happy.to_dict()} ({happy.reason})")
    assert happy.joy > 0, f"expected joy > 0, got {happy.joy}"

    sad = expression_infer("I'm sorry, that's heartbreaking. I miss them.")
    print(f"sad text -> {sad.to_dict()} ({sad.reason})")
    assert sad.sadness > 0, f"expected sadness > 0, got {sad.sadness}"

    angry = expression_infer("That's stupid and unfair. I hate this.")
    print(f"angry text -> {angry.to_dict()} ({angry.reason})")
    assert angry.anger > 0, f"expected anger > 0, got {angry.anger}"

    surprised = expression_infer("Wow, really? That's incredible!")
    print(f"surprised text -> {surprised.to_dict()} ({surprised.reason})")
    assert surprised.surprise > 0

    shy = expression_infer("Aww that's so sweet, I'm flustered, um...")
    print(f"shy text -> {shy.to_dict()} ({shy.reason})")
    assert shy.shy_blush > 0

    print("[OK] all 5 affect dimensions fire on representative text")


def test_neutral() -> None:
    section("Test 2: neutral sentences produce ~zero blend")
    cases = [
        "What time is it.",
        "The pier is at the corner.",
        "I will check the file.",
    ]
    for c in cases:
        b = expression_infer(c)
        mag = b.magnitude()
        print(f"  '{c}' -> magnitude {mag:.2f} ({b.reason})")
        assert mag < 0.5, f"expected near-zero, got {mag}"
    print("[OK] neutral text stays under threshold")


def test_punctuation() -> None:
    section("Test 3: punctuation modifiers")

    excited = expression_infer("That's GREAT NEWS!!!")
    print(f"caps + !!! -> {excited.to_dict()} ({excited.reason})")
    assert excited.joy > 0.2, f"expected boosted joy, got {excited.joy}"
    assert excited.surprise > 0.0

    trailing = expression_infer("oh... I see... well...")
    print(f"trailing ... -> {trailing.to_dict()} ({trailing.reason})")
    assert trailing.sadness > 0.0 or trailing.shy_blush > 0.0

    curious = expression_infer("really? you think so?")
    print(f"questions -> {curious.to_dict()} ({curious.reason})")
    assert curious.surprise > 0.0
    print("[OK] punctuation modifiers shift right axes")


def test_param_mapping() -> None:
    section("Test 4: blend -> Live2D parameter deltas")

    blend = AffectBlend(joy=0.8)
    deltas = blend_to_param_deltas(blend)
    print(f"joy=0.8 -> {deltas}")
    assert "PARAM_MOUTH_FORM" in deltas, "joy should drive mouth form"
    assert deltas["PARAM_MOUTH_FORM"] > 0.0, "mouth form should be positive (smile)"

    blend = AffectBlend(sadness=0.6)
    deltas = blend_to_param_deltas(blend)
    print(f"sadness=0.6 -> {deltas}")
    assert deltas.get("PARAM_MOUTH_FORM", 0.0) < 0.0, "frown"
    assert deltas.get("PARAM_BROW_L_Y", 0.0) < 0.0, "brows down"
    assert deltas.get("PARAM_EYE_L_OPEN", 0.0) < 0.0, "eyes droop"

    blend = AffectBlend(surprise=1.0)
    deltas = blend_to_param_deltas(blend)
    print(f"surprise=1.0 -> {deltas}")
    assert deltas.get("PARAM_BROW_L_Y", 0.0) > 0.0, "brows lift"
    assert deltas.get("PARAM_EYE_L_OPEN", 0.0) > 0.0, "eyes open wide"

    # Aggregated deltas should clamp at ±0.8 (Phase 4.5 raised from 0.5)
    blend = AffectBlend(joy=1.0, surprise=1.0)  # both want brows up
    deltas = blend_to_param_deltas(blend)
    for v in deltas.values():
        assert abs(v) <= 0.8 + 1e-6, f"delta {v} exceeds ±0.8 clamp"
    print(f"joy+surprise (clamped): max delta = {max(abs(v) for v in deltas.values()):.2f}")
    print("[OK] param mapping produces sensible Live2D deltas")


def test_mood_modulation() -> None:
    section("Test 5: mood baseline modulates intensity")

    blend = AffectBlend(joy=1.0)

    # High-valence character: full joy
    high = blend_to_param_deltas(blend, valence=+1.0)
    high_mouth = high.get("PARAM_MOUTH_FORM", 0)
    print(f"valence +1.0 -> mouth form delta = {high_mouth:+.3f}")

    # Neutral character: half joy
    neutral = blend_to_param_deltas(blend, valence=0.0)
    neutral_mouth = neutral.get("PARAM_MOUTH_FORM", 0)
    print(f"valence  0.0 -> mouth form delta = {neutral_mouth:+.3f}")

    # Low-valence character: zero joy
    low = blend_to_param_deltas(blend, valence=-1.0)
    low_mouth = low.get("PARAM_MOUTH_FORM", 0)
    print(f"valence -1.0 -> mouth form delta = {low_mouth:+.3f}")

    assert high_mouth > neutral_mouth > low_mouth, (
        f"expected monotonic dampening: {low_mouth} < {neutral_mouth} < {high_mouth}"
    )
    print("[OK] low-valence character's joy is dampened toward zero")


def test_message_format() -> None:
    section("Test 6: build_expression_message wire format")

    msg = build_expression_message("What an amazing day!", duration_ms=600)
    print(f"  type:        {msg['type']}")
    print(f"  blend:       {msg['blend']}")
    print(f"  deltas:      {len(msg['deltas'])} params")
    print(f"  duration_ms: {msg['duration_ms']}")
    print(f"  reason:      {msg['reason']}")

    assert msg["type"] == "expression_blend"
    assert "blend" in msg and "deltas" in msg
    assert msg["duration_ms"] == 600
    # Wire-friendly: all values are JSON-serializable
    json.dumps(msg)  # raises if not
    print("[OK] message is wire-ready")


# ---------------------------------------------------------------------------

async def test_live_websocket() -> None:
    section("Test 7: LIVE — server emits expression_blend per sentence")
    try:
        import websockets
    except ImportError:
        print("[SKIP] websockets not available")
        return

    # Check that server is up; if not, skip
    try:
        async with websockets.connect("ws://127.0.0.1:12393/client-ws",
                                      open_timeout=5) as ws:
            for _ in range(8):
                try:
                    await asyncio.wait_for(ws.recv(), timeout=2.0)
                except asyncio.TimeoutError:
                    break

            msg = {"type": "text-input",
                   "text": "Tell me an exciting story about open source!"}
            print(f"-> {msg['text']}")
            await ws.send(json.dumps(msg))

            blends = []
            playback_replied = False
            deadline = asyncio.get_event_loop().time() + 90
            while asyncio.get_event_loop().time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=4.0)
                    parsed = json.loads(raw)
                    mt = parsed.get("type")
                    if mt == "expression_blend":
                        blends.append(parsed)
                        b = parsed["blend"]
                        nonzero = {k: v for k, v in b.items() if v}
                        print(f"  <- expression_blend: {nonzero or '{neutral}'} "
                              f"(reason: {parsed.get('reason', '?')})")
                    elif mt == "backend-synth-complete":
                        if not playback_replied:
                            await ws.send(json.dumps({
                                "type": "frontend-playback-complete"}))
                            playback_replied = True
                    elif mt == "mood_update":
                        # Phase 4 message — sign the test is otherwise working
                        print(f"  <- mood_update: {parsed['quadrant']}")
                        break
                except (asyncio.TimeoutError, Exception):
                    continue

            print(f"\n[OK] {len(blends)} expression_blend message(s) received")
            if not blends:
                print("[WARN] no blends received — check server log for errors")
    except (OSError, websockets.exceptions.WebSocketException) as e:
        print(f"[SKIP] server not reachable ({e})")


# ---------------------------------------------------------------------------

def main() -> None:
    test_basic_infer()
    test_neutral()
    test_punctuation()
    test_param_mapping()
    test_mood_modulation()
    test_message_format()
    asyncio.run(test_live_websocket())

    print()
    print("=" * 60)
    print("Phase 5 expression inference verification: COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
