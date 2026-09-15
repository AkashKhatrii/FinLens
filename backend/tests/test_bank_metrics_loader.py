"""Live analysis must attach canonical BankMetrics for classified banks."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.analysis import _bank_metrics_for_analysis
from app.engine.sector import PROFILE_BANK, PROFILE_DEFAULT
from app.providers.bank_metrics import BankMetric, BankMetrics
from test_bank_scoring import HDFC


class TestAnalysisLoadsBankMetrics(unittest.TestCase):
    def test_injected_metrics_are_not_replaced(self):
        with patch("app.analysis.load_canonical_bank_metrics") as loader:
            got = _bank_metrics_for_analysis(
                "HDFCBANK.NS", "Financial Services", "Banks - Regional", HDFC,
            )
            self.assertIs(got, HDFC)
            loader.assert_not_called()

    def test_classified_bank_loads_canonical_metrics(self):
        with patch("app.analysis.load_canonical_bank_metrics", return_value=HDFC) as loader:
            got = _bank_metrics_for_analysis(
                "HDFCBANK.NS", "Financial Services", "Banks - Regional", None,
            )
            self.assertIs(got, HDFC)
            loader.assert_called_once_with("HDFCBANK.NS")

    def test_industrial_company_does_not_load_bank_metrics(self):
        with patch("app.analysis.load_canonical_bank_metrics") as loader:
            got = _bank_metrics_for_analysis(
                "TCS.NS", "Technology", "Information Technology Services", None,
            )
            self.assertIsNone(got)
            loader.assert_not_called()


class TestLoaderUsesRegistryAndCache(unittest.TestCase):
    def test_unsupported_ticker_does_not_touch_the_network(self):
        from app.providers.bank_metrics_loader import load_canonical_bank_metrics

        with patch("app.providers.bank_metrics_loader.discover_bank_documents") as discover:
            self.assertIsNone(load_canonical_bank_metrics("TCS.NS"))
            discover.assert_not_called()

    def test_strips_exchange_suffix_before_registry_lookup(self):
        from app.providers.bank_metrics_loader import bare_equity_ticker

        self.assertEqual(bare_equity_ticker("HDFCBANK.NS"), "HDFCBANK")
        self.assertEqual(bare_equity_ticker("SBIN.BO"), "SBIN")
        self.assertEqual(bare_equity_ticker("AXISBANK"), "AXISBANK")

    def test_successful_extract_is_returned(self):
        from app.providers.bank_documents import BankDocument, BankDiscoveryResult
        from app.providers.bank_metrics_loader import load_canonical_bank_metrics

        doc = BankDocument(
            ticker="HDFCBANK",
            title="Q1 FY27 Investor Presentation",
            url="https://www.hdfc.bank.in/q1.pdf",
            document_type="investor_presentation",
            period="Q1 FY27",
        )
        fetched = type("F", (), {"ok": True, "content": b"%PDF-1.4", "content_type": "application/pdf", "error": None})()
        metrics = BankMetrics(ticker="HDFCBANK", period="Q1 FY27")
        metrics.gnpa = BankMetric(key="gnpa", label="GNPA", value=1.17, unit="%")

        with patch("app.providers.bank_metrics_loader.cache.get", return_value=None), \
             patch("app.providers.bank_metrics_loader.cache.put"), \
             patch("app.providers.bank_metrics_loader.discover_bank_documents", return_value=BankDiscoveryResult(ticker="HDFCBANK", documents=[doc])), \
             patch("app.providers.bank_metrics_loader.fetch_bank_document", return_value=fetched), \
             patch("app.providers.bank_metrics_loader.extract_bank_metrics_from_pdf", return_value=metrics) as extract:
            got = load_canonical_bank_metrics("HDFCBANK.NS")
            self.assertIsNotNone(got)
            self.assertEqual(got.gnpa.value, 1.17)
            extract.assert_called_once()

    def test_fetch_failure_returns_none_without_raising(self):
        from app.providers.bank_documents import BankDocument, BankDiscoveryResult
        from app.providers.bank_metrics_loader import load_canonical_bank_metrics

        doc = BankDocument(
            ticker="HDFCBANK",
            title="Q1 FY27 Investor Presentation",
            url="https://www.hdfc.bank.in/q1.pdf",
            document_type="investor_presentation",
        )
        fetched = type("F", (), {"ok": False, "content": None, "content_type": None, "error": "timeout"})()
        with patch("app.providers.bank_metrics_loader.cache.get", return_value=None), \
             patch("app.providers.bank_metrics_loader.cache.put"), \
             patch("app.providers.bank_metrics_loader.discover_bank_documents", return_value=BankDiscoveryResult(ticker="HDFCBANK", documents=[doc])), \
             patch("app.providers.bank_metrics_loader.fetch_bank_document", return_value=fetched), \
             patch("app.providers.bank_metrics_loader.extract_bank_metrics_from_pdf") as extract:
            self.assertIsNone(load_canonical_bank_metrics("HDFCBANK.NS"))
            extract.assert_not_called()


if __name__ == "__main__":
    unittest.main()
