"""PDF text extraction for official bank documents.

Page-level text only. No OCR. Page numbers come from the PDF parser when it
can iterate pages; they are not invented.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from io import BytesIO

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PdfPage:
    number: int
    text: str


def extract_pdf_pages(content: bytes) -> list[PdfPage]:
    if not content or not content.startswith(b"%PDF"):
        return []
    try:
        from pypdf import PdfReader
    except ImportError:
        log.warning("pypdf is not installed; cannot extract PDF text.")
        return []
    try:
        reader = PdfReader(BytesIO(content))
        pages: list[PdfPage] = []
        for index, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            pages.append(PdfPage(number=index, text=text))
        return pages
    except Exception as exc:
        log.warning("Could not read PDF: %s", exc)
        return []


def extract_pdf_text(content: bytes) -> str:
    return "\n".join(page.text for page in extract_pdf_pages(content) if page.text)


def format_pages_for_ai(pages: list[PdfPage]) -> str:
    """Serialize page-bounded text so evidence can cite a page number."""
    blocks: list[str] = []
    for page in pages:
        body = (page.text or "").strip() or "[no extractable text]"
        blocks.append(f"--- Page {page.number} ---\n{body}")
    return "\n\n".join(blocks)
