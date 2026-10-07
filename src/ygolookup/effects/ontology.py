"""Controlled vocabularies for the effect layer.

Two languages live here, with strictly different jobs:

* **Chinese** is the source language. Everything in `*_ZH` is what actually
  appears on a card.
* **English** is the machine protocol. Every value stored in the database and
  every value a query may use comes from an enum here.

The mapping between the two lives in `lexicon.py` — never inline in a parser.
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "Tri",
    "Action",
    "Zone",
    "ClauseRole",
    "UnitKind",
    "EffectScope",
    "ParseStatus",
    "ExtractedBy",
    "Subject",
    "RACE_VOCABULARY",
    "ATTRIBUTE_VOCABULARY",
    "CARD_CATEGORY_VOCABULARY",
    "RACE_ZH",
    "ATTRIBUTE_ZH",
    "CARD_TYPE_ZH",
    "MONSTER_TAG_ZH",
    "normalize_race_token",
]


class Tri(str, Enum):
    """Three-valued logic for automatically extracted properties.

    UNKNOWN means "the parser did not determine this" — it must never be
    treated as FALSE, otherwise a parser failure silently becomes a claim that
    the card does not do something.
    """

    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def coerce(cls, value: bool | None) -> "Tri":
        if value is None:
            return cls.UNKNOWN
        return cls.TRUE if value else cls.FALSE

    @property
    def is_known(self) -> bool:
        return self is not Tri.UNKNOWN


class Action(str, Enum):
    """What an effect does.

    Values are the machine protocol; the Chinese wording that produces each one
    is declared in `lexicon.ACTION_LEXICON`.
    """

    # --- summoning -----------------------------------------------------------
    SPECIAL_SUMMON = "SPECIAL_SUMMON"
    NORMAL_SUMMON = "NORMAL_SUMMON"
    TRIBUTE_SUMMON = "TRIBUTE_SUMMON"
    FUSION_SUMMON = "FUSION_SUMMON"
    RITUAL_SUMMON = "RITUAL_SUMMON"
    SYNCHRO_SUMMON = "SYNCHRO_SUMMON"
    XYZ_SUMMON = "XYZ_SUMMON"
    LINK_SUMMON = "LINK_SUMMON"

    # --- moving cards --------------------------------------------------------
    ADD_TO_HAND = "ADD_TO_HAND"
    SEARCH = "SEARCH"  # add to hand specifically from the Deck
    DRAW = "DRAW"
    SEND_TO_GRAVEYARD = "SEND_TO_GRAVEYARD"
    MILL = "MILL"  # send from the top of the Deck to the GY
    BANISH = "BANISH"
    RETURN_TO_HAND = "RETURN_TO_HAND"
    RETURN_TO_DECK = "RETURN_TO_DECK"
    RETURN_TO_EXTRA_DECK = "RETURN_TO_EXTRA_DECK"
    DISCARD = "DISCARD"
    TRIBUTE = "TRIBUTE"
    DETACH = "DETACH"
    ATTACH = "ATTACH"
    EXCAVATE = "EXCAVATE"
    REVEAL = "REVEAL"
    SHUFFLE = "SHUFFLE"
    SET_CARD = "SET_CARD"
    EQUIP = "EQUIP"
    GAIN_CONTROL = "GAIN_CONTROL"

    # --- interaction ---------------------------------------------------------
    DESTROY = "DESTROY"
    NEGATE = "NEGATE"
    NEGATE_ACTIVATION = "NEGATE_ACTIVATION"
    NEGATE_EFFECTS = "NEGATE_EFFECTS"
    CHANGE_POSITION = "CHANGE_POSITION"

    # --- stats & identity ----------------------------------------------------
    INCREASE_ATK = "INCREASE_ATK"
    DECREASE_ATK = "DECREASE_ATK"
    INCREASE_DEF = "INCREASE_DEF"
    DECREASE_DEF = "DECREASE_DEF"
    CHANGE_ATK = "CHANGE_ATK"
    CHANGE_NAME = "CHANGE_NAME"
    CHANGE_ATTRIBUTE = "CHANGE_ATTRIBUTE"
    CHANGE_RACE = "CHANGE_RACE"
    CHANGE_LEVEL = "CHANGE_LEVEL"
    CHANGE_SCALE = "CHANGE_SCALE"
    COPY_EFFECT = "COPY_EFFECT"

    # --- battle --------------------------------------------------------------
    ATTACK_DIRECTLY = "ATTACK_DIRECTLY"
    INFLICT_DAMAGE = "INFLICT_DAMAGE"
    PIERCING_DAMAGE = "PIERCING_DAMAGE"

    # --- costs ---------------------------------------------------------------
    PAY_LP = "PAY_LP"

    # --- prevention ----------------------------------------------------------
    PREVENT_DESTRUCTION = "PREVENT_DESTRUCTION"
    PREVENT_ACTIVATION = "PREVENT_ACTIVATION"
    PREVENT_ATTACK = "PREVENT_ATTACK"
    PREVENT_SUMMON = "PREVENT_SUMMON"
    PREVENT_TARGETING = "PREVENT_TARGETING"

    @classmethod
    def parse(cls, value: str) -> "Action | None":
        try:
            return cls(value.strip().upper())
        except ValueError:
            return None


class Zone(str, Enum):
    """Where cards come from and where they go."""

    DECK = "DECK"
    EXTRA_DECK = "EXTRA_DECK"
    HAND = "HAND"
    GRAVEYARD = "GRAVEYARD"
    BANISHED = "BANISHED"
    FIELD = "FIELD"
    MONSTER_ZONE = "MONSTER_ZONE"
    SPELL_TRAP_ZONE = "SPELL_TRAP_ZONE"
    PENDULUM_ZONE = "PENDULUM_ZONE"
    FIELD_ZONE = "FIELD_ZONE"
    ANYWHERE = "ANYWHERE"

    @classmethod
    def parse(cls, value: str) -> "Zone | None":
        try:
            return cls(value.strip().upper())
        except ValueError:
            return None


class ClauseRole(str, Enum):
    """The role a clause plays inside one effect.

    CONDITION and COST are deliberately distinct: in OCG text both sit in front
    of the activation anchor (「发动」), but only COST is something the player
    pays. "自己场上没有怪兽存在的场合才能发动" is a CONDITION, not a COST.
    """

    CONDITION = "CONDITION"
    COST = "COST"
    TARGET = "TARGET"
    RESOLUTION = "RESOLUTION"
    RESTRICTION = "RESTRICTION"
    UNKNOWN = "UNKNOWN"


class UnitKind(str, Enum):
    """What kind of text block an EffectUnit is."""

    NUMBERED = "NUMBERED"  # ① / ② / ③ …
    UNNUMBERED = "UNNUMBERED"  # plain effect text with no number marker
    MATERIAL = "MATERIAL"  # summoning-material line — not an effect
    RESTRICTION = "RESTRICTION"  # card-wide restriction, not tied to one effect


class EffectScope(str, Enum):
    """Which block of a card's text an effect came from."""

    MAIN = "MAIN"
    PENDULUM = "PENDULUM"
    MONSTER = "MONSTER"


class ParseStatus(str, Enum):
    """How complete the parse of one unit is.

    PARTIAL and UNRESOLVED are real states: they say "we did not understand
    this", never "the card does not do this".
    """

    OK = "OK"
    PARTIAL = "PARTIAL"
    UNRESOLVED = "UNRESOLVED"


class ExtractedBy(str, Enum):
    """Which layer produced a value."""

    RULE = "rule"
    GRAMMAR = "grammar"
    LLM = "llm"


class Subject(str, Enum):
    """Who performs the action described by a predicate."""

    SELF = "SELF"  # 自己
    OPPONENT = "OPPONENT"  # 对方
    PLAYER = "PLAYER"  # 玩家 / 双方
    ANY = "ANY"
    UNKNOWN = "UNKNOWN"


# --------------------------------------------------------------- vocabularies
# English vocabularies are for CARD-level fields decoded from upstream data.
RACE_VOCABULARY = {
    "DRAGON": "DRAGON",
    "SPELLCASTER": "SPELLCASTER",
    "WARRIOR": "WARRIOR",
    "BEAST-WARRIOR": "BEAST_WARRIOR",
    "BEAST WARRIOR": "BEAST_WARRIOR",
    "BEAST": "BEAST",
    "WINGED-BEAST": "WINGED_BEAST",
    "WINGED BEAST": "WINGED_BEAST",
    "FIEND": "FIEND",
    "FAIRY": "FAIRY",
    "ANGEL": "FAIRY",
    "ZOMBIE": "ZOMBIE",
    "MACHINE": "MACHINE",
    "AQUA": "AQUA",
    "PYRO": "PYRO",
    "ROCK": "ROCK",
    "PLANT": "PLANT",
    "INSECT": "INSECT",
    "THUNDER": "THUNDER",
    "DINOSAUR": "DINOSAUR",
    "FISH": "FISH",
    "SEA-SERPENT": "SEA_SERPENT",
    "SEA SERPENT": "SEA_SERPENT",
    "REPTILE": "REPTILE",
    "PSYCHIC": "PSYCHIC",
    "DIVINE-BEAST": "DIVINE_BEAST",
    "DIVINE BEAST": "DIVINE_BEAST",
    "CREATOR-GOD": "CREATOR_GOD",
    "CREATOR GOD": "CREATOR_GOD",
    "WYRM": "WYRM",
    "CYBERSE": "CYBERSE",
    "ILLUSIONIST": "ILLUSIONIST",
}

ATTRIBUTE_VOCABULARY = {
    "EARTH": "EARTH",
    "WATER": "WATER",
    "FIRE": "FIRE",
    "WIND": "WIND",
    "LIGHT": "LIGHT",
    "DARK": "DARK",
    "DIVINE": "DIVINE",
}

CARD_CATEGORY_VOCABULARY = {
    "MONSTER": "MONSTER",
    "SPELL": "SPELL",
    "TRAP": "TRAP",
    "MONSTERS": "MONSTER",
    "SPELLS": "SPELL",
    "TRAPS": "TRAP",
    "SPELL/TRAP": "SPELL_TRAP",
    "SPELL/TRAP CARD": "SPELL_TRAP",
}


# ------------------------------------------------------- Chinese vocabularies
# Simplified-Chinese OCG wording -> canonical enum.
RACE_ZH = {
    "龙族": "DRAGON",
    "魔法师族": "SPELLCASTER",
    "战士族": "WARRIOR",
    "兽战士族": "BEAST_WARRIOR",
    "兽族": "BEAST",
    "鸟兽族": "WINGED_BEAST",
    "恶魔族": "FIEND",
    "天使族": "FAIRY",
    "不死族": "ZOMBIE",
    "机械族": "MACHINE",
    "水族": "AQUA",
    "炎族": "PYRO",
    "岩石族": "ROCK",
    "植物族": "PLANT",
    "昆虫族": "INSECT",
    "雷族": "THUNDER",
    "恐龙族": "DINOSAUR",
    "鱼族": "FISH",
    "海龙族": "SEA_SERPENT",
    "爬虫类族": "REPTILE",
    "念动力族": "PSYCHIC",
    "幻神兽族": "DIVINE_BEAST",
    "创造神族": "CREATOR_GOD",
    "幻龙族": "WYRM",
    "电子界族": "CYBERSE",
    "幻想魔族": "ILLUSIONIST",
}

ATTRIBUTE_ZH = {
    "地属性": "EARTH",
    "水属性": "WATER",
    "炎属性": "FIRE",
    "风属性": "WIND",
    "光属性": "LIGHT",
    "暗属性": "DARK",
    "神属性": "DIVINE",
}

CARD_TYPE_ZH = {
    "怪兽": "MONSTER",
    "魔法卡": "SPELL",
    "陷阱卡": "TRAP",
    "魔法·陷阱卡": "SPELL_TRAP",
    "魔法与陷阱卡": "SPELL_TRAP",
    "灵摆怪兽": "MONSTER",
    "效果怪兽": "MONSTER",
}

# Monster subtype tags (a card can carry several).
MONSTER_TAG_ZH = {
    "调整": "TUNER",
    "协调": "TUNER",
    "灵摆": "PENDULUM",
    "反转": "FLIP",
    "二重": "GEMINI",
    "同盟": "UNION",
    "灵魂": "SPIRIT",
    "卡通": "TOON",
    "衍生物": "TOKEN",
}


def normalize_race_token(token: str) -> str | None:
    return RACE_VOCABULARY.get(token.strip().upper())
