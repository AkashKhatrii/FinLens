"""Attach canonical BankMetrics to a live bank analysis.

Uses Stage 2 discovery/fetch and Stage 3 extraction. Failures are swallowed
so Yahoo-based analysis still returns. Not a Stage 2A ranking change.
"""
from __future__ import annotations

import logging
import re

from .. import cache
from ..config import FUNDAMENTAL_TTL, MARKETS
from .bank_document_fetcher import fetch_bank_document
from .bank_documents import (
    DOC_INVESTOR_PRESENTATION,
    BankDocument,
    discover_bank_documents,
)
from .bank_kpi_extractor import (
    extract_bank_metrics_from_pdf,
    extract_bank_metrics_from_text,
)
from .bank_metrics import BANK_METRIC_KEYS, BankMetrics
from .bank_sources import is_supported_bank

log = logging.getLogger(__name__)

CACHE_NS = "bank_metrics"
MISS_TTL = 1800

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


def bare_equity_ticker(symbol: str) -> str:
    text = (symbol or "").strip().upper()
    for suffix in MARKETS["IN"]["suffixes"]:
        if text.endswith(suffix.upper()):
            return text[: -len(suffix)]
    return text


def has_canonical_values(metrics: BankMetrics | None) -> bool:
    if metrics is None:
        return False
    for key in BANK_METRIC_KEYS:
        item = getattr(metrics, key, None)
        if item is not None and item.value is not None:
            return True
    return False


def choose_bank_presentation(documents: list[BankDocument]) -> BankDocument | None:
    presentations = [
        doc for doc in documents
        if doc.document_type == DOC_INVESTOR_PRESENTATION
    ]
    if not presentations:
        return None

    def score(doc: BankDocument) -> tuple:
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


def load_canonical_bank_metrics(symbol: str) -> BankMetrics | None:
    """Best-effort official-PDF extract. None on any failure. No exceptions out."""
    ticker = bare_equity_ticker(symbol)
    if not is_supported_bank(ticker):
        return None
    hit = cache.get(CACHE_NS, ticker, FUNDAMENTAL_TTL)
    if isinstance(hit, BankMetrics):
        return hit
    if cache.get(f"{CACHE_NS}_miss", ticker, MISS_TTL):
        return None
    try:
        metrics = _extract_from_official_documents(ticker)
    except Exception:
        log.exception("Bank KPI load failed for %s", ticker)
        cache.put(f"{CACHE_NS}_miss", ticker, True)
        return None
    if has_canonical_values(metrics):
        cache.put(CACHE_NS, ticker, metrics)
        return metrics
    cache.put(f"{CACHE_NS}_miss", ticker, True)
    return None


def _extract_from_official_documents(ticker: str) -> BankMetrics | None:
    discovered = discover_bank_documents(ticker)
    document = choose_bank_presentation(discovered.documents)
    if document is None:
        log.info("No investor presentation discovered for %s", ticker)
        return None
    fetched = fetch_bank_document(document)
    if not fetched.ok or not fetched.content:
        log.info("Could not fetch bank presentation for %s: %s", ticker, fetched.error)
        return None
    if _looks_like_pdf(fetched.content, fetched.content_type):
        return extract_bank_metrics_from_pdf(
            fetched.content, document, target_period=document.period,
        )
    text = fetched.content.decode("utf-8", errors="ignore")
    return extract_bank_metrics_from_text(
        text, document, target_period=document.period,
    )


def _looks_like_pdf(content: bytes, content_type: str | None) -> bool:
    if content[:4] == b"%PDF":
        return True
    return "pdf" in (content_type or "").lower()
