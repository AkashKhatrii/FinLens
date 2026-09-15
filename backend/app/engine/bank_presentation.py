"""User-facing BankMetrics: labels, grouping, and fact-pack shape.

Scoring stays in bank_scoring.py. This module never reads raw_facts or
resolution_reason.
"""
from __future__ import annotations

from .common import Metric
from ..providers.bank_metrics import BankMetric, BankMetrics

BANK_PUBLIC_LABELS = {
    "gnpa": "GNPA",
    "nnpa": "NNPA",
    "pcr": "PCR",
    "credit_cost": "Credit Cost",
    "slippages": "Slippages",
    "nim": "NIM",
    "roa": "ROA",
    "roe": "ROE",
    "nii_growth": "NII Growth",
    "loan_growth": "Loan Growth",
    "deposit_growth": "Deposit Growth",
    "casa": "CASA",
    "casa_trend": "CASA Trend",
    "car": "CAR / CRAR",
    "cet1": "CET1",
    "cost_income": "Cost / Income",
    "restructured_loans": "Restructured Loans",
    "sma_or_stressed_assets": "SMA / Stressed Assets",
    "writeoffs": "Write-offs",
    "recoveries": "Recoveries",
}

BANK_PUBLIC_GROUPS: list[tuple[str, str, tuple[str, ...]]] = [
    ("asset_quality", "Asset Quality", (
        "gnpa", "nnpa", "pcr", "credit_cost", "slippages",
        "restructured_loans", "sma_or_stressed_assets",
    )),
    ("profitability", "Profitability", (
        "nim", "roa", "roe", "nii_growth", "cost_income",
    )),
    ("growth_deposits", "Growth & Deposits", (
        "loan_growth", "deposit_growth", "casa", "casa_trend",
    )),
    ("capital", "Capital", ("car", "cet1")),
    ("other", "Other", ("writeoffs", "recoveries")),
]

BANK_FACT_PACK_NOTE = (
    "Canonical bank-specific fundamentals from official filings. "
    "These take precedence over generic industrial ratios for this company. "
    "Each figure is a point-in-time reading for the stated period, not a trend."
)


def public_bank_metrics(metrics: BankMetrics | None) -> dict | None:
    """Serializable Bank Fundamentals block. None if there is nothing to show."""
    if metrics is None:
        return None
    groups = []
    for key, label, fields in BANK_PUBLIC_GROUPS:
        items = []
        for field in fields:
            canonical = getattr(metrics, field, None)
            item = _public_item(field, canonical)
            if item is not None:
                items.append(item)
        if items:
            groups.append({"key": key, "label": label, "metrics": items})
    if not groups:
        return None
    return {"period": metrics.period, "groups": groups}


def fact_pack_bank_fundamentals(public: dict | None) -> dict | None:
    if not public:
        return None
    return {
        "note": BANK_FACT_PACK_NOTE,
        "period": public.get("period"),
        "groups": {
            group["label"]: {item["label"]: item["display"] for item in group["metrics"]}
            for group in public["groups"]
        },
    }


def format_bank_display(value: float, unit: str) -> str:
    unit_n = (unit or "%").strip()
    if unit_n in {"%", "percent", "pct", "percentage"}:
        # Small bank ratios (GNPA 1.17, NIM 3.26) need two decimals;
        # larger percentages keep the usual one-decimal FinLens style.
        if abs(value) < 5:
            return f"{value:,.2f}%"
        return f"{value:,.1f}%"
    if unit_n == "x":
        return Metric(key="", label="", value=value, unit="x").display
    number = Metric(key="", label="", value=value, unit="").display
    return f"{number} {unit_n}".strip()


def _public_item(key: str, canonical: BankMetric | None) -> dict | None:
    if canonical is None or canonical.value is None:
        return None
    unit = canonical.unit or "%"
    item = {
        "key": key,
        "label": BANK_PUBLIC_LABELS[key],
        "value": canonical.value,
        "unit": unit,
        "display": format_bank_display(canonical.value, unit),
        "period": canonical.period,
    }
    if canonical.provenance and canonical.provenance.source_title:
        item["source"] = canonical.provenance.source_title
    return item
