"""Typeahead search over the NSE listing master."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.providers.nse_symbols import Listing, search

FAKE = [
    Listing("TCS", "Tata Consultancy Services Limited"),
    Listing("TATASTEEL", "Tata Steel Limited"),
    Listing("TATAPOWER", "Tata Power Company Limited"),
    Listing("INFY", "Infosys Limited"),
    Listing("RELIANCE", "Reliance Industries Limited"),
    Listing("SBIN", "State Bank of India"),
]


class TestSymbolSearch(unittest.TestCase):
    def setUp(self):
        self._p = patch("app.providers.nse_symbols.listings", return_value=FAKE)
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def test_empty_query_is_empty(self):
        self.assertEqual(search(""), [])
        self.assertEqual(search("   "), [])

    def test_ticker_prefix_ranks_exact_symbol_first(self):
        hits = search("TCS")
        self.assertTrue(hits)
        self.assertEqual(hits[0].symbol, "TCS")
        self.assertNotIn("INFY", [h.symbol for h in hits])

    def test_partial_ticker_prefix(self):
        hits = search("TATA")
        symbols = [h.symbol for h in hits]
        self.assertIn("TATASTEEL", symbols)
        self.assertIn("TATAPOWER", symbols)

    def test_company_name_match(self):
        hits = search("infosys")
        self.assertTrue(hits)
        self.assertEqual(hits[0].symbol, "INFY")

    def test_respects_limit(self):
        hits = search("T", limit=2)
        self.assertLessEqual(len(hits), 2)

    def test_garbage_has_no_weak_hits(self):
        self.assertEqual(search("xyznotarealcompany"), [])


if __name__ == "__main__":
    unittest.main()
