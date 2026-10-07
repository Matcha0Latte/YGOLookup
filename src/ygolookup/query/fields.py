"""Field registry: the single place that maps DSL field names onto storage.

Adding a queryable field means adding one entry here — nothing else in the
codebase needs to change, and unknown field names are rejected instead of being
interpolated into SQL.

Effect fields address two different tables:

* `store="clause"`    -> `effect_clause`  (role, timing)
* `store="predicate"` -> `effect_predicate` (action, zones, object)

Both live inside an `exists: effect` block.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .dsl import RANGE_OPS, QueryError
from ..effects.ontology import (
    ATTRIBUTE_VOCABULARY,
    RACE_VOCABULARY,
    Action,
    ClauseRole,
    ExtractedBy,
    Subject,
    Tri,
    Zone,
)

__all__ = [
    "FieldSpec",
    "FIELDS",
    "get_field",
    "validate_value",
    "EFFECT_ACTIONS",
    "EFFECT_ZONES",
]

EFFECT_ACTIONS = sorted(a.value for a in Action)
EFFECT_ZONES = sorted(z.value for z in Zone)
CLAUSE_ROLES = sorted(r.value for r in ClauseRole)
TRI_VALUES = sorted(t.value for t in Tri)
RACE_VALUES = sorted(set(RACE_VOCABULARY.values()))
ATTRIBUTE_VALUES = sorted(set(ATTRIBUTE_VOCABULARY.values()))
CATEGORY_VALUES = ["MONSTER", "SPELL", "TRAP", "SPELL_TRAP"]
SUBJECT_VALUES = sorted(s.value for s in Subject)
EXTRACTED_BY_VALUES = sorted(e.value for e in ExtractedBy)


@dataclass(frozen=True)
class FieldSpec:
    name: str
    table: str  # "card" | "effect"
    column: str | None
    value_kind: str  # "enum" | "int" | "text" | "tri"
    allowed: tuple[str, ...] = ()
    expr: str | None = None  # raw SQL expression for joined columns
    requires_join: bool = False
    store: str = "card"  # "card" | "clause" | "predicate"
    numeric_pair: tuple[str, str] | None = None  # (op_column, value_column)


def _card(column: str, value_kind: str = "enum", allowed: tuple[str, ...] = ()) -> FieldSpec:
    return FieldSpec(name=f"card.{column}", table="card", column=column, value_kind=value_kind, allowed=allowed)


def _predicate(column: str, value_kind: str = "enum", allowed: tuple[str, ...] = ()) -> FieldSpec:
    return FieldSpec(
        name=f"effect.{column}",
        table="effect",
        column=column,
        value_kind=value_kind,
        allowed=allowed,
        store="predicate",
    )


def _clause(column: str, value_kind: str = "enum", allowed: tuple[str, ...] = ()) -> FieldSpec:
    return FieldSpec(
        name=f"clause.{column}",
        table="effect",
        column=column,
        value_kind=value_kind,
        allowed=allowed,
        store="clause",
    )


def _numeric(name: str, op_column: str, value_column: str) -> FieldSpec:
    return FieldSpec(
        name=f"effect.{name}",
        table="effect",
        column=None,
        value_kind="int",
        store="predicate",
        numeric_pair=(op_column, value_column),
    )


FIELDS: dict[str, FieldSpec] = {
    spec.name: spec
    for spec in [
        # ---------------------------------------------------------------- card
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
        # -------------------------------------------------------------- clause
        _clause("role", "enum", tuple(CLAUSE_ROLES)),
        _clause("once_per_turn", "tri", tuple(TRI_VALUES)),
        FieldSpec(
            "clause.confidence", "effect", "confidence", "int", store="clause"
        ),
        # ----------------------------------------------------------- predicate
        _predicate("subject", "enum", tuple(SUBJECT_VALUES)),
        _predicate("action", "enum", tuple(EFFECT_ACTIONS)),
        _predicate("source_zone", "enum", tuple(EFFECT_ZONES)),
        _predicate("destination_zone", "enum", tuple(EFFECT_ZONES)),
        _predicate("object_race", "enum", tuple(RACE_VALUES)),
        _predicate("object_attribute", "enum", tuple(ATTRIBUTE_VALUES)),
        _predicate("object_card_type", "enum", tuple(CATEGORY_VALUES)),
        _predicate("object_archetype", "text"),
        _predicate("object_name", "text"),
        _predicate("result_ref", "text"),
        _predicate("object_ref", "text"),
        _predicate("extracted_by", "enum", tuple(EXTRACTED_BY_VALUES)),
        FieldSpec(
            "effect.action_known", "effect", "action_known", "int", store="predicate"
        ),
        FieldSpec("effect.object_count", "effect", "object_count", "int", store="predicate"),
        FieldSpec("effect.confidence", "effect", "confidence", "int", store="predicate"),
        # Structured numeric comparisons: {op, value} pairs.
        _numeric("object_level", "object_level_op", "object_level_value"),
        _numeric("object_rank", "object_rank_op", "object_rank_value"),
        _numeric("object_link_rating", "object_link_op", "object_link_value"),
        _numeric("object_atk", "object_atk_op", "object_atk_value"),
        _numeric("object_defense", "object_def_op", "object_def_value"),
    ]
}


def get_field(name: str) -> FieldSpec:
    spec = FIELDS.get(name)
    if spec is None:
        raise QueryError(f"unknown field {name!r}. Known fields: {', '.join(sorted(FIELDS))}")
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
        raise QueryError(f"{value!r} is not valid for {spec.name}. Allowed: {list(spec.allowed)}")
    if spec.value_kind == "enum":
        return

    if op == "contains" and spec.value_kind != "text":
        raise QueryError(f"{spec.name} does not support 'contains'")


def assert_range_supported(spec: FieldSpec, op: str) -> None:
    if spec.numeric_pair and op not in RANGE_OPS:
        raise QueryError(f"{spec.name} (structured comparison) only supports {sorted(RANGE_OPS)}")


def field_names(table: str | None = None) -> Iterable[str]:
    for name, spec in sorted(FIELDS.items()):
        if table is None or spec.table == table:
            yield name
