"""Quote construction from yfinance history."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from app.providers.yf_provider import YFinanceProvider


class TestBuildQuote(unittest.TestCase):
    def test_skips_nan_last_bar(self):
        p = YFinanceProvider("IN")
        hist = pd.DataFrame(
            {"Close": [2270.0, 2204.1, np.nan]},
            index=pd.to_datetime(["2026-09-09", "2026-09-10", "2026-09-11"]),
        )
        q = p._build_quote("TCS.NS", {"longName": "TCS"}, hist)
        self.assertAlmostEqual(q.price, 2204.1)
        self.assertAlmostEqual(q.previous_close, 2270.0)
        self.assertIsNotNone(q.day_change_pct)

    def test_last_prices_reads_latest_close(self):
        p = YFinanceProvider("IN")
        hist = pd.DataFrame(
            {"Close": [2100.0, 2215.3]},
            index=pd.to_datetime(["2026-09-14", "2026-09-15"]),
        )
        with patch("app.providers.yf_provider.yf.download", return_value=hist) as download:
            out = p.last_prices(["WABAG"])
        download.assert_called_once()
        self.assertAlmostEqual(out["WABAG"], 2215.3)

    def test_last_prices_isolates_a_missing_ticker(self):
        p = YFinanceProvider("IN")
        cols = pd.MultiIndex.from_product([["WABAG.NS"], ["Open", "High", "Low", "Close"]])
        hist = pd.DataFrame(
            [[2100, 2110, 2090, 2105], [2200, 2220, 2190, 2215.3]],
            index=pd.to_datetime(["2026-09-14", "2026-09-15"]),
            columns=cols,
        )
        with patch("app.providers.yf_provider.yf.download", return_value=hist):
            out = p.last_prices(["WABAG", "MISSING"])
        self.assertAlmostEqual(out["WABAG"], 2215.3)
        self.assertIsNone(out["MISSING"])


if __name__ == "__main__":
    unittest.main()
