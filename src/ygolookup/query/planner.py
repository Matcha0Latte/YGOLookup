"""Rule-based natural language -> Query AST.

This is a *deterministic placeholder* for the LLM planner. It exists so the
system is demoable end-to-end and so the planner interface is exercised by
tests. It is intentionally limited:

  * it recognizes a fixed vocabulary (zh + en) of card properties, actions,
    zones and races;
  * it never guesses — unknown tokens are ignored, and `unmatched` is returned
    so the caller can decide whether to fall back to FTS/semantic search;
  * replacing it with an LLM planner does not change any other module.

The LLM planner planned for a later phase will produce the same `Query` object.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..effects.ontology import Action, Zone
from .dsl import FieldCondition, Query, QueryError, and_

# ------------------------------------------------------------------ vocabulary
RACE_TERMS = {
    "dragon": "DRAGON",
    "龙族": "DRAGON",
    "龙": "DRAGON",
    "spellcaster": "SPELLCASTER",
    "魔法师族": "SPELLCASTER",
    "魔法师": "SPELLCASTER",
    "warrior": "WARRIOR",
    "战士族": "WARRIOR",
    "fiend": "FIEND",
    "恶魔族": "FIEND",
    "恶魔": "FIEND",
    "fairy": "FAIRY",
    "天使族": "FAIRY",
    "zombie": "ZOMBIE",
    "不死族": "ZOMBIE",
    "machine": "MACHINE",
    "机械族": "MACHINE",
    "beast-warrior": "BEAST_WARRIOR",
    "兽战士族": "BEAST_WARRIOR",
    "beast": "BEAST",
    "兽族": "BEAST",
    "winged-beast": "WINGED_BEAST",
    "鸟兽族": "WINGED_BEAST",
    "insect": "INSECT",
    "昆虫族": "INSECT",
    "plant": "PLANT",
    "植物族": "PLANT",
    "psychic": "PSYCHIC",
    "念动力族": "PSYCHIC",
    "cyberse": "CYBERSE",
    "电子界族": "CYBERSE",
    "wyrm": "WYRM",
    "幻龙族": "WYRM",
    "aquatic": "AQUA",
    "水族": "AQUA",
    "reptile": "REPTILE",
    "爬虫类族": "REPTILE",
    "rock": "ROCK",
    "岩石族": "ROCK",
    "thunder": "THUNDER",
    "雷族": "THUNDER",
    "dinosaur": "DINOSAUR",
    "恐龙族": "DINOSAUR",
    "fish": "FISH",
    "鱼族": "FISH",
    "sea serpent": "SEA_SERPENT",
    "海龙族": "SEA_SERPENT",
    "pyro": "PYRO",
    "炎族": "PYRO",
}

ATTRIBUTE_TERMS = {
    "dark": "DARK",
    "暗属性": "DARK",
    "暗": "DARK",
    "light": "LIGHT",
    "光属性": "LIGHT",
    "光": "LIGHT",
    "earth": "EARTH",
    "地属性": "EARTH",
    "water": "WATER",
    "水属性": "WATER",
    "fire": "FIRE",
    "炎属性": "FIRE",
    "wind": "WIND",
    "风属性": "WIND",
    "divine": "DIVINE",
    "神属性": "DIVINE",
}

ACTION_TERMS = {
    "special summon": Action.SPECIAL_SUMMON,
    "特殊召唤": Action.SPECIAL_SUMMON,
    "normal summon": Action.NORMAL_SUMMON,
    "通常召唤": Action.NORMAL_SUMMON,
    "add to hand": Action.ADD_TO_HAND,
    "加入手卡": Action.ADD_TO_HAND,
    "加入手牌": Action.ADD_TO_HAND,
    "search": Action.SEARCH,
    "检索": Action.SEARCH,
    "draw": Action.DRAW,
    "抽卡": Action.DRAW,
    "banish": Action.BANISH,
    "除外": Action.BANISH,
    "destroy": Action.DESTROY,
    "破坏": Action.DESTROY,
    "negate": Action.NEGATE,
    "无效": Action.NEGATE,
    "send to graveyard": Action.SEND_TO_GRAVEYARD,
    "送去墓地": Action.SEND_TO_GRAVEYARD,
    "discard": Action.DISCARD,
    "丢弃": Action.DISCARD,
    "mill": Action.MILL,
    "return to hand": Action.RETURN_TO_HAND,
    "回到手卡": Action.RETURN_TO_HAND,
    "return to deck": Action.RETURN_TO_DECK,
    "回到卡组": Action.RETURN_TO_DECK,
    "tribute": Action.TRIBUTE,
    "解放": Action.TRIBUTE,
}

ZONE_TERMS = {
    "extra deck": Zone.EXTRA_DECK,
    "额外卡组": Zone.EXTRA_DECK,
    "额外": Zone.EXTRA_DECK,
    "deck": Zone.DECK,
    "卡组": Zone.DECK,
    "graveyard": Zone.GRAVEYARD,
    "gy": Zone.GRAVEYARD,
    "墓地": Zone.GRAVEYARD,
    "hand": Zone.HAND,
    "手卡": Zone.HAND,
    "手牌": Zone.HAND,
    "banished": Zone.BANISHED,
    "除外区": Zone.BANISHED,
    "field": Zone.FIELD,
    "场上": Zone.FIELD,
}

CATEGORY_TERMS = {
    "monster": "MONSTER",
    "怪兽": "MONSTER",
    "spell": "SPELL",
    "魔法卡": "SPELL",
    "魔法": "SPELL",
    "trap": "TRAP",
    "陷阱卡": "TRAP",
    "陷阱": "TRAP",
}

_LEVEL_RE = re.compile(
    r"(?:level|lv|等级|星)\s*(\d+)\s*(?:or lower|以下|以下怪兽|以下)?|(\d+)\s*(?:星以下|星或以下)",
    re.IGNORECASE,
)
_LOWER_RE = re.compile(r"(or lower|or less|以下|以内|以下怪兽)", re.IGNORECASE)
_HIGHER_RE = re.compile(r"(or higher|or more|以上|以上怪兽)", re.IGNORECASE)
_COST_RE = re.compile(r"(作为)?(cost|代价|作为cost|作为代价|作为成本)", re.IGNORECASE)
_TUNER_RE = re.compile(r"(tuner|协调|调整)", re.IGNORECASE)
_NON_TUNER_RE = re.compile(r"(non-tuner|非协调|非调整)", re.IGNORECASE)
_ONCE_PER_TURN_RE = re.compile(r"(once per turn|一回合一次|每回合一次)", re.IGNORECASE)

_ARCHETYPE_RE = re.compile(r"[\"“”「」『』]([^\"“”「」『』]{2,40})[\"“”「」『』]|「([^」]{2,40})」")


@dataclass
class PlanResult:
    query: Query
    matched: list[str]
    unmatched: list[str]

    def to_dict(self) -> dict:
        return {
            "query": self.query.to_dict(),
            "matched": self.matched,
            "unmatched": self.unmatched,
        }


def _longest_first(mapping: dict[str, str]) -> list[tuple[str, str]]:
    return sorted(mapping.items(), key=lambda kv: len(kv[0]), reverse=True)


def plan(text: str, *, limit: int = 50) -> PlanResult:
    """Translate a natural language question into a Query AST."""
    source = text.strip()
    lowered = source.lower()
    matched: list[str] = []
    unmatched: list[str] = []

    card_conditions: list[FieldCondition] = []
    effect_conditions: list[FieldCondition] = []

    def take(mapping: dict[str, object]) -> object | None:
        for token, value in _longest_first(mapping):  # type: ignore[arg-type]
            if token.lower() in lowered:
                matched.append(token)
                return value
        return None

    # ---- card-level properties
    race = take(RACE_TERMS)
    if race:
        card_conditions.append(FieldCondition("card.race", "eq", race))

    attribute = take(ATTRIBUTE_TERMS)
    if attribute:
        card_conditions.append(FieldCondition("card.attribute", "eq", attribute))

    category = take(CATEGORY_TERMS)
    if category and _looks_like_card_property(source, category):
        card_conditions.append(FieldCondition("card.card_category", "eq", category))

    level_match = _LEVEL_RE.search(lowered)
    if level_match:
        level = int(level_match.group(1) or level_match.group(2))
        if _LOWER_RE.search(lowered):
            card_conditions.append(FieldCondition("card.level_rank", "lte", level))
            matched.append(f"level<={level}")
        elif _HIGHER_RE.search(lowered):
            card_conditions.append(FieldCondition("card.level_rank", "gte", level))
            matched.append(f"level>={level}")
        else:
            card_conditions.append(FieldCondition("card.level_rank", "eq", level))
            matched.append(f"level={level}")

    if _TUNER_RE.search(lowered) and not _NON_TUNER_RE.search(lowered):
        card_conditions.append(FieldCondition("card.flag", "eq", "TUNER"))
        matched.append("tuner")

    archetype = _ARCHETYPE_RE.search(source)
    if archetype:
        value = (archetype.group(1) or archetype.group(2) or "").strip()
        if value:
            card_conditions.append(FieldCondition("card.archetype", "eq", _slug(value)))
            matched.append(f"archetype={value}")

    # ---- effect-level properties
    action = take(ACTION_TERMS)
    if action:
        effect_conditions.append(FieldCondition("effect.action", "eq", action.value))
    else:
        unmatched.append("action")

    zone = take(ZONE_TERMS)
    if zone:
        effect_conditions.append(FieldCondition("effect.source_zone", "eq", zone.value))

    if _COST_RE.search(lowered):
        effect_conditions.insert(0, FieldCondition("effect.part", "eq", "COST"))
        matched.append("cost")

    if _ONCE_PER_TURN_RE.search(lowered):
        effect_conditions.append(FieldCondition("effect.once_per_turn", "eq", "TRUE"))
        matched.append("once per turn")

    # A second race/attribute mention usually constrains the *target*.
    if race and lowered.count("dragon") + lowered.count("龙") >= 1 and action:
        effect_conditions.append(FieldCondition("effect.target_race", "eq", race))

    conditions = list(card_conditions)
    if effect_conditions:
        from .dsl import ExistsCondition

        conditions.append(
            ExistsCondition(target="effect", where=and_(*effect_conditions))
        )

    if not conditions:
        unmatched.append(source)

    query = Query(where=and_(*conditions) if conditions else None, limit=limit)
    return PlanResult(query=query, matched=matched, unmatched=unmatched)


def _slug(value: str) -> str:
    return re.sub(r"[\s\-_/]+", "-", value.strip()).strip("-").lower()


def _looks_like_card_property(text: str, category: str) -> bool:
    """Avoid turning 'destroy Spell cards' into card_category = SPELL."""
    lowered = text.lower()
    actionish = ("destroy", "negate", "add", "search", "banish", "send", "破坏", "无效", "检索", "除外")
    return not any(token in lowered for token in actionish)
