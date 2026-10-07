"""Clause -> Predicate.

The third stage of the pipeline:

    Clause  ->  Predicate[]

A clause may hold several actions ("那只怪兽回到手卡，这张卡从手卡特殊召唤。"),
so it produces several predicates. Each predicate keeps:

* the canonical English enum values (machine protocol)
* the Chinese span it came from (`source_text`) so every claim is traceable
* `action_known` — False means UNKNOWN, never "the card does not do this"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .clauses import Clause, split_clauses
from .lexicon import (
    ACTION_DEFAULT_SOURCE,
    mask_quoted,
    extract_quoted_names,
    find_actions,
    detect_destination_zone,
    detect_source_zone,
    is_negated,
)
from .ontology import (
    Action,
    ClauseRole,
    EffectScope,
    ExtractedBy,
    ParseStatus,
    Subject,
    UnitKind,
    Zone,
)
from .selector import CardSelector, parse_selector
from .units import EffectUnit

__all__ = ["Predicate", "ParsedClause", "ParsedUnit", "parse_clause", "parse_unit"]

# Actions that put a card somewhere a later clause can refer back to.
_RESULT_PRODUCING = frozenset(
    {
        Action.SPECIAL_SUMMON,
        Action.NORMAL_SUMMON,
        Action.TRIBUTE_SUMMON,
        Action.FUSION_SUMMON,
        Action.RITUAL_SUMMON,
        Action.SYNCHRO_SUMMON,
        Action.XYZ_SUMMON,
        Action.LINK_SUMMON,
        Action.ADD_TO_HAND,
        Action.SEARCH,
        Action.RETURN_TO_HAND,
        Action.SET_CARD,
        Action.EQUIP,
    }
)

# Chinese anaphora that points back at something a previous clause produced.
# 「这张卡」means the card itself, so it is deliberately NOT anaphora.
_ANAPHORA = ("那只", "那张", "那些", "那个", "其效果", "其")

# Clause roles that owe us an action. A CONDITION or TARGET clause is complete
# with just a state or an object, so a missing action there is not a failure.
_ACTION_REQUIRED_ROLES = frozenset(
    {ClauseRole.RESOLUTION, ClauseRole.COST, ClauseRole.UNKNOWN}
)


@dataclass
class Predicate:
    index: int
    subject: Subject = Subject.UNKNOWN
    action: Action | None = None
    action_known: bool = False
    source_zone: Zone | None = None
    destination_zone: Zone | None = None
    object: CardSelector = field(default_factory=CardSelector)
    result_ref: str | None = None
    object_ref: str | None = None
    modifiers: dict = field(default_factory=dict)
    confidence: float = 0.0
    extracted_by: ExtractedBy = ExtractedBy.RULE
    source_text: str = ""
    source_span: tuple[int, int] = (0, 0)

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "subject": self.subject.value,
            "action": self.action.value if self.action else None,
            "action_known": self.action_known,
            "source_zone": self.source_zone.value if self.source_zone else None,
            "destination_zone": self.destination_zone.value if self.destination_zone else None,
            "object": self.object.to_dict(),
            "result_ref": self.result_ref,
            "object_ref": self.object_ref,
            "modifiers": dict(self.modifiers),
            "confidence": self.confidence,
            "extracted_by": self.extracted_by.value,
            "source_text": self.source_text,
            "source_span": list(self.source_span),
        }


@dataclass
class ParsedClause:
    clause: Clause
    predicates: list[Predicate] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "clause": self.clause.to_dict(),
            "predicates": [p.to_dict() for p in self.predicates],
        }


@dataclass
class ParsedUnit:
    unit: EffectUnit
    clauses: list[ParsedClause] = field(default_factory=list)

    @property
    def status(self) -> ParseStatus:
        # A material line or a card-wide restriction has no action to resolve;
        # reporting it as UNRESOLVED would inflate the failure count.
        if self.unit.kind in (UnitKind.MATERIAL, UnitKind.RESTRICTION):
            return ParseStatus.OK

        # CONDITION / TARGET / RESTRICTION clauses describe a state or an object
        # and are complete without an action; a missing action there is not a
        # parser failure. Only RESOLUTION / COST / UNKNOWN owe us an action.
        predicates = [
            p
            for c in self.clauses
            for p in c.predicates
            if c.clause.role in _ACTION_REQUIRED_ROLES
        ]
        if not predicates:
            return ParseStatus.UNRESOLVED
        known = [p for p in predicates if _resolved(p)]
        if not known:
            return ParseStatus.UNRESOLVED
        return ParseStatus.OK if len(known) == len(predicates) else ParseStatus.PARTIAL

    def to_dict(self) -> dict:
        return {
            "unit": self.unit.to_dict(),
            "status": self.status.value,
            "clauses": [c.to_dict() for c in self.clauses],
        }


def _resolved(predicate: "Predicate") -> bool:
    """Whether a predicate says something definite.

    Two ways to be definite: we recognised the action, or we recognised that
    the action is *negated* ("这张卡不能通常召唤" is a resolved fact, not a
    parser failure).
    """
    return predicate.action_known or "negated_action" in predicate.modifiers


def _detect_subject(text: str) -> Subject:
    if "对方" in text:
        return Subject.OPPONENT
    if "自己" in text:
        return Subject.SELF
    if "双方" in text or "玩家" in text:
        return Subject.PLAYER
    return Subject.ANY


def _confidence(action: Action | None, source: Zone | None, destination: Zone | None, selector: CardSelector) -> float:
    score = 0.25
    if action is not None:
        score += 0.35
    if source is not None:
        score += 0.15
    if destination is not None:
        score += 0.10
    if not selector.is_empty():
        score += 0.15
    return round(min(score, 1.0), 3)


_SEPARATORS = re.compile(r"[，,；;]")


def _window(masked: str, actions: list, position: int) -> tuple[int, int]:
    """Text slice belonging to one action.

    Chinese puts the object *in front of* the verb ("把墓地的1只光属性怪兽除
    外"), so the slice has to start at the previous action rather than at this
    one, and it ends at the next action so two actions in one clause do not
    share a noun phrase.

    Both edges are then pulled in to the nearest comma: in
    「自己从卡组抽1张卡，那之后自己墓地的1只怪兽除外。」 the DRAW object must
    stop at the comma, otherwise it picks up the monster that belongs to the
    banish.
    """
    start = actions[position - 1][2] if position > 0 else 0
    stop = actions[position + 1][1] if position + 1 < len(actions) else len(masked)
    stop = min(max(stop, start), len(masked))

    action_start, action_end = actions[position][1], actions[position][2]
    head = list(_SEPARATORS.finditer(masked, start, action_start))
    if head:
        start = head[-1].end()
    tail = _SEPARATORS.search(masked, action_end, stop)
    if tail:
        # Match offsets are absolute, not relative to the search start.
        stop = tail.start()
    return start, max(stop, start)


def parse_clause(clause: Clause, *, unit: EffectUnit | None = None) -> ParsedClause:
    text = clause.raw_text.strip()
    parsed = ParsedClause(clause=clause)
    if not text:
        return parsed

    masked = mask_quoted(text)
    names = extract_quoted_names(text)
    actions = find_actions(masked)

    if not actions:
        # No action recognised. This is UNKNOWN, not "nothing happens".
        parsed.predicates.append(
            Predicate(
                index=0,
                subject=_detect_subject(text),
                object=parse_selector(text, masked=masked, names=names),
                confidence=0.15,
                extracted_by=ExtractedBy.RULE,
                source_text="",
                source_span=(0, len(text)),
            )
        )
        return parsed

    for position, (action, start, end, matched) in enumerate(actions):
        slice_start, slice_stop = _window(masked, actions, position)
        slice_text = masked[slice_start:slice_stop]
        original = text[slice_start:slice_stop]

        # Source is looked for in front of the action, destination behind it.
        # Source is read from this action's own head: from where the previous
        # action ended up to this action's end. Using the inter-action span
        # avoids stealing the *next* action's "从手卡／从卡组".
        head = masked[slice_start:end]
        source = detect_source_zone(head)
        destination = detect_destination_zone(masked[start:slice_stop], action)
        if source is None and action is not None:
            source = ACTION_DEFAULT_SOURCE.get(action)

        selector = parse_selector(original, masked=slice_text, names=names)

        modifiers: dict = {}
        if clause.once_per_turn.value == "TRUE":
            modifiers["once_per_turn"] = True
        if "最多" in text:
            modifiers["up_to"] = True

        # A negated action is not a claim: "这张卡不能通常召唤" must not become
        # NORMAL_SUMMON. The value is kept as a modifier so nothing is lost.
        if is_negated(masked, start):
            modifiers["negated_action"] = action.value
            parsed.predicates.append(
                Predicate(
                    index=position,
                    subject=_detect_subject(text),
                    object=selector,
                    modifiers=modifiers,
                    confidence=0.15,
                    source_text=matched,
                    source_span=(start, end),
                )
            )
            continue

        # "从卡组…加入手卡" is the player-facing concept SEARCH.
        if action is Action.ADD_TO_HAND and source is Zone.DECK and destination is Zone.HAND:
            action = Action.SEARCH

        parsed.predicates.append(
            Predicate(
                index=position,
                subject=_detect_subject(text),
                action=action,
                action_known=True,
                source_zone=source,
                destination_zone=destination,
                object=selector,
                modifiers=modifiers,
                confidence=_confidence(action, source, destination, selector),
                source_text=matched,
                source_span=(start, end),
            )
        )
    return parsed


def parse_unit(unit: EffectUnit) -> ParsedUnit:
    """Full unit -> clauses -> predicates, with simple anaphora wiring."""
    parsed = ParsedUnit(unit=unit)

    if unit.kind is UnitKind.MATERIAL:
        return parsed

    for clause in split_clauses(unit):
        parsed.clauses.append(parse_clause(clause, unit=unit))

    _wire_references(parsed)
    return parsed


def _wire_references(parsed: ParsedUnit) -> None:
    """Link a produced object to a later clause that refers back to it.

    Deliberately narrow: the reference must live in a **different clause** than
    the antecedent, and that clause must *start* with an anaphora. This matches
    the shape 「特殊召唤1只怪兽。那只怪兽的效果无效。」 without producing
    nonsense for 「那只怪兽回到手卡，这张卡从手卡特殊召唤。」, where both
    actions sit in one clause and 「这张卡」means the card itself.

    An antecedent is either a TARGET clause (「以…为对象」 — the object is
    named there, not produced) or a result-producing action.

    Full rule-graph reasoning is out of scope for v1.
    """
    for position, parsed_clause in enumerate(parsed.clauses):
        if parsed_clause.clause.role is ClauseRole.TARGET:
            antecedent = parsed_clause.predicates[0] if parsed_clause.predicates else None
        else:
            antecedent = next(
                (p for p in parsed_clause.predicates if p.action in _RESULT_PRODUCING), None
            )
        if antecedent is None:
            continue

        for later in parsed.clauses[position + 1 :]:
            head = later.clause.raw_text.strip()
            if not any(head.startswith(token) for token in _ANAPHORA):
                continue
            ref = f"ref_{position + 1}"
            antecedent.result_ref = ref
            for predicate in later.predicates:
                predicate.object_ref = ref
            break
