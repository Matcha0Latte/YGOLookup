"""YGOPro / EDOPro `cards.cdb` bitfield decoding.

All constants mirror the upstream `datas` table layout. Nothing here invents
semantics — it only translates upstream bitmasks into readable enums so that
downstream layers never have to do bit arithmetic themselves.
"""

from __future__ import annotations

# ------------------------------------------------------------------- type bits
TYPE_MONSTER = 0x1
TYPE_SPELL = 0x2
TYPE_TRAP = 0x4
TYPE_NORMAL = 0x10
TYPE_EFFECT = 0x20
TYPE_FUSION = 0x40
TYPE_RITUAL = 0x80
TYPE_TRAP_MONSTER = 0x100
TYPE_SPIRIT = 0x200
TYPE_UNION = 0x400
TYPE_GEMINI = 0x800  # upstream calls this TYPE_DUAL
TYPE_TUNER = 0x1000
TYPE_SYNCHRO = 0x2000
TYPE_TOKEN = 0x4000
TYPE_MAXIMUM = 0x8000
TYPE_QUICK_PLAY = 0x10000
TYPE_CONTINUOUS = 0x20000
TYPE_EQUIP = 0x40000
TYPE_FIELD = 0x80000
TYPE_ACTION = 0x100000
TYPE_FLIP = 0x200000
TYPE_PENDULUM = 0x400000
TYPE_XYZ = 0x800000
TYPE_LINK = 0x1000000
TYPE_TOON = 0x2000000
TYPE_ARMOR = 0x4000000
TYPE_SKILL = 0x8000000

# -------------------------------------------------------------- attribute bits
ATTRIBUTE_BITS = {
    0x01: "EARTH",
    0x02: "WATER",
    0x04: "FIRE",
    0x08: "WIND",
    0x10: "LIGHT",
    0x20: "DARK",
    0x40: "DIVINE",
}

# ------------------------------------------------------------------- race bits
RACE_BITS = {
    0x1: "WARRIOR",
    0x2: "SPELLCASTER",
    0x4: "FAIRY",
    0x8: "FIEND",
    0x10: "ZOMBIE",
    0x20: "MACHINE",
    0x40: "AQUA",
    0x80: "PYRO",
    0x100: "ROCK",
    0x200: "WINGED_BEAST",
    0x400: "PLANT",
    0x800: "INSECT",
    0x1000: "THUNDER",
    0x2000: "DRAGON",
    0x4000: "BEAST",
    0x8000: "BEAST_WARRIOR",
    0x10000: "DINOSAUR",
    0x20000: "FISH",
    0x40000: "SEA_SERPENT",
    0x80000: "REPTILE",
    0x100000: "PSYCHIC",
    0x200000: "DIVINE_BEAST",
    0x400000: "CREATOR_GOD",
    0x800000: "WYRM",
    0x1000000: "CYBERSE",
    0x2000000: "ILLUSIONIST",
}

# Order matters: the most specific frame wins when several bits are set.
_FRAME_PRECEDENCE = [
    (TYPE_LINK, "LINK"),
    (TYPE_XYZ, "XYZ"),
    (TYPE_SYNCHRO, "SYNCHRO"),
    (TYPE_FUSION, "FUSION"),
    (TYPE_RITUAL, "RITUAL"),
    (TYPE_PENDULUM, "PENDULUM"),
    (TYPE_TOKEN, "TOKEN"),
    (TYPE_SKILL, "SKILL"),
    (TYPE_NORMAL, "NORMAL"),
    (TYPE_EFFECT, "EFFECT"),
]

# Spell/Trap sub-categories. Note: upstream has no TYPE_COUNTER bit — a counter
# trap is simply a TRAP with no other sub-type bit set, hence the "NORMAL" fallback.
_SPELL_TRAP_PRECEDENCE = [
    (TYPE_QUICK_PLAY, "QUICK_PLAY"),
    (TYPE_FIELD, "FIELD"),
    (TYPE_EQUIP, "EQUIP"),
    (TYPE_CONTINUOUS, "CONTINUOUS"),
]

_FLAG_BITS = {
    TYPE_TUNER: "TUNER",
    TYPE_PENDULUM: "PENDULUM",
    TYPE_TOON: "TOON",
    TYPE_SPIRIT: "SPIRIT",
    TYPE_UNION: "UNION",
    TYPE_GEMINI: "GEMINI",
    TYPE_FLIP: "FLIP",
    TYPE_TRAP_MONSTER: "TRAP_MONSTER",
    TYPE_ARMOR: "ARMOR",
    TYPE_MAXIMUM: "MAXIMUM",
}


def has(mask: int | None, bit: int) -> bool:
    return mask is not None and (mask & bit) == bit


def decode_attribute(mask: int | None) -> str | None:
    if not mask:
        return None
    for bit, name in ATTRIBUTE_BITS.items():
        if has(mask, bit):
            return name
    return None


def decode_race(mask: int | None) -> str | None:
    if not mask:
        return None
    for bit, name in RACE_BITS.items():
        if has(mask, bit):
            return name
    return None


def decode_category(mask: int | None) -> str:
    """MONSTER / SPELL / TRAP."""
    if has(mask, TYPE_MONSTER):
        return "MONSTER"
    if has(mask, TYPE_SPELL):
        return "SPELL"
    if has(mask, TYPE_TRAP):
        return "TRAP"
    raise ValueError(f"cannot decode card category from type mask {mask!r}")


def decode_sub_category(mask: int | None, category: str) -> str | None:
    if mask is None:
        return None
    if category == "MONSTER":
        for bit, name in _FRAME_PRECEDENCE:
            if has(mask, bit):
                return name
        return None
    for bit, name in _SPELL_TRAP_PRECEDENCE:
        if has(mask, bit):
            return name
    return "NORMAL" if category in ("SPELL", "TRAP") else None


def decode_flags(mask: int | None) -> set[str]:
    if not mask:
        return set()
    return {name for bit, name in _FLAG_BITS.items() if has(mask, bit)}


# ------------------------------------------------------------- composite fields
def decode_level(level_field: int | None) -> tuple[int | None, int | None]:
    """Return (level_or_rank, pendulum_scale).

    Upstream packs level into bits 0-7 and the pendulum scale into bits 16-31.
    """
    if level_field is None:
        return None, None
    level = level_field & 0xFF
    scale = (level_field >> 16) & 0xFF
    return (level or None), (scale or None)


def decode_link_rating(level_field: int | None, *, is_link: bool) -> int | None:
    if not is_link or level_field is None:
        return None
    return level_field & 0xFF


def decode_setcode(setcode: int | None) -> list[str]:
    """Up to four 16-bit archetype codes packed into one integer."""
    if not setcode:
        return []
    out = []
    for i in range(4):
        code = (setcode >> (16 * i)) & 0xFFFF
        if code:
            out.append(f"{code:04x}")
    return out
