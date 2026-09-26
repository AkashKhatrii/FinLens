"""Nifty / index constituent CSV parsing. No network in these tests."""
from __future__ import annotations

import unittest

from app.providers.index_constituents import INDEX_SOURCES, parse_index_csv


NIFTY_CSV = """Company Name,Industry,Symbol,Series,ISIN Code
Reliance Industries Ltd.,Oil Gas & Consumable Fuels,RELIANCE,EQ,INE002A01018
HDFC Bank Ltd.,Financial Services,HDFCBANK,EQ,INE040A01034
Infosys Ltd.,Information Technology,INFY,EQ,INE009A01021
Reliance Industries Ltd.,Oil Gas & Consumable Fuels,RELIANCE,EQ,INE002A01018
Adani Enterprises Ltd.,Metals & Mining,ADANIENT,EQ,INE423A01024
Some Bond,Debt,BONDISIN,GB,INE000BOND01
"""


class TestIndexConstituentParsing(unittest.TestCase):
    def test_parses_symbol_and_name(self):
        rows = parse_index_csv(NIFTY_CSV)
        by_symbol = {r.symbol: r.name for r in rows}
        self.assertEqual(by_symbol["RELIANCE"], "Reliance Industries Ltd.")
        self.assertEqual(by_symbol["HDFCBANK"], "HDFC Bank Ltd.")
        self.assertEqual(by_symbol["INFY"], "Infosys Ltd.")

    def test_duplicate_symbols_keep_the_first(self):
        rows = parse_index_csv(NIFTY_CSV)
        symbols = [r.symbol for r in rows]
        self.assertEqual(symbols.count("RELIANCE"), 1)
        self.assertEqual(rows[0].name, "Reliance Industries Ltd.")

    def test_non_equity_series_are_skipped(self):
        rows = parse_index_csv(NIFTY_CSV)
        self.assertNotIn("BONDISIN", [r.symbol for r in rows])

    def test_bom_and_header_spacing_are_tolerated(self):
        blob = "\ufeffCompany Name, Symbol ,Series\nTata Consultancy Services Ltd.,TCS,EQ\n"
        rows = parse_index_csv(blob)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].symbol, "TCS")
        self.assertEqual(rows[0].name, "Tata Consultancy Services Ltd.")

    def test_nifty_indexes_are_registered(self):
        self.assertIn("NIFTY50", INDEX_SOURCES)
        self.assertIn("NIFTY100", INDEX_SOURCES)
        self.assertIn("NIFTY500", INDEX_SOURCES)
        nifty50_urls = " ".join(INDEX_SOURCES["NIFTY50"]["urls"])
        nifty100_urls = " ".join(INDEX_SOURCES["NIFTY100"]["urls"])
        nifty500_urls = " ".join(INDEX_SOURCES["NIFTY500"]["urls"])
        self.assertIn("ind_nifty50list.csv", nifty50_urls)
        self.assertIn("ind_nifty100list.csv", nifty100_urls)
        self.assertIn("ind_nifty500list.csv", nifty500_urls)
        self.assertEqual(INDEX_SOURCES["NIFTY500"]["name"], "Nifty 500")

    def test_nifty100_csv_uses_the_same_parser(self):
        blob = """Company Name,Industry,Symbol,Series,ISIN Code
Alpha Ltd.,IT,AAA,EQ,INEAAA
Beta Ltd.,Bank,BBB,EQ,INEBBB
Alpha Ltd.,IT,AAA,EQ,INEAAA
Gamma Ltd.,Auto,CCC,EQ,INECCC
"""
        rows = parse_index_csv(blob)
        self.assertEqual([r.symbol for r in rows], ["AAA", "BBB", "CCC"])
        self.assertEqual(rows[0].name, "Alpha Ltd.")

    def test_unknown_index_is_rejected(self):
        from app.providers.index_constituents import get_index_constituents
        with self.assertRaises(KeyError):
            get_index_constituents("NIFTY200")
        with self.assertRaises(KeyError):
            get_index_constituents("NOTANINDEX")

    def test_sp500_is_registered_as_us(self):
        self.assertIn("SP500", INDEX_SOURCES)
        spec = INDEX_SOURCES["SP500"]
        self.assertEqual(spec["market"], "US")
        self.assertEqual(spec["name"], "S&P 500")

    def test_generic_csv_parses_symbol_name_files(self):
        blob = """Symbol,Name,Sector
AAPL,Apple Inc.,Information Technology
MSFT,Microsoft Corporation,Information Technology
AAPL,Apple Inc.,Information Technology
"""
        rows = parse_index_csv(blob, format="generic")
        self.assertEqual([r.symbol for r in rows], ["AAPL", "MSFT"])
        self.assertEqual(rows[0].name, "Apple Inc.")

    def test_generic_csv_skips_blank_rows(self):
        blob = "Symbol,Name,Sector\nNVDA,NVIDIA Corporation,Information Technology\n,,\n"
        rows = parse_index_csv(blob, format="generic")
        self.assertEqual([r.symbol for r in rows], ["NVDA"])

    def test_generic_csv_accepts_security_name_column_and_hyphenates_share_classes(self):
        blob = "Symbol,Security,GICS Sector\nBRK.B,Berkshire Hathaway,Financials\nAAPL,Apple Inc.,Information Technology\n"
        rows = parse_index_csv(blob, format="generic")
        self.assertEqual([(r.symbol, r.name) for r in rows],
                         [("BRK-B", "Berkshire Hathaway"), ("AAPL", "Apple Inc.")])


if __name__ == "__main__":
    unittest.main()
