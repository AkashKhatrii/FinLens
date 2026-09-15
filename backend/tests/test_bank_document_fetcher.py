"""Bank document fetcher: mocked HTTP only, no live bank websites."""
from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

from app.providers.bank_document_fetcher import (
    BankDocumentFetchResult,
    fetch_bank_document,
    is_allowed_bank_document_url,
    is_pdf_content,
    validate_document_response,
)
from app.providers.bank_documents import BankDocument


PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
HTML_BYTES = b"<!DOCTYPE html><html><body>Quarterly results</body></html>"
FAKE_PDF_HTML = b"<!DOCTYPE html><html><body>not a pdf</body></html>"

HDFC_PDF_URL = "https://www.hdfc.bank.in/content/IR/Q1FY27-Investor-Presentation.pdf"
HDFC_HTML_URL = "https://www.hdfc.bank.in/about-us/investor-relations/financial-results"
HDFC_ALT_HOST_URL = "https://hdfc.bank.in/content/IR/Q1FY27-Investor-Presentation.pdf"


def _doc(
    url: str = HDFC_PDF_URL,
    ticker: str = "HDFCBANK",
    title: str = "Investor Presentation Q1 FY27",
    document_type: str = "investor_presentation",
    source: str = "official_ir",
) -> BankDocument:
    return BankDocument(
        ticker=ticker,
        title=title,
        url=url,
        document_type=document_type,
        period="Q1 FY27",
        source=source,
    )


class FakeResponse:
    def __init__(
        self,
        url: str,
        status_code: int = 200,
        content: bytes = b"",
        content_type: str | None = None,
        location: str | None = None,
        content_length: int | None = None,
    ) -> None:
        self.url = url
        self.status_code = status_code
        self._content = content
        self.headers = {}
        if content_type is not None:
            self.headers["Content-Type"] = content_type
        if location is not None:
            self.headers["Location"] = location
        if content_length is None:
            content_length = len(content)
        self.headers["Content-Length"] = str(content_length)

    @property
    def content(self) -> bytes:
        return self._content

    def close(self) -> None:
        return None

    def iter_content(self, chunk_size: int = 8192):
        data = self._content
        for i in range(0, len(data), chunk_size):
            yield data[i : i + chunk_size]


class TestUrlValidationHelpers(unittest.TestCase):
    def test_https_official_host_allowed(self):
        self.assertTrue(is_allowed_bank_document_url(HDFC_PDF_URL, "HDFCBANK"))
        self.assertTrue(is_allowed_bank_document_url(HDFC_ALT_HOST_URL, "hdfcbank"))

    def test_http_url_rejected(self):
        self.assertFalse(
            is_allowed_bank_document_url(
                "http://www.hdfc.bank.in/content/IR/Q1FY27-Investor-Presentation.pdf",
                "HDFCBANK",
            )
        )

    def test_third_party_and_unknown_hosts_rejected(self):
        self.assertFalse(
            is_allowed_bank_document_url(
                "https://www.moneycontrol.com/hdfcbank.pdf", "HDFCBANK"
            )
        )
        self.assertFalse(
            is_allowed_bank_document_url("https://evil.example/a.pdf", "HDFCBANK")
        )
        self.assertFalse(
            is_allowed_bank_document_url(HDFC_PDF_URL, "TCS")
        )

    def test_helpers_do_not_touch_the_network(self):
        for fn in (
            is_allowed_bank_document_url,
            is_pdf_content,
            validate_document_response,
        ):
            src = inspect.getsource(fn)
            self.assertNotIn("urlopen", src)
            self.assertNotIn("requests", src)
            self.assertNotIn("http.client", src)
            self.assertNotIn("urllib.request", src)


class TestPdfAndResponseValidation(unittest.TestCase):
    def test_pdf_magic_bytes(self):
        self.assertTrue(is_pdf_content(PDF_BYTES))
        self.assertFalse(is_pdf_content(HTML_BYTES))
        self.assertFalse(is_pdf_content(b""))
        self.assertFalse(is_pdf_content(None))

    def test_html_claiming_to_be_pdf_is_invalid(self):
        error = validate_document_response(
            FAKE_PDF_HTML, "application/pdf"
        )
        self.assertEqual(error, "invalid_pdf")

    def test_real_pdf_and_html_are_accepted(self):
        self.assertIsNone(validate_document_response(PDF_BYTES, "application/pdf"))
        self.assertIsNone(validate_document_response(HTML_BYTES, "text/html"))

    def test_unsupported_content(self):
        self.assertEqual(
            validate_document_response(b"\x89PNG\r\n", "image/png"),
            "unsupported_content",
        )
        self.assertEqual(
            validate_document_response(b"PK\x03\x04", "application/zip"),
            "unsupported_content",
        )


class TestFetchBankDocument(unittest.TestCase):
    def test_successful_pdf_fetch(self):
        resp = FakeResponse(
            HDFC_PDF_URL, content=PDF_BYTES, content_type="application/pdf"
        )
        with patch("app.providers.bank_document_fetcher.requests.get", return_value=resp) as get:
            result = fetch_bank_document(_doc())
        get.assert_called_once()
        self.assertIsInstance(result, BankDocumentFetchResult)
        self.assertTrue(result.ok)
        self.assertIsNone(result.error)
        self.assertEqual(result.content, PDF_BYTES)
        self.assertTrue(result.content.startswith(b"%PDF"))
        self.assertEqual(result.content_type, "application/pdf")
        self.assertEqual(result.content_length, len(PDF_BYTES))
        self.assertEqual(result.final_url, HDFC_PDF_URL)
        self.assertEqual(result.document.url, HDFC_PDF_URL)

    def test_html_claiming_pdf_is_rejected(self):
        resp = FakeResponse(
            HDFC_PDF_URL, content=FAKE_PDF_HTML, content_type="application/pdf"
        )
        with patch("app.providers.bank_document_fetcher.requests.get", return_value=resp):
            result = fetch_bank_document(_doc())
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "invalid_pdf")
        self.assertIsNone(result.content)

    def test_successful_official_html_document(self):
        resp = FakeResponse(
            HDFC_HTML_URL, content=HTML_BYTES, content_type="text/html; charset=utf-8"
        )
        with patch("app.providers.bank_document_fetcher.requests.get", return_value=resp) as get:
            result = fetch_bank_document(
                _doc(url=HDFC_HTML_URL, document_type="financial_results", title="Financial Results")
            )
        get.assert_called_once()
        self.assertTrue(result.ok)
        self.assertEqual(result.content, HTML_BYTES)
        self.assertIn("html", (result.content_type or "").lower())

    def test_http_url_rejected_without_network(self):
        with patch("app.providers.bank_document_fetcher.requests.get") as get:
            result = fetch_bank_document(
                _doc(url="http://www.hdfc.bank.in/content/IR/Q1FY27-Investor-Presentation.pdf")
            )
        get.assert_not_called()
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "invalid_url")

    def test_third_party_host_rejected_without_network(self):
        with patch("app.providers.bank_document_fetcher.requests.get") as get:
            result = fetch_bank_document(
                _doc(url="https://www.moneycontrol.com/hdfcbank.pdf")
            )
        get.assert_not_called()
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "unregistered_host")

    def test_unknown_bank_host_rejected_without_network(self):
        with patch("app.providers.bank_document_fetcher.requests.get") as get:
            result = fetch_bank_document(_doc(ticker="TCS"))
        get.assert_not_called()
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "unregistered_host")

    def test_non_official_source_rejected_without_network(self):
        with patch("app.providers.bank_document_fetcher.requests.get") as get:
            result = fetch_bank_document(_doc(source="mirror"))
        get.assert_not_called()
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "unsupported_source")

    def test_official_to_official_redirect_accepted(self):
        hops = [
            FakeResponse(HDFC_PDF_URL, status_code=302, location=HDFC_ALT_HOST_URL),
            FakeResponse(
                HDFC_ALT_HOST_URL, content=PDF_BYTES, content_type="application/pdf"
            ),
        ]
        with patch("app.providers.bank_document_fetcher.requests.get", side_effect=hops) as get:
            result = fetch_bank_document(_doc())
        self.assertEqual(get.call_count, 2)
        self.assertTrue(result.ok)
        self.assertEqual(result.final_url, HDFC_ALT_HOST_URL)
        self.assertEqual(result.content, PDF_BYTES)

    def test_redirect_to_third_party_rejected(self):
        hops = [
            FakeResponse(
                HDFC_PDF_URL,
                status_code=302,
                location="https://cdn.example.com/stolen.pdf",
            ),
            FakeResponse(
                "https://cdn.example.com/stolen.pdf",
                content=PDF_BYTES,
                content_type="application/pdf",
            ),
        ]
        with patch("app.providers.bank_document_fetcher.requests.get", side_effect=hops) as get:
            result = fetch_bank_document(_doc())
        self.assertEqual(get.call_count, 1)
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "redirect_blocked")
        self.assertIsNone(result.content)

    def test_timeout(self):
        with patch(
            "app.providers.bank_document_fetcher.requests.get",
            side_effect=TimeoutError("timed out"),
        ):
            result = fetch_bank_document(_doc())
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "timeout")
        self.assertIsNone(result.content)

    def test_http_errors(self):
        for status, code in ((404, "http_404"), (403, "http_403"), (500, "http_500")):
            resp = FakeResponse(HDFC_PDF_URL, status_code=status, content=b"nope")
            with patch("app.providers.bank_document_fetcher.requests.get", return_value=resp):
                result = fetch_bank_document(_doc())
            self.assertFalse(result.ok, status)
            self.assertEqual(result.error, code)
            self.assertEqual(result.status_code, status)
            self.assertIsNone(result.content)

    def test_oversized_response(self):
        resp = FakeResponse(
            HDFC_PDF_URL,
            content=PDF_BYTES,
            content_type="application/pdf",
            content_length=50_000_000,
        )
        with patch("app.providers.bank_document_fetcher.requests.get", return_value=resp):
            result = fetch_bank_document(_doc(), max_bytes=1024)
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "oversized")
        self.assertIsNone(result.content)

    def test_empty_response(self):
        resp = FakeResponse(HDFC_PDF_URL, content=b"", content_type="application/pdf")
        with patch("app.providers.bank_document_fetcher.requests.get", return_value=resp):
            result = fetch_bank_document(_doc())
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "empty")
        self.assertIsNone(result.content)

    def test_unsupported_content(self):
        resp = FakeResponse(
            HDFC_PDF_URL, content=b"\x89PNG\r\n", content_type="image/png"
        )
        with patch("app.providers.bank_document_fetcher.requests.get", return_value=resp):
            result = fetch_bank_document(_doc())
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "unsupported_content")
        self.assertIsNone(result.content)


if __name__ == "__main__":
    unittest.main()
