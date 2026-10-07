"""Query AST — storage-agnostic, JSON-serializable.

Natural language must never be turned straight into SQL. It becomes a `Query`,
and a *backend* (see `retrieval/structured`) turns that into SQL. That split is
what lets the same query be answered by structured search, FTS and semantic
search without rewriting the planner.

Shape:

    {
      "select": "card",
      "limit": 50,
      "min_confidence": 0.0,
      "where": {
        "and": [
          {"field": "card.race", "op": "eq", "value": "DRAGON"},
          {"field": "card.level_rank", "op": "lte", "value": 4},
          {"exists": "effect", "where": {
            "and": [
              {"field": "effect.part", "op": "eq", "value": "RESOLUTION"},
              {"field": "effect.action", "op": "eq", "value": "SPECIAL_SUMMON"},
              {"field": "effect.source_zone", "op": "eq", "value": "EXTRA_DECK"},
              {"field": "effect.target_race", "op": "eq", "value": "DRAGON"}
            ]
          }}
        ]
      }
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

OPS = frozenset({"eq", "ne", "in", "nin", "lt", "lte", "gt", "gte", "contains"})
RANGE_OPS = frozenset({"lt", "lte", "gt", "gte"})


class QueryError(ValueError):
    pass


@dataclass
class FieldCondition:
    field: str
    op: str
    value: Any

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "op": self.op, "value": self.value}


@dataclass
class ExistsCondition:
    """'the card has at least one effect satisfying this sub-query'."""

    target: str  # currently only "effect"
    where: "Condition | None" = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"exists": self.target}
        if self.where is not None:
            payload["where"] = self.where.to_dict()
        return payload


@dataclass
class BoolCondition:
    kind: str  # "and" | "or" | "not"
    children: list["Condition"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        if self.kind == "not":
            return {"not": self.children[0].to_dict()}
        return {self.kind: [child.to_dict() for child in self.children]}


Condition = FieldCondition | ExistsCondition | BoolCondition


def parse_condition(node: dict[str, Any]) -> Condition:
    if not isinstance(node, dict):
        raise QueryError(f"condition must be an object, got {type(node).__name__}")
    if not node:
        raise QueryError("empty condition object")

    keys = set(node)
    if "field" in keys:
        missing = {"op", "value"} - keys
        if missing:
            raise QueryError(f"field condition missing {sorted(missing)}")
        op = node["op"]
        if op not in OPS:
            raise QueryError(f"unsupported op {op!r}; allowed: {sorted(OPS)}")
        if op in ("in", "nin") and not isinstance(node["value"], list):
            raise QueryError(f"op {op!r} requires a list value")
        return FieldCondition(field=str(node["field"]), op=op, value=node["value"])

    if "exists" in keys:
        target = str(node["exists"])
        if target != "effect":
            raise QueryError(f"unsupported exists target {target!r}")
        where = node.get("where")
        return ExistsCondition(
            target=target, where=parse_condition(where) if where is not None else None
        )

    if "and" in keys or "or" in keys:
        kind = "and" if "and" in keys else "or"
        children = node[kind]
        if not isinstance(children, list) or not children:
            raise QueryError(f"{kind!r} requires a non-empty list")
        return BoolCondition(kind=kind, children=[parse_condition(c) for c in children])

    if "not" in keys:
        return BoolCondition(kind="not", children=[parse_condition(node["not"])])

    raise QueryError(f"unrecognized condition: {sorted(keys)}")


@dataclass
class Query:
    where: Condition | None = None
    select: str = "card"
    limit: int = 50
    offset: int = 0
    min_confidence: float = 0.0

    def __post_init__(self) -> None:
        if self.select != "card":
            raise QueryError(f"unsupported select {self.select!r}")
        if self.limit < 0:
            raise QueryError("limit must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "select": self.select,
            "limit": self.limit,
            "offset": self.offset,
            "min_confidence": self.min_confidence,
        }
        if self.where is not None:
            payload["where"] = self.where.to_dict()
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Query":
        if not isinstance(data, dict):
            raise QueryError("query must be an object")
        where = data.get("where")
        return cls(
            where=parse_condition(where) if where is not None else None,
            select=data.get("select", "card"),
            limit=int(data.get("limit", 50)),
            offset=int(data.get("offset", 0)),
            min_confidence=float(data.get("min_confidence", 0.0)),
        )


# ------------------------------------------------------------------ builders
def and_(*children: Condition) -> BoolCondition:
    return BoolCondition(kind="and", children=list(children))


def or_(*children: Condition) -> BoolCondition:
    return BoolCondition(kind="or", children=list(children))


def not_(child: Condition) -> BoolCondition:
    return BoolCondition(kind="not", children=[child])


def card_eq(field_name: str, value: Any) -> FieldCondition:
    return FieldCondition(field=f"card.{field_name}", op="eq", value=value)


def effect_eq(field_name: str, value: Any, *, part: str | None = None) -> ExistsCondition:
    children: list[Condition] = [FieldCondition(field=f"effect.{field_name}", op="eq", value=value)]
    if part:
        children.insert(0, FieldCondition(field="effect.part", op="eq", value=part))
    return ExistsCondition(target="effect", where=and_(*children))


def iter_conditions(condition: Condition | None):
    """Depth-first walk over every condition node."""
    if condition is None:
        return
    yield condition
    if isinstance(condition, BoolCondition):
        for child in condition.children:
            yield from iter_conditions(child)
    elif isinstance(condition, ExistsCondition):
        yield from iter_conditions(condition.where)
