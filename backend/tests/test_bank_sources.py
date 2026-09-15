"""Official bank IR source registry: declarative, no network."""
from __future__ import annotations

import inspect
import unittest
from urllib.parse import urlparse

from app.providers.bank_sources import (
    BankSource,
    get_bank_source,
    get_supported_bank_tickers,
    is_supported_bank,
)


REQUIRED_TICKERS = [
    "HDFCBANK",
    "ICICIBANK",
    "SBIN",
    "AXISBANK",
    "KOTAKBANK",
    "INDUSINDBK",
    "BANKBARODA",
    "PNB",
    "CANBK",
    "UNIONBANK",
    "IDFCFIRSTB",
    "FEDERALBNK",
    "AUBANK",
    "BANDHANBNK",
    "BANKINDIA",
]


def _https_url(url: str) -> None:
    parsed = urlparse(url)
    assert parsed.scheme == "https", url
    assert parsed.netloc, url


class TestBankSourceRegistry(unittest.TestCase):
    def test_all_fifteen_tickers_are_registered(self):
        tickers = get_supported_bank_tickers()
        self.assertEqual(len(tickers), 15)
        self.assertEqual(set(tickers), set(REQUIRED_TICKERS))

    def test_no_duplicate_tickers(self):
        tickers = get_supported_bank_tickers()
        self.assertEqual(len(tickers), len(set(tickers)))

    def test_every_entry_has_name_and_ir_url(self):
        for ticker in REQUIRED_TICKERS:
            src = get_bank_source(ticker)
            self.assertIsInstance(src, BankSource)
            self.assertEqual(src.ticker, ticker)
            self.assertTrue(src.name.strip())
            self.assertTrue(src.investor_relations_url)
            self.assertEqual(src.source_type, "official_ir")
            _https_url(src.investor_relations_url)

    def test_optional_urls_are_https_when_present(self):
        for ticker in REQUIRED_TICKERS:
            src = get_bank_source(ticker)
            if src.financial_results_url:
                _https_url(src.financial_results_url)
            if src.investor_presentations_url:
                _https_url(src.investor_presentations_url)

    def test_get_bank_source_is_case_insensitive(self):
        src = get_bank_source("hdfcbank")
        self.assertIsNotNone(src)
        self.assertEqual(src.ticker, "HDFCBANK")
        self.assertEqual(get_bank_source("HdfcBank").ticker, "HDFCBANK")
        self.assertEqual(get_bank_source(" hdfcbank ").ticker, "HDFCBANK")

    def test_unknown_ticker_returns_none(self):
        self.assertIsNone(get_bank_source("TCS"))
        self.assertIsNone(get_bank_source(""))
        self.assertIsNone(get_bank_source(None))  # type: ignore[arg-type]

    def test_is_supported_bank(self):
        self.assertTrue(is_supported_bank("SBIN"))
        self.assertTrue(is_supported_bank("idfcfirstb"))
        self.assertFalse(is_supported_bank("TCS"))
        self.assertFalse(is_supported_bank("BAJFINANCE"))
        self.assertFalse(is_supported_bank(""))

    def test_helpers_do_not_touch_the_network(self):
        for fn in (get_bank_source, is_supported_bank, get_supported_bank_tickers):
            src = inspect.getsource(fn)
            self.assertNotIn("urlopen", src)
            self.assertNotIn("requests", src)
            self.assertNotIn("http.client", src)
            self.assertNotIn("urllib.request", src)


if __name__ == "__main__":
    unittest.main()
