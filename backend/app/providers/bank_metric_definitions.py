"""Declarative FinLens canonical bank metric definitions.

Stage 3A extracts and validates candidates. This module states which
candidate is the FinLens metric. It does not score, classify, or call an AI.
"""
from __future__ import annotations

from dataclasses import dataclass

from .bank_metrics import (
    BANK_METRIC_KEYS,
    COMPARISON_PIT,
    COMPARISON_YOY,
    MEASUREMENT_EOP,
)


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    explanation: str
    resolution_reason: str
    required_basis: str | None = None
    preferred_basis: str | None = None
    required_measurement: str | None = None
    preferred_measurement: str | None = None
    headline_only: bool = True
    exclude_patterns: tuple[str, ...] = ()
    prefer_patterns: tuple[str, ...] = ()


_SEGMENT_GROWTH = (
    r"\bretail\b",
    r"\bdomestic\b",
    r"\bforeign\b",
    r"\bagri\b",
    r"\bcorporate\b",
    r"\bsme\b",
    r"\baum\b",
)

BANK_METRIC_DEFINITIONS: dict[str, MetricDefinition] = {
    "gnpa": MetricDefinition(
        key="gnpa",
        required_basis=COMPARISON_PIT,
        explanation=(
            "Headline bank-wide GNPA ratio for the current quarter. "
            "Sub-series such as ex-agri are not canonical."
        ),
        resolution_reason="headline_pit_current_period",
    ),
    "nnpa": MetricDefinition(
        key="nnpa",
        required_basis=COMPARISON_PIT,
        explanation=(
            "Headline bank-wide NNPA ratio for the current quarter. "
            "Do not substitute a prior period, segment, or ex-agri figure."
        ),
        resolution_reason="headline_pit_current_period",
    ),
    "pcr": MetricDefinition(
        key="pcr",
        required_basis=COMPARISON_PIT,
        explanation=(
            "Headline bank-wide provision coverage ratio. Specific PCR and "
            "PCR including AUCA/write-offs are not canonical unless that is "
            "the only remaining headline, which it is not when tagged as a series."
        ),
        resolution_reason="headline_pit_current_period",
    ),
    "credit_cost": MetricDefinition(
        key="credit_cost",
        explanation=(
            "Headline bank-level credit cost for the current period. "
            "Net-of-recoveries is not substituted for a distinct gross/headline "
            "figure. Quarterly and annualized headlines are not interchangeable."
        ),
        resolution_reason="headline_bank_level_credit_cost",
    ),
    "slippages": MetricDefinition(
        key="slippages",
        exclude_patterns=_SEGMENT_GROWTH,
        explanation=(
            "Bank-level slippages for the current reporting period. "
            "Segment slippages are not canonical."
        ),
        resolution_reason="headline_bank_level_current_period",
    ),
    "nim": MetricDefinition(
        key="nim",
        exclude_patterns=(r"\bdomestic\b",),
        prefer_patterns=(r"\boverall\b", r"whole\s+bank"),
        explanation=(
            "Overall/whole-bank NIM for the current period. Domestic-only or "
            "segment NIM is not canonical and is not used as a fallback."
        ),
        resolution_reason="headline_overall_nim",
    ),
    "roa": MetricDefinition(
        key="roa",
        exclude_patterns=_SEGMENT_GROWTH,
        explanation=(
            "Bank-level return on assets (including return on average assets) "
            "for the current period. Segment ROA is not canonical. Differing "
            "standalone and consolidated values stay unresolved."
        ),
        resolution_reason="headline_bank_level_roa",
    ),
    "roe": MetricDefinition(
        key="roe",
        exclude_patterns=_SEGMENT_GROWTH,
        explanation=(
            "Bank-level return on equity for the current period. "
            "Differing standalone and consolidated values stay unresolved."
        ),
        resolution_reason="headline_bank_level_roe",
    ),
    "nii_growth": MetricDefinition(
        key="nii_growth",
        required_basis=COMPARISON_YOY,
        exclude_patterns=_SEGMENT_GROWTH,
        explanation=(
            "Headline bank-level NII growth as YoY for the current period. "
            "QoQ is not a fallback."
        ),
        resolution_reason="preferred_yoy_bank_level_headline",
    ),
    "loan_growth": MetricDefinition(
        key="loan_growth",
        required_basis=COMPARISON_YOY,
        required_measurement=MEASUREMENT_EOP,
        exclude_patterns=_SEGMENT_GROWTH,
        explanation=(
            "Bank-level total loans/advances growth as end-of-period YoY. "
            "Average balances, QoQ, segment books, and AUM are not canonical "
            "and are not used as fallbacks."
        ),
        resolution_reason="preferred_yoy_eop_bank_level_headline",
    ),
    "deposit_growth": MetricDefinition(
        key="deposit_growth",
        required_basis=COMPARISON_YOY,
        required_measurement=MEASUREMENT_EOP,
        exclude_patterns=_SEGMENT_GROWTH + (r"\bcasa\b",),
        explanation=(
            "Bank-level total deposits growth as end-of-period YoY. "
            "Average balances, QoQ, and CASA deposit growth are not canonical "
            "and are not used as fallbacks."
        ),
        resolution_reason="preferred_yoy_eop_bank_level_headline",
    ),
    "casa": MetricDefinition(
        key="casa",
        required_basis=COMPARISON_PIT,
        explanation=(
            "Headline bank-level CASA ratio for the current period. "
            "CASA deposit growth is a different metric. Competing QAB and "
            "MEB/period-end ratios stay unresolved unless only one remains."
        ),
        resolution_reason="headline_casa_ratio",
    ),
    "casa_trend": MetricDefinition(
        key="casa_trend",
        preferred_basis=COMPARISON_YOY,
        explanation=(
            "Change/trend in CASA deposits or ratio, not the CASA ratio itself. "
            "YoY is preferred when both YoY and QoQ exist; QoQ-only is allowed."
        ),
        resolution_reason="preferred_yoy_casa_trend",
    ),
    "car": MetricDefinition(
        key="car",
        required_basis=COMPARISON_PIT,
        exclude_patterns=(r"\bat-?1\b", r"\btier\s*[12]\b"),
        explanation=(
            "Headline bank-level CAR/CRAR/capital adequacy ratio. "
            "AT1, Tier 1, Tier 2, and CET1 are not canonical CAR."
        ),
        resolution_reason="headline_car_crar",
    ),
    "cet1": MetricDefinition(
        key="cet1",
        required_basis=COMPARISON_PIT,
        exclude_patterns=(r"\bat-?1\b", r"\btier\s*2\b"),
        explanation=(
            "Headline bank-level Common Equity Tier 1. AT1, Tier 2, and CAR "
            "are not canonical CET1."
        ),
        resolution_reason="headline_cet1",
    ),
    "cost_income": MetricDefinition(
        key="cost_income",
        required_basis=COMPARISON_PIT,
        exclude_patterns=(r"cost\s*[-/]?\s*to\s*[-/]?\s*assets",),
        explanation=(
            "Bank-level cost-to-income ratio, including a clearly presented "
            "core cost-to-income headline. Cost-to-assets is a different metric."
        ),
        resolution_reason="headline_cost_to_income",
    ),
    "restructured_loans": MetricDefinition(
        key="restructured_loans",
        exclude_patterns=(r"\bsma\b", r"stressed\s+assets", r"\bgnpa\b"),
        explanation=(
            "Clearly labeled bank-level restructured loans. Not inferred from "
            "SMA, stressed assets, GNPA, or provisions."
        ),
        resolution_reason="headline_restructured_loans",
    ),
    "sma_or_stressed_assets": MetricDefinition(
        key="sma_or_stressed_assets",
        exclude_patterns=(r"restructured",),
        explanation=(
            "Clearly labeled SMA or stressed assets. Not interchangeable with "
            "restructured loans."
        ),
        resolution_reason="headline_sma_or_stressed",
    ),
    "writeoffs": MetricDefinition(
        key="writeoffs",
        exclude_patterns=(
            r"write[-\s]?offs?\s*(?:&|and)\s*recover",
            r"technical\s+write",
        ),
        explanation=(
            "Clearly labeled bank-level write-offs for the current period. "
            "Combined write-offs and recoveries are not canonical."
        ),
        resolution_reason="headline_writeoffs",
    ),
    "recoveries": MetricDefinition(
        key="recoveries",
        exclude_patterns=(
            r"upgrades?\s*(?:&|and|,)\s*recover",
            r"recover(?:y|ies)?\s*(?:&|and|,|\+)\s*upgrad",
        ),
        explanation=(
            "Clearly labeled bank-level recoveries. Combined upgrades and "
            "recoveries are not canonical."
        ),
        resolution_reason="headline_recoveries",
    ),
}


def _assert_definitions_cover_schema() -> None:
    missing = [key for key in BANK_METRIC_KEYS if key not in BANK_METRIC_DEFINITIONS]
    extra = [key for key in BANK_METRIC_DEFINITIONS if key not in BANK_METRIC_KEYS]
    if missing or extra:
        raise RuntimeError(
            f"canonical definitions out of sync with BankMetrics: missing={missing} extra={extra}"
        )


_assert_definitions_cover_schema()
