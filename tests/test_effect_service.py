import json
import sqlite3
from pathlib import Path

import pytest

from ygolookup.db.connection import connect
from ygolookup.db.migrations import apply_migrations
from ygolookup.db.repository import upsert_card
from ygolookup.effects.ontology import Action, EffectPart, Tri, Zone
from ygolookup.effects.schema import EffectPredicate, PARSER_VERSION, TargetConstraint
from ygolookup.effects.service import build_effects, build_parsed_effects, replace_card_effects
from ygolookup.effects.validator import (
    ValidationIssue,
    has_errors,
    validate_parsed_effect,
    validate_predicate,
)
from ygolookup.ingest.normalize import normalize_ygoprodeck_record

FIXTURE = Path(__file__).parent / "fixtures" / "ygoprodeck_sample.json"
SAMPLE = json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]


@pytest.fixture
def seeded(tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    apply_migrations(conn)
    ids = []
    for raw in SAMPLE:
        ids.append(upsert_card(conn, normalize_ygoprodeck_record(raw)))
    conn.commit()
    yield conn, ids
    conn.close()


# ------------------------------------------------------------------- validator
def test_valid_predicate_has_no_issues():
    predicate = EffectPredicate(
        part=EffectPart.RESOLUTION,
        action=Action.SPECIAL_SUMMON,
        source=Zone.EXTRA_DECK,
        destination=Zone.FIELD,
        target=TargetConstraint(race="DRAGON"),
        confidence=0.9,
    )
    assert validate_predicate(predicate) == []


def test_unknown_vocabulary_is_an_error():
    predicate = EffectPredicate(part=EffectPart.RESOLUTION, target=TargetConstraint(race="PIZZA"))
    issues = validate_predicate(predicate)
    assert has_errors(issues)
    assert "PIZZA" in str(issues[0])


def test_inverted_level_range_is_an_error():
    predicate = EffectPredicate(
        part=EffectPart.RESOLUTION, target=TargetConstraint(level_min=8, level_max=4)
    )
    assert has_errors(validate_predicate(predicate))


def test_unknown_action_with_high_confidence_is_only_a_warning():
    predicate = EffectPredicate(part=EffectPart.RESOLUTION, action=None, confidence=0.9)
    issues = validate_predicate(predicate)
    assert not has_errors(issues)
    assert any(i.level == "warning" for i in issues)


def test_special_summon_without_source_is_a_warning():
    predicate = EffectPredicate(part=EffectPart.RESOLUTION, action=Action.SPECIAL_SUMMON, confidence=0.7)
    assert any(i.level == "warning" for i in validate_predicate(predicate))


def test_confidence_out_of_range_is_an_error():
    predicate = EffectPredicate(part=EffectPart.RESOLUTION, confidence=1.5)
    assert has_errors(validate_predicate(predicate))


def test_empty_segment_is_an_error():
    from ygolookup.effects.ontology import EffectScope, SegmentMarker
    from ygolookup.effects.schema import EffectSegment, ParsedEffect

    parsed = ParsedEffect(
        segment=EffectSegment(
            index=0, scope=EffectScope.MAIN, marker=SegmentMarker.BLOCK, raw_text="   "
        )
    )
    assert has_errors(validate_parsed_effect(parsed))


# --------------------------------------------------------------------- service
def test_replace_card_effects_writes_rows(seeded):
    conn, ids = seeded
    card_id = ids[0]
    count = replace_card_effects(conn, card_id, "Banish 1 LIGHT monster from your GY; Special Summon 1 Dragon monster from your Deck.")
    conn.commit()

    assert count == 1
    effect = conn.execute("SELECT * FROM effect WHERE card_id = ?", (card_id,)).fetchone()
    assert effect["parser_version"] == PARSER_VERSION

    predicates = conn.execute(
        "SELECT * FROM effect_predicate WHERE effect_id = ? ORDER BY predicate_id",
        (effect["effect_id"],),
    ).fetchall()
    assert len(predicates) == 2
    assert predicates[0]["part"] == "COST"
    assert predicates[0]["action"] == "BANISH"
    assert predicates[0]["source_zone"] == "GRAVEYARD"
    assert predicates[1]["action"] == "SPECIAL_SUMMON"
    assert predicates[1]["target_race"] == "DRAGON"
    assert predicates[1]["action_known"] == 1


def test_unknown_action_stored_as_null_not_empty(seeded):
    conn, ids = seeded
    replace_card_effects(conn, ids[0], "This card's name becomes \"Blue-Eyes White Dragon\".")
    conn.commit()
    row = conn.execute(
        "SELECT action, action_known FROM effect_predicate ORDER BY predicate_id LIMIT 1"
    ).fetchone()
    assert row["action"] is None
    assert row["action_known"] == 0


def test_rebuild_is_idempotent(seeded):
    conn, ids = seeded
    build_effects(conn, card_ids=ids[:3])
    first = conn.execute("SELECT COUNT(*) FROM effect").fetchone()[0]
    build_effects(conn, card_ids=ids[:3])
    second = conn.execute("SELECT COUNT(*) FROM effect").fetchone()[0]
    assert first == second


def test_build_effects_for_all_cards(seeded):
    conn, ids = seeded
    result = build_effects(conn)
    assert result.cards == len(ids)
    assert result.effects > len(ids)  # most cards split into >1 segment
    assert result.predicates > 0
    assert not result.validation_errors


def test_build_effects_empty_card_text(seeded):
    conn, ids = seeded
    conn.execute("UPDATE card SET raw_text = '' WHERE card_id = ?", (ids[0],))
    conn.commit()
    result = build_effects(conn, card_ids=[ids[0]])
    assert result.effects == 0


def test_predicate_payload_json_roundtrip(seeded):
    conn, ids = seeded
    replace_card_effects(conn, ids[0], "Discard 1 card; draw 2 cards.")
    conn.commit()
    row = conn.execute("SELECT payload_json FROM effect_predicate LIMIT 1").fetchone()
    payload = json.loads(row["payload_json"])
    assert payload["part"] in {"COST", "RESOLUTION", "CONDITION", "RESTRICTION"}
    assert "target" in payload


def test_cascade_delete_removes_effects(seeded):
    conn, ids = seeded
    build_effects(conn, card_ids=[ids[0]])
    conn.commit()
    conn.execute("DELETE FROM card WHERE card_id = ?", (ids[0],))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM effect WHERE card_id = ?", (ids[0],)).fetchone()[0] == 0


def test_build_parsed_effects_keeps_raw_text():
    parsed = build_parsed_effects("Discard 1 card; draw 2 cards.")
    assert parsed[0].segment.raw_text == "Discard 1 card; draw 2 cards."
    assert all(p.once_per_turn in tuple(Tri) for e in parsed for p in e.predicates)
