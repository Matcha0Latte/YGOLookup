import pytest

from ygolookup.query.dsl import (
    Query,
    QueryError,
    and_,
    card_eq,
    effect_eq,
    not_,
    or_,
    parse_condition,
)
from ygolookup.query.fields import get_field, validate_value


def test_query_roundtrip():
    query = Query(where=and_(card_eq("race", "DRAGON"), card_eq("attribute", "DARK")))
    restored = Query.from_dict(query.to_dict())
    assert restored.to_dict() == query.to_dict()


def test_or_and_not_serialize():
    node = not_(or_(card_eq("race", "DRAGON"), card_eq("race", "FIEND")))
    assert node.to_dict()["not"]["or"][0]["field"] == "card.race"


def test_exists_builder_sets_part():
    node = effect_eq("action", "SPECIAL_SUMMON", part="RESOLUTION")
    assert node.to_dict()["exists"] == "effect"
    assert node.to_dict()["where"]["and"][0]["value"] == "RESOLUTION"


def test_unknown_op_is_rejected():
    with pytest.raises(QueryError):
        parse_condition({"field": "card.race", "op": "like", "value": "DRAGON"})


def test_field_condition_requires_op_and_value():
    with pytest.raises(QueryError):
        parse_condition({"field": "card.race"})


def test_in_requires_list():
    with pytest.raises(QueryError):
        parse_condition({"field": "card.race", "op": "in", "value": "DRAGON"})


def test_empty_and_is_rejected():
    with pytest.raises(QueryError):
        parse_condition({"and": []})


def test_unrecognized_node():
    with pytest.raises(QueryError):
        parse_condition({"where": {}})


def test_unsupported_exists_target():
    with pytest.raises(QueryError):
        parse_condition({"exists": "card"})


def test_unknown_field_is_rejected_with_helpful_message():
    with pytest.raises(QueryError, match="unknown field"):
        get_field("card.colour")


def test_invalid_enum_value_is_rejected():
    spec = get_field("card.race")
    with pytest.raises(QueryError):
        validate_value(spec, "eq", "LIZARD")


def test_numeric_field_rejects_string():
    spec = get_field("card.level_rank")
    with pytest.raises(QueryError):
        validate_value(spec, "lte", "four")


def test_virtual_range_field_only_supports_comparisons():
    from ygolookup.query.fields import assert_range_supported

    spec = get_field("effect.target_level")
    assert_range_supported(spec, "lte")  # ok
    with pytest.raises(QueryError):
        assert_range_supported(spec, "eq")


def test_limit_must_be_positive():
    with pytest.raises(QueryError):
        Query(limit=-1)


def test_unsupported_select():
    with pytest.raises(QueryError):
        Query(select="effect")
