"""Deterministic canonical resolution of validated bank KPI candidates.

The AI does not choose the FinLens metric. This layer applies the declarative
definitions in bank_metric_definitions.py to already-validated RawFacts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .bank_metric_definitions import BANK_METRIC_DEFINITIONS, MetricDefinition
from .bank_metrics import RawFact


@dataclass(frozen=True)
class CanonicalResolution:
    fact: RawFact | None
    reason: str | None = None
    survivors: tuple[RawFact, ...] = ()


def resolve_canonical_metric(
    facts: list[RawFact],
    key: str,
    target_period: str | None = None,
) -> CanonicalResolution:
    """Return the unique FinLens candidate for `key`, or None if unresolved."""
    definition = BANK_METRIC_DEFINITIONS[key]
    eligible = [fact for fact in facts if fact.key == key]
    eligible = _filter_invalid(eligible)
    eligible = _filter_period(eligible, target_period)
    eligible = _filter_series(eligible, definition)
    eligible = _filter_basis(eligible, definition)
    eligible = _filter_measurement(eligible, definition)
    eligible = _filter_patterns(eligible, definition.exclude_patterns, keep_matches=False)
    eligible = _prefer_patterns(eligible, definition.prefer_patterns)
    if not eligible:
        return CanonicalResolution(None, None, ())
    if _mixed_scope_values(eligible):
        return CanonicalResolution(None, None, tuple(eligible))
    unique = {
        (fact.value, fact.unit, fact.comparison, fact.measurement)
        for fact in eligible
    }
    if len(unique) != 1:
        return CanonicalResolution(None, None, tuple(eligible))
    chosen = _pick_duplicate(eligible)
    return CanonicalResolution(chosen, definition.resolution_reason, tuple(eligible))


def _filter_invalid(facts: list[RawFact]) -> list[RawFact]:
    return [fact for fact in facts if not fact.uncertain]


def _filter_period(facts: list[RawFact], target_period: str | None) -> list[RawFact]:
    if not target_period:
        return facts
    return [fact for fact in facts if fact.period is None or fact.period == target_period]


def _filter_series(facts: list[RawFact], definition: MetricDefinition) -> list[RawFact]:
    if not definition.headline_only:
        return facts
    return [fact for fact in facts if not fact.series]


def _filter_basis(facts: list[RawFact], definition: MetricDefinition) -> list[RawFact]:
    if definition.required_basis:
        facts = [fact for fact in facts if fact.comparison == definition.required_basis]
    if definition.preferred_basis:
        preferred = [fact for fact in facts if fact.comparison == definition.preferred_basis]
        if preferred:
            return preferred
    return facts


def _filter_measurement(facts: list[RawFact], definition: MetricDefinition) -> list[RawFact]:
    if definition.required_measurement:
        facts = [fact for fact in facts if fact.measurement == definition.required_measurement]
    if definition.preferred_measurement:
        preferred = [fact for fact in facts if fact.measurement == definition.preferred_measurement]
        if preferred:
            return preferred
    return facts


def _filter_patterns(
    facts: list[RawFact],
    patterns: tuple[str, ...],
    *,
    keep_matches: bool,
) -> list[RawFact]:
    if not patterns:
        return facts
    compiled = [re.compile(pattern, re.I) for pattern in patterns]
    kept: list[RawFact] = []
    for fact in facts:
        haystack = f"{fact.raw_label} {fact.excerpt}"
        matched = any(pattern.search(haystack) for pattern in compiled)
        if keep_matches == matched:
            kept.append(fact)
    return kept


def _prefer_patterns(facts: list[RawFact], patterns: tuple[str, ...]) -> list[RawFact]:
    preferred = _filter_patterns(facts, patterns, keep_matches=True)
    return preferred if preferred else facts


def _mixed_scope_values(facts: list[RawFact]) -> bool:
    scopes = {fact.consolidation for fact in facts if fact.consolidation}
    values = {(fact.value, fact.unit) for fact in facts}
    return len(scopes) > 1 and len(values) > 1


def _pick_duplicate(facts: list[RawFact]) -> RawFact:
    """Identical remaining values: pick by confidence, then earlier page."""
    return max(
        facts,
        key=lambda fact: (
            fact.confidence if fact.confidence is not None else -1.0,
            -(fact.page or 10**9),
        ),
    )
