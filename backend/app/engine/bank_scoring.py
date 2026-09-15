"""Map canonical BankMetrics onto existing FinLens pillars.

Does not change Swing/Long pillar mix, verdict bands, or non-bank scoring.
Only canonical BankMetrics fields are consumed — never unresolved
extraction candidates or ticker names.
"""
from __future__ import annotations

from .common import Metric, Pillar, band
from .sector import PROFILE_BANK
from ..providers.bank_metrics import BankMetric, BankMetrics

BANK_GROWTH_WEIGHTS = {
    "loan_growth": 1.00,
    "deposit_growth": 0.80,
    "nii_growth": 0.90,
    "casa_trend": 0.50,
}

BANK_PROFIT_WEIGHTS = {
    "nim": 1.00,
    "roa": 1.20,
    "roe": 0.80,
    "cost_income": 0.60,
}

# GNPA/NNPA and CET1/CAR share an economic family, so companions are
# down-weighted rather than treated as unrelated full votes.
BANK_HEALTH_WEIGHTS = {
    "gnpa": 1.00,
    "nnpa": 0.70,
    "pcr": 0.80,
    "credit_cost": 1.00,
    "slippages": 0.90,
    "restructured_loans": 0.60,
    "sma_or_stressed_assets": 0.60,
    "cet1": 0.80,
    "car": 0.50,
}

BANK_LABELS = {
    "loan_growth": "Loan growth",
    "deposit_growth": "Deposit growth",
    "nii_growth": "NII growth",
    "casa_trend": "CASA trend",
    "nim": "NIM",
    "roa": "RoA",
    "roe": "RoE",
    "cost_income": "Cost / Income",
    "gnpa": "GNPA",
    "nnpa": "NNPA",
    "pcr": "PCR",
    "credit_cost": "Credit cost",
    "slippages": "Slippages",
    "restructured_loans": "Restructured loans",
    "sma_or_stressed_assets": "SMA / stressed assets",
    "cet1": "CET1",
    "car": "CAR / CRAR",
}

LOWER_IS_BETTER = frozenset({
    "gnpa", "nnpa", "credit_cost", "slippages",
    "restructured_loans", "sma_or_stressed_assets", "cost_income",
})

# Indian bank operating ranges. Not fitted to any ticker.
BANK_BANDS: dict[str, list[tuple[float, float]]] = {
    "loan_growth": [(0, 20), (6, 40), (10, 55), (14, 72), (18, 85), (25, 95)],
    "deposit_growth": [(0, 20), (6, 40), (10, 55), (14, 72), (18, 85), (25, 95)],
    "nii_growth": [(0, 22), (4, 40), (8, 58), (12, 74), (18, 88), (25, 95)],
    "casa_trend": [(0, 25), (4, 45), (8, 62), (12, 78), (18, 90)],
    "nim": [(2.0, 20), (2.5, 40), (3.0, 55), (3.5, 72), (4.0, 85), (4.5, 95)],
    "roa": [(0.4, 15), (0.8, 35), (1.2, 55), (1.6, 72), (2.0, 85), (2.5, 95)],
    "roe": [(0, 8), (8, 30), (13, 52), (18, 74), (25, 90), (40, 97)],
    "cost_income": [(30, 95), (38, 82), (45, 62), (52, 40), (60, 22), (70, 8)],
    "gnpa": [(0.3, 95), (1.0, 82), (2.0, 62), (3.5, 40), (5.0, 22), (8.0, 8)],
    "nnpa": [(0.15, 95), (0.4, 82), (0.8, 65), (1.2, 45), (2.0, 25), (4.0, 8)],
    "pcr": [(50, 20), (60, 40), (70, 60), (80, 78), (90, 92)],
    "credit_cost": [(0.15, 92), (0.4, 78), (0.7, 58), (1.0, 40), (1.5, 22), (2.5, 8)],
    "slippages": [(0.4, 90), (0.8, 75), (1.2, 58), (1.8, 40), (2.5, 22), (4.0, 8)],
    "restructured_loans": [(0.2, 90), (0.5, 75), (1.0, 55), (2.0, 32), (4.0, 12)],
    "sma_or_stressed_assets": [(0.3, 90), (0.8, 72), (1.5, 52), (2.5, 32), (4.5, 12)],
    "cet1": [(9, 15), (11, 40), (13, 62), (15, 78), (17, 90), (20, 96)],
    "car": [(11, 18), (13, 42), (15, 62), (17, 78), (19, 90), (22, 96)],
}

_INDUSTRIAL_GROWTH = frozenset({
    "rev_yoy", "rev_cagr", "pat_yoy", "pat_cagr", "q_rev_yoy", "q_pat_yoy",
})

_PILLAR_MAP = {
    "growth": BANK_GROWTH_WEIGHTS,
    "profitability": BANK_PROFIT_WEIGHTS,
    "health": BANK_HEALTH_WEIGHTS,
}


def score_bank_metric(key: str, value: float | None, unit: str = "%") -> float | None:
    """0–100 band for a canonical bank KPI. None stays None."""
    scaled = _scoreable_value(key, value, unit)
    if scaled is None:
        return None
    points = BANK_BANDS.get(key)
    if not points:
        return None
    return band(scaled, points)


def apply_bank_metrics(
    pillars: dict[str, Pillar],
    bank_metrics: BankMetrics | None,
    profile: str,
) -> None:
    """Inject canonical bank KPIs into existing pillars. No-op for non-banks."""
    if profile != PROFILE_BANK or bank_metrics is None:
        return
    _null_industrial_growth(pillars.get("growth"))
    for pillar_key, weights in _PILLAR_MAP.items():
        pillar = pillars.get(pillar_key)
        if pillar is None:
            continue
        for key, weight in weights.items():
            canonical = getattr(bank_metrics, key, None)
            _upsert_metric(pillar, _metric_from_canonical(key, canonical, weight))


def _metric_from_canonical(key: str, canonical: BankMetric | None, weight: float) -> Metric:
    value = canonical.value if canonical is not None else None
    unit = canonical.unit if canonical is not None and canonical.unit else "%"
    score = score_bank_metric(key, value, unit)
    note = ""
    if canonical is not None and canonical.provenance and canonical.provenance.excerpt:
        note = canonical.provenance.excerpt[:160]
    return Metric(
        key=key,
        label=BANK_LABELS[key],
        value=value,
        unit=unit,
        score=score,
        note=note,
        weight=weight,
        higher_is_better=key not in LOWER_IS_BETTER,
    )


def _scoreable_value(key: str, value: float | None, unit: str) -> float | None:
    if value is None:
        return None
    unit_n = (unit or "%").strip().lower()
    if unit_n in {"bps", "bp", "basis_points", "basis points"}:
        return float(value) / 100.0
    if key in {"slippages", "restructured_loans", "sma_or_stressed_assets", "credit_cost"}:
        if unit_n not in {"%", "percent", "pct", "percentage"} and unit_n not in {
            "bps", "bp", "basis_points", "basis points",
        }:
            return None
    return float(value)


def _null_industrial_growth(pillar: Pillar | None) -> None:
    if pillar is None:
        return
    for metric in pillar.metrics:
        if metric.key in _INDUSTRIAL_GROWTH:
            metric.score = None
            metric.weight = 0.0


def _upsert_metric(pillar: Pillar, metric: Metric) -> None:
    for index, existing in enumerate(pillar.metrics):
        if existing.key == metric.key:
            pillar.metrics[index] = metric
            return
    pillar.metrics.append(metric)
