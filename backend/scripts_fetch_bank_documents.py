"""Manually probe official bank document fetches. Not part of unittest.

PYTHONPATH=. .venv/bin/python scripts_fetch_bank_documents.py
"""
from __future__ import annotations

import logging
import sys

logging.basicConfig(level=logging.WARNING)

from app.providers.bank_document_fetcher import (  # noqa: E402
    fetch_bank_document,
    is_pdf_content,
)
from app.providers.bank_documents import discover_bank_documents  # noqa: E402

TICKERS = ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK"]
MAX_DOCS = 2


def _type_label(document_type: str) -> str:
    return {
        "investor_presentation": "Investor Presentation",
        "financial_results": "Financial Results",
    }.get(document_type, document_type)


def _print_fetch(ticker: str, doc, result) -> None:
    print(ticker)
    print(doc.period or "period unknown")
    print(_type_label(doc.document_type))
    print(f"URL: {result.final_url or doc.url}")
    print(f"HTTP: {result.status_code if result.status_code is not None else '-'}")
    print(f"Content-Type: {result.content_type or '-'}")
    size = result.content_length
    print(f"Size: {size if size is not None else '-'}")
    if result.ok and is_pdf_content(result.content):
        pdf = "valid"
    elif result.ok:
        pdf = "no"
    else:
        pdf = f"no ({result.error})"
    print(f"PDF: {pdf}")
    print()


def main() -> int:
    for ticker in TICKERS:
        discovery = discover_bank_documents(ticker)
        if discovery.error:
            print(ticker)
            print(f"discovery error: {discovery.error}")
            print()
            continue
        if not discovery.documents:
            unavailable = ", ".join(
                f"{s.url} ({s.error or 'unavailable'})"
                for s in discovery.sources
                if not s.ok
            )
            print(ticker)
            print("no documents discovered")
            if unavailable:
                print(f"sources unavailable: {unavailable}")
            print()
            continue
        chosen = [
            d for d in discovery.documents
            if d.document_type in {"investor_presentation", "financial_results"}
        ][:MAX_DOCS]
        if not chosen:
            chosen = discovery.documents[:MAX_DOCS]
        for doc in chosen:
            result = fetch_bank_document(doc)
            _print_fetch(ticker, doc, result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
