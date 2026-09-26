"""US typeahead over the S&P 500 list. No network (constituents stubbed)."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app import main
from app.providers.index_constituents import Constituent, IndexUniverse

STUB = IndexUniverse(
    index_id="SP500",
    name="S&P 500",
    market="US",
    constituents=[
        Constituent("ANET", "Arista Networks Inc"),
        Constituent("AAPL", "Apple Inc"),
        Constituent("MSFT", "Microsoft Corporation"),
        Constituent("META", "Meta Platforms Inc"),
        Constituent("BRK-B", "Berkshire Hathaway Inc"),
    ],
)


class TestUSSearch(unittest.TestCase):
    def setUp(self):
        self._patcher = patch.object(main, "get_index_constituents", return_value=STUB)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def test_symbol_prefix_first(self):
        hits = main._search_us("anet", 8)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["symbol"], "ANET")
        self.assertEqual(hits[0]["name"], "Arista Networks Inc")

    def test_prefix_beats_substring(self):
        hits = main._search_us("a", 8)
        syms = [h["symbol"] for h in hits]
        # AAPL/ANET start with A; META/BRK-B only contain it -> later
        self.assertLess(syms.index("AAPL"), syms.index("META"))
        self.assertLess(syms.index("ANET"), syms.index("BRK-B"))

    def test_name_match(self):
        hits = main._search_us("berkshire", 8)
        self.assertEqual([h["symbol"] for h in hits], ["BRK-B"])

    def test_empty_query(self):
        self.assertEqual(main._search_us("", 8), [])
        self.assertEqual(main._search_us("   ", 8), [])

    def test_limit_respected(self):
        hits = main._search_us("a", 2)
        self.assertEqual(len(hits), 2)

    def test_list_failure_degrades(self):
        with patch.object(main, "get_index_constituents", side_effect=RuntimeError("down")):
            self.assertEqual(main._search_us("anet", 8), [])

    def test_api_search_routes_by_market(self):
        us = main.api_search(q="anet", limit=8, market="US")
        self.assertEqual(us["market"], "US")
        self.assertEqual(us["matches"][0]["symbol"], "ANET")
        other = main.api_search(q="anet", limit=8, market="XX")
        self.assertEqual(other["matches"], [])


if __name__ == "__main__":
    unittest.main()
