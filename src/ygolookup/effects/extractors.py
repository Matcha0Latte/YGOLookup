"""Pluggable extraction layers.

The pipeline is:

    deterministic rules  ->  grammar / templates  ->  LLM  ->  validator

The first two are implemented. The LLM layer is **deliberately left empty in
v1**: the interface is fixed, the implementation is not wired to any model.

Contract for an extractor:

* input is the **Chinese** source text — never an English translation
* output uses only the predefined English enums from `ontology`
* it may create no new enum values
* every extracted value carries the Chinese span it came from
* when it cannot determine something it yields UNKNOWN / unresolved; it must
  never guess just to fill the schema
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .predicates import ParsedUnit
from .units import EffectUnit

__all__ = ["EffectExtractor", "NullExtractor", "LlmExtractor", "get_extractor"]


class EffectExtractor(Protocol):
    """A layer that can turn one EffectUnit into a ParsedUnit."""

    name: str

    def extract(self, unit: EffectUnit) -> ParsedUnit | None:
        """Return a ParsedUnit, or None to defer to a later layer."""
        ...


@dataclass
class NullExtractor:
    """Terminal layer that always defers. Used as the default LLM slot."""

    name: str = "null"

    def extract(self, unit: EffectUnit) -> ParsedUnit | None:
        return None


@dataclass
class LlmExtractor:
    """LLM-backed extraction — **not implemented in v1**.

    It is declared so the pipeline slot exists and can be tested against. When
    it is implemented it must:

    1. send `unit.raw_text` verbatim (Chinese, no translation)
    2. constrain the model to the enums in `ontology`
    3. attach `extracted_by = ExtractedBy.LLM` to every value it produces
    4. return `None` on any failure so the validator can mark the unit
       UNRESOLVED rather than storing a hallucination
    """

    model: str = ""
    name: str = "llm"

    def __post_init__(self) -> None:
        self.enabled = bool(self.model)

    def extract(self, unit: EffectUnit) -> ParsedUnit | None:
        # Intentionally empty for v1. Returning None keeps the unit on the
        # deterministic result and marks it PARTIAL / UNRESOLVED downstream.
        return None


def get_extractor(model: str = "") -> EffectExtractor:
    """Pick the LLM slot implementation. Empty model -> disabled slot."""
    if model:
        return LlmExtractor(model=model)
    return NullExtractor()
