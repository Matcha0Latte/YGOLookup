"""Structured retrieval tests against a small, hand-checked card pool."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ygolookup.db.connection import connect
from ygolookup.db.migrations import apply_migrations
from ygolookup.effects.service import build_effects
from ygolookup.ingest.normalize import normalize_ygoprodeck_record
from ygolookup.ingest.pipeline import ingest_records
from ygolookup.query.dsl import FieldCondition, Query, QueryError, and_, not_, or_
from ygolookup.query.parser import parse_filters
from ygolookup.query.dsl import ExistsCondition
from ygolookup.retrieval.structured.search import StructuredSearcher

from conftest import load_fixture_pool


@pytest.fixture(scope="module")
def conn():
    connection = connect(Path(__file__).parent / ".tmp" / "search.db")
    apply_migrations(connection)
    load_fixture_pool(connection)
    build_effects(connection)
    connection.commit()
    yield connection
    connection.close()


def search(conn, query, **kwargs):
    return StructuredSearcher(conn).search(query, **kwargs)


def names(result) -> list[str]:
    return [hit.name for hit in result.hits]


def hits(conn, *conditions, **kwargs):
    return search(conn, Query(where=and_(*conditions)), **kwargs)


# ------------------------------------------------------------- card properties
def test_race_filter(conn):
    result = hits(conn, FieldCondition("card.race", "eq", "DRAGON"))
    assert set(names(result)) == {"Testcase Dragon Alpha", "Testcase Big Dragon"}


def test_attribute_and_level_range(conn):
    result = hits(
        conn,
        FieldCondition("card.attribute", "eq", "DARK"),
        FieldCondition("card.level_rank", "lte", 4),
    )
    assert set(names(result)) == {"Testcase Dragon Alpha", "Testcase Fiend Beta"}


def test_level_greater_than(conn):
    result = hits(conn, FieldCondition("card.level_rank", "gte", 8))
    assert names(result) == ["Testcase Big Dragon"]


def test_card_category_filter(conn):
    assert names(hits(conn, FieldCondition("card.card_category", "eq", "SPELL"))) == [
        "Testcase Mystic Spell"
    ]


def test_archetype_filter_uses_join(conn):
    assert names(hits(conn, FieldCondition("card.archetype", "eq", "testcase"))) == [
        "Testcase Fiend Beta"
    ]


def test_flag_filter(conn):
    assert names(hits(conn, FieldCondition("card.flag", "eq", "TUNER"))) == ["Testcase Tuner Gamma"]


def test_name_contains(conn):
    result = hits(conn, FieldCondition("card.name", "contains", "Big"))
    assert names(result) == ["Testcase Big Dragon"]


# ------------------------------------------------------------------- effects
def _exists(*conditions):
    return ExistsCondition(target="effect", where=and_(*conditions))


def test_effect_action_filter(conn):
    result = hits(conn, _exists(FieldCondition("effect.action", "eq", "SPECIAL_SUMMON")))
    assert set(names(result)) == {"Testcase Dragon Alpha", "Testcase Big Dragon"}


def test_special_summon_from_extra_deck_targeting_dragon(conn):
    result = hits(
        conn,
        _exists(
            FieldCondition("effect.action", "eq", "SPECIAL_SUMMON"),
            FieldCondition("effect.source_zone", "eq", "EXTRA_DECK"),
            FieldCondition("effect.object_race", "eq", "DRAGON"),
        ),
    )
    assert names(result) == ["Testcase Dragon Alpha"]


def test_banish_from_graveyard_as_cost(conn):
    result = hits(
        conn,
        _exists(
            FieldCondition("clause.role", "eq", "COST"),
            FieldCondition("effect.action", "eq", "BANISH"),
            FieldCondition("effect.source_zone", "eq", "GRAVEYARD"),
        ),
    )
    assert set(names(result)) == {"Testcase Dragon Alpha", "Testcase Grave Tender"}


def test_cost_and_resolution_are_distinguishable(conn):
    """Banishing from the GY as a COST must not match a banish at resolution."""
    as_cost = hits(
        conn,
        _exists(
            FieldCondition("clause.role", "eq", "COST"),
            FieldCondition("effect.action", "eq", "BANISH"),
        ),
    )
    as_resolution = hits(
        conn,
        _exists(
            FieldCondition("clause.role", "eq", "RESOLUTION"),
            FieldCondition("effect.action", "eq", "BANISH"),
        ),
    )
    assert set(names(as_cost)).isdisjoint(names(as_resolution))


def test_virtual_level_range_on_target(conn):
    """'4星以下' is stored as {op: '<=', value: 4} and must be found by lte."""
    result = hits(conn, _exists(FieldCondition("effect.object_level", "lte", 4)))
    assert "Testcase Big Dragon" in names(result)


def test_spell_trap_category_is_stored_as_one_token(conn):
    result = hits(
        conn, _exists(FieldCondition("effect.object_card_type", "eq", "SPELL_TRAP"))
    )
    assert names(result) == ["Testcase Mystic Spell"]


def test_querying_spell_also_matches_spell_trap(conn):
    """'Target 1 Spell/Trap' is an effect that targets Spells."""
    result = hits(conn, _exists(FieldCondition("effect.object_card_type", "eq", "SPELL")))
    assert names(result) == ["Testcase Mystic Spell"]


def test_destination_zone(conn):
    result = hits(
        conn,
        _exists(
            FieldCondition("effect.action", "eq", "SEARCH"),
            FieldCondition("effect.destination_zone", "eq", "HAND"),
        ),
    )
    assert set(names(result)) == {"Testcase Fiend Beta", "Testcase Grave Tender"}


def test_once_per_turn_tri_state(conn):
    result = hits(conn, _exists(FieldCondition("clause.once_per_turn", "eq", "TRUE")))
    assert names(result) == []  # no fixture card says "Once per turn"


# ---------------------------------------------------------- boolean composition
def test_or_composition(conn):
    result = search(
        conn,
        Query(
            where=or_(
                FieldCondition("card.race", "eq", "FIEND"),
                FieldCondition("card.race", "eq", "SPELLCASTER"),
            )
        ),
    )
    assert set(names(result)) == {"Testcase Fiend Beta", "Testcase Grave Tender"}


def test_not_composition(conn):
    result = search(conn, Query(where=not_(FieldCondition("card.card_category", "eq", "MONSTER"))))
    assert set(names(result)) == {"Testcase Mystic Spell", "Testcase Counter Trap"}


def test_card_and_effect_combined(conn):
    result = hits(
        conn,
        FieldCondition("card.race", "eq", "DRAGON"),
        _exists(FieldCondition("effect.action", "eq", "SPECIAL_SUMMON")),
    )
    assert set(names(result)) == {"Testcase Dragon Alpha", "Testcase Big Dragon"}


def test_count_matches_hits_total(conn):
    query = Query(where=FieldCondition("card.race", "eq", "DRAGON"))
    assert StructuredSearcher(conn).count(query) == 2


# --------------------------------------------------------------- result shape
def test_hits_carry_matched_effect_text(conn):
    result = hits(
        conn,
        _exists(
            FieldCondition("effect.action", "eq", "SPECIAL_SUMMON"),
            FieldCondition("effect.source_zone", "eq", "EXTRA_DECK"),
        ),
    )
    effect = result.hits[0].matched_effects[0]
    assert "额外卡组" in effect.raw_text
    assert effect.predicates, "predicates are needed to verify the match"


def test_result_is_json_serializable(conn):
    payload = hits(conn, FieldCondition("card.race", "eq", "DRAGON")).to_dict()
    assert json.dumps(payload, ensure_ascii=False)


def test_limit_is_respected(conn):
    result = search(conn, Query(where=FieldCondition("card.card_category", "eq", "MONSTER")), limit=2)
    assert len(result.hits) == 2
    assert result.total == 5


# ------------------------------------------------------------------- errors
def test_effect_field_outside_exists_is_rejected(conn):
    with pytest.raises(QueryError, match="must be inside an 'exists: effect' block"):
        search(conn, Query(where=FieldCondition("effect.action", "eq", "DRAW")))


def test_card_field_inside_exists_is_rejected(conn):
    with pytest.raises(QueryError, match="cannot appear inside an 'exists: effect' block"):
        search(
            conn,
            Query(where=_exists(FieldCondition("card.race", "eq", "DRAGON"))),
        )


# ------------------------------------------------------------ filter shorthand
def test_parse_filters_wraps_effect_fields(conn):
    query = parse_filters(["race=DRAGON", "effect.action=SPECIAL_SUMMON"])
    assert set(names(search(conn, query))) == {"Testcase Dragon Alpha", "Testcase Big Dragon"}


def test_parse_filters_aliases(conn):
    query = parse_filters(["level<=3"])
    assert set(names(search(conn, query))) == {"Testcase Fiend Beta", "Testcase Grave Tender"}


def test_parse_filters_bad_expression():
    with pytest.raises(QueryError):
        parse_filters(["race DRAGON"])
