"""Horizon scores must use economically relevant metrics, not the same mix thrice.

Pillar weights in HORIZONS stay as they are. Within each pillar, a metric can
be scaled (including to zero) for a given horizon so CAGR/ROCE do not leak
into Short and RSI/1-week return do not leak into Long.

Displayed pillar scores and metric_weights.py are unchanged: this only
affects how score_all aggregates a horizon.
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
from app.engine.scoring import HORIZONS, OVERALL_BLEND, score_all
from app.engine.sector import BANK_SUPPRESS, apply_profile


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
    for h in ("short", "swing", "long"):
        out[h] = high["horizons"][h]["score"] - base["horizons"][h]["score"]
    out["overall"] = high["overall"]["score"] - base["overall"]["score"]
    return out


class TestHorizonMixUnchanged(unittest.TestCase):
    def test_overall_is_still_the_existing_blend(self):
        self.assertEqual(OVERALL_BLEND, {"short": 0.20, "swing": 0.30, "long": 0.50})

    def test_horizon_pillar_weights_are_unchanged(self):
        self.assertEqual(HORIZONS["short"]["weights"]["technical_short"], 0.40)
        self.assertEqual(HORIZONS["short"]["weights"]["profitability"], 0.01)
        self.assertEqual(HORIZONS["short"]["weights"]["health"], 0.01)
        self.assertEqual(HORIZONS["swing"]["weights"]["technical_trend"], 0.26)
        self.assertEqual(HORIZONS["swing"]["weights"]["earnings"], 0.16)
        self.assertEqual(HORIZONS["long"]["weights"]["profitability"], 0.22)
        self.assertEqual(HORIZONS["long"]["weights"]["technical_short"], 0.00)
        self.assertEqual(HORIZONS["long"]["weights"]["valuation"], 0.20)

    def test_displayed_pillar_score_still_uses_all_metrics(self):
        pillars = _pillars({"roce": 90.0, "rsi14": 10.0})
        before = pillars["profitability"].score
        score_all(pillars, _Tech(), _Val(), 100.0)
        self.assertEqual(pillars["profitability"].score, before)


class TestHorizonApplicability(unittest.TestCase):
    def test_roce_helps_long_somewhat_swing_and_not_short(self):
        d = _delta("roce", 50.0, 95.0)
        self.assertAlmostEqual(d["short"], 0.0, delta=0.15)
        self.assertGreater(d["long"], 1.5)
        self.assertGreater(d["long"], d["swing"])
        self.assertGreater(d["swing"], d["short"] + 0.2)

    def test_revenue_cagr_follows_the_same_long_swing_short_order(self):
        d = _delta("rev_cagr", 50.0, 95.0)
        self.assertAlmostEqual(d["short"], 0.0, delta=0.15)
        self.assertGreater(d["long"], 1.5)
        self.assertGreater(d["long"], d["swing"])
        self.assertGreater(d["swing"], d["short"] + 0.2)

    def test_one_week_return_moves_short_not_long(self):
        d = _delta("ret_1w", 50.0, 90.0)
        self.assertGreater(d["short"], 0.4)
        self.assertAlmostEqual(d["long"], 0.0, delta=0.15)
        self.assertGreater(d["short"], d["swing"])

    def test_rsi_does_not_materially_move_long(self):
        d = _delta("rsi14", 80.0, 20.0)
        self.assertAlmostEqual(d["long"], 0.0, delta=0.15)
        self.assertGreater(abs(d["short"]), abs(d["long"]) + 0.3)

    def test_earnings_surprise_matters_more_for_swing_than_long(self):
        d = _delta("avg_surprise", 50.0, 95.0)
        self.assertGreater(d["swing"], d["long"] + 0.3)
        self.assertGreater(d["swing"], d["short"])

    def test_beat_rate_matters_more_for_long_than_surprise_does(self):
        surprise = _delta("avg_surprise", 50.0, 95.0)
        beat = _delta("beat_rate", 50.0, 95.0)
        self.assertGreater(beat["long"], surprise["long"])
        self.assertGreater(surprise["swing"], surprise["long"])

    def test_valuation_matters_most_for_long_and_still_for_swing(self):
        d = _delta("pe", 50.0, 90.0)
        self.assertGreater(d["long"], d["swing"])
        self.assertGreater(d["swing"], d["short"] + 0.15)
        self.assertGreater(d["short"], 0.05)

    def test_dcf_does_not_move_short(self):
        d = _delta("dcf_upside", 50.0, 95.0)
        self.assertAlmostEqual(d["short"], 0.0, delta=0.15)
        self.assertGreater(d["long"], d["swing"])
        self.assertGreater(d["long"], 0.8)

    def test_three_month_relative_strength_is_not_a_long_factor(self):
        d = _delta("rs_3m", 50.0, 95.0)
        self.assertGreater(d["swing"], d["long"] + 0.4)
        self.assertGreater(d["short"], d["long"])
        self.assertAlmostEqual(d["long"], 0.0, delta=0.35)

    def test_quarterly_growth_does_not_dominate_long(self):
        q = _delta("q_rev_yoy", 50.0, 95.0)
        cagr = _delta("rev_cagr", 50.0, 95.0)
        self.assertGreater(cagr["long"], q["long"])
        self.assertGreater(q["swing"], q["long"])

    def test_overall_is_the_blend_of_the_three_horizons(self):
        result = _run({"roce": 95.0, "rsi14": 20.0})
        short = result["horizons"]["short"]["score"]
        swing = result["horizons"]["swing"]["score"]
        long = result["horizons"]["long"]["score"]
        expected = 0.20 * short + 0.30 * swing + 0.50 * long
        self.assertAlmostEqual(result["overall"]["score"], round(expected, 1), places=1)


class TestBankProfileStillApplies(unittest.TestCase):
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
        for h in ("short", "swing", "long"):
            self.assertAlmostEqual(
                a["horizons"][h]["score"], b["horizons"][h]["score"], places=1, msg=h,
            )
        self.assertTrue(BANK_SUPPRESS)


if __name__ == "__main__":
    unittest.main()
