"""Regression tests driven by tests/fixtures/effect_parser_cases.json.

Every parser change must keep these green. Adding coverage means adding a
fixture case — not adding a bespoke test method.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ygolookup.effects.ontology import Action, EffectPart, SegmentMarker, Tri, Zone
from ygolookup.effects.parser import parse_segment, parse_effect_text
from ygolookup.effects.schema import EffectPredicate, ParsedEffect, PARSER_VERSION
from ygolookup.effects.splitter import split_effects
from ygolookup.effects.validator import has_errors, validate_parsed_effect

FIXTURE = Path(__file__).parent / "fixtures" / "effect_parser_cases.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


def _matches(predicate: EffectPredicate, expected: dict) -> bool:
    if "part" in expected and predicate.part.value != expected["part"]:
        return False
    if "action" in expected:
        want = expected["action"]
        got = predicate.action.value if predicate.action else None
        if got != want:
            return False
    for key, zone_name in (("source", "source"), ("destination", "destination")):
        if key in expected:
            value = getattr(predicate, zone_name)
            got = value.value if value else None
            if got != expected[key]:
                return False
    if "once_per_turn" in expected and predicate.once_per_turn.value != expected["once_per_turn"]:
        return False
    for key, value in (expected.get("target") or {}).items():
        actual = getattr(predicate.target, key)
        actual_value = actual.value if isinstance(actual, Tri) else actual
        if actual_value != value:
            return False
    return True


def _parse(text: str) -> list[ParsedEffect]:
    return [parse_segment(segment) for segment in split_effects(text)]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_parser_fixture(case):
    parsed = _parse(case["text"])
    predicates = [p for effect in parsed for p in effect.predicates]

    if case.get("no_predicates"):
        assert predicates == [], f"expected no predicates, got {[p.to_dict() for p in predicates]}"
        return

    if "scopes" in case:
        assert [e.segment.scope.value for e in parsed] == case["scopes"]

    for expected in case.get("expect", []):
        assert any(_matches(p, expected) for p in predicates), (
            f"no predicate matches {expected}\n"
            + "\n".join(f"  {json.dumps(p.to_dict(), ensure_ascii=False)}" for p in predicates)
        )


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_parser_output_is_valid(case):
    """Parser output must always be well-formed, even when it is wrong."""
    for parsed in _parse(case["text"]):
        assert not has_errors(validate_parsed_effect(parsed))


# ------------------------------------------------------------------- splitter
def test_splitter_pendulum_scopes():
    text = "[ Pendulum Effect ] \nPendulum text here.\n\n[ Monster Effect ] \nMonster text here."
    segments = split_effects(text)
    assert [s.scope.value for s in segments] == ["PENDULUM", "MONSTER"]
    assert "Pendulum text here." in segments[0].raw_text
    assert "Monster text here." in segments[1].raw_text


def test_splitter_bullets():
    segments = split_effects("● First effect. ● Second effect.")
    assert [s.marker.value for s in segments] == ["BULLET", "BULLET"]


def test_splitter_material_line():
    assert split_effects("2 Level 4 monsters")[0].marker is SegmentMarker.MATERIAL
    assert split_effects("1 Tuner + 1+ non-Tuner monsters")[0].marker is SegmentMarker.MATERIAL


def test_splitter_empty_text():
    assert split_effects("") == []
    assert split_effects("   \n  ") == []


def test_splitter_does_not_split_on_semicolon():
    """';' is the PSCT cost/resolution delimiter and must stay in one segment."""
    segments = split_effects("Discard 1 card; draw 2 cards.")
    assert len(segments) == 1


# ------------------------------------------------------------- three-valuedness
def test_unknown_action_is_none_not_false():
    parsed = parse_effect_text("This card's name becomes \"Blue-Eyes White Dragon\".")
    resolution = [p for p in parsed.predicates if p.part is EffectPart.RESOLUTION]
    assert resolution, "a resolution predicate must always exist"
    assert resolution[0].action is None, "unparsed action must be UNKNOWN, not a wrong guess"


def test_tri_coerce():
    assert Tri.coerce(None) is Tri.UNKNOWN
    assert Tri.coerce(True) is Tri.TRUE
    assert Tri.coerce(False) is Tri.FALSE
    assert Tri.TRUE.is_known and not Tri.UNKNOWN.is_known


def test_unknown_is_not_treated_as_false_in_target():
    parsed = parse_effect_text("Special Summon 1 monster from your Deck.")
    predicate = parsed.predicates[-1]
    assert predicate.target.tuner is Tri.UNKNOWN
    assert predicate.target.race is None


# -------------------------------------------------------------------- ontology
def test_action_and_zone_parse_reject_junk():
    assert Action.parse("special_summon") is Action.SPECIAL_SUMMON
    assert Action.parse("NOT_AN_ACTION") is None
    assert Zone.parse("extra_deck") is Zone.EXTRA_DECK
    assert Zone.parse("moon") is None


def test_serialization_roundtrip():
    parsed = parse_effect_text("Banish 1 LIGHT monster from your GY; Special Summon 1 Dragon monster from your Deck.")
    for predicate in parsed.predicates:
        restored = EffectPredicate.from_dict(predicate.to_dict())
        assert restored.to_dict() == predicate.to_dict()


def test_parsed_effect_is_json_serializable():
    parsed = parse_effect_text("Discard 1 card; draw 2 cards.")
    payload = json.dumps(parsed.to_dict(), ensure_ascii=False)
    assert PARSER_VERSION in payload
