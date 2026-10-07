"""EffectUnit -> Clause.

The second stage of the pipeline:

    EffectUnit  ->  Clause[]

Clause roles follow the OCG text standard. The critical rule is that
**CONDITION and COST both sit in front of the activation anchor**, and the way
to tell them apart is *not* the anchor wording itself:

    「自己场上没有怪兽存在的场合才能发动」      -> CONDITION (a state)
    「把墓地的1只光属性怪兽除外才能发动」      -> COST      (something is paid)

So everything in front of 「发动」 is segmented, and each segment becomes a COST
only when it contains a payable action.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .lexicon import (
    RESTRICTION_PATTERNS,
    TARGET_PATTERN,
    find_activation_anchor,
    has_cost_verb,
    looks_like_condition,
)
from .ontology import ClauseRole, ExtractedBy, Tri, UnitKind
from .units import EffectUnit

__all__ = ["Clause", "split_clauses"]

_COMMA = re.compile(r"[，,]")
_PERIOD = re.compile(r"[。;；]")

# "…的场合，X" / "只要…，X" — a continuous effect introduced by a state.
_LEADING_CONDITION = re.compile(r"^(.+?(?:的场合|时|只要.+?))\s*[，,]\s*(.+)$")

# Confidence per role: how much we trust the *classification*, not the content.
_ROLE_CONFIDENCE = {
    ClauseRole.RESTRICTION: 0.8,
    ClauseRole.TARGET: 0.9,
    ClauseRole.COST: 0.75,
    ClauseRole.CONDITION: 0.7,
    ClauseRole.RESOLUTION: 0.6,
    ClauseRole.UNKNOWN: 0.2,
}


@dataclass
class Clause:
    """One semantic component of an effect."""

    index: int
    role: ClauseRole
    raw_text: str
    start: int = 0
    end: int = 0
    confidence: float = 0.0
    extracted_by: ExtractedBy = ExtractedBy.GRAMMAR
    once_per_turn: Tri = Tri.UNKNOWN

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "role": self.role.value,
            "raw_text": self.raw_text,
            "start": self.start,
            "end": self.end,
            "confidence": self.confidence,
            "extracted_by": self.extracted_by.value,
            "once_per_turn": self.once_per_turn.value,
        }


def _segments(text: str, pattern: re.Pattern[str]) -> list[tuple[int, int, str]]:
    """Split on separators, keeping offsets into the original text."""
    out: list[tuple[int, int, str]] = []
    pos = 0
    for match in pattern.finditer(text):
        chunk = text[pos : match.start()].strip()
        if chunk:
            out.append((text.index(chunk, pos), match.start(), chunk))
        pos = match.end()
    tail = text[pos:].strip()
    if tail:
        out.append((text.index(tail, pos), len(text), tail))
    return out or ([(0, len(text), text.strip())] if text.strip() else [])


def _make(index: int, role: ClauseRole, start: int, end: int, raw: str, once: Tri) -> Clause:
    return Clause(
        index=index,
        role=role,
        raw_text=raw,
        start=start,
        end=end,
        confidence=_ROLE_CONFIDENCE[role],
        once_per_turn=once,
    )


def _classify_pre_anchor(segment: str) -> ClauseRole:
    """Classify a segment sitting in front of the activation anchor."""
    if TARGET_PATTERN.search(segment):
        return ClauseRole.TARGET
    if has_cost_verb(segment):
        return ClauseRole.COST
    if looks_like_condition(segment):
        return ClauseRole.CONDITION
    # In front of the anchor and neither payable nor a state: safest is
    # UNKNOWN rather than guessing a cost.
    return ClauseRole.UNKNOWN


def _is_restriction_sentence(segment: str) -> bool:
    return any(p.search(segment) for p in RESTRICTION_PATTERNS)


def split_clauses(unit: EffectUnit) -> list[Clause]:
    """Split one unit into clauses."""
    text = unit.raw_text.strip()
    if not text:
        return []

    once = Tri.TRUE if "1回合1次" in text or "1回合各能使用1次" in text else Tri.UNKNOWN

    if unit.kind is UnitKind.MATERIAL:
        return []

    if unit.kind is UnitKind.RESTRICTION:
        return [_make(0, ClauseRole.RESTRICTION, 0, len(text), text, once)]

    clauses: list[Clause] = []
    anchor = find_activation_anchor(text)

    if anchor is not None:
        pre = text[: anchor.start()].strip(" ，,。")
        post = text[anchor.end() :].strip(" ，,。")

        for start, end, segment in _segments(pre, _COMMA):
            role = _classify_pre_anchor(segment)
            clauses.append(_make(len(clauses), role, start, end, segment, once))

        if post:
            for start, end, segment in _segments(post, _PERIOD):
                absolute = anchor.end() + start
                clauses.append(
                    _make(
                        len(clauses),
                        ClauseRole.RESOLUTION,
                        absolute,
                        anchor.end() + end,
                        segment,
                        once,
                    )
                )

    # No activation anchor: a continuous effect, a summoning procedure, or a
    # bare restriction. Split on sentence boundaries and classify each.
    else:
        for start, end, segment in _segments(text, _PERIOD):
            # "…的场合，X" — a continuous effect guarded by a state. Split it so
            # the state does not get mixed into the effect itself.
            lead = _LEADING_CONDITION.match(segment)
            if lead:
                head_text = lead.group(1).strip()
                tail_text = lead.group(2).strip()
                clauses.append(_make(len(clauses), ClauseRole.CONDITION, start, start + len(head_text), head_text, once))
                if tail_text:
                    clauses.append(
                        _make(len(clauses), ClauseRole.RESOLUTION, start + len(head_text), end, tail_text, once)
                    )
                continue

            if _is_restriction_sentence(segment) and not has_cost_verb(segment):
                clauses.append(_make(len(clauses), ClauseRole.RESTRICTION, start, end, segment, once))
                continue
            if TARGET_PATTERN.search(segment) and not has_cost_verb(segment):
                clauses.append(_make(len(clauses), ClauseRole.TARGET, start, end, segment, once))
                continue
            # A summoning procedure ("…的场合可以特殊召唤") is a condition on
            # how the card may be summoned — it is not a cost. Full summoning
            # procedures are out of scope for v1; CONDITION is the honest role.
            if "特殊召唤" in segment and ("场合" in segment or "可以" in segment):
                clauses.append(_make(len(clauses), ClauseRole.CONDITION, start, end, segment, once))
                continue
            if looks_like_condition(segment) and has_cost_verb(segment):
                clauses.append(_make(len(clauses), ClauseRole.COST, start, end, segment, once))
                continue
            clauses.append(_make(len(clauses), ClauseRole.RESOLUTION, start, end, segment, once))

    if not clauses:
        clauses.append(_make(0, ClauseRole.UNKNOWN, 0, len(text), text, once))
    return clauses
