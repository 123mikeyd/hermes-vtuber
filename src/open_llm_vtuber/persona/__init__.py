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

__all__ = [
    "Identity",
    "MoodBaseline",
    "load_identity",
    "SessionMemory",
    "Turn",
    "PersonaComposer",
    "ComposedPrompt",
]
