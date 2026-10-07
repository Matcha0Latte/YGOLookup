"""Schema / enum validation for parsed effects.

The parser is allowed to be wrong; the validator's job is to make "wrong but
well-formed" impossible. It reports problems instead of silently repairing
them, so parser regressions show up in tests.
"""

from __future__ import annotations

from dataclasses import dataclass

from .ontology import (
    ATTRIBUTE_VOCABULARY,
    RACE_VOCABULARY,
    Action,
    EffectPart,
    Tri,
    Zone,
)
from .schema import EffectPredicate, ParsedEffect

VALID_TARGET_CATEGORIES = frozenset({"MONSTER", "SPELL", "TRAP", "SPELL_TRAP"})


@dataclass
class ValidationIssue:
    level: str  # error | warning
    message: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.message}"


def validate_predicate(predicate: EffectPredicate) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if not isinstance(predicate.part, EffectPart):
        issues.append(ValidationIssue("error", f"part must be an EffectPart, got {predicate.part!r}"))

    if predicate.action is not None and not isinstance(predicate.action, Action):
        issues.append(ValidationIssue("error", f"unknown action {predicate.action!r}"))

    for field_name in ("source", "destination"):
        value = getattr(predicate, field_name)
        if value is not None and not isinstance(value, Zone):
            issues.append(ValidationIssue("error", f"unknown {field_name} zone {value!r}"))

    target = predicate.target
    if target.race is not None and target.race not in set(RACE_VOCABULARY.values()):
        issues.append(ValidationIssue("error", f"unknown race {target.race!r}"))
    if target.attribute is not None and target.attribute not in set(ATTRIBUTE_VOCABULARY.values()):
        issues.append(ValidationIssue("error", f"unknown attribute {target.attribute!r}"))
    if target.card_category is not None and target.card_category not in VALID_TARGET_CATEGORIES:
        issues.append(ValidationIssue("error", f"unknown target category {target.card_category!r}"))

    if target.level_min is not None and target.level_max is not None and target.level_min > target.level_max:
        issues.append(
            ValidationIssue("error", f"level_min {target.level_min} > level_max {target.level_max}")
        )
    if target.atk_min is not None and target.atk_max is not None and target.atk_min > target.atk_max:
        issues.append(ValidationIssue("error", f"atk_min {target.atk_min} > atk_max {target.atk_max}"))

    for tri_field in ("tuner", "pendulum", "effect_monster", "token"):
        value = getattr(target, tri_field)
        if value not in tuple(Tri):
            issues.append(ValidationIssue("error", f"target.{tri_field} must be Tri, got {value!r}"))

    if predicate.once_per_turn not in tuple(Tri):
        issues.append(ValidationIssue("error", f"once_per_turn must be Tri, got {predicate.once_per_turn!r}"))

    if not 0.0 <= predicate.confidence <= 1.0:
        issues.append(ValidationIssue("error", f"confidence out of range: {predicate.confidence}"))

    # Semantic sanity checks (non-fatal).
    if predicate.action is None and predicate.confidence > 0.5:
        issues.append(
            ValidationIssue("warning", "confidence > 0.5 but the action was not determined")
        )
    if predicate.action is Action.SPECIAL_SUMMON and predicate.source is None:
        issues.append(
            ValidationIssue("warning", "SPECIAL_SUMMON without a source zone — recall may be incomplete")
        )
    if predicate.part is EffectPart.COST and predicate.action is not None:
        cost_like = {
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
        if predicate.action not in cost_like:
            issues.append(
                ValidationIssue("warning", f"{predicate.action.value} parsed as COST — check clause split")
            )

    return issues


def validate_parsed_effect(parsed: ParsedEffect) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not parsed.segment.raw_text.strip():
        issues.append(ValidationIssue("error", "effect segment has no raw text"))
    for predicate in parsed.predicates:
        issues.extend(validate_predicate(predicate))
    return issues


def has_errors(issues: list[ValidationIssue]) -> bool:
    return any(issue.level == "error" for issue in issues)
