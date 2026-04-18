"""
Persona v2 — the persona memory layer for Hermes VTuber.

This package provides the 3-tier persona context injected on every turn:

    Tier 1 — IDENTITY     (identity.py)    static character definition
    Tier 2 — BIOGRAPHY    (biography.py)   RAG over long-term knowledge
    Tier 3 — SESSION      (session_memory.py)  rolling recent + summary

A composer (composer.py) assembles them into a budgeted system prompt
that hermes_agent.py injects on turn 1.

Phase 2a (initial ship) implements tiers 1 and 3 plus composer.
Phase 2b will add tier 2 (biography RAG) as an optional Chroma-backed
module so the core pipeline stays dependency-free.

Part of: .hermes/plans/2026-04-17_personality-evolution.md
"""

from .identity import Identity, MoodBaseline, load_identity
from .session_memory import SessionMemory, Turn
from .composer import PersonaComposer, ComposedPrompt
from .mood import MoodState, MoodDelta
from .mood_classifier import classify as mood_classify
from .pool_map import (
    PoolMap,
    POOL_KEYS,
    register_pool,
    get_pool_for_model,
    resolve_pool,
    HERMES_DARK_POOL,
)
from .expression_inference import (
    AffectBlend,
    infer as expression_infer,
    blend_to_param_deltas,
    build_expression_message,
)
from .sleep_detector import is_sleep_command, SLEEP_PHRASES

__all__ = [
    "Identity",
    "MoodBaseline",
    "load_identity",
    "SessionMemory",
    "Turn",
    "PersonaComposer",
    "ComposedPrompt",
    # Phase 3
    "MoodState",
    "MoodDelta",
    "mood_classify",
    # Phase 4
    "PoolMap",
    "POOL_KEYS",
    "register_pool",
    "get_pool_for_model",
    "resolve_pool",
    "HERMES_DARK_POOL",
    # Phase 5
    "AffectBlend",
    "expression_infer",
    "blend_to_param_deltas",
    "build_expression_message",
    # Phase 6
    "is_sleep_command",
    "SLEEP_PHRASES",
]
