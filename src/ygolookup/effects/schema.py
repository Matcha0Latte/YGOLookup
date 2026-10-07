"""Structured effect data model.

The model is intentionally JSON-serializable: the same object is stored in
`effect_predicate.payload_json`, returned by the agent tools, and used as the
expected value in parser regression fixtures.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .ontology import Action, EffectPart, EffectScope, SegmentMarker, Tri, Zone

__all__ = [
    "TargetConstraint",
    "EffectPredicate",
    "ParsedEffect",
    "EffectSegment",
    "PARSER_VERSION",
]

PARSER_VERSION = "deterministic-v1"


@dataclass
class TargetConstraint:
    """Constraints on *what* an effect applies to.

    `None` means "the text does not constrain this" (equivalently: any value
    matches). `Tri` fields distinguish an explicit negation ("non-Tuner") from
    simply not being mentioned.
    """

    count: int | None = None
    card_category: str | None = None
    race: str | None = None
    attribute: str | None = None
    archetype: str | None = None
    name: str | None = None
    level_min: int | None = None
    level_max: int | None = None
    rank: int | None = None
    link_rating: int | None = None
    atk_min: int | None = None
    atk_max: int | None = None
    def_min: int | None = None
    def_max: int | None = None
    tuner: Tri = Tri.UNKNOWN
    pendulum: Tri = Tri.UNKNOWN
    effect_monster: Tri = Tri.UNKNOWN
    token: Tri = Tri.UNKNOWN

    def is_empty(self) -> bool:
        return all(
            value is None or value is Tri.UNKNOWN
            for value in asdict(self).values()
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "card_category": self.card_category,
            "race": self.race,
            "attribute": self.attribute,
            "archetype": self.archetype,
            "name": self.name,
            "level_min": self.level_min,
            "level_max": self.level_max,
            "rank": self.rank,
            "link_rating": self.link_rating,
            "atk_min": self.atk_min,
            "atk_max": self.atk_max,
            "def_min": self.def_min,
            "def_max": self.def_max,
            "tuner": self.tuner.value,
            "pendulum": self.pendulum.value,
            "effect_monster": self.effect_monster.value,
            "token": self.token.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TargetConstraint":
        data = dict(data)
        for tri_field in ("tuner", "pendulum", "effect_monster", "token"):
            if tri_field in data:
                data[tri_field] = Tri(data[tri_field])
        return cls(**data)


@dataclass
class EffectPredicate:
    """One atomic claim about an effect, scoped to a part (cost / resolution / …)."""

    part: EffectPart
    action: Action | None = None
    source: Zone | None = None
    destination: Zone | None = None
    target: TargetConstraint = field(default_factory=TargetConstraint)
    once_per_turn: Tri = Tri.UNKNOWN
    confidence: float = 0.0
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "part": self.part.value,
            "action": self.action.value if self.action else None,
            "action_known": self.action is not None,
            "source": self.source.value if self.source else None,
            "destination": self.destination.value if self.destination else None,
            "target": self.target.to_dict(),
            "once_per_turn": self.once_per_turn.value,
            "confidence": round(self.confidence, 3),
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EffectPredicate":
        return cls(
            part=EffectPart(data["part"]),
            action=Action.parse(data["action"]) if data.get("action") else None,
            source=Zone.parse(data["source"]) if data.get("source") else None,
            destination=Zone.parse(data["destination"]) if data.get("destination") else None,
            target=TargetConstraint.from_dict(data.get("target") or {}),
            once_per_turn=Tri(data.get("once_per_turn", Tri.UNKNOWN.value)),
            confidence=float(data.get("confidence", 0.0)),
            evidence=data.get("evidence", ""),
        )


@dataclass
class EffectSegment:
    """Output of the splitter: one candidate effect with its raw text."""

    index: int
    scope: EffectScope
    marker: SegmentMarker
    raw_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "scope": self.scope.value,
            "marker": self.marker.value,
            "raw_text": self.raw_text,
        }


@dataclass
class ParsedEffect:
    """Splitter output + parser output, ready to be persisted."""

    segment: EffectSegment
    predicates: list[EffectPredicate] = field(default_factory=list)
    parser_version: str = PARSER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment": self.segment.to_dict(),
            "parser_version": self.parser_version,
            "predicates": [p.to_dict() for p in self.predicates],
        }
