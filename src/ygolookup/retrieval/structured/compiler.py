"""DSL -> parameterized SQL.

This is the only module that knows how the query model maps onto tables. The
DSL itself stays storage-agnostic; swapping in FTS5 or a vector backend means
writing a different translator, not changing the query model.

Every value is bound as a parameter — no user string is ever interpolated.

The effect layer is three tables deep (unit -> clause -> predicate), so an
`exists: effect` block compiles to nested EXISTS. Clause-level and
predicate-level fields may be mixed inside one block.
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
UNIT_ALIAS = "u"
CLAUSE_ALIAS = "cl"
PREDICATE_ALIAS = "p"
# Spelling alias: the three-level model still reads as "effect" in the DSL.
EFFECT_ALIAS = UNIT_ALIAS

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

_STORE_ALIAS = {"card": CARD_ALIAS, "clause": CLAUSE_ALIAS, "predicate": PREDICATE_ALIAS}


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
    return value


def _expand_category_value(value: str) -> list[str]:
    """A query for SPELL also matches objects stored as SPELL_TRAP."""
    if value == "SPELL":
        return ["SPELL", "SPELL_TRAP"]
    if value == "TRAP":
        return ["TRAP", "SPELL_TRAP"]
    return [value]


def _compile_numeric(spec, op: str, value, alias: str, out: CompiledQuery) -> str:
    """Compile a query against a stored {op, value} comparison.

    A predicate stores what the card says ("4星以下" -> `<= 4`). A query asks
    what the user wants ("能特召4星以下吗"). The two match when the ranges they
    describe can both be satisfied, so `<= 4` finds `<= 9` and `= 3`, but not
    `>= 8`. This is recall-oriented on purpose.
    """
    op_column, value_column = spec.numeric_pair
    target = int(value)
    if op == "lt":
        op, target = "lte", target - 1
    elif op == "gt":
        op, target = "gte", target + 1

    if op == "lte":
        parts = [
            f"{alias}.{op_column} IN ('<=', '<')",
            f"({alias}.{op_column} = '=' AND {alias}.{value_column} <= ?)",
            f"({alias}.{op_column} = '>=' AND {alias}.{value_column} <= ?)",
            f"({alias}.{op_column} = '>' AND {alias}.{value_column} < ?)",
        ]
        out.params.extend([target, target, target])
    elif op == "gte":
        parts = [
            f"{alias}.{op_column} IN ('>=', '>')",
            f"({alias}.{op_column} = '=' AND {alias}.{value_column} >= ?)",
            f"({alias}.{op_column} = '<=' AND {alias}.{value_column} >= ?)",
            f"({alias}.{op_column} = '<' AND {alias}.{value_column} > ?)",
        ]
        out.params.extend([target, target, target])
    else:
        raise QueryError(f"{spec.name} supports lt / lte / gt / gte only")

    return "(" + " OR ".join(parts) + ")"


# ------------------------------------------------------------ condition compile
def _compile_field(condition: FieldCondition, out: CompiledQuery, *, inside_exists: bool) -> str:
    spec = get_field(condition.field)
    if spec.table == "card" and inside_exists:
        raise QueryError(
            f"{spec.name} is a card field and cannot appear inside an 'exists: effect' block"
        )
    if spec.table == "effect" and not inside_exists:
        raise QueryError(
            f"{spec.name} is an effect field and must be inside an 'exists: effect' block"
        )

    validate_value(spec, condition.op, condition.value)
    assert_range_supported(spec, condition.op)

    alias = _STORE_ALIAS[spec.store]
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

    # Structured {op, value} comparisons
    if spec.numeric_pair is not None:
        return _compile_numeric(spec, op, condition.value, alias, out)

    column = f"{alias}.{spec.column}"
    values = _expand_category_value(condition.value) if isinstance(condition.value, str) else condition.value
    # SPELL_TRAP only expands for object_card_type.
    if spec.name != "effect.object_card_type" and isinstance(values, list):
        values = condition.value

    if op == "eq":
        if isinstance(values, list):
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


def _compile_condition(condition: Condition, out: CompiledQuery, *, inside_exists: bool) -> str:
    if isinstance(condition, FieldCondition):
        return _compile_field(condition, out, inside_exists=inside_exists)

    if isinstance(condition, BoolCondition):
        parts = [_compile_condition(child, out, inside_exists=inside_exists) for child in condition.children]
        if condition.kind == "not":
            return f"NOT ({parts[0]})"
        joiner = " AND " if condition.kind == "and" else " OR "
        return "(" + joiner.join(parts) + ")"

    if isinstance(condition, ExistsCondition):
        return _compile_exists(condition, out)

    raise QueryError(f"unsupported condition node {condition!r}")


def _compile_exists(condition: ExistsCondition, out: CompiledQuery) -> str:
    """Nested EXISTS over unit -> clause -> predicate.

    Measured on the 14.6k-card database: a flattened join takes ~68s while the
    nested form runs in ~0.1s, because the correlated `u.card_id = c.card_id`
    constraint is applied before any predicate filter.
    """
    inner = CompiledQuery(sql="")
    where = "1 = 1"
    if condition.where is not None:
        where = _compile_condition(condition.where, inner, inside_exists=True)
    out.params.extend(inner.params)
    return (
        f"EXISTS (SELECT 1 FROM effect_unit {UNIT_ALIAS} "
        f"WHERE {UNIT_ALIAS}.card_id = {CARD_ALIAS}.card_id "
        f"AND EXISTS (SELECT 1 FROM effect_clause {CLAUSE_ALIAS} "
        f"WHERE {CLAUSE_ALIAS}.unit_id = {UNIT_ALIAS}.unit_id "
        f"AND EXISTS (SELECT 1 FROM effect_predicate {PREDICATE_ALIAS} "
        f"WHERE {PREDICATE_ALIAS}.clause_id = {CLAUSE_ALIAS}.clause_id AND ({where}))))"
    )


# ------------------------------------------------------------------ public API
def _compile_where(query: Query, out: CompiledQuery) -> str:
    if query.where is None:
        return "1 = 1"
    return _compile_condition(query.where, out, inside_exists=False)


def compile_card_query(query: Query) -> CompiledQuery:
    """SQL that returns matching cards."""
    out = CompiledQuery(sql="")
    where = _compile_where(query, out)

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
    where = _compile_where(query, out)
    return CompiledQuery(
        sql=f"SELECT COUNT(*) AS total FROM card {CARD_ALIAS} WHERE {where}",
        params=out.params,
    )


def collect_effect_conditions(condition: Condition | None) -> list[ExistsCondition]:
    """Every `exists: effect` block in the query, in document order."""
    return [node for node in iter_conditions(condition) if isinstance(node, ExistsCondition)]


def compile_effect_match_query(query: Query, card_ids: list[int]) -> CompiledQuery:
    """SQL that returns the units of `card_ids` matching the effect blocks.

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
            clauses.append(_compile_condition(exists.where, inner, inside_exists=True))
        out.params.extend(inner.params)

    where = " AND ".join(clauses) if clauses else "1 = 1"
    join = "JOIN" if clauses else "LEFT JOIN"
    sql = (
        f"SELECT DISTINCT {UNIT_ALIAS}.unit_id, {UNIT_ALIAS}.card_id, "
        f"{UNIT_ALIAS}.unit_index, {UNIT_ALIAS}.scope, {UNIT_ALIAS}.kind, "
        f"{UNIT_ALIAS}.marker, {UNIT_ALIAS}.raw_text "
        f"FROM effect_unit {UNIT_ALIAS} "
        f"{join} effect_clause {CLAUSE_ALIAS} ON {CLAUSE_ALIAS}.unit_id = {UNIT_ALIAS}.unit_id "
        f"{join} effect_predicate {PREDICATE_ALIAS} ON {PREDICATE_ALIAS}.clause_id = {CLAUSE_ALIAS}.clause_id "
        f"WHERE {UNIT_ALIAS}.card_id IN ({placeholders}) AND ({where}) "
        f"ORDER BY {UNIT_ALIAS}.card_id, {UNIT_ALIAS}.unit_index"
    )
    return CompiledQuery(sql=sql, params=out.params)
