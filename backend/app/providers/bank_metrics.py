"""Normalized bank KPI contract.

Missing metrics stay None and are never inferred. Extraction and scoring
live elsewhere; this module is schema only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

BANK_METRIC_KEYS = (
    "gnpa",
    "nnpa",
    "pcr",
    "credit_cost",
    "slippages",
    "nim",
    "roa",
    "roe",
    "nii_growth",
    "loan_growth",
    "deposit_growth",
    "casa",
    "casa_trend",
    "car",
    "cet1",
    "cost_income",
    "restructured_loans",
    "sma_or_stressed_assets",
    "writeoffs",
    "recoveries",
)

COMPARISON_YOY = "yoy"
COMPARISON_QOQ = "qoq"
COMPARISON_PIT = "point_in_time"

MEASUREMENT_AVERAGE = "average"
MEASUREMENT_EOP = "end_of_period"

EXTRACTION_OK = "ok"
EXTRACTION_PARTIAL = "partial"
EXTRACTION_FAILED = "failed"


@dataclass(frozen=True)
class MetricProvenance:
    source_title: str
    source_url: str
    source_type: str
    excerpt: str
    raw_label: str = ""
    page: int | None = None


@dataclass(frozen=True)
class RawFact:
    """A value as the document literally reported it, before schema mapping."""

    key: str
    raw_label: str
    value: float
    unit: str
    period: str | None = None
    comparison: str | None = None
    measurement: str | None = None
    consolidation: str | None = None
    excerpt: str = ""
    page: int | None = None
    confidence: float | None = None
    uncertain: bool = False
    series: str | None = None


@dataclass(frozen=True)
class BankMetric:
    key: str
    label: str
    value: float | None
    unit: str = "%"
    period: str | None = None
    comparison: str | None = None
    measurement: str | None = None
    consolidation: str | None = None
    provenance: MetricProvenance | None = None
    confidence: float | None = None
    resolution_reason: str | None = None


@dataclass
class BankMetrics:
    ticker: str
    period: str | None = None
    status: str = EXTRACTION_OK
    error: str | None = None
    gnpa: BankMetric | None = None
    nnpa: BankMetric | None = None
    pcr: BankMetric | None = None
    credit_cost: BankMetric | None = None
    slippages: BankMetric | None = None
    nim: BankMetric | None = None
    roa: BankMetric | None = None
    roe: BankMetric | None = None
    nii_growth: BankMetric | None = None
    loan_growth: BankMetric | None = None
    deposit_growth: BankMetric | None = None
    casa: BankMetric | None = None
    casa_trend: BankMetric | None = None
    car: BankMetric | None = None
    cet1: BankMetric | None = None
    cost_income: BankMetric | None = None
    restructured_loans: BankMetric | None = None
    sma_or_stressed_assets: BankMetric | None = None
    writeoffs: BankMetric | None = None
    recoveries: BankMetric | None = None
    raw_facts: list[RawFact] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ambiguous: dict[str, list[RawFact]] = field(default_factory=dict)
    rejected: list[str] = field(default_factory=list)
    candidate_page_numbers: list[int] = field(default_factory=list)
