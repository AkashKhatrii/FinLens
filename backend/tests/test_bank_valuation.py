"""Bank valuation uses own-history P/B, not industrial P/B bands.

No live network. Four-bank fixtures are validation cases, not target ratings.
"""
from __future__ import annotations

import unittest

import pandas as pd

from app.engine.bank_scoring import apply_bank_metrics
from app.engine.common import band as score_band
from app.engine.fundamentals import analyse as fund_analyse
from app.engine.metric_weights import PROFIT, VALUATION
from app.engine.scoring import score_all
from app.engine.sector import PROFILE_BANK
from app.engine.valuation import analyse as val_analyse
from app.providers.bank_metrics import BankMetric, BankMetrics
from test_bank_scoring import (
    AXIS,
    HDFC,
    ICICI,
    SBI,
    _Tech,
    _Val,
    _pillars_from_bundle,
)
from test_sector_bank import _bank_bundle, _industrial_bundle, _metric

INDUSTRIAL_PB_BAND = [(0.6, 92), (1.5, 76), (3, 56), (6, 34), (10, 14), (18, 4)]
OWN_HISTORY_REL_BAND = [(-45, 94), (-20, 80), (0, 60), (20, 38), (50, 16), (100, 4)]


def _bm_roe(roe: float | None) -> BankMetrics | None:
    if roe is None:
        return None
    metrics = BankMetrics(ticker="TESTBANK", period="Q1 FY27")
    metrics.roe = BankMetric(key="roe", label="RoE", value=roe, unit="%", period="Q1 FY27")
    return metrics


def _score_bank(pb: float | None, median: float | None = None, roe: float | None = None,
                extra_info: dict | None = None):
    bundle = _bank_bundle()
    info = dict(bundle.info)
    if pb is None:
        info.pop("priceToBook", None)
    else:
        info["priceToBook"] = pb
    if median is not None:
        info["priceToBookMedian5Y"] = median
    if extra_info:
        info.update(extra_info)
    bundle.info = info
    facts = fund_analyse(bundle)[0]
    if pb is None:
        facts.book_value_ps = None
    return val_analyse(bundle, facts, 1.0, bank_metrics=_bm_roe(roe))


class TestBankPbVsOwnHistory(unittest.TestCase):
    def test_current_below_own_median_is_favorable(self):
        _, pillar = _score_bank(pb=1.5, median=2.0)
        pb = _metric(pillar, "pb")
        self.assertEqual(pb.value, 1.5)
        self.assertGreater(pb.score, 60)
        self.assertEqual(pb.peer, 2.0)

    def test_current_above_own_median_is_unfavorable(self):
        _, pillar = _score_bank(pb=2.5, median=2.0)
        pb = _metric(pillar, "pb")
        self.assertLess(pb.score, 60)

    def test_current_equal_to_own_median_is_neutral(self):
        _, pillar = _score_bank(pb=2.0, median=2.0)
        pb = _metric(pillar, "pb")
        self.assertAlmostEqual(pb.score, 60.0, places=1)

    def test_industrial_pb_bands_are_not_used_for_banks(self):
        _, pillar = _score_bank(pb=3.0, median=2.0)
        pb = _metric(pillar, "pb")
        industrial = score_band(3.0, INDUSTRIAL_PB_BAND)
        self.assertIsNotNone(pb.score)
        self.assertNotAlmostEqual(pb.score, industrial, places=2)

    def test_discount_to_history_outscore_premium_to_history(self):
        _, cheap = _score_bank(pb=1.5, median=2.0)
        _, rich = _score_bank(pb=2.5, median=2.0)
        self.assertGreater(_metric(cheap, "pb").score, _metric(rich, "pb").score)


class TestMissingAndInvalidPb(unittest.TestCase):
    def test_missing_historical_pb_does_not_score_or_penalize(self):
        facts, pillar = _score_bank(pb=3.0)
        pb = _metric(pillar, "pb")
        self.assertEqual(pb.value, 3.0)
        self.assertIsNone(pb.score)
        self.assertIsNone(facts.pb_median_5y)
        self.assertNotAlmostEqual(pillar.score or 0, 0)
        self.assertIsNotNone(_metric(pillar, "pe").score)

    def test_missing_current_pb_is_skipped(self):
        facts, pillar = _score_bank(pb=None, median=2.0)
        pb = _metric(pillar, "pb")
        self.assertIsNone(pb.value)
        self.assertIsNone(pb.score)
        self.assertIsNotNone(pillar.score)

    def test_negative_pb_is_excluded(self):
        facts, pillar = _score_bank(pb=-1.2, median=2.0)
        pb = _metric(pillar, "pb")
        self.assertIsNone(pb.value)
        self.assertIsNone(pb.score)

    def test_non_finite_injected_median_is_ignored(self):
        _, pillar = _score_bank(pb=2.0, extra_info={"priceToBookMedian5Y": float("nan")})
        self.assertIsNone(_metric(pillar, "pb").score)


class TestBankValuationExclusions(unittest.TestCase):
    def test_ev_ebitda_and_fcf_dcf_do_not_contribute(self):
        facts, pillar = _score_bank(pb=2.0, median=2.0)
        self.assertIsNone(_metric(pillar, "ev_ebitda").score)
        self.assertIsNone(facts.dcf_upside_pct)
        self.assertNotIn("dcf_upside", {m.key for m in pillar.metrics})


class TestBankPeAndEarningsYield(unittest.TestCase):
    def test_valid_bank_pe_remains_usable(self):
        _, pillar = _score_bank(pb=2.0, median=2.0)
        pe = _metric(pillar, "pe")
        self.assertEqual(pe.value, 20.0)
        self.assertIsNotNone(pe.score)
        self.assertAlmostEqual(
            pe.score,
            score_band(20.0, [(5, 92), (12, 80), (20, 62), (30, 42), (45, 22), (70, 6)]),
            places=4,
        )

    def test_earnings_yield_stays_the_existing_companion(self):
        self.assertLess(VALUATION["earnings_yield_spread"], VALUATION["pe"])
        _, pillar = _score_bank(pb=2.0, median=2.0)
        self.assertIsNotNone(_metric(pillar, "earnings_yield_spread").score)


class TestRoeValuationContext(unittest.TestCase):
    def test_roe_is_not_a_second_full_valuation_vote(self):
        keys = {m.key for m in _score_bank(pb=2.5, median=2.0, roe=18.0)[1].metrics}
        self.assertNotIn("roe", keys)
        self.assertLess(VALUATION["pb"] * 0.15, PROFIT["roe"])

    def test_pb_history_moves_valuation_more_than_roe_context(self):
        _, cheap = _score_bank(pb=1.5, median=2.0, roe=13.0)
        _, rich = _score_bank(pb=2.5, median=2.0, roe=13.0)
        history_delta = abs(_metric(cheap, "pb").score - _metric(rich, "pb").score)
        _, high_roe = _score_bank(pb=2.5, median=2.0, roe=18.0)
        _, low_roe = _score_bank(pb=2.5, median=2.0, roe=7.0)
        roe_delta = abs(_metric(high_roe, "pb").score - _metric(low_roe, "pb").score)
        self.assertGreater(history_delta, roe_delta * 2)

    def test_high_pb_with_high_roe_is_not_automatically_worse_than_low_pb_low_roe(self):
        # Different own-history: 2.5x can be a discount, 1.2x a premium.
        _, high_quality = _score_bank(pb=2.5, median=3.2, roe=18.0)
        _, low_quality = _score_bank(pb=1.2, median=0.85, roe=7.0)
        self.assertGreater(
            _metric(high_quality, "pb").score,
            _metric(low_quality, "pb").score,
        )

    def test_missing_roe_does_not_create_a_pb_penalty(self):
        _, with_roe = _score_bank(pb=2.0, median=2.0, roe=13.8)
        _, no_roe = _score_bank(pb=2.0, median=2.0, roe=None)
        self.assertAlmostEqual(_metric(no_roe, "pb").score, 60.0, places=1)
        self.assertIsNotNone(_metric(with_roe, "pb").score)


class TestMissingnessCoverage(unittest.TestCase):
    def test_only_available_metrics_contribute_and_coverage_falls(self):
        _, full = _score_bank(pb=2.0, median=2.0)
        _, missing_hist = _score_bank(pb=2.0)
        self.assertIsNotNone(full.score)
        self.assertIsNotNone(missing_hist.score)
        self.assertLess(missing_hist.coverage, full.coverage)
        self.assertIsNone(_metric(missing_hist, "pb").score)
        self.assertIsNotNone(_metric(missing_hist, "pe").score)


class TestNonBankRegression(unittest.TestCase):
    def test_industrial_pb_still_uses_generic_bands(self):
        bundle = _industrial_bundle()
        _, pillar = val_analyse(bundle, fund_analyse(bundle)[0], 1.0)
        pb = _metric(pillar, "pb")
        self.assertEqual(pb.value, 3.0)
        self.assertAlmostEqual(pb.score, score_band(3.0, INDUSTRIAL_PB_BAND), places=4)
        self.assertIsNotNone(_metric(pillar, "ev_ebitda").score)
        self.assertIn("dcf_upside", {m.key for m in pillar.metrics})

    def test_industrial_valuation_does_not_read_injected_bank_median(self):
        bundle = _industrial_bundle()
        bundle.info = {**bundle.info, "priceToBookMedian5Y": 1.0, "priceToBook": 3.0}
        _, pillar = val_analyse(bundle, fund_analyse(bundle)[0], 1.0)
        pb = _metric(pillar, "pb")
        self.assertAlmostEqual(pb.score, score_band(3.0, INDUSTRIAL_PB_BAND), places=4)


class TestHistoricalPbFromStatements(unittest.TestCase):
    def test_reconstructs_median_from_book_and_price_history(self):
        bundle = _bank_bundle()
        bundle.info = {**bundle.info, "priceToBook": 2.0}
        # Book = 50, 45, 40. Prices chosen so historical P/B is 2.4, 2.0, 2.0.
        bundle.history = pd.DataFrame(
            {"Close": [120.0, 90.0, 80.0]},
            index=pd.to_datetime(["2025-03-31", "2024-03-31", "2023-03-31"]),
        )
        facts, pillar = val_analyse(bundle, fund_analyse(bundle)[0], 1.0)
        self.assertIsNotNone(facts.pb_median_5y)
        self.assertGreaterEqual(len(facts.pb_history), 2)
        self.assertIsNotNone(_metric(pillar, "pb").score)

    def test_does_not_invent_history_when_prices_are_missing(self):
        bundle = _bank_bundle()
        facts, pillar = val_analyse(bundle, fund_analyse(bundle)[0], 1.0)
        self.assertIsNone(facts.pb_median_5y)
        self.assertEqual(facts.pb_history, [])
        self.assertIsNone(_metric(pillar, "pb").score)


class TestFourBankFixtures(unittest.TestCase):
    def test_mocked_fixtures_score_without_network_or_ticker_branches(self):
        from pathlib import Path

        from app.engine import valuation as valuation_mod

        src = Path(valuation_mod.__file__).read_text()
        self.assertNotIn("HDFCBANK", src)
        self.assertNotIn("ICICIBANK", src)
        self.assertNotIn("ticker ==", src)
        for metrics in (HDFC, ICICI, SBI, AXIS):
            bundle = _bank_bundle()
            bundle.info = {**bundle.info, "priceToBook": 2.5, "priceToBookMedian5Y": 2.0}
            pillars = _pillars_from_bundle(bundle)
            apply_bank_metrics(pillars, metrics, PROFILE_BANK)
            scored = score_all(pillars, _Tech(), _Val(), 100.0)
            self.assertIsNotNone(scored["overall"]["score"])
            self.assertIsNone(_metric(pillars["valuation"], "ev_ebitda").score)


if __name__ == "__main__":
    unittest.main()
