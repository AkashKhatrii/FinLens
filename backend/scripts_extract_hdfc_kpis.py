"""Manually extract HDFC Q1 FY27 bank KPIs from the official IR presentation.

Uses Stage 2A discovery, Stage 2B fetch, then the Stage 3A hybrid extractor.
Not part of unittest. Does not write the PDF to a cache.

PYTHONPATH=. .venv/bin/python scripts_extract_hdfc_kpis.py
"""
from __future__ import annotations

import logging
import sys

logging.basicConfig(level=logging.WARNING)

from app.providers.bank_document_fetcher import fetch_bank_document  # noqa: E402
from app.providers.bank_documents import discover_bank_documents  # noqa: E402
from app.providers.bank_kpi_extractor import extract_bank_metrics_from_pdf  # noqa: E402
from app.providers.bank_metrics import BANK_METRIC_KEYS  # noqa: E402

TICKER = "HDFCBANK"
PERIOD = "Q1 FY27"


def main() -> int:
    discovery = discover_bank_documents(TICKER)
    if discovery.error:
        print(f"{TICKER} discovery error: {discovery.error}")
        return 1
    chosen = [
        doc for doc in discovery.documents
        if doc.document_type == "investor_presentation" and doc.period == PERIOD
    ]
    if not chosen:
        print(f"{TICKER}: no {PERIOD} investor presentation discovered.")
        for source in discovery.sources:
            if not source.ok:
                print(f"  unavailable: {source.url} ({source.error})")
        return 1

    document = chosen[0]
    print(TICKER)
    print(document.period or PERIOD)
    print(document.title)
    print(f"URL: {document.url}")
    print()

    fetched = fetch_bank_document(document)
    if not fetched.ok or not fetched.content:
        print(f"fetch failed: {fetched.error or 'empty'}")
        print(f"HTTP: {fetched.status_code}")
        return 1

    metrics = extract_bank_metrics_from_pdf(
        fetched.content, document, target_period=PERIOD
    )
    print(f"status: {metrics.status}")
    if metrics.error:
        print(f"error: {metrics.error}")
    if metrics.candidate_page_numbers:
        pages = ", ".join(str(n) for n in metrics.candidate_page_numbers)
        print(f"candidate pages: {pages}")
    print()
    print("Extracted KPIs")
    missing: list[str] = []
    for key in BANK_METRIC_KEYS:
        metric = getattr(metrics, key)
        if metric is None or metric.value is None:
            missing.append(key)
            continue
        page = metric.provenance.page if metric.provenance else None
        excerpt = (metric.provenance.excerpt if metric.provenance else "")[:160]
        conf = f"{metric.confidence:.2f}" if metric.confidence is not None else "-"
        print(
            f"  {key:24s} {metric.value}{metric.unit}  "
            f"period={metric.period or '-'}  "
            f"basis={metric.comparison or '-'}  "
            f"meas={metric.measurement or '-'}  "
            f"scope={metric.consolidation or '-'}  "
            f"page={page if page is not None else '-'}  "
            f"conf={conf}"
        )
        print(f"    evidence: {excerpt}")
    print()
    print("Missing:", ", ".join(missing) if missing else "(none)")
    if metrics.ambiguous:
        print("Ambiguous:")
        for key, facts in metrics.ambiguous.items():
            values = ", ".join(
                f"{fact.value}{fact.unit}"
                f"{'/' + fact.measurement if fact.measurement else ''}"
                f"{'/' + fact.comparison if fact.comparison else ''}"
                f"{'/' + fact.series if fact.series else ''}"
                for fact in facts
            )
            print(f"  {key}: {values}")
    if metrics.warnings:
        print("Warnings:")
        for warning in metrics.warnings[:20]:
            print(f"  {warning}")
        if len(metrics.warnings) > 20:
            print(f"  ... {len(metrics.warnings) - 20} more")
    return 0 if metrics.status != "failed" else 2


if __name__ == "__main__":
    sys.exit(main())
