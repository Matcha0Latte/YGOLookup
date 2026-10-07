"""Card text -> EffectUnit.

The first stage of the pipeline:

    card text  ->  EffectUnit[]

Splitting rules come from the OCG text standard (see
`docs/chinese-text-spec.md`):

* numbered effects are separated by ① ② ③ … followed by a full-width colon
* a restriction that applies to the whole card sits *before* every numbered
  effect and belongs to no single one
* pendulum text (`pdesc`) and monster text (`desc`) are different scopes
* summoning-material lines are stored but are NOT effects
* `●` items inside a numbered effect are separate sub-effects
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .lexicon import (
    MATERIAL_PATTERN,
    NUMBER_MARKERS,
    NUMBER_MARKER_PATTERN,
    RESTRICTION_PATTERNS,
)
from .ontology import EffectScope, UnitKind

__all__ = ["EffectUnit", "split_units", "split_card_text", "normalize_text"]

_BULLET = "●"

# A whole-card restriction always mentions a counted use.
_GLOBAL_RESTRICTION = re.compile(
    r"(?:这个卡名|「[^」]+」)[^。]*?1回合(?:各能|只能|仅能|各只能)使用\d*次"
)

# Summoning conditions and rule text are restrictions, not effects.
_PURE_RESTRICTION = re.compile(r"不能通常召唤|只能有1只表侧表示存在|在规则上当作")

# "衍生物2只" / "2只效果怪兽" / "调整＋1只以上调整以外的怪兽"
_MATERIAL_LOOK = re.compile(r"^[^\n。：①]*[＋+][^\n。：①]*$|^(?:\d+只以上|[^\n。：①]{0,20})(?:怪兽|衍生物|调整)[^\n。：①]{0,10}$")


def normalize_text(text: str) -> str:
    """`\\r\\n` is how the upstream source encodes newlines (8,453 cards)."""
    if not text:
        return ""
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


@dataclass
class EffectUnit:
    """One independent effect (or a non-effect text block)."""

    index: int
    scope: EffectScope
    kind: UnitKind
    raw_text: str
    marker: str | None = None
    sub_index: int = 0

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "scope": self.scope.value,
            "kind": self.kind.value,
            "raw_text": self.raw_text,
            "marker": self.marker,
            "sub_index": self.sub_index,
        }


def _is_material_line(line: str) -> bool:
    if not line or "：" in line or "。" in line:
        return False
    if NUMBER_MARKER_PATTERN.match(line):
        return False
    return bool(MATERIAL_PATTERN.match(line) or _MATERIAL_LOOK.match(line))


def _is_global_restriction(line: str) -> bool:
    """Whether an unnumbered block is card-wide rule text rather than an effect.

    The `发动` guard matters: 「1回合1次，把1张手卡丢弃才能发动。…」 is a real
    effect that happens to be unnumbered, while 「这个卡名的效果1回合只能使用
    1次」 or 「这张卡不能通常召唤」 applies to the whole card.
    """
    if NUMBER_MARKER_PATTERN.match(line):
        return False
    if "发动" in line:
        return False
    return bool(_GLOBAL_RESTRICTION.search(line) or _PURE_RESTRICTION.search(line))


def _split_numbered(text: str) -> list[tuple[str | None, str]]:
    """Split on ①： / ②： … keeping any preamble as an unnumbered block."""
    matches = list(re.finditer(rf"([{NUMBER_MARKERS}])\s*[：:]", text))
    if not matches:
        return [(None, text)]

    out: list[tuple[str | None, str]] = []
    preamble = text[: matches[0].start()].strip()
    if preamble:
        out.append((None, preamble))

    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            out.append((match.group(1), body))
    return out


def _split_bullets(chunk: str) -> list[str]:
    if _BULLET not in chunk:
        return [chunk]
    head, _, rest = chunk.partition(_BULLET)
    parts = []
    if head.strip(" \n:："):
        parts.append(head.strip(" \n:："))
    for item in rest.split(_BULLET):
        item = item.strip()
        if item:
            parts.append(item)
    return parts or [chunk]


def split_units(text: str, *, scope: EffectScope = EffectScope.MAIN, start_index: int = 0) -> list[EffectUnit]:
    """Split one text block into units."""
    text = normalize_text(text)
    if not text:
        return []

    units: list[EffectUnit] = []
    index = start_index

    for marker, chunk in _split_numbered(text):
        pieces = _split_bullets(chunk) if marker else [chunk]
        for sub_index, piece in enumerate(pieces):
            piece = piece.strip()
            if not piece:
                continue

            if marker is None:
                if _is_material_line(piece):
                    kind = UnitKind.MATERIAL
                elif _is_global_restriction(piece):
                    kind = UnitKind.RESTRICTION
                else:
                    kind = UnitKind.UNNUMBERED
            elif sub_index > 0:
                kind = UnitKind.NUMBERED
            else:
                kind = UnitKind.NUMBERED

            units.append(
                EffectUnit(
                    index=index,
                    scope=scope,
                    kind=kind,
                    raw_text=piece,
                    marker=marker,
                    sub_index=sub_index,
                )
            )
            index += 1

    return units


def split_card_text(
    *,
    desc: str,
    pdesc: str = "",
    pendulum: bool = False,
) -> list[EffectUnit]:
    """Full card -> ordered units across both text blocks.

    Pendulum effects come first because that is how the card reads.
    """
    units: list[EffectUnit] = []
    if pendulum and normalize_text(pdesc):
        units.extend(split_units(pdesc, scope=EffectScope.PENDULUM, start_index=0))
    monster_scope = EffectScope.MONSTER if pendulum else EffectScope.MAIN
    units.extend(split_units(desc, scope=monster_scope, start_index=len(units)))
    return units
