"""US-market display helpers and market-aware scoring guards. No network."""
from __future__ import annotations

import unittest

from app.engine.common import currency_symbol_for, fmt_money, fmt_price


class TestCurrencyHelpers(unittest.TestCase):
    def test_symbols(self):
        self.assertEqual(currency_symbol_for("IN"), "₹")
        self.assertEqual(currency_symbol_for("US"), "$")
        self.assertEqual(currency_symbol_for("XX"), "₹")  # unknown -> default

    def test_fmt_money_india_in_crores(self):
        self.assertEqual(fmt_money(68_464_000_000, "IN"), "₹6,846 Cr")

    def test_fmt_money_us_scales(self):
        self.assertEqual(fmt_money(3_200_000_000_000, "US"), "$3.20T")
        self.assertEqual(fmt_money(917_000_000, "US"), "$917M")
        self.assertEqual(fmt_money(45_000, "US"), "$45,000")
        self.assertEqual(fmt_money(None, "US"), "—")

    def test_fmt_price(self):
        self.assertEqual(fmt_price(1234.5, "IN"), "₹1,234.50")
        self.assertEqual(fmt_price(1234.5, "US"), "$1,234.50")
        self.assertEqual(fmt_price(None, "US"), "—")


if __name__ == "__main__":
    unittest.main()
