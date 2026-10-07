"""Persist parsed effects.

Splitting + parsing are deterministic and cheap, so a rebuild is a normal
operation, not a migration. Re-running replaces all effects for the cards
processed and never touches `card.raw_text`.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from .parser import parse_segment
from .schema import EffectPredicate, ParsedEffect, PARSER_VERSION
from .splitter import split_effects
from .validator import ValidationIssue, validate_parsed_effect


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_parsed_effects(raw_text: str) -> list[ParsedEffect]:
    return [parse_segment(segment) for segment in split_effects(raw_text)]


def _predicate_row(predicate: EffectPredicate) -> tuple:
    target = predicate.target
    return (
        predicate.part.value,
        predicate.action.value if predicate.action else None,
        int(predicate.action is not None),
        predicate.source.value if predicate.source else None,
        predicate.destination.value if predicate.destination else None,
        target.count,
        target.card_category,
        target.race,
        target.attribute,
        target.archetype,
        target.name,
        target.level_min,
        target.level_max,
        target.rank,
        target.link_rating,
        target.atk_min,
        target.atk_max,
        target.tuner.value,
        predicate.once_per_turn.value,
        predicate.confidence,
        predicate.evidence,
        json.dumps(predicate.to_dict(), ensure_ascii=False, sort_keys=True),
    )


_PREDICATE_COLUMNS = """
    part, action, action_known, source_zone, destination_zone,
    target_count, target_card_category, target_race, target_attribute,
    target_archetype, target_name, target_level_min, target_level_max,
    target_rank, target_link_rating, target_atk_min, target_atk_max,
    target_tuner, once_per_turn, confidence, evidence, payload_json
"""


def replace_card_effects(conn: sqlite3.Connection, card_id: int, raw_text: str) -> int:
    """Drop and rebuild every effect for one card. Returns the effect count."""
    conn.execute("DELETE FROM effect WHERE card_id = ?", (card_id,))
    if not raw_text.strip():
        return 0

    parsed_at = datetime.now().isoformat(timespec="seconds")
    count = 0
    for parsed in build_parsed_effects(raw_text):
        cur = conn.execute(
            """
            INSERT INTO effect (card_id, effect_index, scope, marker, raw_text, text_sha256,
                                parser_version, parsed_at)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                card_id,
                parsed.segment.index,
                parsed.segment.scope.value,
                parsed.segment.marker.value,
                parsed.segment.raw_text,
                text_sha256(parsed.segment.raw_text),
                PARSER_VERSION,
                parsed_at,
            ),
        )
        effect_id = int(cur.lastrowid)
        conn.executemany(
            f"INSERT INTO effect_predicate (effect_id, {_PREDICATE_COLUMNS}) "
            f"VALUES (?, {', '.join('?' * 22)})",
            [(effect_id, *_predicate_row(p)) for p in parsed.predicates],
        )
        count += 1
    return count


@dataclass
class BuildResult:
    cards: int = 0
    effects: int = 0
    predicates: int = 0
    validation_errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "cards": self.cards,
            "effects": self.effects,
            "predicates": self.predicates,
            "validation_errors": self.validation_errors[:20],
            "validation_error_count": len(self.validation_errors),
        }


def build_effects(
    conn: sqlite3.Connection,
    *,
    card_ids: Iterable[int] | None = None,
    validate: bool = True,
    batch_size: int = 500,
) -> BuildResult:
    """Rebuild effects for every card (or a subset)."""
    sql = "SELECT card_id, raw_text FROM card"
    args: tuple = ()
    if card_ids is not None:
        card_ids = list(card_ids)
        if not card_ids:
            return BuildResult()
        placeholders = ",".join("?" * len(card_ids))
        sql += f" WHERE card_id IN ({placeholders})"
        args = tuple(card_ids)

    result = BuildResult()
    rows = conn.execute(sql, args).fetchall()

    for offset in range(0, len(rows), batch_size):
        batch = rows[offset : offset + batch_size]
        with conn:
            for row in batch:
                if validate:
                    for parsed in build_parsed_effects(row["raw_text"]):
                        for issue in validate_parsed_effect(parsed):
                            if issue.level == "error":
                                result.validation_errors.append(
                                    f"card {row['card_id']}: {issue.message}"
                                )
                result.effects += replace_card_effects(conn, row["card_id"], row["raw_text"])
                result.cards += 1

    result.predicates = int(conn.execute("SELECT COUNT(*) FROM effect_predicate").fetchone()[0])
    return result
