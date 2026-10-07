"""Compact filter syntax -> Query AST.

Used by the CLI for quick, unambiguous queries:

    race=DRAGON attribute=DARK level<=4
    effect.action=SPECIAL_SUMMON effect.source_zone=EXTRA_DECK effect.target_race=DRAGON

This is a convenience surface, not the planner. Anything ambiguous should be
expressed as a JSON Query instead.
"""

from __future__ import annotations

import re

from .dsl import ExistsCondition, Query, QueryError, and_, parse_condition

_FILTER_RE = re.compile(
    r"^(?P<field>[A-Za-z_][A-Za-z0-9_.]*)\s*(?P<op><=|>=|!=|=~|=|<|>)\s*(?P<value>.+)$"
)

# Fields whose values are free text and must not be upper-cased.
TEXT_FIELDS = frozenset(
    {
        "card.canonical_name",
        "card.archetype",
        "card.name",
        "effect.object_name",
        "effect.object_archetype",
        "effect.result_ref",
        "effect.object_ref",
    }
)

# Filters that live inside an `exists: effect` block.
NESTED_PREFIXES = ("effect.", "clause.")

_OP_MAP = {
    "=": "eq",
    "!=": "ne",
    "=~": "contains",
    "<": "lt",
    "<=": "lte",
    ">": "gt",
    ">=": "gte",
}


def parse_filter(expression: str) -> dict:
    match = _FILTER_RE.match(expression.strip())
    if not match:
        raise QueryError(
            f"cannot parse filter {expression!r}; expected field=value or field<=value"
        )
    field = match.group("field")
    # Bare names default to card fields: "race=DRAGON" == "card.race=DRAGON".
    if "." not in field:
        field = f"card.{field}"
    op = _OP_MAP[match.group("op")]
    raw_value = match.group("value").strip().strip("'\"")

    if op in ("lt", "lte", "gt", "gte"):
        try:
            value: object = int(raw_value)
        except ValueError:
            try:
                value = float(raw_value)
            except ValueError as exc:
                raise QueryError(f"{field}: {raw_value!r} is not a number") from exc
    elif field in TEXT_FIELDS or op == "contains":
        value = raw_value
    else:
        # Vocabulary fields are stored upper-case ("DRAGON", "EXTRA_DECK").
        value = raw_value.upper()

    return {"field": field, "op": op, "value": value}


# Convenience aliases for the most commonly typed names.
FIELD_ALIASES = {
    "card.level": "card.level_rank",
    "card.rank": "card.level_rank",
    "card.type": "card.card_category",
    "card.link": "card.link_rating",
    "card.scale": "card.pendulum_scale",
    "effect.race": "effect.object_race",
    "effect.attribute": "effect.object_attribute",
    "effect.level": "effect.object_level",
    "effect.rank": "effect.object_rank",
    "effect.atk": "effect.object_atk",
    "effect.archetype": "effect.object_archetype",
    "effect.card_type": "effect.object_card_type",
    "effect.part": "clause.role",
}


def parse_filters(expressions: list[str]) -> Query:
    """`--filter a=1 --filter b<=2` -> Query(and([...])).

    `effect.*` and `clause.*` filters are wrapped in an `exists: effect` block
    automatically, because a bare effect predicate at card level has no meaning.
    """
    parsed: list[dict] = []
    for expression in expressions:
        node = parse_filter(expression)
        node["field"] = FIELD_ALIASES.get(node["field"], node["field"])
        parsed.append(node)

    if not parsed:
        return Query()

    nested = [n for n in parsed if n["field"].startswith(NESTED_PREFIXES)]
    card_nodes = [n for n in parsed if n not in nested]
    effect_nodes = nested

    conditions = [parse_condition(n) for n in card_nodes]
    if effect_nodes:
        conditions.append(
            ExistsCondition(
                target="effect", where=and_(*[parse_condition(n) for n in effect_nodes])
            )
        )

    return Query(where=and_(*conditions))
