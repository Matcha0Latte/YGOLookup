"""Tool surface for an LLM orchestrator.

Each tool is a plain function with a JSON input schema and a JSON-serializable
output. Nothing here contains database business logic — that lives in
`retrieval/` — and nothing here depends on a specific LLM.

Tools still to be implemented (interfaces are defined, bodies raise
`NotImplementedError`): `fulltext_search`, `semantic_search`, `search_rulings`.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..db.repository import (
    card_archetypes,
    card_external_ids,
    card_flags,
    card_names,
    find_card_by_name,
    get_card,
)
from ..query.dsl import Query, QueryError
from ..query.planner import plan
from ..retrieval.structured.search import StructuredSearcher

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "get_card": {
        "description": "Fetch one card by name (or id) including its raw effect text.",
        "input": {"name": "string", "card_id": "int (optional)"},
        "output": "card object",
    },
    "search_cards": {
        "description": "Structured search over card fields and effect predicates.",
        "input": {"query": "Query object (see docs/query-dsl.md)", "limit": "int"},
        "output": "{total, returned, hits[]}",
    },
    "search_effects": {
        "description": "Return the individual effects that match a query, not the cards.",
        "input": {"query": "Query object", "limit": "int"},
        "output": "[{card, effect}]",
    },
    "plan_query": {
        "description": "Turn a natural language question into a Query AST.",
        "input": {"text": "string"},
        "output": "{query, matched, unmatched}",
    },
    "fulltext_search": {
        "description": "FTS5 keyword search over card names and effect text. (planned)",
        "input": {"text": "string", "limit": "int"},
        "output": "[{card_id, name, snippet}]",
    },
    "semantic_search": {
        "description": "Vector recall over effect text. (planned)",
        "input": {"text": "string", "limit": "int"},
        "output": "[{effect_id, score}]",
    },
}


class ToolError(RuntimeError):
    pass


def _searcher(conn: sqlite3.Connection) -> StructuredSearcher:
    return StructuredSearcher(conn)


def _coerce_query(payload: dict[str, Any] | Query | None) -> Query:
    if payload is None:
        return Query()
    if isinstance(payload, Query):
        return payload
    if not isinstance(payload, dict):
        raise ToolError("query must be an object")
    return Query.from_dict(payload)


def get_card_tool(conn: sqlite3.Connection, *, name: str | None = None, card_id: int | None = None) -> dict:
    if card_id is not None:
        row = get_card(conn, card_id)
    elif name:
        row = find_card_by_name(conn, name, exact=False)
    else:
        raise ToolError("provide either name or card_id")
    if row is None:
        raise ToolError(f"card not found: {name or card_id}")

    card_id = int(row["card_id"])
    return {
        "card_id": card_id,
        "name": row["canonical_name"],
        "card_category": row["card_category"],
        "sub_category": row["sub_category"],
        "race": row["race"],
        "attribute": row["attribute"],
        "level_rank": row["level_rank"],
        "link_rating": row["link_rating"],
        "pendulum_scale": row["pendulum_scale"],
        "atk": row["atk"],
        "def": row["def"],
        "names": card_names(conn, card_id),
        "archetypes": card_archetypes(conn, card_id),
        "flags": card_flags(conn, card_id),
        "external_ids": [{"source": s, "value": v} for s, v in card_external_ids(conn, card_id)],
        "raw_text": row["raw_text"],
    }


def search_cards_tool(
    conn: sqlite3.Connection, *, query: dict[str, Any] | Query | None = None, limit: int | None = None
) -> dict:
    try:
        parsed = _coerce_query(query)
    except QueryError as exc:
        raise ToolError(str(exc)) from exc
    result = _searcher(conn).search(parsed, limit=limit)
    return result.to_dict()


def search_effects_tool(
    conn: sqlite3.Connection, *, query: dict[str, Any] | Query | None = None, limit: int = 50
) -> list[dict]:
    result = search_cards_tool(conn, query=query, limit=limit)
    out: list[dict] = []
    for hit in result["hits"]:
        for effect in hit.get("matched_effects", []):
            out.append(
                {
                    "card_id": hit["card_id"],
                    "card_name": hit["name"],
                    "effect_id": effect["effect_id"],
                    "scope": effect["scope"],
                    "raw_text": effect["raw_text"],
                    "predicates": effect["predicates"],
                }
            )
    return out


def plan_query_tool(conn: sqlite3.Connection, *, text: str) -> dict:
    return plan(text).to_dict()


def fulltext_search_tool(conn: sqlite3.Connection, *, text: str, limit: int = 20) -> list[dict]:
    raise NotImplementedError("FTS5 retrieval is planned for the next phase")


def semantic_search_tool(conn: sqlite3.Connection, *, text: str, limit: int = 20) -> list[dict]:
    raise NotImplementedError("semantic retrieval is planned for the next phase")
