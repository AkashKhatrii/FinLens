"""Manually extract bank KPIs from official IR presentations.

Uses Stage 2A discovery, Stage 2B fetch, then the Stage 3A hybrid extractor.
Not part of unittest. Does not write the PDF to a cache.

PYTHONPATH=. .venv/bin/python scripts_extract_bank_kpis.py
PYTHONPATH=. .venv/bin/python scripts_extract_bank_kpis.py HDFCBANK ICICIBANK SBIN AXISBANK
"""
from __future__ import annotations

import logging
import re
import sys

logging.basicConfig(level=logging.WARNING)

from app.providers.bank_document_fetcher import fetch_bank_document  # noqa: E402
from app.providers.bank_documents import (  # noqa: E402
    DOC_INVESTOR_PRESENTATION,
    discover_bank_documents,
)
from app.providers.bank_kpi import normalize_period_label  # noqa: E402
from app.providers.bank_kpi_extractor import extract_bank_metrics_from_pdf  # noqa: E402
from app.providers.bank_metrics import BANK_METRIC_KEYS  # noqa: E402

DEFAULT_TICKERS = ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK"]

# Prefer an already-discovered quarterly bank deck over a subsidiary/product
# deck. Does not add ticker URL logic and does not change Stage 2A ranking.
_NON_BANK_DECK_RE = re.compile(
    r"insurance|\bamc\b|\besg\b|\bsustainability\b|general\s+insurance",
    re.I,
)
_EXPLICIT_QUARTER_RE = re.compile(
    r"Q\s*[1-4]\s*[-_/]?\s*(?:FY\s*)?(?:20)?\d{2}",
    re.I,
)
_QUARTERLY_DECK_RE = re.compile(
    r"earnings(?:[- ]presentation)?|analyst[- ]presentation|"
    r"quarter[- ]ended|quarterly|"
    r"q[1-4]\s*[-_/]?\s*(?:fy|20\d{2})",
    re.I,
)


def _choose_presentation(documents):
    presentations = [
        doc for doc in documents
        if doc.document_type == DOC_INVESTOR_PRESENTATION
    ]
    if not presentations:
        return None

    def score(doc) -> tuple:
        blob = f"{doc.title or ''} {doc.url or ''}"
        penalty = 50 if _NON_BANK_DECK_RE.search(blob) else 0
        explicit_q = 20 if _EXPLICIT_QUARTER_RE.search(blob) else 0
        quarterly = 8 if _QUARTERLY_DECK_RE.search(blob) else 0
        period = 10 if doc.period else 0
        return (explicit_q + quarterly + period - penalty, explicit_q, period)

    ranked = sorted(presentations, key=score, reverse=True)
    best = ranked[0]
    if score(best)[0] <= 0:
        return presentations[0]
    return best


def _print_metrics(metrics) -> None:
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


def extract_ticker(ticker: str) -> int:
    discovery = discover_bank_documents(ticker)
    if discovery.error:
        print(f"{ticker} discovery error: {discovery.error}")
        return 1
    presentations = [
        doc for doc in discovery.documents
        if doc.document_type == DOC_INVESTOR_PRESENTATION
    ]
    document = _choose_presentation(discovery.documents)
    if document is None:
        print(f"{ticker}: no investor presentation discovered.")
        for source in discovery.sources:
            if not source.ok:
                print(f"  unavailable: {source.url} ({source.error})")
        return 1

    period = document.period
    if not period:
        blob = f"{document.title or ''} {document.url or ''}"
        match = _EXPLICIT_QUARTER_RE.search(blob)
        if match:
            period = normalize_period_label(match.group(0))

    print(ticker)
    print(period or "period unknown")
    print(document.title)
    print(f"URL: {document.url}")
    if presentations and presentations[0].url != document.url:
        print(f"Stage 2A first presentation was: {presentations[0].title}")
        print(f"  {presentations[0].url}")
    print()

    fetched = fetch_bank_document(document)
    if not fetched.ok or not fetched.content:
        print(f"fetch failed: {fetched.error or 'empty'}")
        print(f"HTTP: {fetched.status_code}")
        return 1

    metrics = extract_bank_metrics_from_pdf(
        fetched.content, document, target_period=period
    )
    _print_metrics(metrics)
    return 0 if metrics.status != "failed" else 2


def main(argv: list[str]) -> int:
    tickers = [item.strip().upper() for item in argv[1:] if item.strip()] or list(DEFAULT_TICKERS)
    status = 0
    for index, ticker in enumerate(tickers):
        if index:
            print()
            print("=" * 72)
            print()
        code = extract_ticker(ticker)
        status = max(status, code)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
