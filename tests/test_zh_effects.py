"""Simplified-Chinese OCG effect regression tests.

Every case in `tests/fixtures/zh_effects.json` is real card wording with a
hand-checked expectation. Chinese is the **source language**; the English enums
in `ygolookup.effects.ontology` are only the machine protocol that gets stored.

The cases below are the ones that broke the previous English parser or that the
spec calls out explicitly:

    basic attribute restriction / SS from deck / SS from extra deck /
    GY banish as COST / CONDITION vs COST / multiple RESOLUTION /
    multi-effect card / global restriction / simple reference / UNKNOWN
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import fields
from pathlib import Path

import pytest

from ygolookup.db.connection import connect
from ygolookup.db.migrations import apply_migrations
from ygolookup.effects.extractors import LlmExtractor, NullExtractor, get_extractor
from ygolookup.effects.lexicon import ACTION_LEXICON, COST_ACTIONS
from ygolookup.effects.ontology import (
    Action,
    ClauseRole,
    ExtractedBy,
    ParseStatus,
    UnitKind,
    Zone,
)
from ygolookup.effects.predicates import Predicate, parse_unit
from ygolookup.effects.selector import CardSelector, NumericConstraint
from ygolookup.effects.service import PARSER_VERSION, build_effects, build_parsed_units
from ygolookup.effects.units import split_units
from ygolookup.effects.validator import has_errors, validate_parsed_units

CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "zh_effects.json").read_text(encoding="utf-8")
)["cases"]
BY_CASE = {case["case"]: case for case in CASES}


# ------------------------------------------------------------------- helpers
def units_of(name: str):
    return build_parsed_units(desc=BY_CASE[name]["zh_desc"])


def flat(name: str) -> list[tuple[ClauseRole, Predicate]]:
    """(role, predicate) pairs of one case, in document order."""
    return [
        (parsed_clause.clause.role, predicate)
        for parsed in units_of(name)
        for parsed_clause in parsed.clauses
        for predicate in parsed_clause.predicates
    ]


def one(name: str) -> Predicate:
    pairs = flat(name)
    assert len(pairs) == 1, f"expected one predicate, got {len(pairs)}"
    return pairs[0][1]


def role_of(name: str, role: ClauseRole) -> Predicate:
    for found, predicate in flat(name):
        if found is role:
            return predicate
    raise AssertionError(f"no {role.value} clause in {name!r}")


def roles_of(name: str) -> list[str]:
    return [
        parsed_clause.clause.role.value
        for parsed in units_of(name)
        for parsed_clause in parsed.clauses
    ]


# ---------------------------------------------------------- fixture integrity
def test_every_case_is_exercised():
    """Guard against a fixture entry nobody asserts on."""
    covered = {name[len("test_") :] for name in globals() if name.startswith("test_")}
    assert covered >= set(BY_CASE), sorted(set(BY_CASE) - covered)


def test_fixture_has_all_required_cases():
    assert set(BY_CASE) == {
        "basic_attribute_restriction",
        "special_summon_from_deck",
        "special_summon_from_extra_deck",
        "banish_from_graveyard_as_cost",
        "condition_is_not_cost",
        "multiple_resolutions",
        "multi_effect_card",
        "global_restriction",
        "simple_reference",
        "unknown_is_not_false",
        "quoted_name_is_not_race",
        "negation_is_not_a_claim",
    }


# ------------------------------------------------------------- the ten cases
def test_basic_attribute_restriction():
    predicate = one("basic_attribute_restriction")
    assert predicate.action is Action.SEARCH
    assert predicate.source_zone is Zone.DECK
    assert predicate.destination_zone is Zone.HAND
    assert predicate.object.attribute == "DARK"
    # Numeric conditions are structured comparisons, never max_level / min_atk.
    assert predicate.object.level == NumericConstraint("<=", 4)
    assert predicate.object.count == 1


def test_special_summon_from_deck():
    predicate = one("special_summon_from_deck")
    assert predicate.action is Action.SPECIAL_SUMMON
    assert predicate.source_zone is Zone.DECK
    assert predicate.object.race == "DRAGON"


def test_special_summon_from_extra_deck():
    predicate = one("special_summon_from_extra_deck")
    assert predicate.action is Action.SPECIAL_SUMMON
    # 「额外卡组」must not degrade to 「卡组」.
    assert predicate.source_zone is Zone.EXTRA_DECK
    assert predicate.source_zone is not Zone.DECK
    assert predicate.object.race == "DRAGON"


def test_banish_from_graveyard_as_cost():
    assert roles_of("banish_from_graveyard_as_cost") == ["COST", "RESOLUTION"]

    cost = role_of("banish_from_graveyard_as_cost", ClauseRole.COST)
    assert cost.action is Action.BANISH
    assert cost.source_zone is Zone.GRAVEYARD
    assert cost.object.attribute == "LIGHT"
    assert cost.action in COST_ACTIONS

    resolution = role_of("banish_from_graveyard_as_cost", ClauseRole.RESOLUTION)
    assert resolution.action is Action.SPECIAL_SUMMON
    assert resolution.source_zone is Zone.EXTRA_DECK


def test_condition_is_not_cost():
    """「没有怪兽存在的场合」is a state, not something you pay."""
    assert roles_of("condition_is_not_cost") == ["CONDITION", "RESOLUTION"]
    assert ClauseRole.COST not in [role for role, _ in flat("condition_is_not_cost")]

    condition_clause = units_of("condition_is_not_cost")[0].clauses[0]
    assert "没有怪兽存在" in condition_clause.clause.raw_text
    resolution = role_of("condition_is_not_cost", ClauseRole.RESOLUTION)
    assert resolution.action is Action.SPECIAL_SUMMON
    assert resolution.source_zone is Zone.HAND


def test_multiple_resolutions():
    resolution = [
        parsed_clause
        for parsed in units_of("multiple_resolutions")
        for parsed_clause in parsed.clauses
        if parsed_clause.clause.role is ClauseRole.RESOLUTION
    ]
    assert len(resolution) == 1, "one clause, two actions"

    actions = [predicate.action for predicate in resolution[0].predicates]
    assert actions == [Action.DRAW, Action.BANISH]

    draw, banish = resolution[0].predicates
    assert draw.source_zone is Zone.DECK and draw.object.count == 1
    assert banish.source_zone is Zone.GRAVEYARD
    # The two actions must not share a noun phrase: drawing is not monsters.
    assert draw.object.card_type is None
    assert banish.object.card_type == "MONSTER"


def test_multi_effect_card():
    parsed = units_of("multi_effect_card")
    assert [unit.unit.marker for unit in parsed] == ["①", "②"]
    assert [unit.unit.kind for unit in parsed] == [UnitKind.NUMBERED, UnitKind.NUMBERED]
    assert [unit.unit.index for unit in parsed] == [0, 1]

    second = parsed[1]
    assert role_of_clause(second, ClauseRole.COST).action is Action.TRIBUTE
    resolution = role_of_clause(second, ClauseRole.RESOLUTION)
    assert resolution.action is Action.SEARCH
    assert resolution.object.race == "FIEND"


def test_global_restriction():
    parsed = units_of("global_restriction")
    assert parsed[0].unit.kind is UnitKind.RESTRICTION
    assert parsed[0].unit.marker is None
    assert parsed[0].unit.raw_text.startswith("这个卡名")
    assert parsed[0].status is ParseStatus.OK

    assert parsed[1].unit.marker == "①"
    assert parsed[1].unit.kind is UnitKind.NUMBERED


def test_simple_reference():
    target = role_of("simple_reference", ClauseRole.TARGET)
    resolution = role_of("simple_reference", ClauseRole.RESOLUTION)

    assert target.result_ref is not None
    assert target.result_ref == resolution.object_ref
    assert resolution.action is Action.SPECIAL_SUMMON
    # The TARGET clause carries the constraint; the resolution only points back.
    assert target.object.level == NumericConstraint("<=", 4)
    assert resolution.object.level is None


def test_unknown_is_not_false():
    parsed = units_of("unknown_is_not_false")[0]
    predicate = parsed.clauses[0].predicates[0]

    assert parsed.status is ParseStatus.UNRESOLVED
    assert predicate.action is None
    assert predicate.action_known is False, "UNKNOWN must never become FALSE"
    assert predicate.confidence <= 0.5
    # The unit is still stored — a parser failure is not a missing effect.
    assert predicate.source_span[1] > 0


def test_quoted_name_is_not_race():
    predicate = one("quoted_name_is_not_race")
    assert predicate.object.name == "青眼白龙"
    assert predicate.object.race is None, "「青眼白龙」is a name, not a Dragon"
    assert predicate.object.attribute is None


def test_negation_is_not_a_claim():
    predicate = one("negation_is_not_a_claim")
    assert predicate.action is None
    assert predicate.action_known is False
    assert predicate.modifiers["negated_action"] == Action.NORMAL_SUMMON.value
    # The restriction was understood, so it must not be reported as a failure.
    assert units_of("negation_is_not_a_claim")[0].status is ParseStatus.OK


# ------------------------------------------------------------------- ontology
def role_of_clause(parsed, role: ClauseRole) -> Predicate:
    for parsed_clause in parsed.clauses:
        if parsed_clause.clause.role is role:
            assert parsed_clause.predicates, f"{role.value} clause has no predicate"
            return parsed_clause.predicates[0]
    raise AssertionError(f"no {role.value} clause")


def test_selector_has_no_min_max_columns():
    names = {field.name for field in fields(CardSelector)}
    assert not [name for name in names if name.startswith(("max_", "min_"))]
    assert {"level", "rank", "link_rating", "atk", "defense"} <= names


def test_numeric_constraint_rejects_bad_operator():
    with pytest.raises(ValueError):
        NumericConstraint("=<", 4)
    with pytest.raises(ValueError):
        NumericConstraint("<=", "4")


def test_numeric_constraint_evaluates():
    assert NumericConstraint("<=", 4).contains(4)
    assert not NumericConstraint("<=", 4).contains(5)
    assert NumericConstraint(">=", 4).contains(9)


def test_enum_values_are_the_machine_protocol():
    """Canonical concepts must not depend on Chinese strings."""
    for action in Action:
        assert action.value.isascii() and action.value.isupper()
    for role in ClauseRole:
        assert role.value.isascii() and role.value.isupper()


def test_cost_actions_are_a_subset_of_actions():
    assert COST_ACTIONS <= set(Action)
    assert Action.BANISH in COST_ACTIONS
    assert Action.SPECIAL_SUMMON not in COST_ACTIONS


def test_action_lexicon_is_not_empty():
    assert len(ACTION_LEXICON) > 30


def test_every_case_validates():
    for case in CASES:
        issues = validate_parsed_units(build_parsed_units(desc=case["zh_desc"]))
        assert not has_errors(issues), f"{case['case']}: {issues}"


def test_every_predicate_records_how_it_was_extracted():
    for case in CASES:
        for _, predicate in flat(case["case"]):
            assert predicate.extracted_by is ExtractedBy.RULE
            assert 0.0 <= predicate.confidence <= 1.0


# ----------------------------------------------------------------- LLM slot
def test_llm_extractor_is_blank_in_v1():
    """The LLM layer is deliberately empty; it must not invent results."""
    unit = split_units("①：这张卡的攻击力变成原本攻击力的一半。")[0]
    assert LlmExtractor().extract(unit) is None


def test_default_extractor_is_the_terminal_layer():
    assert isinstance(get_extractor(""), NullExtractor)


def test_unresolved_units_survive_the_null_extractor():
    parsed = build_parsed_units(
        desc=BY_CASE["unknown_is_not_false"]["zh_desc"], extractor=NullExtractor()
    )
    assert parsed[0].status is ParseStatus.UNRESOLVED


# --------------------------------------------------------------- persistence
@pytest.fixture(scope="module")
def zh_db(tmp_path_factory) -> sqlite3.Connection:
    connection = connect(tmp_path_factory.mktemp("zh") / "zh.db")
    apply_migrations(connection)
    for position, case in enumerate(CASES, start=1):
        connection.execute(
            "INSERT INTO card (card_id, canonical_name, card_category, text_lang,"
            " raw_text, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (position, case["name"], "MONSTER", "zh", case["zh_desc"], "now", "now"),
        )
        connection.execute(
            "INSERT INTO card_text (card_id, lang, kind, source, text, text_sha256, updated_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (position, "zh", "effect", "zh_fixture", case["zh_desc"], "0", "now"),
        )
    connection.commit()
    return connection


def test_build_persists_three_levels(zh_db):
    result = build_effects(zh_db)
    assert result.cards == len(CASES)
    assert result.units > len(CASES)
    assert result.clauses >= result.units
    assert result.predicates >= result.clauses
    assert not result.validation_errors
    assert result.status_counts


def test_persisted_rows_carry_parse_metadata(zh_db):
    rows = zh_db.execute(
        "SELECT unit_id, parse_status, parser_version, lang, marker FROM effect_unit"
        " ORDER BY unit_id"
    ).fetchall()
    assert rows, "no units persisted"
    for row in rows:
        assert row["parser_version"] == PARSER_VERSION
        assert row["lang"] == "zh"
        assert row["parse_status"] in {status.value for status in ParseStatus}


def test_unknown_action_is_stored_as_null_not_false(zh_db):
    card_id = [c for c in CASES if c["case"] == "unknown_is_not_false"][0]["name"]
    rows = zh_db.execute(
        "SELECT p.action, p.action_known FROM effect_predicate p"
        " JOIN effect_clause cl ON cl.clause_id = p.clause_id"
        " JOIN effect_unit u ON u.unit_id = cl.unit_id"
        " JOIN card c ON c.card_id = u.card_id"
        " WHERE c.canonical_name = ?",
        (card_id,),
    ).fetchall()
    assert rows
    assert all(row["action"] is None and row["action_known"] == 0 for row in rows)


def test_cost_and_resolution_are_distinguishable_in_sql(zh_db):
    rows = zh_db.execute(
        "SELECT p.action, cl.role FROM effect_predicate p"
        " JOIN effect_clause cl ON cl.clause_id = p.clause_id"
        " WHERE p.action = 'BANISH'"
    ).fetchall()
    roles = {row["role"] for row in rows}
    assert "COST" in roles, "the GY-banish case must be retrievable as a cost"


def test_payload_json_keeps_the_chinese_span(zh_db):
    row = zh_db.execute("SELECT payload_json FROM effect_predicate LIMIT 1").fetchone()
    payload = json.loads(row["payload_json"])
    assert "source_text" in payload and "object" in payload
    assert payload["extracted_by"] == ExtractedBy.RULE.value


def test_parse_unit_returns_clauses_for_a_numbered_effect():
    unit = split_units("①：从额外卡组特殊召唤1只龙族怪兽。")[0]
    parsed = parse_unit(unit)
    assert [c.clause.role for c in parsed.clauses] == [ClauseRole.RESOLUTION]
