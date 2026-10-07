"""Parse Chinese card text and persist the result.

Pipeline (all deterministic in v1):

    card_text (zh)  ->  EffectUnit  ->  Clause  ->  Predicate  ->  SQL

Splitting and parsing are deterministic and cheap, so rebuilding is a normal
operation rather than a migration. A rebuild replaces every unit for the cards
processed and never touches `card_text.text`.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from .extractors import EffectExtractor, NullExtractor
from .predicates import ParsedUnit, Predicate, parse_unit
from .units import split_card_text
from .validator import ValidationIssue, validate_parsed_units

PARSER_VERSION = "zh-rule-1"

# lang / kind keys used in `card_text`.
ZH_EFFECT = ("zh", "effect")
ZH_PENDULUM = ("zh", "pendulum")
ZH_TYPES = ("zh", "types")


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_parsed_units(
    *,
    desc: str,
    pdesc: str = "",
    pendulum: bool = False,
    extractor: EffectExtractor | None = None,
) -> list[ParsedUnit]:
    """Card text -> parsed units. The LLM slot runs only when the rule layer
    leaves a unit unresolved."""
    extractor = extractor or NullExtractor()
    units = split_card_text(desc=desc, pdesc=pdesc, pendulum=pendulum)
    parsed: list[ParsedUnit] = []

    for unit in units:
        result = parse_unit(unit)
        if result.status.value == "UNRESOLVED" and unit.kind.value != "MATERIAL":
            fallback = extractor.extract(unit)
            if fallback is not None:
                result = fallback
        parsed.append(result)
    return parsed


def _predicate_row(predicate: Predicate) -> tuple:
    obj = predicate.object

    def num(name: str) -> tuple:
        constraint = getattr(obj, name)
        return (constraint.op, constraint.value) if constraint else (None, None)

    level_op, level_value = num("level")
    rank_op, rank_value = num("rank")
    link_op, link_value = num("link_rating")
    atk_op, atk_value = num("atk")
    def_op, def_value = num("defense")

    return (
        predicate.index,
        predicate.subject.value,
        predicate.action.value if predicate.action else None,
        int(predicate.action_known),
        predicate.source_zone.value if predicate.source_zone else None,
        predicate.destination_zone.value if predicate.destination_zone else None,
        obj.count,
        obj.count_op,
        obj.card_type,
        obj.race,
        obj.attribute,
        obj.archetype,
        obj.name,
        level_op,
        level_value,
        rank_op,
        rank_value,
        link_op,
        link_value,
        atk_op,
        atk_value,
        def_op,
        def_value,
        json.dumps(obj.tags, ensure_ascii=False) if obj.tags else None,
        predicate.result_ref,
        predicate.object_ref,
        json.dumps(predicate.modifiers, ensure_ascii=False, sort_keys=True),
        predicate.confidence,
        predicate.extracted_by.value,
        predicate.source_text,
        json.dumps(predicate.to_dict(), ensure_ascii=False, sort_keys=True),
    )


_PREDICATE_COLUMNS = """
    pred_index, subject, action, action_known, source_zone, destination_zone,
    object_count, object_count_op, object_card_type, object_race, object_attribute,
    object_archetype, object_name, object_level_op, object_level_value,
    object_rank_op, object_rank_value, object_link_op, object_link_value,
    object_atk_op, object_atk_value, object_def_op, object_def_value,
    object_tags, result_ref, object_ref, modifiers_json,
    confidence, extracted_by, source_text, payload_json
"""


def replace_card_effects(
    conn: sqlite3.Connection,
    card_id: int,
    *,
    desc: str,
    pdesc: str = "",
    pendulum: bool = False,
    extractor: EffectExtractor | None = None,
) -> int:
    """Drop and rebuild every effect unit for one card. Returns the unit count."""
    conn.execute("DELETE FROM effect_unit WHERE card_id = ?", (card_id,))
    if not (desc or "").strip():
        return 0

    parsed_at = datetime.now().isoformat(timespec="seconds")
    count = 0
    for parsed in build_parsed_units(
        desc=desc, pdesc=pdesc, pendulum=pendulum, extractor=extractor
    ):
        unit = parsed.unit
        cur = conn.execute(
            """
            INSERT INTO effect_unit (card_id, unit_index, scope, kind, marker, sub_index,
                                     raw_text, text_sha256, lang, parse_status,
                                     parser_version, parsed_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                card_id,
                unit.index,
                unit.scope.value,
                unit.kind.value,
                unit.marker,
                unit.sub_index,
                unit.raw_text,
                text_sha256(unit.raw_text),
                "zh",
                parsed.status.value,
                PARSER_VERSION,
                parsed_at,
            ),
        )
        unit_id = int(cur.lastrowid)

        for parsed_clause in parsed.clauses:
            clause = parsed_clause.clause
            cur = conn.execute(
                """
                INSERT INTO effect_clause (unit_id, clause_index, role, raw_text,
                                           start_offset, end_offset, once_per_turn,
                                           confidence, extracted_by)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    unit_id,
                    clause.index,
                    clause.role.value,
                    clause.raw_text,
                    clause.start,
                    clause.end,
                    clause.once_per_turn.value,
                    clause.confidence,
                    clause.extracted_by.value,
                ),
            )
            clause_id = int(cur.lastrowid)
            conn.executemany(
                f"INSERT INTO effect_predicate (clause_id, {_PREDICATE_COLUMNS}) "
                f"VALUES (?, {', '.join('?' * 31)})",
                [(clause_id, *_predicate_row(p)) for p in parsed_clause.predicates],
            )
        count += 1
    return count


@dataclass
class BuildResult:
    cards: int = 0
    units: int = 0
    clauses: int = 0
    predicates: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    validation_errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "cards": self.cards,
            "units": self.units,
            "clauses": self.clauses,
            "predicates": self.predicates,
            "status_counts": self.status_counts,
            "validation_errors": self.validation_errors[:20],
            "validation_error_count": len(self.validation_errors),
        }


def _load_text_rows(conn: sqlite3.Connection, card_ids: Iterable[int] | None) -> list[sqlite3.Row]:
    sql = """
        SELECT c.card_id,
               MAX(CASE WHEN t.kind = 'effect'   THEN t.text END) AS desc,
               MAX(CASE WHEN t.kind = 'pendulum' THEN t.text END) AS pdesc
        FROM card c
        LEFT JOIN card_text t ON t.card_id = c.card_id AND t.lang = 'zh'
        WHERE t.text IS NOT NULL
    """
    args: tuple = ()
    if card_ids is not None:
        card_ids = list(card_ids)
        if not card_ids:
            return []
        placeholders = ",".join("?" * len(card_ids))
        sql += f" AND c.card_id IN ({placeholders})"
        args = tuple(card_ids)
    sql += " GROUP BY c.card_id ORDER BY c.card_id"
    return conn.execute(sql, args).fetchall()


def build_effects(
    conn: sqlite3.Connection,
    *,
    card_ids: Iterable[int] | None = None,
    validate: bool = True,
    extractor: EffectExtractor | None = None,
    batch_size: int = 500,
) -> BuildResult:
    """Rebuild effects for every card that has Chinese text."""
    result = BuildResult()
    rows = _load_text_rows(conn, card_ids)

    for offset in range(0, len(rows), batch_size):
        batch = rows[offset : offset + batch_size]
        with conn:
            for row in batch:
                desc = row["desc"] or ""
                pdesc = row["pdesc"] or ""
                if not desc.strip():
                    continue

                if validate:
                    for parsed in build_parsed_units(
                        desc=desc, pdesc=pdesc, pendulum=bool(pdesc.strip()), extractor=extractor
                    ):
                        for issue in validate_unit_issues(parsed):
                            if issue.level == "error":
                                result.validation_errors.append(
                                    f"card {row['card_id']}: {issue}"
                                )

                result.units += replace_card_effects(
                    conn,
                    row["card_id"],
                    desc=desc,
                    pdesc=pdesc,
                    pendulum=bool(pdesc.strip()),
                    extractor=extractor,
                )
                result.cards += 1

    result.clauses = int(conn.execute("SELECT COUNT(*) FROM effect_clause").fetchone()[0])
    result.predicates = int(conn.execute("SELECT COUNT(*) FROM effect_predicate").fetchone()[0])
    result.status_counts = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT parse_status, COUNT(*) FROM effect_unit GROUP BY parse_status ORDER BY 2 DESC"
        )
    }
    return result


def validate_unit_issues(parsed: ParsedUnit) -> list[ValidationIssue]:
    from .validator import validate_unit

    return validate_unit(parsed)


__all__ = [
    "PARSER_VERSION",
    "BuildResult",
    "build_parsed_units",
    "build_effects",
    "replace_card_effects",
    "text_sha256",
    "validate_parsed_units",
]
