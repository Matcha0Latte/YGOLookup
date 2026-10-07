"""Validation of parsed effects.

The validator is the last layer before anything is written. It exists so a
parser failure can never be stored as a claim about a card.

It checks:

* every enum value comes from the ontology
* numeric comparisons are well formed
* COST clauses only carry payable actions
* UNKNOWN stays UNKNOWN (a missing action is not a contradiction)
"""

from __future__ import annotations

from dataclasses import dataclass

from .lexicon import COST_ACTIONS
from .ontology import (
    Action,
    ClauseRole,
    ExtractedBy,
    ParseStatus,
    Subject,
    UnitKind,
    Zone,
)
from .predicates import ParsedUnit, Predicate
from .selector import CardSelector

__all__ = [
    "ValidationIssue",
    "validate_predicate",
    "validate_unit",
    "validate_parsed_units",
    "has_errors",
]

VALID_OPS = frozenset({"<=", ">=", "==", "<", ">"})
VALID_CARD_TYPES = frozenset({"MONSTER", "SPELL", "TRAP", "SPELL_TRAP"})


@dataclass
class ValidationIssue:
    level: str  # "error" | "warning"
    message: str
    context: str = ""

    def __str__(self) -> str:
        prefix = f"[{self.context}] " if self.context else ""
        return f"{prefix}{self.message}"


def _validate_selector(selector: CardSelector, issues: list[ValidationIssue], context: str) -> None:
    for name in ("level", "rank", "link_rating", "atk", "defense"):
        constraint = getattr(selector, name)
        if constraint is None:
            continue
        if constraint.op not in VALID_OPS:
            issues.append(ValidationIssue("error", f"{name} has invalid op {constraint.op!r}", context))
        if not isinstance(constraint.value, int):
            issues.append(ValidationIssue("error", f"{name} value must be int", context))
    if selector.card_type not in VALID_CARD_TYPES and selector.card_type is not None:
        issues.append(ValidationIssue("error", f"bad card_type {selector.card_type!r}", context))


def validate_predicate(
    predicate: Predicate, context: str = "", role: ClauseRole | None = None
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if predicate.action is not None and not isinstance(predicate.action, Action):
        issues.append(ValidationIssue("error", f"action is not an Action: {predicate.action!r}", context))
    if predicate.action_known and predicate.action is None:
        issues.append(ValidationIssue("error", "action_known is True but action is None", context))
    if not predicate.action_known and predicate.action is not None:
        issues.append(ValidationIssue("warning", "action present but action_known is False", context))

    for name in ("source_zone", "destination_zone"):
        zone = getattr(predicate, name)
        if zone is not None and not isinstance(zone, Zone):
            issues.append(ValidationIssue("error", f"{name} is not a Zone: {zone!r}", context))

    if not isinstance(predicate.subject, Subject):
        issues.append(ValidationIssue("error", f"bad subject {predicate.subject!r}", context))

    if predicate.extracted_by not in tuple(ExtractedBy):
        issues.append(ValidationIssue("error", f"bad extracted_by {predicate.extracted_by!r}", context))

    if not 0.0 <= predicate.confidence <= 1.0:
        issues.append(ValidationIssue("error", f"confidence out of range: {predicate.confidence}", context))

    # Semantic sanity (non-fatal).
    if role is ClauseRole.COST and predicate.action is not None and predicate.action not in COST_ACTIONS:
        issues.append(
            ValidationIssue("warning", f"{predicate.action.value} parsed as COST — check clause split", context)
        )
    if not predicate.action_known and predicate.confidence > 0.5:
        issues.append(ValidationIssue("warning", "confidence > 0.5 but action was not determined", context))

    _validate_selector(predicate.object, issues, context)
    return issues


def validate_unit(parsed: ParsedUnit) -> list[ValidationIssue]:
    context = f"unit[{parsed.unit.index}]"
    issues: list[ValidationIssue] = []

    if parsed.unit.kind is UnitKind.MATERIAL and parsed.clauses:
        issues.append(ValidationIssue("error", "material line produced clauses", context))

    if not parsed.unit.raw_text.strip():
        issues.append(ValidationIssue("error", "unit has no raw text", context))

    for parsed_clause in parsed.clauses:
        clause_context = f"{context}.clause[{parsed_clause.clause.index}]"
        clause = parsed_clause.clause
        if not isinstance(clause.role, ClauseRole):
            issues.append(ValidationIssue("error", "clause role is not a ClauseRole", clause_context))
        if not clause.raw_text.strip():
            issues.append(ValidationIssue("warning", "empty clause text", clause_context))
        if clause.start > clause.end:
            issues.append(ValidationIssue("error", "clause span is inverted", clause_context))
        for predicate in parsed_clause.predicates:
            issues.extend(validate_predicate(predicate, clause_context, clause.role))

    return issues


def validate_parsed_units(units: list[ParsedUnit]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for parsed in units:
        issues.extend(validate_unit(parsed))
    return issues


def has_errors(issues: list[ValidationIssue]) -> bool:
    return any(issue.level == "error" for issue in issues)


def status_of(parsed: ParsedUnit) -> ParseStatus:
    return parsed.status
