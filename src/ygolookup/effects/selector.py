"""CardSelector — what an effect acts on.

Two rules drive this module:

1. **Numeric conditions are structured comparisons**, never bespoke
   `max_level` / `min_atk` fields. "4星以下" is `{"op": "<=", "value": 4}`.
2. **Quoted card names are masked before any vocabulary lookup.** 「青眼白龙」
   is a name; it is not a Dragon. See `lexicon.mask_quoted`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .lexicon import (
    _ATK_EXACT,
    _ATK_RANGE,
    _COUNT_ALL,
    _COUNT_PATTERN,
    _DEF_EXACT,
    _DEF_RANGE,
    _LEVEL_EXACT,
    _LEVEL_MIN,
    _LEVEL_RANGE,
    _LINK,
    _RANK,
    _UP_TO,
)
from .ontology import (
    ATTRIBUTE_ZH,
    CARD_TYPE_ZH,
    MONSTER_TAG_ZH,
    RACE_ZH,
)

__all__ = ["NumericConstraint", "CardSelector", "parse_selector"]

_VALID_OPS = ("<=", ">=", "==", "<", ">")


@dataclass(frozen=True)
class NumericConstraint:
    """A comparison against a numeric card property."""

    op: str
    value: int

    def __post_init__(self) -> None:
        if self.op not in _VALID_OPS:
            raise ValueError(f"invalid comparison operator: {self.op!r}")
        if not isinstance(self.value, int):
            raise ValueError(f"comparison value must be int, got {self.value!r}")

    def contains(self, other: int) -> bool:
        if self.op == "<=":
            return other <= self.value
        if self.op == ">=":
            return other >= self.value
        if self.op == "==":
            return other == self.value
        if self.op == "<":
            return other < self.value
        return other > self.value

    def to_dict(self) -> dict:
        return {"op": self.op, "value": self.value}

    @classmethod
    def from_dict(cls, data: dict | None) -> "NumericConstraint | None":
        if not data:
            return None
        return cls(op=data["op"], value=data["value"])


@dataclass
class CardSelector:
    """The object an action applies to.

    Every field is either a canonical enum value or `None` meaning "the parser
    did not determine this". `None` is UNKNOWN, never "no constraint".
    """

    card_type: str | None = None
    monster_type: str | None = None
    race: str | None = None
    attribute: str | None = None
    archetype: str | None = None
    name: str | None = None
    level: NumericConstraint | None = None
    rank: NumericConstraint | None = None
    link_rating: NumericConstraint | None = None
    atk: NumericConstraint | None = None
    defense: NumericConstraint | None = None
    count: int | None = None
    count_op: str | None = None  # "==" | "<=" for 最多N / 全部
    tags: list[str] = field(default_factory=list)
    raw_text: str = ""

    def is_empty(self) -> bool:
        return not [
            f
            for f in (
                self.card_type,
                self.monster_type,
                self.race,
                self.attribute,
                self.archetype,
                self.name,
                self.level,
                self.rank,
                self.link_rating,
                self.atk,
                self.defense,
                self.count,
                self.tags,
            )
            if f not in (None, [], "")
        ]

    def to_dict(self) -> dict:
        return {
            "card_type": self.card_type,
            "monster_type": self.monster_type,
            "race": self.race,
            "attribute": self.attribute,
            "archetype": self.archetype,
            "name": self.name,
            "level": self.level.to_dict() if self.level else None,
            "rank": self.rank.to_dict() if self.rank else None,
            "link_rating": self.link_rating.to_dict() if self.link_rating else None,
            "atk": self.atk.to_dict() if self.atk else None,
            "defense": self.defense.to_dict() if self.defense else None,
            "count": self.count,
            "count_op": self.count_op,
            "tags": list(self.tags),
            "raw_text": self.raw_text,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CardSelector":
        return cls(
            card_type=data.get("card_type"),
            monster_type=data.get("monster_type"),
            race=data.get("race"),
            attribute=data.get("attribute"),
            archetype=data.get("archetype"),
            name=data.get("name"),
            level=NumericConstraint.from_dict(data.get("level")),
            rank=NumericConstraint.from_dict(data.get("rank")),
            link_rating=NumericConstraint.from_dict(data.get("link_rating")),
            atk=NumericConstraint.from_dict(data.get("atk")),
            defense=NumericConstraint.from_dict(data.get("defense")),
            count=data.get("count"),
            count_op=data.get("count_op"),
            tags=list(data.get("tags") or []),
            raw_text=data.get("raw_text", ""),
        )


def _first_group(match: re.Match[str] | None) -> str | None:
    if not match:
        return None
    for group in match.groups():
        if group:
            return group
    return None


def _parse_count(masked: str, selector: CardSelector) -> None:
    """数量必须绑定量词（只/张/个/枚），否则「4星以下」的 4 会被误当成数量。"""
    up_to = _UP_TO.search(masked)
    if up_to:
        selector.count = int(up_to.group(1))
        selector.count_op = "<="
        return
    if _COUNT_ALL.search(masked):
        selector.count = None
        selector.count_op = "ALL"
        return
    match = _COUNT_PATTERN.search(masked)
    if match:
        selector.count = int(match.group(1))
        selector.count_op = "=="


def _parse_numeric(masked: str, selector: CardSelector) -> None:
    match = _LEVEL_RANGE.search(masked)
    if match:
        selector.level = NumericConstraint("<=", int(_first_group(match)))
    else:
        match = _LEVEL_MIN.search(masked)
        if match:
            selector.level = NumericConstraint(">=", int(_first_group(match)))
        else:
            match = _LEVEL_EXACT.search(masked)
            if match:
                selector.level = NumericConstraint("==", int(_first_group(match)))

    match = _RANK.search(masked)
    if match:
        selector.rank = NumericConstraint("==", int(_first_group(match)))

    match = _LINK.search(masked)
    if match:
        selector.link_rating = NumericConstraint("==", int(_first_group(match)))

    match = _ATK_RANGE.search(masked)
    if match:
        raw = match.group(0)
        value = int(_first_group(match))
        selector.atk = NumericConstraint("<=" if "以下" in raw else ">=", value)

    match = _DEF_RANGE.search(masked)
    if match:
        raw = match.group(0)
        value = int(_first_group(match))
        selector.defense = NumericConstraint("<=" if "以下" in raw else ">=", value)


def _parse_vocabulary(masked: str, selector: CardSelector) -> None:
    for word, canonical in RACE_ZH.items():
        if word in masked:
            selector.race = canonical
            break
    for word, canonical in ATTRIBUTE_ZH.items():
        if word in masked:
            selector.attribute = canonical
            break
    for word, canonical in CARD_TYPE_ZH.items():
        if word in masked:
            selector.card_type = canonical
            break
    for word, canonical in MONSTER_TAG_ZH.items():
        if word in masked and canonical not in selector.tags:
            selector.tags.append(canonical)


def parse_selector(text: str, *, masked: str | None = None, names: list[str] | None = None) -> CardSelector:
    """Build a CardSelector from one clause.

    `masked` is `text` with 「…」 contents blanked out; `names` carries the
    card names that were masked out.
    """
    selector = CardSelector(raw_text=text)
    working = masked if masked is not None else text

    _parse_count(working, selector)
    _parse_numeric(working, selector)
    _parse_vocabulary(working, selector)

    # 「…」以外 — the quoted name is *excluded* from the selection, so it must
    # not be recorded as the object of the action.
    excluded = bool(re.search(r"「◆+」\s*以外", working))

    for name in names or []:
        if excluded:
            break
        if selector.name is None:
            selector.name = name
            # 「…」怪兽 / 「…」卡 —— the quoted token acts as an archetype.
            tail = working.split("「")[-1] if "「" in working else ""
            if "怪兽" in tail or "卡" in tail:
                selector.archetype = name
    return selector
