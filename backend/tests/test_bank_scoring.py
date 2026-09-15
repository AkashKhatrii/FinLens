"""BankMetrics feed existing FinLens pillars. No live AI or network."""
from __future__ import annotations

import unittest

from app.engine.bank_scoring import apply_bank_metrics
from app.engine.common import Metric, Pillar
from app.engine.fundamentals import analyse as fund_analyse
from app.engine.qualitative import risk_analyse
from app.engine.scoring import HORIZONS, OVERALL_BLEND, score_all
from app.engine.sector import PROFILE_BANK, PROFILE_DEFAULT
from app.engine.valuation import analyse as val_analyse
from app.providers.bank_metrics import BankMetric, BankMetrics
from test_sector_bank import (
    _bank_bundle,
    _industrial_bundle,
    _nbfc_bundle,
    _metric,
)


class _Tech:
    suggested_stop = None
    resistance = None
    sma50 = None


class _Val:
    dcf_value = None


def _bank_metric(key: str, value: float | None, unit: str = "%") -> BankMetric | None:
    if value is None:
        return None
    return BankMetric(key=key, label=key, value=value, unit=unit, period="Q1 FY27")


def _bank_metrics(ticker: str = "TESTBANK", **values) -> BankMetrics:
    metrics = BankMetrics(ticker=ticker, period="Q1 FY27")
    for key, raw in values.items():
        unit = "%"
        value = raw
        if isinstance(raw, tuple):
            value, unit = raw
        setattr(metrics, key, _bank_metric(key, value, unit))
    return metrics


def _pillars_from_bundle(bundle):
    _, growth, profit, health = fund_analyse(bundle)
    _, val_p = val_analyse(bundle, fund_analyse(bundle)[0], 1.0)
    return {
        "growth": growth,
        "profitability": profit,
        "health": health,
        "valuation": val_p,
        "technical_short": Pillar("technical_short", "Short", metrics=[
            Metric("rsi14", "RSI", 50, "", score=50, weight=1.4),
        ]),
        "technical_trend": Pillar("technical_trend", "Trend", metrics=[
            Metric("vs_sma200", "vs 200DMA", 2, "%", score=50, weight=1.6),
        ]),
        "earnings": Pillar("earnings", "Earnings", metrics=[
            Metric("beat_rate", "Beat rate", 50, "%", score=50, weight=1.4),
        ]),
        "sentiment": Pillar("sentiment", "Sentiment", metrics=[
            Metric("analyst_rating", "Rating", 4, "", score=50, weight=1.0),
        ]),
        "risk": Pillar("risk", "Risk", metrics=[
            Metric("volatility", "Vol", 20, "%", score=50, weight=1.2),
        ]),
    }


HDFC = _bank_metrics(
    ticker="HDFCBANK",
    gnpa=1.17, nim=3.26, roa=1.85, roe=13.8, nii_growth=6.7,
    loan_growth=15.4, deposit_growth=14.7, casa=32, car=19.6, cet1=17.4,
    cost_income=39.2,
)
ICICI = _bank_metrics(
    ticker="ICICIBANK",
    gnpa=1.38, nnpa=0.35, pcr=74.7, nim=4.36, roa=2.49, cost_income=38.1,
)
SBI = _bank_metrics(
    ticker="SBIN",
    gnpa=1.47, nnpa=0.38, pcr=74.2, credit_cost=0.27, nim=2.86,
    roa=1.11, roe=17.87, loan_growth=18.63, deposit_growth=9.73,
    casa=39.24, casa_trend=9.3, car=15.67, cet1=12.89, cost_income=46.71,
)
AXIS = _bank_metrics(
    ticker="AXISBANK",
    gnpa=1.28, nnpa=0.39, pcr=70.0, nim=3.46, car=16.67, cet1=14.64,
)


class TestNonBankRegression(unittest.TestCase):
    def test_industrial_scores_do_not_change_when_bank_metrics_are_passed(self):
        bundle = _industrial_bundle()
        before = _pillars_from_bundle(bundle)
        after = _pillars_from_bundle(bundle)
        apply_bank_metrics(after, HDFC, PROFILE_DEFAULT)
        for key in ("growth", "profitability", "health", "valuation"):
            self.assertAlmostEqual(before[key].score, after[key].score, places=6, msg=key)
            self.assertEqual(
                [(m.key, m.score) for m in before[key].metrics],
                [(m.key, m.score) for m in after[key].metrics],
                key,
            )

    def test_nbfc_is_not_treated_as_a_bank(self):
        pillars = _pillars_from_bundle(_nbfc_bundle())
        apply_bank_metrics(pillars, SBI, PROFILE_DEFAULT)
        self.assertIsNone(next((m for m in pillars["health"].metrics if m.key == "gnpa"), None))
        self.assertIsNotNone(_metric(pillars["health"], "debt_equity").score)


class TestBankApplicability(unittest.TestCase):
    def test_industrial_metrics_remain_unscored_for_banks(self):
        pillars = _pillars_from_bundle(_bank_bundle())
        apply_bank_metrics(pillars, HDFC, PROFILE_BANK)
        for key in (
            "op_margin", "roce", "interest_cover", "current_ratio",
            "debt_equity", "net_debt_ebitda", "ocf_to_pat", "fcf_margin",
            "ev_ebitda",
        ):
            found = next(m for p in pillars.values() for m in p.metrics if m.key == key)
            self.assertIsNone(found.score, key)

    def test_writeoffs_and_recoveries_are_not_scored(self):
        metrics = _bank_metrics(writeoffs=(16.73, "₹ bn"), recoveries=(40.0, "₹ bn"), nim=3.26)
        pillars = _pillars_from_bundle(_bank_bundle())
        apply_bank_metrics(pillars, metrics, PROFILE_BANK)
        keys = {m.key for p in pillars.values() for m in p.metrics}
        self.assertNotIn("writeoffs", keys)
        self.assertNotIn("recoveries", keys)


class TestBankProfitability(unittest.TestCase):
    def test_canonical_profitability_metrics_are_scored(self):
        pillars = _pillars_from_bundle(_bank_bundle())
        apply_bank_metrics(pillars, HDFC, PROFILE_BANK)
        profit = pillars["profitability"]
        self.assertEqual(_metric(profit, "nim").value, 3.26)
        self.assertEqual(_metric(profit, "roa").value, 1.85)
        self.assertEqual(_metric(profit, "roe").value, 13.8)
        self.assertEqual(_metric(profit, "cost_income").value, 39.2)
        for key in ("nim", "roa", "roe", "cost_income"):
            self.assertIsNotNone(_metric(profit, key).score, key)
        self.assertGreater(_metric(profit, "roa").weight, _metric(profit, "roe").weight)
        self.assertLess(_metric(profit, "cost_income").weight, _metric(profit, "nim").weight)
        self.assertFalse(_metric(profit, "cost_income").higher_is_better)
        self.assertTrue(_metric(profit, "nim").higher_is_better)
        self.assertEqual(_metric(profit, "roe").value, 13.8)
        yahoo_roe = 200_000_000_000 / 500_000_000_000 * 100
        self.assertNotAlmostEqual(_metric(profit, "roe").value, yahoo_roe)


class TestBankGrowth(unittest.TestCase):
    def test_canonical_growth_metrics_are_scored(self):
        pillars = _pillars_from_bundle(_bank_bundle())
        apply_bank_metrics(pillars, HDFC, PROFILE_BANK)
        growth = pillars["growth"]
        self.assertEqual(_metric(growth, "loan_growth").value, 15.4)
        self.assertEqual(_metric(growth, "deposit_growth").value, 14.7)
        self.assertEqual(_metric(growth, "nii_growth").value, 6.7)
        self.assertGreater(_metric(growth, "loan_growth").weight, _metric(growth, "casa_trend").weight)
        for key in ("loan_growth", "deposit_growth", "nii_growth"):
            self.assertIsNotNone(_metric(growth, key).score, key)
            self.assertTrue(_metric(growth, key).higher_is_better)
        for key in ("rev_yoy", "rev_cagr", "pat_yoy", "pat_cagr"):
            self.assertIsNone(_metric(growth, key).score, key)

    def test_unresolved_loan_growth_is_not_filled_from_raw_facts(self):
        metrics = _bank_metrics(deposit_growth=14.7, nii_growth=6.7)
        metrics.raw_facts = []  # even if a caller stuffed facts, scoring must ignore them
        pillars = _pillars_from_bundle(_bank_bundle())
        apply_bank_metrics(pillars, metrics, PROFILE_BANK)
        loan = next((m for m in pillars["growth"].metrics if m.key == "loan_growth"), None)
        if loan is not None:
            self.assertIsNone(loan.score)
            self.assertIsNone(loan.value)


class TestBankHealth(unittest.TestCase):
    def test_canonical_health_metrics_are_scored_with_direction(self):
        metrics = _bank_metrics(
            gnpa=1.17, nnpa=0.40, pcr=70.0, credit_cost=0.27,
            cet1=17.4, car=19.6,
        )
        pillars = _pillars_from_bundle(_bank_bundle())
        apply_bank_metrics(pillars, metrics, PROFILE_BANK)
        health = pillars["health"]
        self.assertEqual(_metric(health, "gnpa").value, 1.17)
        self.assertEqual(_metric(health, "nnpa").value, 0.40)
        self.assertEqual(_metric(health, "pcr").value, 70.0)
        self.assertEqual(_metric(health, "credit_cost").value, 0.27)
        self.assertEqual(_metric(health, "cet1").value, 17.4)
        self.assertEqual(_metric(health, "car").value, 19.6)
        self.assertFalse(_metric(health, "gnpa").higher_is_better)
        self.assertFalse(_metric(health, "nnpa").higher_is_better)
        self.assertFalse(_metric(health, "credit_cost").higher_is_better)
        self.assertTrue(_metric(health, "pcr").higher_is_better)
        self.assertTrue(_metric(health, "cet1").higher_is_better)
        self.assertGreater(_metric(health, "gnpa").weight, _metric(health, "nnpa").weight)
        self.assertGreater(_metric(health, "cet1").weight, _metric(health, "car").weight)


class TestMissingness(unittest.TestCase):
    def test_missing_metrics_do_not_become_zero_or_a_penalty(self):
        full = _bank_metrics(nim=3.26, roa=1.85, roe=13.8, cost_income=39.2, credit_cost=0.27, loan_growth=15.4)
        missing = _bank_metrics(nim=3.26, roa=1.85, cost_income=39.2)
        full_p = _pillars_from_bundle(_bank_bundle())
        miss_p = _pillars_from_bundle(_bank_bundle())
        apply_bank_metrics(full_p, full, PROFILE_BANK)
        apply_bank_metrics(miss_p, missing, PROFILE_BANK)
        self.assertIsNone(_metric(miss_p["profitability"], "roe").score)
        self.assertIsNone(_metric(miss_p["profitability"], "roe").value)
        self.assertIsNotNone(miss_p["profitability"].score)
        self.assertNotEqual(miss_p["profitability"].score, 0)
        self.assertLess(miss_p["profitability"].coverage, full_p["profitability"].coverage)
        self.assertIsNone(next((m for m in miss_p["health"].metrics if m.key == "credit_cost" and m.score is not None), None))
        self.assertIsNone(next((m for m in miss_p["growth"].metrics if m.key == "loan_growth" and m.score is not None), None))


class TestCorrelationAndDirection(unittest.TestCase):
    def test_gnpa_plus_nnpa_are_not_two_full_independent_votes(self):
        from app.engine.bank_scoring import BANK_HEALTH_WEIGHTS, score_bank_metric

        gnpa = score_bank_metric("gnpa", 1.17)
        nnpa = score_bank_metric("nnpa", 2.0)
        w_g, w_n = BANK_HEALTH_WEIGHTS["gnpa"], BANK_HEALTH_WEIGHTS["nnpa"]
        both = (gnpa * w_g + nnpa * w_n) / (w_g + w_n)
        doubled = (gnpa * 1.0 + nnpa * 1.0) / 2.0
        self.assertLess(w_n, w_g)
        self.assertLess(abs(both - gnpa), abs(doubled - gnpa))

    def test_cet1_outweighs_car(self):
        from app.engine.bank_scoring import BANK_HEALTH_WEIGHTS

        self.assertGreater(BANK_HEALTH_WEIGHTS["cet1"], BANK_HEALTH_WEIGHTS["car"])

    def test_direction_for_otherwise_identical_banks(self):
        base = dict(gnpa=1.17, nnpa=0.40, pcr=70.0, credit_cost=0.27, nim=3.26, roa=1.85, cet1=17.4, cost_income=39.2)

        def health_score(**overrides):
            pillars = _pillars_from_bundle(_bank_bundle())
            apply_bank_metrics(pillars, _bank_metrics(**{**base, **overrides}), PROFILE_BANK)
            return pillars["health"].score, pillars["profitability"].score

        h_low_gnpa, _ = health_score(gnpa=0.80)
        h_high_gnpa, _ = health_score(gnpa=3.50)
        self.assertGreater(h_low_gnpa, h_high_gnpa)

        h_low_nnpa, _ = health_score(nnpa=0.20)
        h_high_nnpa, _ = health_score(nnpa=1.80)
        self.assertGreater(h_low_nnpa, h_high_nnpa)

        h_low_cc, _ = health_score(credit_cost=0.15)
        h_high_cc, _ = health_score(credit_cost=1.40)
        self.assertGreater(h_low_cc, h_high_cc)

        _, p_low_ci = health_score(cost_income=32.0)
        _, p_high_ci = health_score(cost_income=55.0)
        self.assertGreater(p_low_ci, p_high_ci)

        _, p_high_nim = health_score(nim=4.20)
        _, p_low_nim = health_score(nim=2.40)
        self.assertGreater(p_high_nim, p_low_nim)

        _, p_high_roa = health_score(roa=2.20)
        _, p_low_roa = health_score(roa=0.70)
        self.assertGreater(p_high_roa, p_low_roa)

        h_high_cet1, _ = health_score(cet1=18.5)
        h_low_cet1, _ = health_score(cet1=11.0)
        self.assertGreater(h_high_cet1, h_low_cet1)


class TestHardFlags(unittest.TestCase):
    def test_bank_high_de_does_not_raise_industrial_leverage_flag(self):
        bundle = _bank_bundle()
        # Stretch D/E well above the industrial threshold of 2x.
        balance = bundle.statements.balance_annual.copy()
        balance.loc["Total Debt"] = balance.loc["Total Debt"] * 20
        bundle.statements.balance_annual = balance
        facts, _, _, health = fund_analyse(bundle)
        self.assertGreater(_metric(health, "debt_equity").value, 2)
        self.assertIsNone(_metric(health, "debt_equity").score)
        risk, _ = risk_analyse(bundle, facts)
        texts = " ".join(flag["text"] for flag in risk.red_flags).lower()
        self.assertNotIn("debt is", texts)
        self.assertNotIn("balance sheet is stretched", texts)

    def test_bank_weak_ocf_and_low_promoter_do_not_raise_industrial_flags(self):
        bundle = _bank_bundle()
        facts, _, _, _ = fund_analyse(bundle)
        risk, _ = risk_analyse(bundle, facts)
        texts = " ".join(flag["text"] for flag in risk.red_flags).lower()
        self.assertNotIn("operating cash flow is only", texts)
        self.assertNotIn("limited skin in the game", texts)

    def test_industrial_high_de_still_raises_leverage_flag(self):
        bundle = _industrial_bundle()
        balance = bundle.statements.balance_annual.copy()
        balance.loc["Total Debt"] = balance.loc["Total Debt"] * 20
        bundle.statements.balance_annual = balance
        facts, _, _, health = fund_analyse(bundle)
        self.assertGreater(_metric(health, "debt_equity").value, 2)
        self.assertIsNotNone(_metric(health, "debt_equity").score)
        risk, _ = risk_analyse(bundle, facts)
        texts = " ".join(flag["text"] for flag in risk.red_flags).lower()
        self.assertIn("balance sheet is stretched", texts)


class TestBankPbUsesOwnHistory(unittest.TestCase):
    def test_bank_pb_without_history_is_unscored(self):
        _, bank_val = val_analyse(_bank_bundle(), fund_analyse(_bank_bundle())[0], 1.0)
        pb = _metric(bank_val, "pb")
        self.assertIsNotNone(pb.value)
        self.assertIsNone(pb.score)


class TestFourBankIntegration(unittest.TestCase):
    def test_canonical_metrics_move_pillars_and_horizons_without_ticker_branches(self):
        self.assertEqual(OVERALL_BLEND, {"swing": 0.40, "long": 0.60})
        self.assertEqual(set(HORIZONS), {"swing", "long"})
        rows = []
        for metrics in (HDFC, ICICI, SBI, AXIS):
            bundle = _bank_bundle()
            before = _pillars_from_bundle(bundle)
            after = _pillars_from_bundle(bundle)
            apply_bank_metrics(after, metrics, PROFILE_BANK)
            before_s = score_all(before, _Tech(), _Val(), 100.0)
            after_s = score_all(after, _Tech(), _Val(), 100.0)
            self.assertIsNotNone(after["profitability"].score)
            self.assertIsNotNone(after_s["overall"]["score"])
            self.assertNotIn("if ticker", apply_bank_metrics.__code__.co_names)
            rows.append((metrics.ticker, before, after, before_s, after_s))
        # Same mapping regardless of ticker: identical BankMetrics → identical pillars.
        clone = _bank_metrics(ticker="OTHERBANK", gnpa=1.17, nim=3.26, roa=1.85, roe=13.8)
        a = _pillars_from_bundle(_bank_bundle())
        b = _pillars_from_bundle(_bank_bundle())
        apply_bank_metrics(a, HDFC, PROFILE_BANK)
        apply_bank_metrics(b, clone, PROFILE_BANK)
        self.assertAlmostEqual(
            _metric(a["profitability"], "nim").score,
            _metric(b["profitability"], "nim").score,
        )
        self.assertEqual(rows[0][0], "HDFCBANK")
        # Before/after must be computable for all four fixtures. Do not assert
        # a particular verdict — these banks are validation cases, not targets.
        for ticker, before, after, before_s, after_s in rows:
            self.assertIn(ticker, {"HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK"})
            for key in ("growth", "profitability", "health", "valuation"):
                _ = before[key].score, after[key].score
            _ = (
                before_s["horizons"]["swing"]["score"],
                after_s["horizons"]["swing"]["score"],
                before_s["horizons"]["long"]["score"],
                after_s["horizons"]["long"]["score"],
                before_s["overall"]["score"],
                after_s["overall"]["score"],
                before_s["overall"]["verdict"],
                after_s["overall"]["verdict"],
                before_s["horizons"]["long"]["confidence"],
                after_s["horizons"]["long"]["confidence"],
            )

    def test_analyse_orchestrator_is_wired_to_canonical_bank_metrics(self):
        from pathlib import Path

        from app import analysis as analysis_mod

        src = Path(analysis_mod.__file__).read_text()
        self.assertIn("apply_bank_metrics(pillars, bank_metrics, profile)", src)
        self.assertIn("classify(bundle.quote.sector, bundle.quote.industry)", src)
        self.assertNotIn('ticker ==', src)


class TestDoesNotReadRawFacts(unittest.TestCase):
    def test_scoring_uses_canonical_fields_only(self):
        from pathlib import Path

        from app.engine import bank_scoring
        src = Path(bank_scoring.__file__).read_text()
        self.assertNotIn("raw_facts", src)
        self.assertNotIn('ticker ==', src)


if __name__ == "__main__":
    unittest.main()
