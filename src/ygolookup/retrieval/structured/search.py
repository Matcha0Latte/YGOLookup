"""Structured search — the authoritative retrieval path.

Correctness over recall: a card is returned only when the database actually
supports the claim. Every hit carries the effect text that produced the match so
the caller (or the agent) can verify against the original wording.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from ...db.repository import card_archetypes
from ...query.dsl import Query
from .compiler import compile_card_query, compile_count_query, compile_effect_match_query


@dataclass
class MatchedEffect:
    """An effect unit that produced the match.

    One unit = one numbered effect (①②③) or one global restriction. Its
    predicates are collected across all of its clauses, so the caller sees the
    whole effect rather than the single clause that happened to match.
    """

    unit_id: int
    index: int
    kind: str
    scope: str
    marker: str
    raw_text: str
    predicates: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "effect_id": self.unit_id,
            "index": self.index,
            "kind": self.kind,
            "scope": self.scope,
            "marker": self.marker,
            "raw_text": self.raw_text,
            "predicates": self.predicates,
        }


@dataclass
class SearchHit:
    card_id: int
    name: str
    card_category: str
    sub_category: str | None
    race: str | None
    attribute: str | None
    level_rank: int | None
    link_rating: int | None
    atk: int | None
    defense: int | None
    archetypes: list[str] = field(default_factory=list)
    matched_effects: list[MatchedEffect] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "card_id": self.card_id,
            "name": self.name,
            "card_category": self.card_category,
            "sub_category": self.sub_category,
            "race": self.race,
            "attribute": self.attribute,
            "level_rank": self.level_rank,
            "link_rating": self.link_rating,
            "atk": self.atk,
            "def": self.defense,
            "archetypes": self.archetypes,
        }
        if self.matched_effects:
            payload["matched_effects"] = [e.to_dict() for e in self.matched_effects]
        return payload


@dataclass
class SearchResult:
    hits: list[SearchHit]
    total: int
    query: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "returned": len(self.hits),
            "query": self.query,
            "hits": [hit.to_dict() for hit in self.hits],
        }


class StructuredSearcher:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def count(self, query: Query) -> int:
        compiled = compile_count_query(query)
        return int(self.conn.execute(compiled.sql, compiled.params).fetchone()[0])

    def search(self, query: Query, *, limit: int | None = None, with_effects: bool = True) -> SearchResult:
        effective = Query(
            where=query.where,
            select=query.select,
            limit=limit if limit is not None else query.limit,
            offset=query.offset,
            min_confidence=query.min_confidence,
        )
        compiled = compile_card_query(effective)
        rows = self.conn.execute(compiled.sql, compiled.params).fetchall()
        total = self.count(query)

        hits = [
            SearchHit(
                card_id=int(row["card_id"]),
                name=row["canonical_name"],
                card_category=row["card_category"],
                sub_category=row["sub_category"],
                race=row["race"],
                attribute=row["attribute"],
                level_rank=row["level_rank"],
                link_rating=row["link_rating"],
                atk=row["atk"],
                defense=row["def"],
                archetypes=card_archetypes(self.conn, int(row["card_id"])),
            )
            for row in rows
        ]

        if with_effects and hits:
            self._attach_effects(hits, query)

        return SearchResult(hits=hits, total=total, query=query.to_dict())

    def _attach_effects(self, hits: list[SearchHit], query: Query) -> None:
        card_ids = [hit.card_id for hit in hits]
        compiled = compile_effect_match_query(query, card_ids)
        if not compiled.sql:
            return

        by_card: dict[int, list[MatchedEffect]] = {card_id: [] for card_id in card_ids}
        for row in self.conn.execute(compiled.sql, compiled.params):
            by_card[int(row["card_id"])].append(
                MatchedEffect(
                    unit_id=int(row["unit_id"]),
                    index=int(row["unit_index"]),
                    kind=row["kind"],
                    scope=row["scope"],
                    marker=row["marker"],
                    raw_text=row["raw_text"],
                )
            )

        if any(effects for effects in by_card.values()):
            self._attach_predicates(by_card)

        for hit in hits:
            hit.matched_effects = by_card.get(hit.card_id, [])

    def _attach_predicates(self, by_card: dict[int, list[MatchedEffect]]) -> None:
        unit_ids = [e.unit_id for effects in by_card.values() for e in effects]
        if not unit_ids:
            return
        placeholders = ",".join("?" for _ in unit_ids)
        rows = self.conn.execute(
            f"SELECT cl.unit_id AS unit_id, p.payload_json AS payload_json "
            f"FROM effect_clause cl JOIN effect_predicate p ON p.clause_id = cl.clause_id "
            f"WHERE cl.unit_id IN ({placeholders}) "
            f"ORDER BY cl.unit_id, cl.clause_index, p.pred_index",
            unit_ids,
        )
        payloads: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            payloads.setdefault(int(row["unit_id"]), []).append(json.loads(row["payload_json"]))
        for effects in by_card.values():
            for effect in effects:
                effect.predicates = payloads.get(effect.unit_id, [])
