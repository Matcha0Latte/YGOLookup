"""Normalize upstream records into canonical `CardRecord`s.

One function per upstream format. Both produce exactly the same model, so the
database layer never needs to know where a card came from.
"""

from __future__ import annotations

import re
from typing import Any

from ..db.models import CardName, CardRecord, ExternalId
from .ygopro import bitmask

# --------------------------------------------------------------------- helpers
_WHITESPACE = re.compile(r"[\s\-_/]+")

# YGOProDeck prints spell/trap sub-types inside `race`.
_YGOPRODECK_RACE_TO_SUB = {
    "Normal": "NORMAL",
    "Quick-Play": "QUICK_PLAY",
    "Continuous": "CONTINUOUS",
    "Equip": "EQUIP",
    "Field": "FIELD",
    "Counter": "COUNTER",
}

_YGOPRODECK_FRAME_TO_CATEGORY = {
    "normal": ("MONSTER", "NORMAL"),
    "effect": ("MONSTER", "EFFECT"),
    "ritual": ("MONSTER", "RITUAL"),
    "fusion": ("MONSTER", "FUSION"),
    "synchro": ("MONSTER", "SYNCHRO"),
    "xyz": ("MONSTER", "XYZ"),
    "link": ("MONSTER", "LINK"),
    "pendulum": ("MONSTER", "PENDULUM"),
    "normal_pendulum": ("MONSTER", "PENDULUM"),
    "effect_pendulum": ("MONSTER", "PENDULUM"),
    "ritual_pendulum": ("MONSTER", "PENDULUM"),
    "fusion_pendulum": ("MONSTER", "PENDULUM"),
    "synchro_pendulum": ("MONSTER", "PENDULUM"),
    "xyz_pendulum": ("MONSTER", "PENDULUM"),
    "spell": ("SPELL", None),
    "trap": ("TRAP", None),
    "skill": ("SPELL", "SKILL"),
    "token": ("MONSTER", "TOKEN"),
}


def slugify(value: str) -> str:
    return _WHITESPACE.sub("-", value.strip()).strip("-").lower()


def _clean_atk_def(value: Any) -> int | None:
    """Upstream encodes a printed '?' as -1. Keep the sentinel, drop None."""
    if value is None:
        return None
    value = int(value)
    return value


# ------------------------------------------------------------------- cards.cdb
def normalize_cdb_row(row: dict[str, Any]) -> CardRecord:
    """`datas` + `texts` join row -> CardRecord."""
    type_mask = row.get("type")
    category = bitmask.decode_category(type_mask)
    sub_category = bitmask.decode_sub_category(type_mask, category)
    level, scale = bitmask.decode_level(row.get("level"))
    is_link = sub_category == "LINK"

    race = bitmask.decode_race(row.get("race"))
    attribute = bitmask.decode_attribute(row.get("attribute"))

    if category != "MONSTER":
        # For spells/traps the upstream 'race' field carries the sub-type.
        race = None
        attribute = None
        level = None
        scale = None

    archetypes = [(f"setcode-{code}", code) for code in bitmask.decode_setcode(row.get("setcode"))]

    record = CardRecord(
        canonical_name=(row.get("name") or "").strip(),
        card_category=category,
        raw_text=(row.get("desc") or "").strip(),
        text_lang="en",
        sub_category=sub_category,
        race=race,
        attribute=attribute,
        level_rank=level,
        link_rating=bitmask.decode_link_rating(row.get("level"), is_link=is_link),
        pendulum_scale=scale,
        atk=_clean_atk_def(row.get("atk")),
        defense=_clean_atk_def(row.get("def")),
        type_mask=type_mask,
        race_mask=row.get("race"),
        attribute_mask=row.get("attribute"),
        category_mask=row.get("category"),
        setcode_mask=row.get("setcode"),
        alias_passcode=row.get("alias") or None,
        external_ids=[ExternalId("ygopro_passcode", str(row.get("id")))],
        archetypes=archetypes,
        flags=bitmask.decode_flags(type_mask),
    )
    if is_link:
        record.defense = None
    return record


# --------------------------------------------------------------- YGOProDeck JSON
def normalize_ygoprodeck_record(rec: dict[str, Any]) -> CardRecord:
    """YGOProDeck cardinfo.php entry -> CardRecord."""
    frame = (rec.get("frameType") or "").strip()
    category, sub_category = _YGOPRODECK_FRAME_TO_CATEGORY.get(frame, (None, None))

    if category is None:  # frameType missing / unknown -> fall back to `type`
        category, sub_category = _category_from_type_string(rec.get("type") or "")

    raw_race = (rec.get("race") or "").strip()
    is_monster = category == "MONSTER"
    race = None
    attribute = None

    if is_monster:
        race = slugify(raw_race).upper()
        attribute = (rec.get("attribute") or "").strip().upper() or None
        if sub_category is None:
            sub_category = "EFFECT" if "Effect" in (rec.get("type") or "") else "NORMAL"
    else:
        sub_category = sub_category or _YGOPRODECK_RACE_TO_SUB.get(raw_race, "NORMAL")

    level = rec.get("level")
    scale = rec.get("scale")
    link_rating = rec.get("linkval")

    flags: set[str] = set()
    if is_monster:
        if "pendulum" in frame:
            flags.add("PENDULUM")
        type_str = (rec.get("type") or "").lower()
        for token, flag in (
            ("tuner", "TUNER"),
            ("toon", "TOON"),
            ("spirit", "SPIRIT"),
            ("union", "UNION"),
            ("gemini", "GEMINI"),
            ("flip", "FLIP"),
        ):
            if token in type_str:
                flags.add(flag)

    archetype_raw = (rec.get("archetype") or "").strip()
    archetypes = [(slugify(archetype_raw), archetype_raw)] if archetype_raw else []

    passcode = _first_passcode(rec)

    return CardRecord(
        canonical_name=(rec.get("name") or "").strip(),
        card_category=category,
        raw_text=(rec.get("desc") or "").strip(),
        text_lang="en",
        sub_category=sub_category,
        race=race,
        attribute=attribute,
        level_rank=int(level) if level else None,
        link_rating=int(link_rating) if link_rating else None,
        pendulum_scale=int(scale) if scale else None,
        atk=_clean_atk_def(rec.get("atk")) if is_monster else None,
        defense=_clean_atk_def(rec.get("def")) if (is_monster and not link_rating) else None,
        external_ids=[
            eid
            for eid in (
                ExternalId("ygopro_passcode", str(passcode)) if passcode else None,
                ExternalId("ygoprodeck_id", str(rec["id"])) if rec.get("id") is not None else None,
            )
            if eid
        ],
        archetypes=archetypes,
        flags=flags,
    )


def _first_passcode(rec: dict[str, Any]) -> int | None:
    for image in rec.get("card_images") or []:
        if image.get("id"):
            return int(image["id"])
    return rec.get("id")


def _category_from_type_string(type_str: str) -> tuple[str, str | None]:
    t = (type_str or "").lower()
    if "monster" in t:
        for token, sub in (
            ("link", "LINK"),
            ("xyz", "XYZ"),
            ("synchro", "SYNCHRO"),
            ("fusion", "FUSION"),
            ("ritual", "RITUAL"),
            ("token", "TOKEN"),
        ):
            if token in t:
                return "MONSTER", sub
        return "MONSTER", ("EFFECT" if "effect" in t else "NORMAL")
    if "spell" in t:
        return "SPELL", "NORMAL"
    if "trap" in t:
        return "TRAP", "NORMAL"
    if "skill" in t:
        return "SPELL", "SKILL"
    raise ValueError(f"cannot decode card category from type string {type_str!r}")


def attach_name_variants(record: CardRecord, extra_names: list[tuple[str, str, str]]) -> CardRecord:
    """extra_names: list of (lang, name, kind)."""
    for lang, name, kind in extra_names:
        if not name:
            continue
        entry = CardName(lang=lang, name=name, kind=kind, is_primary=False)
        if entry not in record.names:
            record.names.append(entry)
    return record
