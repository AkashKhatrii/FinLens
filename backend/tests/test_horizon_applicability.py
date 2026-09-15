"""User-facing scores are Swing and Long only.

Pillar mix in HORIZONS (for those two horizons) and metric_weights.py stay as
they are. Within each pillar, HORIZON_FACTOR can scale a metric so RSI/1-week
return do not leak into Long. Displayed pillar scores are unchanged.
"""
from __future__ import annotations

import unittest

from app.engine.common import Metric, Pillar
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
from app.engine.scoring import HORIZONS, OVERALL_BLEND, VERDICT_BANDS, score_all, verdict_for
from app.engine.sector import BANK_SUPPRESS, apply_profile, classify


class _Tech:
    suggested_stop = None
    resistance = None
    sma50 = None


class _Val:
    dcf_value = None


PILLAR_WEIGHTS = {
    "growth": GROWTH,
    "profitability": PROFIT,
    "health": HEALTH,
    "valuation": VALUATION,
    "technical_short": TECH_SHORT,
    "technical_trend": TECH_TREND,
    "risk": RISK,
    "earnings": EARNINGS,
    "sentiment": SENTIMENT,
}

USER_HORIZONS = ("swing", "long")

WEAK_FUNDAMENTALS = {
    "rev_yoy": 18, "rev_cagr": 15, "pat_yoy": 18, "pat_cagr": 15,
    "q_rev_yoy": 22, "q_pat_yoy": 22,
    "op_margin": 15, "net_margin": 15, "margin_trend": 20, "roe": 15, "roce": 15,
    "debt_equity": 18, "net_debt_ebitda": 18, "interest_cover": 18,
    "current_ratio": 20, "ocf_to_pat": 18, "fcf_margin": 18,
    "pe": 15, "pe_vs_history": 15, "pb": 15, "ev_ebitda": 15, "peg": 15,
    "earnings_yield_spread": 15, "dividend_yield": 20, "dcf_upside": 15,
    "beat_rate": 22, "avg_surprise": 22,
    "analyst_rating": 25, "analyst_upside": 22, "promoter_holding": 25,
    "institutional_holding": 25,
    "beta": 30, "volatility": 30, "max_drawdown": 30, "liquidity": 40,
}

STRONG_SETUP = {
    "rsi14": 92, "pct_b": 90, "vs_sma20": 90, "ret_1w": 90, "ret_1m": 88, "volume_ratio": 85,
    "vs_sma50": 88, "vs_sma200": 85, "adx14": 80, "rs_3m": 90, "rs_1y": 82,
    "week52_position": 75,
}

STRONG_COMPANY = {
    "rev_yoy": 82, "rev_cagr": 88, "pat_yoy": 80, "pat_cagr": 86,
    "q_rev_yoy": 70, "q_pat_yoy": 68,
    "op_margin": 84, "net_margin": 80, "margin_trend": 75, "roe": 90, "roce": 92,
    "debt_equity": 88, "net_debt_ebitda": 90, "interest_cover": 90,
    "current_ratio": 80, "ocf_to_pat": 85, "fcf_margin": 84,
    "pe": 72, "pe_vs_history": 70, "pb": 68, "ev_ebitda": 70, "peg": 74,
    "earnings_yield_spread": 72, "dividend_yield": 60, "dcf_upside": 78,
    "beat_rate": 80, "avg_surprise": 62,
    "analyst_rating": 70, "analyst_upside": 65, "promoter_holding": 75,
    "institutional_holding": 70,
    "beta": 70, "volatility": 72, "max_drawdown": 68, "liquidity": 85,
}

WEAK_SETUP = {
    "rsi14": 22, "pct_b": 25, "vs_sma20": 20, "ret_1w": 18, "ret_1m": 20, "volume_ratio": 30,
    "vs_sma50": 28, "vs_sma200": 32, "adx14": 35, "rs_3m": 25, "rs_1y": 30,
    "week52_position": 28,
}


def _pillars(overrides: dict[str, float] | None = None) -> dict[str, Pillar]:
    overrides = overrides or {}
    out: dict[str, Pillar] = {}
    for key, weights in PILLAR_WEIGHTS.items():
        p = Pillar(key, key.replace("_", " ").title())
        for mk, w in weights.items():
            score = overrides[mk] if mk in overrides else 50.0
            p.metrics.append(Metric(mk, mk, 1.0, "", score=score, weight=w))
        out[key] = p
    return out


def _run(overrides: dict[str, float] | None = None) -> dict:
    return score_all(_pillars(overrides), _Tech(), _Val(), 100.0)


def _delta(metric: str, from_score: float, to_score: float) -> dict[str, float]:
    base = _run({metric: from_score})
    high = _run({metric: to_score})
    out = {}
    for h in USER_HORIZONS:
        out[h] = high["horizons"][h]["score"] - base["horizons"][h]["score"]
    out["overall"] = high["overall"]["score"] - base["overall"]["score"]
    return out


class TestTwoHorizonModel(unittest.TestCase):
    def test_only_swing_and_long_are_user_facing(self):
        result = _run()
        self.assertEqual(tuple(HORIZONS), USER_HORIZONS)
        self.assertEqual(set(result["horizons"]), {"swing", "long"})
        self.assertNotIn("short", HORIZONS)
        self.assertNotIn("short", result["horizons"])

    def test_short_is_not_in_the_overall_blend(self):
        self.assertEqual(OVERALL_BLEND, {"swing": 0.40, "long": 0.60})
        self.assertNotIn("short", OVERALL_BLEND)

    def test_overall_is_forty_swing_sixty_long(self):
        result = _run({"roce": 95.0, "rsi14": 20.0})
        self.assertNotIn("short", result["horizons"])
        swing = result["horizons"]["swing"]["score"]
        long = result["horizons"]["long"]["score"]
        expected = 0.40 * swing + 0.60 * long
        self.assertAlmostEqual(result["overall"]["score"], round(expected, 1), places=1)

    def test_verdict_thresholds_are_unchanged(self):
        self.assertEqual(VERDICT_BANDS, [
            (80, "Strong Buy", "strong-buy"),
            (66, "Buy", "buy"),
            (50, "Hold", "hold"),
            (35, "Reduce", "reduce"),
            (0, "Avoid", "avoid"),
        ])
        self.assertEqual(verdict_for(80), ("Strong Buy", "strong-buy"))
        self.assertEqual(verdict_for(66), ("Buy", "buy"))
        self.assertEqual(verdict_for(50), ("Hold", "hold"))
        self.assertEqual(verdict_for(35), ("Reduce", "reduce"))
        self.assertEqual(verdict_for(34.9), ("Avoid", "avoid"))

    def test_swing_and_long_pillar_weights_are_unchanged(self):
        self.assertEqual(HORIZONS["swing"]["weights"]["technical_trend"], 0.26)
        self.assertEqual(HORIZONS["swing"]["weights"]["technical_short"], 0.16)
        self.assertEqual(HORIZONS["swing"]["weights"]["earnings"], 0.16)
        self.assertEqual(HORIZONS["long"]["weights"]["profitability"], 0.22)
        self.assertEqual(HORIZONS["long"]["weights"]["growth"], 0.20)
        self.assertEqual(HORIZONS["long"]["weights"]["valuation"], 0.20)
        self.assertEqual(HORIZONS["long"]["weights"]["health"], 0.16)
        self.assertEqual(HORIZONS["long"]["weights"]["technical_short"], 0.00)

    def test_displayed_pillar_score_still_uses_all_metrics(self):
        pillars = _pillars({"roce": 90.0, "rsi14": 10.0})
        before = pillars["profitability"].score
        score_all(pillars, _Tech(), _Val(), 100.0)
        self.assertEqual(pillars["profitability"].score, before)


class TestHorizonApplicability(unittest.TestCase):
    def test_roce_helps_long_more_than_swing(self):
        d = _delta("roce", 50.0, 95.0)
        self.assertGreater(d["long"], 1.5)
        self.assertGreater(d["long"], d["swing"])
        self.assertGreater(d["swing"], 0.05)

    def test_revenue_cagr_helps_long_more_than_swing(self):
        d = _delta("rev_cagr", 50.0, 95.0)
        self.assertGreater(d["long"], 1.5)
        self.assertGreater(d["long"], d["swing"])
        self.assertGreater(d["swing"], 0.2)

    def test_one_week_return_moves_swing_not_long(self):
        d = _delta("ret_1w", 50.0, 90.0)
        self.assertGreater(d["swing"], 0.15)
        self.assertAlmostEqual(d["long"], 0.0, delta=0.15)

    def test_rsi_does_not_materially_move_long(self):
        d = _delta("rsi14", 80.0, 20.0)
        self.assertAlmostEqual(d["long"], 0.0, delta=0.15)
        self.assertGreater(abs(d["swing"]), abs(d["long"]) + 0.2)

    def test_bollinger_does_not_materially_move_long(self):
        d = _delta("pct_b", 80.0, 20.0)
        self.assertAlmostEqual(d["long"], 0.0, delta=0.15)

    def test_twenty_dma_does_not_materially_move_long(self):
        d = _delta("vs_sma20", 20.0, 90.0)
        self.assertAlmostEqual(d["long"], 0.0, delta=0.15)
        self.assertGreater(d["swing"], 0.15)

    def test_earnings_surprise_matters_more_for_swing_than_long(self):
        d = _delta("avg_surprise", 50.0, 95.0)
        self.assertGreater(d["swing"], d["long"] + 0.3)

    def test_beat_rate_matters_more_for_long_than_surprise_does(self):
        surprise = _delta("avg_surprise", 50.0, 95.0)
        beat = _delta("beat_rate", 50.0, 95.0)
        self.assertGreater(beat["long"], surprise["long"])
        self.assertGreater(surprise["swing"], surprise["long"])

    def test_valuation_matters_most_for_long_and_still_for_swing(self):
        d = _delta("pe", 50.0, 90.0)
        self.assertGreater(d["long"], d["swing"])
        self.assertGreater(d["swing"], 0.2)

    def test_dcf_helps_long_more_than_swing(self):
        d = _delta("dcf_upside", 50.0, 95.0)
        self.assertGreater(d["long"], d["swing"])
        self.assertGreater(d["long"], 0.8)

    def test_three_month_relative_strength_is_not_a_long_factor(self):
        d = _delta("rs_3m", 50.0, 95.0)
        self.assertGreater(d["swing"], d["long"] + 0.4)
        self.assertAlmostEqual(d["long"], 0.0, delta=0.35)

    def test_quarterly_growth_does_not_dominate_long(self):
        q = _delta("q_rev_yoy", 50.0, 95.0)
        cagr = _delta("rev_cagr", 50.0, 95.0)
        self.assertGreater(cagr["long"], q["long"])
        self.assertGreater(q["swing"], q["long"])

    def test_growth_profitability_valuation_and_health_move_long(self):
        for metric in ("rev_cagr", "roce", "pe", "debt_equity"):
            d = _delta(metric, 50.0, 95.0)
            self.assertGreater(d["long"], 0.8, msg=metric)

    def test_swing_still_uses_setup_and_trend(self):
        rsi = _delta("rsi14", 50.0, 90.0)
        trend = _delta("vs_sma200", 50.0, 90.0)
        self.assertGreater(rsi["swing"], 0.2)
        self.assertGreater(trend["swing"], 0.3)
        self.assertGreater(trend["swing"], rsi["long"] + 0.2)


class TestLongGuardrails(unittest.TestCase):
    def test_strong_setup_cannot_rescue_a_weak_company_to_long_buy(self):
        result = _run({**WEAK_FUNDAMENTALS, **STRONG_SETUP})
        long = result["horizons"]["long"]
        self.assertLess(long["score"], 50)
        self.assertNotIn(long["verdict"], ("Buy", "Strong Buy"))
        swing = result["horizons"]["swing"]
        self.assertGreater(swing["score"], long["score"])
        self.assertLess(swing["score"], 66)

    def test_good_company_weak_setup_can_still_be_a_long_buy(self):
        result = _run({**STRONG_COMPANY, **WEAK_SETUP})
        long = result["horizons"]["long"]
        swing = result["horizons"]["swing"]
        self.assertGreaterEqual(long["score"], 66)
        self.assertEqual(long["verdict"], "Buy")
        self.assertGreater(long["score"], swing["score"])
        self.assertLess(swing["score"], 66)


class TestBankAndNbfcStillApply(unittest.TestCase):
    def test_bank_suppressed_metrics_cannot_move_any_horizon(self):
        keys = {
            "op_margin": (10.0, 95.0),
            "interest_cover": (5.0, 95.0),
            "ocf_to_pat": (5.0, 95.0),
            "dcf_upside": (5.0, 95.0),
            "promoter_holding": (15.0, 95.0),
        }
        low = _pillars({k: a for k, (a, _) in keys.items()})
        high = _pillars({k: b for k, (_, b) in keys.items()})
        for p in list(low.values()) + list(high.values()):
            apply_profile(p, "bank")
        a = score_all(low, _Tech(), _Val(), 100.0)
        b = score_all(high, _Tech(), _Val(), 100.0)
        for h in USER_HORIZONS:
            self.assertAlmostEqual(
                a["horizons"][h]["score"], b["horizons"][h]["score"], places=1, msg=h,
            )
        self.assertTrue(BANK_SUPPRESS)

    def test_nbfc_credit_services_is_still_not_a_bank(self):
        self.assertEqual(classify("Financial Services", "Credit Services"), "default")
        self.assertEqual(classify("Financial Services", "Banks - Regional"), "bank")


if __name__ == "__main__":
    unittest.main()
