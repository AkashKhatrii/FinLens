"""Fetch official bank documents discovered by Stage 2A.

Downloads only. This module does not parse PDFs, extract text, or compute
bank KPIs. Bodies stay in memory: the existing pickle cache is for small
market-data blobs, not multi-megabyte filings.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests

from .bank_documents import BankDocument, DEFAULT_TIMEOUT, UA
from .bank_sources import SOURCE_TYPE_OFFICIAL_IR, get_bank_source

log = logging.getLogger(__name__)

MAX_REDIRECTS = 5
# Quarterly decks are a few MB; this caps accidental giant dumps / zip bombs.
DEFAULT_MAX_BYTES = int(os.getenv("FINLENS_BANK_DOC_MAX_BYTES", str(20 * 1024 * 1024)))

_REDIRECTS = {301, 302, 303, 307, 308}
_PDF_TYPE = "application/pdf"
_HTML_MARKERS = (b"<!doctype html", b"<html", b"<head", b"<body")


@dataclass
class BankDocumentFetchResult:
    document: BankDocument
    ok: bool
    error: str | None = None
    content_type: str | None = None
    content_length: int | None = None
    content: bytes | None = None
    final_url: str | None = None
    status_code: int | None = None


def official_hosts_for_ticker(ticker: str) -> set[str]:
    source = get_bank_source(ticker)
    if source is None:
        return set()
    hosts: set[str] = set()
    for url in (
        source.investor_relations_url,
        source.financial_results_url,
        source.investor_presentations_url,
    ):
        if not url:
            continue
        host = urlparse(url).netloc.lower()
        if not host:
            continue
        hosts.add(host)
        if host.startswith("www."):
            hosts.add(host[4:])
        else:
            hosts.add(f"www.{host}")
    return hosts


def is_allowed_bank_document_url(url: str, ticker: str) -> bool:
    parsed = urlparse(url or "")
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    return parsed.netloc.lower() in official_hosts_for_ticker(ticker)


def is_pdf_content(content: bytes | None) -> bool:
    return bool(content) and content.startswith(b"%PDF")


def validate_document_response(
    content: bytes,
    content_type: str | None,
    url: str = "",
) -> str | None:
    """Return an error code, or None if the body is an allowed PDF/HTML document."""
    ct = (content_type or "").lower()
    path = urlparse(url).path.lower()
    if is_pdf_content(content):
        return None
    if _PDF_TYPE in ct:
        return "invalid_pdf"
    if "text/html" in ct or "application/xhtml" in ct:
        return None
    if ct:
        return "unsupported_content"
    if _looks_like_html(content):
        return None
    if path.endswith(".pdf"):
        return "invalid_pdf"
    return "unsupported_content"


def fetch_bank_document(
    document: BankDocument,
    timeout: int = DEFAULT_TIMEOUT,
    max_bytes: int | None = None,
) -> BankDocumentFetchResult:
    limit = DEFAULT_MAX_BYTES if max_bytes is None else max_bytes
    if document.source != SOURCE_TYPE_OFFICIAL_IR:
        return _fail(document, "unsupported_source")
    parsed = urlparse(document.url or "")
    if parsed.scheme != "https":
        return _fail(document, "invalid_url")
    if not is_allowed_bank_document_url(document.url, document.ticker):
        return _fail(document, "unregistered_host")

    url = document.url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            resp = requests.get(
                url,
                timeout=timeout,
                headers={"User-Agent": UA},
                allow_redirects=False,
                stream=True,
            )
            status = resp.status_code
            if status in _REDIRECTS:
                location = (resp.headers.get("Location") or "").strip()
                resp.close()
                if not location:
                    return _fail(document, "redirect_blocked", status_code=status)
                nxt = urljoin(url, location)
                if not is_allowed_bank_document_url(nxt, document.ticker):
                    return _fail(document, "redirect_blocked", status_code=status)
                url = nxt
                continue
            return _read_body(document, resp, url, limit)
        return _fail(document, "redirect_blocked")
    except (TimeoutError, requests.Timeout):
        log.warning("Timed out fetching bank document %s", document.url)
        return _fail(document, "timeout")
    except Exception as exc:
        log.warning("Could not fetch bank document %s: %s", document.url, exc)
        return _fail(document, "unavailable")


def _read_body(
    document: BankDocument,
    resp: requests.Response,
    url: str,
    limit: int,
) -> BankDocumentFetchResult:
    status = resp.status_code
    content_type = resp.headers.get("Content-Type")
    declared_len = _content_length(resp.headers.get("Content-Length"))
    try:
        if status >= 400:
            return _fail(
                document,
                f"http_{status}",
                content_type=content_type,
                content_length=declared_len,
                final_url=url,
                status_code=status,
            )
        if declared_len is not None and declared_len > limit:
            return _fail(
                document,
                "oversized",
                content_type=content_type,
                content_length=declared_len,
                final_url=url,
                status_code=status,
            )
        buf = bytearray()
        for chunk in resp.iter_content(chunk_size=65536):
            if not chunk:
                continue
            buf.extend(chunk)
            if len(buf) > limit:
                return _fail(
                    document,
                    "oversized",
                    content_type=content_type,
                    content_length=len(buf),
                    final_url=url,
                    status_code=status,
                )
        content = bytes(buf)
    finally:
        resp.close()

    if not content:
        return _fail(
            document,
            "empty",
            content_type=content_type,
            content_length=0,
            final_url=url,
            status_code=status,
        )
    error = validate_document_response(content, content_type, url)
    if error:
        return _fail(
            document,
            error,
            content_type=content_type,
            content_length=len(content),
            final_url=url,
            status_code=status,
        )
    return BankDocumentFetchResult(
        document=document,
        ok=True,
        content_type=content_type,
        content_length=len(content),
        content=content,
        final_url=url,
        status_code=status,
    )


def _content_length(raw: str | None) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _looks_like_html(content: bytes) -> bool:
    head = content.lstrip()[:64].lower()
    return any(head.startswith(marker) for marker in _HTML_MARKERS)


def _fail(
    document: BankDocument,
    error: str,
    content_type: str | None = None,
    content_length: int | None = None,
    final_url: str | None = None,
    status_code: int | None = None,
) -> BankDocumentFetchResult:
    return BankDocumentFetchResult(
        document=document,
        ok=False,
        error=error,
        content_type=content_type,
        content_length=content_length,
        content=None,
        final_url=final_url,
        status_code=status_code,
    )
