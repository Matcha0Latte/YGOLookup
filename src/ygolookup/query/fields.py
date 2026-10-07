"""Field registry: the single place that maps DSL field names onto storage.

Adding a queryable field means adding one entry here — nothing else in the
codebase needs to change, and unknown field names are rejected instead of being
interpolated into SQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from .dsl import RANGE_OPS, QueryError
from ..effects.ontology import (
    ATTRIBUTE_VOCABULARY,
    RACE_VOCABULARY,
    Action,
    EffectPart,
    Tri,
    Zone,
)

__all__ = ["FieldSpec", "FIELDS", "get_field", "validate_value", "EFFECT_ACTIONS", "EFFECT_ZONES"]

EFFECT_ACTIONS = sorted(a.value for a in Action)
EFFECT_ZONES = sorted(z.value for z in Zone)
EFFECT_PARTS = sorted(p.value for p in EffectPart)
TRI_VALUES = sorted(t.value for t in Tri)
RACE_VALUES = sorted(set(RACE_VOCABULARY.values()))
ATTRIBUTE_VALUES = sorted(set(ATTRIBUTE_VOCABULARY.values()))
CATEGORY_VALUES = ["MONSTER", "SPELL", "TRAP", "SPELL_TRAP"]


@dataclass(frozen=True)
class FieldSpec:
    name: str
    table: str  # "card" | "effect"
    column: str | None  # None -> handled by `expr`
    value_kind: str  # "enum" | "int" | "text" | "tri" | "bool"
    allowed: tuple[str, ...] = ()
    range_pair: tuple[str, str] | None = None  # virtual range field -> (min_col, max_col)
    expr: str | None = None  # raw SQL expression, "%s" not used; use column instead
    requires_join: bool = False


def _card(column: str, value_kind: str = "enum", allowed: tuple[str, ...] = ()) -> FieldSpec:
    return FieldSpec(name=f"card.{column}", table="card", column=column, value_kind=value_kind, allowed=allowed)


def _effect(column: str, value_kind: str = "enum", allowed: tuple[str, ...] = ()) -> FieldSpec:
    return FieldSpec(name=f"effect.{column}", table="effect", column=column, value_kind=value_kind, allowed=allowed)


FIELDS: dict[str, FieldSpec] = {
    # ---------------------------------------------------------------- card
    spec.name: spec
    for spec in [
        FieldSpec("card.card_id", "card", "card_id", "int"),
        _card("canonical_name", "text"),
        _card("card_category", "enum", ("MONSTER", "SPELL", "TRAP")),
        _card(
            "sub_category",
            "enum",
            (
                "NORMAL",
                "EFFECT",
                "FUSION",
                "RITUAL",
                "SYNCHRO",
                "XYZ",
                "LINK",
                "PENDULUM",
                "QUICK_PLAY",
                "CONTINUOUS",
                "EQUIP",
                "FIELD",
                "COUNTER",
                "TRAP_MONSTER",
                "TOKEN",
                "SKILL",
                "MAXIMUM",
                "ARMOR",
            ),
        ),
        _card("race", "enum", tuple(RACE_VALUES)),
        _card("attribute", "enum", tuple(ATTRIBUTE_VALUES)),
        FieldSpec("card.level_rank", "card", "level_rank", "int"),
        FieldSpec("card.link_rating", "card", "link_rating", "int"),
        FieldSpec("card.pendulum_scale", "card", "pendulum_scale", "int"),
        FieldSpec("card.atk", "card", "atk", "int"),
        FieldSpec("card.def", "card", "def", "int"),
        # Virtual / joined fields
        FieldSpec(
            "card.archetype",
            "card",
            None,
            "text",
            requires_join=True,
            expr="EXISTS (SELECT 1 FROM card_archetype ca WHERE ca.card_id = c.card_id AND ca.archetype = ?)",
        ),
        FieldSpec(
            "card.flag",
            "card",
            None,
            "enum",
            requires_join=True,
            expr="EXISTS (SELECT 1 FROM card_flag cf WHERE cf.card_id = c.card_id AND cf.flag = ?)",
        ),
        FieldSpec(
            "card.name",
            "card",
            None,
            "text",
            requires_join=True,
            expr="EXISTS (SELECT 1 FROM card_name cn WHERE cn.card_id = c.card_id AND cn.name LIKE ? COLLATE NOCASE)",
        ),
        # -------------------------------------------------------------- effect
        _effect("part", "enum", tuple(EFFECT_PARTS)),
        _effect("action", "enum", tuple(EFFECT_ACTIONS)),
        _effect("source_zone", "enum", tuple(EFFECT_ZONES)),
        _effect("destination_zone", "enum", tuple(EFFECT_ZONES)),
        _effect("target_race", "enum", tuple(RACE_VALUES)),
        _effect("target_attribute", "enum", tuple(ATTRIBUTE_VALUES)),
        _effect("target_card_category", "enum", tuple(CATEGORY_VALUES)),
        _effect("target_archetype", "text"),
        _effect("target_name", "text"),
        _effect("target_tuner", "tri", tuple(TRI_VALUES)),
        _effect("once_per_turn", "tri", tuple(TRI_VALUES)),
        FieldSpec("effect.target_count", "effect", "target_count", "int"),
        FieldSpec("effect.target_rank", "effect", "target_rank", "int"),
        FieldSpec("effect.target_link_rating", "effect", "target_link_rating", "int"),
        FieldSpec("effect.confidence", "effect", "confidence", "int"),
        # Virtual range fields: "Level 4 or lower" is stored as level_max = 4,
        # an exact Level 4 as min = max = 4. A query for "<= 4" must match both.
        FieldSpec(
            "effect.target_level",
            "effect",
            None,
            "int",
            range_pair=("target_level_min", "target_level_max"),
        ),
        FieldSpec(
            "effect.target_atk",
            "effect",
            None,
            "int",
            range_pair=("target_atk_min", "target_atk_max"),
        ),
    ]
}


def get_field(name: str) -> FieldSpec:
    spec = FIELDS.get(name)
    if spec is None:
        raise QueryError(
            f"unknown field {name!r}. Known fields: {', '.join(sorted(FIELDS))}"
        )
    return spec


def validate_value(spec: FieldSpec, op: str, value) -> None:
    if op in ("in", "nin"):
        if not isinstance(value, list) or not value:
            raise QueryError(f"{spec.name}: op {op!r} needs a non-empty list")
        for item in value:
            validate_value(spec, "eq", item)
        return

    if spec.value_kind == "int":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise QueryError(f"{spec.name} expects a number, got {value!r}")
        return

    if not isinstance(value, str):
        raise QueryError(f"{spec.name} expects a string, got {value!r}")

    if spec.allowed and value not in spec.allowed:
        raise QueryError(
            f"{value!r} is not valid for {spec.name}. Allowed: {list(spec.allowed)}"
        )
    if spec.value_kind == "enum":
        return

    if op == "contains" and spec.value_kind != "text":
        raise QueryError(f"{spec.name} does not support 'contains'")


def assert_range_supported(spec: FieldSpec, op: str) -> None:
    if spec.range_pair and op not in RANGE_OPS:
        raise QueryError(f"{spec.name} (virtual range field) only supports {sorted(RANGE_OPS)}")


def field_names(table: str | None = None) -> Iterable[str]:
    for name, spec in sorted(FIELDS.items()):
        if table is None or spec.table == table:
            yield name
