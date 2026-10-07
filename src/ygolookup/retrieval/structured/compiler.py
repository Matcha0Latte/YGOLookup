"""DSL -> parameterized SQL.

This is the only module that knows how the query model maps onto tables. The
DSL itself stays storage-agnostic; swapping in FTS5 or a vector backend means
writing a different translator, not changing the query model.

Every value is bound as a parameter — no user string is ever interpolated.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...effects.ontology import Action, Zone
from ...query.dsl import (
    BoolCondition,
    Condition,
    ExistsCondition,
    FieldCondition,
    Query,
    QueryError,
    iter_conditions,
)
from ...query.fields import assert_range_supported, get_field, validate_value

CARD_ALIAS = "c"
EFFECT_ALIAS = "e"
PREDICATE_ALIAS = "p"

_CARD_SELECT_COLUMNS = (
    "card_id",
    "canonical_name",
    "card_category",
    "sub_category",
    "race",
    "attribute",
    "level_rank",
    "link_rating",
    "pendulum_scale",
    "atk",
    "def",
)


@dataclass
class CompiledQuery:
    sql: str
    params: list = field(default_factory=list)


# ------------------------------------------------------------ value translation
def _translate_value(field_name: str, value):
    """Normalize DSL values into their stored representation."""
    if field_name == "effect.action" and isinstance(value, str):
        action = Action.parse(value)
        if action is None:
            raise QueryError(f"unknown action {value!r}")
        return action.value
    if field_name in ("effect.source_zone", "effect.destination_zone") and isinstance(value, str):
        zone = Zone.parse(value)
        if zone is None:
            raise QueryError(f"unknown zone {value!r}")
        return zone.value
    if field_name == "effect.target_card_category" and value == "SPELL_TRAP":
        return "SPELL_TRAP"
    return value


def _expand_category_value(value: str) -> list[str]:
    """A query for SPELL also matches predicates stored as SPELL_TRAP.

    "Target 1 Spell/Trap" is stored as the single token SPELL_TRAP, but asking
    for effects that target Spells must still find it. The reverse is not true:
    asking for SPELL_TRAP means "either", which SPELL alone does not satisfy.
    """
    if value == "SPELL":
        return ["SPELL", "SPELL_TRAP"]
    if value == "TRAP":
        return ["TRAP", "SPELL_TRAP"]
    return [value]


# ------------------------------------------------------------ condition compile
def _compile_field(condition: FieldCondition, alias: str, out: CompiledQuery) -> str:
    spec = get_field(condition.field)
    expected_table = "card" if alias == CARD_ALIAS else "effect"
    if spec.table != expected_table:
        if spec.table == "effect":
            raise QueryError(
                f"{spec.name} is an effect field and must be inside an 'exists: effect' block"
            )
        raise QueryError(
            f"{spec.name} is a card field and cannot appear inside an 'exists: effect' block"
        )
    validate_value(spec, condition.op, condition.value)
    assert_range_supported(spec, condition.op)

    op = condition.op

    # Joined / expression-backed columns
    if spec.expr is not None:
        value = condition.value
        if op == "eq":
            out.params.append(_translate_value(spec.name, value))
            return spec.expr
        if op == "ne":
            out.params.append(_translate_value(spec.name, value))
            return f"NOT ({spec.expr})"
        if op == "contains":
            out.params.append(f"%{value}%")
            return spec.expr
        raise QueryError(f"{spec.name} supports eq / ne / contains only")

    # Virtual range fields (min/max pair)
    if spec.range_pair is not None:
        min_col, max_col = spec.range_pair
        value = condition.value
        operator = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">="}[op]
        out.params.extend([value, value])
        return (
            f"({alias}.{min_col} {operator} ? OR {alias}.{max_col} {operator} ?)"
        )

    column = f"{alias}.{spec.column}"
    values = _expand_category_value(condition.value) if isinstance(condition.value, str) else condition.value

    if op == "eq":
        if isinstance(values, list):  # SPELL_TRAP expands to an OR
            placeholders = ", ".join("?" for _ in values)
            out.params.extend(_translate_value(spec.name, v) for v in values)
            return f"{column} IN ({placeholders})"
        out.params.append(_translate_value(spec.name, values))
        return f"{column} = ?"

    if op == "ne":
        if isinstance(values, list):
            placeholders = ", ".join("?" for _ in values)
            out.params.extend(_translate_value(spec.name, v) for v in values)
            return f"{column} IS NOT NULL AND {column} NOT IN ({placeholders})"
        out.params.append(_translate_value(spec.name, values))
        # IS NOT is NULL-safe: an UNKNOWN (NULL) value is "not equal" too.
        return f"{column} IS NOT ?"

    if op == "contains":
        out.params.append(f"%{values}%")
        return f"{column} LIKE ? COLLATE NOCASE"

    if op in ("in", "nin"):
        flat: list = []
        for value in condition.value:
            flat.extend(_expand_category_value(value) if isinstance(value, str) else [value])
        placeholders = ", ".join("?" for _ in flat)
        out.params.extend(_translate_value(spec.name, v) for v in flat)
        if op == "in":
            return f"{column} IN ({placeholders})"
        return f"({column} IS NULL OR {column} NOT IN ({placeholders}))"

    operator = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">="}[op]
    out.params.append(values)
    return f"{column} {operator} ?"


def _compile_condition(condition: Condition, alias: str, out: CompiledQuery) -> str:
    if isinstance(condition, FieldCondition):
        return _compile_field(condition, alias, out)

    if isinstance(condition, BoolCondition):
        parts = [_compile_condition(child, alias, out) for child in condition.children]
        if condition.kind == "not":
            return f"NOT ({parts[0]})"
        joiner = " AND " if condition.kind == "and" else " OR "
        return "(" + joiner.join(parts) + ")"

    if isinstance(condition, ExistsCondition):
        return _compile_exists(condition, out)

    raise QueryError(f"unsupported condition node {condition!r}")


def _compile_exists(condition: ExistsCondition, out: CompiledQuery) -> str:
    """Nested EXISTS, not a flattened join.

    Measured on the 14.6k-card database: a flat
    `effect JOIN effect_predicate ... WHERE e.card_id = c.card_id` plan takes
    ~68s, while the nested form below runs in ~0.1s because the correlated
    `e.card_id = c.card_id` constraint is applied before the predicate filter.
    """
    inner = CompiledQuery(sql="")
    where = "1 = 1"
    if condition.where is not None:
        where = _compile_condition(condition.where, PREDICATE_ALIAS, inner)
    out.params.extend(inner.params)
    return (
        f"EXISTS (SELECT 1 FROM effect {EFFECT_ALIAS} "
        f"WHERE {EFFECT_ALIAS}.card_id = {CARD_ALIAS}.card_id "
        f"AND EXISTS (SELECT 1 FROM effect_predicate {PREDICATE_ALIAS} "
        f"WHERE {PREDICATE_ALIAS}.effect_id = {EFFECT_ALIAS}.effect_id AND ({where})))"
    )


# ------------------------------------------------------------------ public API
def compile_card_query(query: Query) -> CompiledQuery:
    """SQL that returns matching cards."""
    out = CompiledQuery(sql="")
    where = "1 = 1"
    if query.where is not None:
        where = _compile_condition(query.where, CARD_ALIAS, out)

    columns = ", ".join(f"{CARD_ALIAS}.{name}" for name in _CARD_SELECT_COLUMNS)
    sql = (
        f"SELECT {columns} FROM card {CARD_ALIAS} WHERE {where} "
        f"ORDER BY {CARD_ALIAS}.canonical_name COLLATE NOCASE "
        f"LIMIT ? OFFSET ?"
    )
    out.params.extend([query.limit, query.offset])
    return CompiledQuery(sql=sql, params=out.params)


def compile_count_query(query: Query) -> CompiledQuery:
    out = CompiledQuery(sql="")
    where = "1 = 1"
    if query.where is not None:
        where = _compile_condition(query.where, CARD_ALIAS, out)
    return CompiledQuery(
        sql=f"SELECT COUNT(*) AS total FROM card {CARD_ALIAS} WHERE {where}",
        params=out.params,
    )


def collect_effect_conditions(condition: Condition | None) -> list[ExistsCondition]:
    """Every `exists: effect` block in the query, in document order."""
    return [node for node in iter_conditions(condition) if isinstance(node, ExistsCondition)]


def compile_effect_match_query(query: Query, card_ids: list[int]) -> CompiledQuery:
    """SQL that returns the effects of `card_ids` that satisfy the effect blocks.

    Used only to annotate results with the evidence that matched — it never
    changes which cards are returned.
    """
    if not card_ids:
        return CompiledQuery(sql="", params=[])

    out = CompiledQuery(sql="")
    placeholders = ", ".join("?" for _ in card_ids)
    out.params.extend(card_ids)

    conditions = collect_effect_conditions(query.where)
    clauses = []
    for exists in conditions:
        inner = CompiledQuery(sql="")
        if exists.where is not None:
            clauses.append(_compile_condition(exists.where, PREDICATE_ALIAS, inner))
        out.params.extend(inner.params)

    where = " AND ".join(clauses) if clauses else "1 = 1"
    sql = (
        f"SELECT DISTINCT {EFFECT_ALIAS}.effect_id, {EFFECT_ALIAS}.card_id, "
        f"{EFFECT_ALIAS}.effect_index, {EFFECT_ALIAS}.scope, {EFFECT_ALIAS}.marker, "
        f"{EFFECT_ALIAS}.raw_text "
        f"FROM effect {EFFECT_ALIAS} "
        f"JOIN effect_predicate {PREDICATE_ALIAS} ON {PREDICATE_ALIAS}.effect_id = {EFFECT_ALIAS}.effect_id "
        f"WHERE {EFFECT_ALIAS}.card_id IN ({placeholders}) AND ({where}) "
        f"ORDER BY {EFFECT_ALIAS}.card_id, {EFFECT_ALIAS}.effect_index"
    )
    return CompiledQuery(sql=sql, params=out.params)
