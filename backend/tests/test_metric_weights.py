"""Correlated metrics must not stack into extra pillar influence.

Horizon mix and verdict bands stay in scoring.py. These tests only lock the
within-pillar budgets: the distinctive member of a family keeps weight;
companions that measure the same thing cannot outvote it.
"""
from __future__ import annotations

import unittest

from app.engine.metric_weights import (
    EARNINGS,
    GROWTH,
    HEALTH,
    PROFIT,
    RISK,
    SENTIMENT,
    TECH_SHORT,
    TECH_TREND,
    VALUATION,
)


class TestGrowthFamily(unittest.TestCase):
    def test_cagr_is_the_primary_growth_signal(self):
        self.assertGreater(GROWTH["rev_cagr"], GROWTH["rev_yoy"])
        self.assertGreater(GROWTH["rev_cagr"], GROWTH["q_rev_yoy"])
        self.assertGreater(GROWTH["pat_cagr"], GROWTH["pat_yoy"])
        self.assertGreater(GROWTH["pat_cagr"], GROWTH["q_pat_yoy"])

    def test_yoy_plus_quarter_cannot_outvote_cagr(self):
        self.assertLessEqual(GROWTH["rev_yoy"] + GROWTH["q_rev_yoy"], GROWTH["rev_cagr"])
        self.assertLessEqual(GROWTH["pat_yoy"] + GROWTH["q_pat_yoy"], GROWTH["pat_cagr"])


class TestProfitabilityFamily(unittest.TestCase):
    def test_net_margin_is_a_check_on_operating_margin(self):
        self.assertLess(PROFIT["net_margin"], PROFIT["op_margin"])

    def test_roce_outranks_roe(self):
        self.assertGreater(PROFIT["roce"], PROFIT["roe"])


class TestHealthFamily(unittest.TestCase):
    def test_leverage_stock_outranks_nd_ebitda(self):
        self.assertGreater(HEALTH["debt_equity"], HEALTH["net_debt_ebitda"])

    def test_cash_conversion_outranks_fcf_margin(self):
        self.assertGreater(HEALTH["ocf_to_pat"], HEALTH["fcf_margin"])


class TestValuationFamily(unittest.TestCase):
    def test_trailing_pe_is_not_restated_at_full_weight(self):
        self.assertLess(VALUATION["peg"], VALUATION["pe"])
        self.assertLess(VALUATION["earnings_yield_spread"], VALUATION["pe"])

    def test_own_history_and_dcf_stay_first_class(self):
        self.assertGreaterEqual(VALUATION["pe_vs_history"], VALUATION["pe"])
        self.assertGreater(VALUATION["dcf_upside"], VALUATION["peg"])


class TestTechnicalFamilies(unittest.TestCase):
    def test_setup_is_led_by_20dma_and_one_month_momentum(self):
        self.assertGreater(TECH_SHORT["vs_sma20"], TECH_SHORT["rsi14"])
        self.assertGreater(TECH_SHORT["ret_1m"], TECH_SHORT["ret_1w"])
        self.assertGreater(TECH_SHORT["rsi14"], TECH_SHORT["pct_b"])

    def test_rsi_and_bollinger_cannot_outvote_setup_and_momentum(self):
        self.assertLessEqual(
            TECH_SHORT["rsi14"] + TECH_SHORT["pct_b"] + TECH_SHORT["ret_1w"],
            TECH_SHORT["vs_sma20"] + TECH_SHORT["ret_1m"],
        )

    def test_200dma_and_3m_rs_are_the_primary_trend_signals(self):
        self.assertGreater(TECH_TREND["vs_sma200"], TECH_TREND["vs_sma50"])
        self.assertGreater(TECH_TREND["rs_3m"], TECH_TREND["rs_1y"])
        self.assertGreater(TECH_TREND["vs_sma200"], TECH_TREND["week52_position"])


class TestRiskAndStreet(unittest.TestCase):
    def test_volatility_outranks_beta_and_drawdown(self):
        self.assertGreater(RISK["volatility"], RISK["beta"])
        self.assertGreater(RISK["volatility"], RISK["max_drawdown"])

    def test_beat_rate_outranks_average_surprise(self):
        self.assertGreater(EARNINGS["beat_rate"], EARNINGS["avg_surprise"])

    def test_rating_not_doubled_by_target_upside(self):
        self.assertLessEqual(SENTIMENT["analyst_upside"], SENTIMENT["analyst_rating"])


class TestEnginesReadSharedWeights(unittest.TestCase):
    def test_engines_reference_the_shared_tables(self):
        import inspect

        from app.engine import fundamentals, qualitative, technicals, valuation

        self.assertIn("GROWTH[", inspect.getsource(fundamentals.analyse))
        self.assertIn("VALUATION[", inspect.getsource(valuation.analyse))
        self.assertIn("TECH_SHORT[", inspect.getsource(technicals._build_short))
        self.assertIn("TECH_TREND[", inspect.getsource(technicals._build_trend))
        self.assertIn("RISK[", inspect.getsource(qualitative.risk_analyse))
        self.assertIn("EARNINGS[", inspect.getsource(qualitative.earnings_analyse))
        self.assertIn("SENTIMENT[", inspect.getsource(qualitative.sentiment_analyse))


if __name__ == "__main__":
    unittest.main()
