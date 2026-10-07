"""Rule-based planner + agent tool surface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ygolookup.agent.tools import (
    TOOL_SCHEMAS,
    ToolError,
    get_card_tool,
    plan_query_tool,
    search_cards_tool,
    search_effects_tool,
)
from ygolookup.db.connection import connect
from ygolookup.db.migrations import apply_migrations
from ygolookup.effects.service import build_effects
from ygolookup.query.planner import plan

from conftest import FIXTURE, RAW, load_fixture_pool


@pytest.fixture(scope="module")
def conn():
    connection = connect(Path(__file__).parent / ".tmp" / "tools.db")
    apply_migrations(connection)
    load_fixture_pool(connection)
    build_effects(connection)
    connection.commit()
    yield connection
    connection.close()


# --------------------------------------------------------------------- planner
def test_plan_chinese_dragon():
    result = plan("龙族")
    assert {"field": "card.race", "op": "eq", "value": "DRAGON"} in [
        c.to_dict() for c in result.query.where.children
    ]


def test_plan_level_ceiling():
    result = plan("4星以下的暗属性怪兽")
    conditions = [c.to_dict() for c in result.query.where.children]
    assert {"field": "card.attribute", "op": "eq", "value": "DARK"} in conditions
    assert {"field": "card.level_rank", "op": "lte", "value": 4} in conditions


def test_plan_effect_with_zone():
    result = plan("能够从额外卡组特殊召唤龙族怪兽的卡")
    payload = result.query.to_dict()
    exists = payload["where"]["and"][-1]
    assert exists["exists"] == "effect"
    values = {c["field"]: c["value"] for c in exists["where"]["and"]}
    assert values["effect.action"] == "SPECIAL_SUMMON"
    assert values["effect.source_zone"] == "EXTRA_DECK"


def test_plan_marks_cost():
    result = plan("以除外墓地怪兽作为cost特殊召唤")
    exists = result.query.to_dict()["where"]["and"][-1]
    parts = {c["field"]: c["value"] for c in exists["where"]["and"]}
    assert parts["clause.role"] == "COST"


def test_plan_reports_unmatched_text():
    result = plan("找一张能让对手笑出来的卡")
    assert result.unmatched, "unknown intent must be reported, not silently dropped"
    assert result.query.where is None or result.matched == []


def test_plan_archetype_from_quotes():
    result = plan('找「Testcase」系列的卡')
    conditions = [c.to_dict() for c in (result.query.where.children if result.query.where else [])]
    assert any(c["field"] == "card.archetype" for c in conditions)


def test_plan_output_is_json_serializable():
    assert json.dumps(plan("暗属性龙族").to_dict(), ensure_ascii=False)


def test_planner_is_deterministic():
    assert plan("龙族").query.to_dict() == plan("龙族").query.to_dict()


# ----------------------------------------------------------------------- tools
def test_tool_schemas_are_declared():
    assert {"get_card", "search_cards", "search_effects", "plan_query"} <= set(TOOL_SCHEMAS)


def test_get_card_tool(conn):
    card = get_card_tool(conn, name="Testcase Dragon Alpha")
    assert card["race"] == "DRAGON"
    assert "Extra Deck" in card["raw_text"]
    assert any(e["source"] == "ygopro_passcode" for e in card["external_ids"])


def test_get_card_tool_not_found(conn):
    with pytest.raises(ToolError):
        get_card_tool(conn, name="Definitely Not A Card")


def test_search_cards_tool(conn):
    result = search_cards_tool(
        conn,
        query={"where": {"and": [{"field": "card.race", "op": "eq", "value": "DRAGON"}]}},
    )
    assert result["total"] == 2
    assert "hits" in result


def test_search_cards_tool_rejects_bad_query(conn):
    with pytest.raises(ToolError):
        search_cards_tool(conn, query={"where": {"field": "card.race", "op": "magic", "value": 1}})


def test_search_effects_tool_returns_effect_granularity(conn):
    effects = search_effects_tool(
        conn,
        query={
            "where": {
                "exists": "effect",
                "where": {"field": "effect.action", "op": "eq", "value": "SPECIAL_SUMMON"},
            }
        },
    )
    assert effects, "expected at least one matching effect"
    assert all("raw_text" in e for e in effects)


def test_plan_query_tool(conn):
    payload = plan_query_tool(conn, text="暗属性恶魔族")
    assert "query" in payload and "matched" in payload


def test_fulltext_and_semantic_are_declared_but_unimplemented(conn):
    from ygolookup.agent import tools

    with pytest.raises(NotImplementedError):
        tools.fulltext_search_tool(conn, text="dragon")
    with pytest.raises(NotImplementedError):
        tools.semantic_search_tool(conn, text="combo starter")
