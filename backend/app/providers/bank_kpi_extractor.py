"""Orchestrate bank KPI extraction from official document pages.

Pipeline: page text → candidate pages → AI extraction → deterministic
validation → canonical resolution → BankMetrics. No scoring.
No ticker-specific branches. The AI does not choose canonical metrics.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from .bank_documents import BankDocument
from .bank_kpi import validate_ai_candidates
from .bank_metric_canonical import resolve_canonical_metric
from .bank_metrics import (
    BANK_METRIC_KEYS,
    EXTRACTION_FAILED,
    EXTRACTION_OK,
    EXTRACTION_PARTIAL,
    BankMetric,
    BankMetrics,
    MetricProvenance,
    RawFact,
)
from .pdf_text import PdfPage, extract_pdf_pages

AiComplete = Callable[[str, str], dict[str, Any]]

_METRIC_LABELS = {
    "gnpa": "Gross NPA",
    "nnpa": "Net NPA",
    "pcr": "PCR",
    "credit_cost": "Credit Cost",
    "slippages": "Slippages",
    "nim": "NIM",
    "roa": "RoA",
    "roe": "RoE",
    "nii_growth": "NII growth",
    "loan_growth": "Loan growth",
    "deposit_growth": "Deposit growth",
    "casa": "CASA",
    "casa_trend": "CASA trend",
    "car": "CAR",
    "cet1": "CET1",
    "cost_income": "Cost to income",
    "restructured_loans": "Restructured loans",
    "sma_or_stressed_assets": "SMA / stressed assets",
    "writeoffs": "Write-offs",
    "recoveries": "Recoveries",
}

_CANDIDATE_RE = re.compile(
    r"\bgnpa\b|\bnnpa\b|\bnpa\b|slippage|credit\s+cost|\bpcr\b|provision|"
    r"\bnim\b|net\s+interest\s+margin|\bnii\b|net\s+interest\s+income|"
    r"\broa\b|\broe\b|return\s+on\s+(?:average\s+)?assets|return\s+on\s+(?:average\s+)?equity|"
    r"\badvances\b|\bloans\b|\bdeposits\b|\bcasa\b|"
    r"\bcrar\b|\bcar\b|\bcet\s*[-–]?\s*1\b|capital\s+adequacy|"
    r"cost\s*[-/]?\s*to\s*[-/]?\s*income|cost\s*/\s*income|"
    r"restructur|\bsma\b|stressed\s+assets|write[-\s]?off|recover",
    re.I,
)


def select_candidate_pages(pages: list[PdfPage]) -> list[PdfPage]:
    """Return pages that look KPI-relevant. Does not choose a financial value."""
    if not pages:
        return []
    matched = [page for page in pages if _CANDIDATE_RE.search(page.text or "")]
    return matched or list(pages)


def extract_bank_metrics_from_text(
    text: str,
    document: BankDocument,
    target_period: str | None = None,
    *,
    ai_complete: AiComplete | None = None,
) -> BankMetrics:
    pages = [PdfPage(number=1, text=text or "")]
    return extract_bank_metrics_from_pages(
        pages, document, target_period=target_period, ai_complete=ai_complete,
    )


def extract_bank_metrics_from_pdf(
    content: bytes,
    document: BankDocument,
    target_period: str | None = None,
    *,
    ai_complete: AiComplete | None = None,
) -> BankMetrics:
    pages = extract_pdf_pages(content)
    period = target_period or document.period
    if not pages:
        result = BankMetrics(
            ticker=document.ticker,
            period=period,
            status=EXTRACTION_FAILED,
            error="No PDF text could be extracted.",
        )
        result.warnings.append("No PDF text could be extracted.")
        return result
    return extract_bank_metrics_from_pages(
        pages, document, target_period=period, ai_complete=ai_complete,
    )


def extract_bank_metrics_from_pages(
    pages: list[PdfPage],
    document: BankDocument,
    target_period: str | None = None,
    *,
    ai_complete: AiComplete | None = None,
) -> BankMetrics:
    period = target_period or document.period
    candidates = select_candidate_pages(pages)
    metrics = BankMetrics(
        ticker=document.ticker,
        period=period,
        candidate_page_numbers=[page.number for page in candidates],
    )
    if not candidates:
        metrics.status = EXTRACTION_FAILED
        metrics.error = "No document pages were available for extraction."
        return metrics

    from ..ai.bank_kpi_extraction import BANK_KPI_SYSTEM_PROMPT, build_kpi_user_prompt, complete_bank_kpi_json

    user = build_kpi_user_prompt(candidates, document, period)
    complete = ai_complete or complete_bank_kpi_json
    try:
        payload = complete(BANK_KPI_SYSTEM_PROMPT, user)
    except Exception as exc:
        metrics.status = EXTRACTION_FAILED
        metrics.error = f"Bank KPI extraction failed: {exc}"
        return metrics

    if not isinstance(payload, dict):
        metrics.status = EXTRACTION_FAILED
        metrics.error = "AI output was not a JSON object."
        return metrics
    if payload.get("error"):
        metrics.status = EXTRACTION_FAILED
        metrics.error = str(payload["error"])
        return metrics

    validated = validate_ai_candidates(payload, candidates, target_period=period)
    metrics.raw_facts = list(validated.facts)
    metrics.rejected = list(validated.rejected)
    metrics.warnings.extend(validated.rejected)
    if validated.malformed:
        metrics.status = EXTRACTION_FAILED
        metrics.error = "The AI response did not match the expected format."
        return metrics

    _apply_facts(metrics, validated.facts, document, period)
    if metrics.ambiguous:
        metrics.status = EXTRACTION_PARTIAL
    else:
        metrics.status = EXTRACTION_OK
    return metrics


def _apply_facts(
    metrics: BankMetrics,
    facts: list[RawFact],
    document: BankDocument,
    target_period: str | None,
) -> None:
    for key in BANK_METRIC_KEYS:
        keyed = [fact for fact in facts if fact.key == key]
        if not keyed:
            continue
        resolved = resolve_canonical_metric(keyed, key, target_period)
        if resolved.fact is None:
            metrics.ambiguous[key] = keyed
            if any(fact.series or fact.uncertain for fact in keyed) and not resolved.survivors:
                metrics.warnings.append(
                    f"{key} has no headline candidate and was not assigned."
                )
            elif len(keyed) > 1:
                metrics.warnings.append(
                    f"Multiple candidates for {key} were equally plausible; left unassigned."
                )
            continue
        chosen = resolved.fact
        setattr(
            metrics,
            key,
            BankMetric(
                key=key,
                label=_METRIC_LABELS[key],
                value=chosen.value,
                unit=chosen.unit,
                period=chosen.period or target_period,
                comparison=chosen.comparison,
                measurement=chosen.measurement,
                consolidation=chosen.consolidation,
                confidence=chosen.confidence,
                resolution_reason=resolved.reason,
                provenance=MetricProvenance(
                    source_title=document.title,
                    source_url=document.url,
                    source_type=document.source,
                    excerpt=chosen.excerpt,
                    raw_label=chosen.raw_label,
                    page=chosen.page,
                ),
            ),
        )
