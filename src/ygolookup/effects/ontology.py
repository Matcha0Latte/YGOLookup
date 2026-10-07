"""Controlled vocabularies for the effect layer.

Every string that ends up in the database must come from here. New vocabulary
is added in one place, never scattered through the parser as magic strings.
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "Tri",
    "Action",
    "Zone",
    "EffectPart",
    "EffectScope",
    "SegmentMarker",
    "RACE_VOCABULARY",
    "ATTRIBUTE_VOCABULARY",
    "CARD_CATEGORY_VOCABULARY",
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
    """What an effect does."""

    SPECIAL_SUMMON = "SPECIAL_SUMMON"
    NORMAL_SUMMON = "NORMAL_SUMMON"
    TRIBUTE_SUMMON = "TRIBUTE_SUMMON"
    ADD_TO_HAND = "ADD_TO_HAND"
    SEARCH = "SEARCH"  # add to hand specifically from the Deck
    DRAW = "DRAW"
    SEND_TO_GRAVEYARD = "SEND_TO_GRAVEYARD"
    BANISH = "BANISH"
    DESTROY = "DESTROY"
    NEGATE = "NEGATE"
    RETURN_TO_HAND = "RETURN_TO_HAND"
    RETURN_TO_DECK = "RETURN_TO_DECK"
    TRIBUTE = "TRIBUTE"
    DISCARD = "DISCARD"
    MILL = "MILL"  # send from the top of the Deck to the GY
    CHANGE_POSITION = "CHANGE_POSITION"
    INCREASE_ATK = "INCREASE_ATK"
    DECREASE_ATK = "DECREASE_ATK"
    EXCAVATE = "EXCAVATE"
    REVEAL = "REVEAL"
    ATTACH = "ATTACH"  # attach as material
    DETACH = "DETACH"
    GAIN_CONTROL = "GAIN_CONTROL"
    COPY_EFFECT = "COPY_EFFECT"
    EQUIP = "EQUIP"
    SET_CARD = "SET_CARD"
    PREVENT_DESTRUCTION = "PREVENT_DESTRUCTION"
    PREVENT_ACTIVATION = "PREVENT_ACTIVATION"
    CHANGE_NAME = "CHANGE_NAME"
    SHUFFLE = "SHUFFLE"

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
    ANYWHERE = "ANYWHERE"

    @classmethod
    def parse(cls, value: str) -> "Zone | None":
        try:
            return cls(value.strip().upper())
        except ValueError:
            return None


class EffectPart(str, Enum):
    """Which component of an effect a predicate belongs to.

    Keeping COST separate from RESOLUTION is the whole point: "banish from the
    GY" as a cost and "banish from the GY" as an effect answer different
    questions.
    """

    CONDITION = "CONDITION"
    COST = "COST"
    RESOLUTION = "RESOLUTION"
    RESTRICTION = "RESTRICTION"


class EffectScope(str, Enum):
    """Which block of a card's text an effect came from."""

    MAIN = "MAIN"
    PENDULUM = "PENDULUM"
    MONSTER = "MONSTER"


class SegmentMarker(str, Enum):
    """How the splitter decided this segment was its own effect."""

    BLOCK = "BLOCK"  # whole text / pendulum block
    BULLET = "BULLET"  # "●" item
    LINE = "LINE"  # a line that starts with an effect keyword
    SENTENCE = "SENTENCE"  # sentence-level split within a line
    MATERIAL = "MATERIAL"  # summoning-material line, e.g. "2 Level 4 monsters"


# --------------------------------------------------------------- vocabularies
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


def normalize_race_token(token: str) -> str | None:
    return RACE_VOCABULARY.get(token.strip().upper())
