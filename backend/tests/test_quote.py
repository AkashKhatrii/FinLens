"""Quote construction from yfinance history."""
from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
