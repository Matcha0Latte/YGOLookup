"""Deterministic effect parser.

Scope: translate the *high frequency* phrasing of YGOPro English card text into
`EffectPredicate`s. It is a recall-oriented first pass — anything it cannot
determine is left as `UNKNOWN` rather than guessed.

Explicit non-goals (handled by later layers, not here):
  * full rulings semantics
  * Japanese / Chinese text
  * long narrative clauses that need LLM extraction

The parser never raises on unexpected input; it degrades to a single
RESOLUTION predicate with `action = None`.
"""

from __future__ import annotations

import re

from .ontology import (
    ATTRIBUTE_VOCABULARY,
    RACE_VOCABULARY,
    Action,
    EffectPart,
    SegmentMarker,
    Tri,
    Zone,
    normalize_race_token,
)
from .schema import EffectPredicate, EffectSegment, ParsedEffect, TargetConstraint

# ------------------------------------------------------------------ clause split
_CONDITION_COST_SPLIT = re.compile(r"\s*;\s*", re.IGNORECASE)
_TRIGGER_SPLIT = re.compile(r"\s*:\s*")

_CLAUSE_CONNECTORS = re.compile(
    r",\s*(?:and if you do,?\s*|and if you do|then\s*|and\s*)|;\s*", re.IGNORECASE
)

_RESTRICTION_PATTERNS = (
    re.compile(r"you can only use (?:this|the) effect of .*? once per turn", re.IGNORECASE),
    re.compile(r"you can only activate \d+ .*? per turn", re.IGNORECASE),
    re.compile(r"you can only use each effect of .*? once per turn", re.IGNORECASE),
    re.compile(r"you cannot .*? for the rest of this turn", re.IGNORECASE),
    re.compile(r"for the rest of this turn", re.IGNORECASE),
)

# ------------------------------------------------------------------- zone rules
# Order matters: EXTRA_DECK must be tested before DECK.
_ZONE_PATTERNS: tuple[tuple[re.Pattern[str], Zone], ...] = (
    (re.compile(r"from (?:your|their|the) Extra Deck|in (?:your|their) Extra Deck", re.IGNORECASE), Zone.EXTRA_DECK),
    (
        re.compile(
            r"from (?:your|their|the) (?:Main )?Deck|in (?:your|their) Deck"
            r"|of (?:your|their|the) Deck|from the top of (?:your|their) Deck",
            re.IGNORECASE,
        ),
        Zone.DECK,
    ),
    (re.compile(r"from (?:your|their|the) hand|in (?:your|their) hand", re.IGNORECASE), Zone.HAND),
    (re.compile(r"from (?:your|their|the) (?:Graveyard|GY)|in (?:your|their) (?:Graveyard|GY)", re.IGNORECASE), Zone.GRAVEYARD),
    (re.compile(r"from (?:your|their) banishment|among (?:your|their) banished|that (?:is|are) banished|your banished", re.IGNORECASE), Zone.BANISHED),
    (re.compile(r"in (?:your|their) Pendulum Zone", re.IGNORECASE), Zone.PENDULUM_ZONE),
    (re.compile(r"on the field|on (?:your|their) field|you control|they control", re.IGNORECASE), Zone.FIELD),
)

_DESTINATION_PATTERNS: tuple[tuple[re.Pattern[str], Zone], ...] = (
    (re.compile(r"to (?:your|their|the) hand", re.IGNORECASE), Zone.HAND),
    (re.compile(r"to (?:your|their|the) (?:Graveyard|GY)", re.IGNORECASE), Zone.GRAVEYARD),
    (re.compile(r"to (?:your|their|the) (?:Main )?Deck|into (?:your|their|the) Deck", re.IGNORECASE), Zone.DECK),
    (re.compile(r"to (?:your|their) (?:side of the )?field", re.IGNORECASE), Zone.FIELD),
)

# ----------------------------------------------------------------- action rules
# First match wins; ordered from most specific to most generic.
_ACTION_PATTERNS: tuple[tuple[re.Pattern[str], Action], ...] = (
    (re.compile(r"\bspecial summon", re.IGNORECASE), Action.SPECIAL_SUMMON),
    (re.compile(r"\bnormal summon", re.IGNORECASE), Action.NORMAL_SUMMON),
    (re.compile(r"\btribute summon", re.IGNORECASE), Action.TRIBUTE_SUMMON),
    (re.compile(r"\badd\b.*?\bto (?:your|their) hand\b", re.IGNORECASE | re.DOTALL), Action.ADD_TO_HAND),
    (re.compile(r"\bdraw\b", re.IGNORECASE), Action.DRAW),
    (re.compile(r"\bbanish\b", re.IGNORECASE), Action.BANISH),
    (re.compile(r"\bexcavate\b", re.IGNORECASE), Action.EXCAVATE),
    (re.compile(r"\bsend\b.*?\bto the (?:Graveyard|GY)\b", re.IGNORECASE | re.DOTALL), Action.SEND_TO_GRAVEYARD),
    (re.compile(r"\bmill\b", re.IGNORECASE), Action.MILL),
    (re.compile(r"\bdestroy\b", re.IGNORECASE), Action.DESTROY),
    (re.compile(r"\bnegate\b", re.IGNORECASE), Action.NEGATE),
    (re.compile(r"\breturn\b.*?\bto (?:the|your|their) hand\b", re.IGNORECASE | re.DOTALL), Action.RETURN_TO_HAND),
    (re.compile(r"\breturn\b.*?\bto (?:the|your|their) (?:Main )?Deck\b|\bshuffle\b.*?\binto the Deck\b", re.IGNORECASE | re.DOTALL), Action.RETURN_TO_DECK),
    (re.compile(r"\bdiscard\b", re.IGNORECASE), Action.DISCARD),
    (re.compile(r"\bdetach\b", re.IGNORECASE), Action.DETACH),
    (re.compile(r"\battach\b", re.IGNORECASE), Action.ATTACH),
    (re.compile(r"\btribute\b", re.IGNORECASE), Action.TRIBUTE),
    (re.compile(r"\breveal\b", re.IGNORECASE), Action.REVEAL),
    (re.compile(r"\bgain control\b", re.IGNORECASE), Action.GAIN_CONTROL),
    (re.compile(r"\bequip\b", re.IGNORECASE), Action.EQUIP),
    (re.compile(r"\bgains?\b.*?\bATK\b|\bATK\b.*?\bincreas", re.IGNORECASE | re.DOTALL), Action.INCREASE_ATK),
    (re.compile(r"\blose\b.*?\bATK\b|\breduc\b.*?\bATK\b", re.IGNORECASE | re.DOTALL), Action.DECREASE_ATK),
    (re.compile(r"\bchange\b.*?\bposition\b|\bchange\b.*?\bto face-(?:up|down)", re.IGNORECASE | re.DOTALL), Action.CHANGE_POSITION),
    (re.compile(r"\bcannot be destroyed\b", re.IGNORECASE), Action.PREVENT_DESTRUCTION),
    (re.compile(r"\bcannot (?:be )?activate\b", re.IGNORECASE), Action.PREVENT_ACTIVATION),
    (re.compile(r"\bshuffle\b", re.IGNORECASE), Action.SHUFFLE),
)

# Actions that are legal as a COST.
_COST_ACTIONS = frozenset(
    {
        Action.BANISH,
        Action.DISCARD,
        Action.TRIBUTE,
        Action.SEND_TO_GRAVEYARD,
        Action.DETACH,
        Action.MILL,
        Action.REVEAL,
        Action.SHUFFLE,
        Action.RETURN_TO_HAND,
        Action.RETURN_TO_DECK,
    }
)

# ------------------------------------------------------- constraint expressions
_COUNT_EXACT = re.compile(
    r"\b(\d+|one|two|three)\s+(?:\+\s*)?(?:\S+\s+){0,8}?(?:monster|card|monsters|cards)\b",
    re.IGNORECASE,
)
_COUNT_UP_TO = re.compile(r"\bup to (\d+|one|two|three)\b", re.IGNORECASE)
_WORD_NUMBER = {"one": 1, "two": 2, "three": 3}

_LEVEL_RANGE = re.compile(r"\bLevel (\d+)\s*(or (?:lower|less|higher|more))?", re.IGNORECASE)
_RANK = re.compile(r"\bRank (\d+)\b", re.IGNORECASE)
_LINK = re.compile(r"\bLink-?\s?(\d+)\b|\bLink Rating (\d+)\b", re.IGNORECASE)
_ATK_RANGE = re.compile(r"(?:with\s+)?(\d+)\s+or\s+(more|less)\s+ATK\b|\bATK\s+(\d+)\s+or\s+(more|less)\b", re.IGNORECASE)
_ATK_EXACT = re.compile(r"\bwith\s+(?:exactly\s+)?(\d+)\s+ATK\b|\bATK\s+(\d+)\b", re.IGNORECASE)
_QUOTED = re.compile(r"[\"“]([^\"”]{2,60})[\"”]")

_RACE_RE = re.compile(
    r"\b(" + "|".join(sorted((re.escape(k) for k in RACE_VOCABULARY), key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
_ATTRIBUTE_RE = re.compile(r"\b(" + "|".join(ATTRIBUTE_VOCABULARY) + r")\b", re.IGNORECASE)

_TUNER_TRUE = re.compile(r"\bTuner monster", re.IGNORECASE)
_TUNER_FALSE = re.compile(r"\bnon-Tuner\b", re.IGNORECASE)
_PENDULUM_TRUE = re.compile(r"\bPendulum Monster", re.IGNORECASE)
_EFFECT_MONSTER = re.compile(r"\bEffect Monster", re.IGNORECASE)
_TOKEN_TRUE = re.compile(r"\bToken\b", re.IGNORECASE)

_CATEGORY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bSpell/?Trap Card\b|\bSpell/Trap\b", re.IGNORECASE), "SPELL_TRAP"),
    (re.compile(r"\bSpell Card\b|\bSpell\b", re.IGNORECASE), "SPELL"),
    (re.compile(r"\bTrap Card\b|\bTrap\b", re.IGNORECASE), "TRAP"),
    (re.compile(r"\bmonster\b", re.IGNORECASE), "MONSTER"),
)

_ONCE_PER_TURN = re.compile(r"\bonce per turn\b", re.IGNORECASE)


# ------------------------------------------------------------------- utilities
def _to_int(token: str | None) -> int | None:
    if not token:
        return None
    token = token.strip().lower()
    if token.isdigit():
        return int(token)
    return _WORD_NUMBER.get(token)


def detect_zone(text: str) -> Zone | None:
    for pattern, zone in _ZONE_PATTERNS:
        if pattern.search(text):
            return zone
    return None


def detect_destination(text: str) -> Zone | None:
    for pattern, zone in _DESTINATION_PATTERNS:
        if pattern.search(text):
            return zone
    return None


def detect_action(text: str) -> tuple[Action | None, str]:
    """Return (action, evidence)."""
    for pattern, action in _ACTION_PATTERNS:
        match = pattern.search(text)
        if match:
            return action, match.group(0)
    return None, ""


def _first_group(match: re.Match[str] | None) -> str | None:
    if not match:
        return None
    for group in match.groups():
        if group:
            return group
    return None


def parse_target(text: str) -> TargetConstraint:
    target = TargetConstraint()

    count = _first_group(_COUNT_UP_TO.search(text)) or _first_group(_COUNT_EXACT.search(text))
    target.count = _to_int(count)

    level_match = _LEVEL_RANGE.search(text)
    if level_match:
        level = int(level_match.group(1))
        direction = (level_match.group(2) or "").lower()
        if "lower" in direction or "less" in direction:
            target.level_max = level
        elif "higher" in direction or "more" in direction:
            target.level_min = level
        else:
            target.level_min = level
            target.level_max = level

    rank = _RANK.search(text)
    if rank:
        target.rank = int(rank.group(1))

    link = _LINK.search(text)
    if link:
        target.link_rating = int(_first_group(link))

    atk_range = _ATK_RANGE.search(text)
    if atk_range:
        value = int(atk_range.group(1) or atk_range.group(3))
        direction = (atk_range.group(2) or atk_range.group(4) or "").lower()
        if direction == "more":
            target.atk_min = value
        else:
            target.atk_max = value
    else:
        atk_exact = _ATK_EXACT.search(text)
        if atk_exact:
            value = _to_int(_first_group(atk_exact))
            if value is not None:
                target.atk_min = value
                target.atk_max = value

    race_match = _RACE_RE.search(text)
    if race_match:
        target.race = normalize_race_token(race_match.group(1))

    attribute_match = _ATTRIBUTE_RE.search(text)
    if attribute_match:
        target.attribute = ATTRIBUTE_VOCABULARY[attribute_match.group(1).upper()]

    quoted = _QUOTED.search(text)
    if quoted:
        raw = quoted.group(1).strip()
        target.name = raw
        tail = text[quoted.end() : quoted.end() + 30].lower()
        if "monster" in tail or "card" in tail:
            target.archetype = re.sub(r"[\s\-_/]+", "-", raw).strip("-").lower()

    for pattern, category in _CATEGORY_PATTERNS:
        if pattern.search(text):
            target.card_category = category
            break

    if _TUNER_FALSE.search(text):
        target.tuner = Tri.FALSE
    elif _TUNER_TRUE.search(text):
        target.tuner = Tri.TRUE

    if _PENDULUM_TRUE.search(text):
        target.pendulum = Tri.TRUE

    if _EFFECT_MONSTER.search(text):
        target.effect_monster = Tri.TRUE

    if _TOKEN_TRUE.search(text):
        target.token = Tri.TRUE

    return target


def _confidence(action: Action | None, source: Zone | None, destination: Zone | None, target: TargetConstraint) -> float:
    score = 0.30
    if action is not None:
        score += 0.30
    if source is not None:
        score += 0.15
    if destination is not None:
        score += 0.10
    if not target.is_empty():
        score += 0.15
    return round(min(score, 1.0), 3)


def _split_clauses(text: str) -> list[str]:
    parts = [p.strip(" ,.") for p in _CLAUSE_CONNECTORS.split(text) if p and p.strip(" ,.")]
    return parts or ([text] if text else [])


def _extract_restrictions(text: str) -> list[str]:
    out: list[str] = []
    for pattern in _RESTRICTION_PATTERNS:
        match = pattern.search(text)
        if match:
            out.append(match.group(0).strip())
            text = text.replace(match.group(0), " ")
    return out


def _build_resolution(clause: str, *, once_per_turn: Tri) -> EffectPredicate:
    action, evidence = detect_action(clause)
    source = detect_zone(clause)
    destination = detect_destination(clause)

    # "Special Summon" always resolves onto the field.
    if action is Action.SPECIAL_SUMMON and destination is None:
        destination = Zone.FIELD
    if action is Action.BANISH and destination is None:
        destination = Zone.BANISHED
    if action is Action.SEND_TO_GRAVEYARD and destination is None:
        destination = Zone.GRAVEYARD
    if action is Action.DISCARD and destination is None:
        destination = Zone.GRAVEYARD
    if action is Action.DRAW and destination is None:
        destination = Zone.HAND
    if action in (Action.ADD_TO_HAND, Action.RETURN_TO_HAND) and destination is None:
        destination = Zone.HAND
    if action is Action.MILL:
        source = source or Zone.DECK
        destination = Zone.GRAVEYARD
    if action is Action.DRAW and source is None:
        source = Zone.DECK

    # "add ... from your Deck to your hand" is the player-facing concept SEARCH.
    if action is Action.ADD_TO_HAND and source is Zone.DECK and destination is Zone.HAND:
        action = Action.SEARCH

    target = parse_target(clause)
    return EffectPredicate(
        part=EffectPart.RESOLUTION,
        action=action,
        source=source,
        destination=destination,
        target=target,
        once_per_turn=once_per_turn,
        confidence=_confidence(action, source, destination, target),
        evidence=clause[:240],
    )


def _build_cost(clause: str) -> EffectPredicate | None:
    action, evidence = detect_action(clause)
    if action is None:
        return None
    source = detect_zone(clause)
    destination = detect_destination(clause)
    if action is Action.BANISH and destination is None:
        destination = Zone.BANISHED
    if action in (Action.SEND_TO_GRAVEYARD, Action.DISCARD) and destination is None:
        destination = Zone.GRAVEYARD

    target = parse_target(clause)
    return EffectPredicate(
        part=EffectPart.COST,
        action=action,
        source=source,
        destination=destination,
        target=target,
        once_per_turn=Tri.UNKNOWN,
        confidence=_confidence(action, source, destination, target),
        evidence=clause[:240],
    )


# ------------------------------------------------------------------ entry point
def parse_segment(segment: EffectSegment) -> ParsedEffect:
    text = segment.raw_text.strip()
    predicates: list[EffectPredicate] = []
    if not text:
        return ParsedEffect(segment=segment, predicates=[])

    # A summoning-material line states requirements, not an effect. Keeping it
    # as an effect row with zero predicates preserves the text without making
    # up a claim.
    if segment.marker is SegmentMarker.MATERIAL:
        return ParsedEffect(segment=segment, predicates=[])

    once_per_turn = Tri.TRUE if _ONCE_PER_TURN.search(text) else Tri.UNKNOWN

    restrictions = _extract_restrictions(text)
    for restriction in restrictions:
        predicates.append(
            EffectPredicate(
                part=EffectPart.RESTRICTION,
                once_per_turn=Tri.TRUE if "once per turn" in restriction.lower() else Tri.UNKNOWN,
                confidence=0.6,
                evidence=restriction[:240],
            )
        )

    body = text
    for restriction in restrictions:
        body = body.replace(restriction, " ")
    body = body.strip(" ,.")

    condition_text = ""
    cost_text = ""
    resolution_text = body

    if ";" in body:
        left, _, right = body.partition(";")
        resolution_text = right.strip()
        left = left.strip()
        if ":" in left:
            head, _, tail = left.partition(":")
            condition_text, cost_text = head.strip(), tail.strip()
        else:
            cost_text = left
    elif ":" in body:
        head, _, tail = body.partition(":")
        # A colon only marks a condition when the head reads like a trigger.
        if len(head.split()) <= 14:
            condition_text, resolution_text = head.strip(), tail.strip()

    if condition_text:
        predicates.append(
            EffectPredicate(
                part=EffectPart.CONDITION,
                once_per_turn=Tri.TRUE if _ONCE_PER_TURN.search(condition_text) else Tri.UNKNOWN,
                confidence=0.5,
                evidence=condition_text[:240],
            )
        )

    # "Target 1 Spell/Trap on the field; destroy that target." — the clause
    # before ";" describes *what is targeted*, not a cost. Rather than invent a
    # COST predicate with an unknown action, carry it as activation context and
    # fold it into the resolution predicate.
    activation_target: TargetConstraint | None = None
    activation_zone: Zone | None = None

    if cost_text:
        cost_predicate = _build_cost(cost_text)
        if cost_predicate is not None:
            predicates.append(cost_predicate)
        else:
            activation_target = parse_target(cost_text)
            activation_zone = detect_zone(cost_text)

    for clause in _split_clauses(resolution_text):
        predicates.append(_build_resolution(clause, once_per_turn=once_per_turn))

    if activation_target is not None:
        resolutions = [p for p in predicates if p.part is EffectPart.RESOLUTION]
        if resolutions:
            _merge_context(resolutions[0], activation_target, activation_zone)

    return ParsedEffect(segment=segment, predicates=predicates)


_RANGE_COUNTERPART = {
    "level_min": "level_max",
    "level_max": "level_min",
    "atk_min": "atk_max",
    "atk_max": "atk_min",
}


def _merge_context(predicate: EffectPredicate, extra: TargetConstraint, zone: Zone | None) -> None:
    """Fill in target/source gaps from the activation clause.

    Range fields are only merged when neither bound is already known — merging a
    second, unrelated range would otherwise produce contradictions such as
    "Level 9 … Level 8 or lower".
    """
    if zone is not None and predicate.source is None:
        predicate.source = zone
    for name, value in extra.to_dict().items():
        if name in ("tuner", "pendulum", "effect_monster", "token"):
            continue
        if value is None:
            continue
        counterpart = _RANGE_COUNTERPART.get(name)
        if counterpart is not None and getattr(predicate.target, counterpart) is not None:
            continue
        if getattr(predicate.target, name) is None:
            setattr(predicate.target, name, value)


def parse_effect_text(raw_text: str, *, index: int = 0) -> ParsedEffect:
    """Convenience wrapper for tests and ad-hoc use."""
    from .ontology import EffectScope, SegmentMarker

    return parse_segment(
        EffectSegment(index=index, scope=EffectScope.MAIN, marker=SegmentMarker.BLOCK, raw_text=raw_text)
    )
