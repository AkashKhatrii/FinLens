"""Bank scoring profile: suppress industrial metrics, leave everyone else alone.

Classification is conservative: only Yahoo industries whose leading token is
bank/banks become `bank`. Credit Services (NBFCs) and unknown industries stay
on the default profile.
"""
from __future__ import annotations

import unittest

import pandas as pd

from app.engine.common import Metric, Pillar
from app.engine.fundamentals import FundamentalFacts, analyse as fund_analyse
from app.engine.qualitative import risk_analyse, sentiment_analyse
from app.engine.sector import BANK_SUPPRESS, apply_profile, classify
from app.engine.valuation import analyse as val_analyse
from app.providers.base import (
    AnalystView,
    Ownership,
    Quote,
    Statements,
    StockBundle,
)

BANK_INDUSTRY = "Banks - Regional"
NBFC_INDUSTRY = "Credit Services"
IT_INDUSTRY = "Information Technology Services"

BANK_YAHOO = [
    ("HDFC Bank", "Financial Services", "Banks - Regional"),
    ("ICICI Bank", "Financial Services", "Banks - Regional"),
    ("State Bank of India", "Financial Services", "Banks - Regional"),
    ("Axis Bank Limited", "Financial Services", "Banks - Regional"),
]


def _metric(pillar: Pillar, key: str) -> Metric:
    return next(m for m in pillar.metrics if m.key == key)


def _dates():
    return [
        pd.Timestamp("2025-03-31"),
        pd.Timestamp("2024-03-31"),
        pd.Timestamp("2023-03-31"),
    ]


def _col(values_newest_first: list[float]) -> dict:
    return dict(zip(_dates(), values_newest_first))


def _statements() -> Statements:
    """Numbers chosen so suppressed bank metrics would otherwise score badly."""
    dates = _dates()
    income = pd.DataFrame(
        {
            "Total Revenue": _col([1_000_000_000_000, 900_000_000_000, 800_000_000_000]),
            "Operating Income": _col([80_000_000_000, 70_000_000_000, 60_000_000_000]),
            "EBIT": _col([80_000_000_000, 70_000_000_000, 60_000_000_000]),
            "EBITDA": _col([90_000_000_000, 80_000_000_000, 70_000_000_000]),
            "Net Income": _col([200_000_000_000, 160_000_000_000, 120_000_000_000]),
            "Interest Expense": _col([70_000_000_000, 65_000_000_000, 60_000_000_000]),
            "Basic EPS": _col([20.0, 16.0, 12.0]),
        },
        index=dates,
    ).T
    balance = pd.DataFrame(
        {
            "Stockholders Equity": _col([500_000_000_000, 450_000_000_000, 400_000_000_000]),
            "Total Debt": _col([80_000_000_000, 75_000_000_000, 70_000_000_000]),
            "Cash And Cash Equivalents": _col([80_000_000_000, 70_000_000_000, 60_000_000_000]),
            "Total Assets": _col([2_000_000_000_000, 1_800_000_000_000, 1_600_000_000_000]),
            "Current Liabilities": _col([900_000_000_000, 800_000_000_000, 700_000_000_000]),
            "Current Assets": _col([400_000_000_000, 350_000_000_000, 300_000_000_000]),
            "Ordinary Shares Number": _col([10_000_000_000, 10_000_000_000, 10_000_000_000]),
        },
        index=dates,
    ).T
    cashflow = pd.DataFrame(
        {
            "Operating Cash Flow": _col([40_000_000_000, 35_000_000_000, 30_000_000_000]),
            "Free Cash Flow": _col([50_000_000_000, 40_000_000_000, 30_000_000_000]),
            "Capital Expenditure": _col([-10_000_000_000, -10_000_000_000, -10_000_000_000]),
        },
        index=dates,
    ).T
    return Statements(
        income_annual=income,
        balance_annual=balance,
        cashflow_annual=cashflow,
    )


def _bundle(*, sector: str, industry: str, name: str = "Test Co",
            symbol: str = "TEST.NS") -> StockBundle:
    return StockBundle(
        market="IN",
        quote=Quote(
            symbol=symbol,
            name=name,
            sector=sector,
            industry=industry,
            price=100.0,
            shares_outstanding=10_000_000_000,
            market_cap=1_000_000_000_000,
        ),
        statements=_statements(),
        ownership=Ownership(
            promoter_or_insider_pct=5.0,
            institutions_pct=40.0,
        ),
        analysts=AnalystView(recommendation="buy", analyst_count=20, target_mean=120.0),
        info={
            "enterpriseToEbitda": 8.0,
            "trailingPE": 20.0,
            "priceToBook": 3.0,
            "dividendRate": 1.0,
        },
    )


def _bank_bundle() -> StockBundle:
    return _bundle(
        sector="Financial Services",
        industry=BANK_INDUSTRY,
        name="HDFC Bank Limited",
        symbol="HDFCBANK.NS",
    )


def _nbfc_bundle() -> StockBundle:
    return _bundle(
        sector="Financial Services",
        industry=NBFC_INDUSTRY,
        name="Bajaj Finance Limited",
        symbol="BAJFINANCE.NS",
    )


def _industrial_bundle() -> StockBundle:
    return _bundle(
        sector="Technology",
        industry=IT_INDUSTRY,
        name="Tata Consultancy Services Limited",
        symbol="TCS.NS",
    )


class TestBankClassification(unittest.TestCase):
    def test_hdfc_bank_is_classified_bank(self):
        self.assertEqual(
            classify("Financial Services", "Banks - Regional"),
            "bank",
        )

    def test_clear_indian_banks_are_classified_bank(self):
        for name, sector, industry in BANK_YAHOO:
            with self.subTest(name=name):
                self.assertEqual(classify(sector, industry), "bank", name)

    def test_bajaj_finance_nbfc_is_not_a_bank(self):
        self.assertEqual(
            classify("Financial Services", "Credit Services"),
            "default",
        )

    def test_unknown_and_unrecognized_industries_stay_default(self):
        self.assertEqual(classify("", ""), "default")
        self.assertEqual(classify(None, None), "default")
        self.assertEqual(classify("Financial Services", ""), "default")
        self.assertEqual(classify("Unknown", "Something Else"), "default")
        self.assertEqual(
            classify("Financial Services", "Investment Banking & Brokerage"),
            "default",
        )
        self.assertEqual(classify("Financial Services", "Asset Management"), "default")

    def test_company_name_does_not_classify(self):
        self.assertEqual(
            classify("Financial Services", "Credit Services"),
            "default",
        )


class TestBankMetricSuppression(unittest.TestCase):
    def test_suppressed_metrics_return_score_none_and_keep_values(self):
        profit = Pillar("profitability", "Profitability", metrics=[
            Metric("op_margin", "Operating Margin", 8.0, "%", score=10.0, weight=1.3),
            Metric("roe", "RoE", 20.0, "%", score=87.0, weight=1.1),
        ])
        apply_profile(profit, "bank")
        op = _metric(profit, "op_margin")
        roe = _metric(profit, "roe")
        self.assertIsNone(op.score)
        self.assertEqual(op.value, 8.0)
        self.assertEqual(roe.score, 87.0)
        self.assertEqual(roe.value, 20.0)

    def test_suppressed_metrics_cannot_influence_pillar_scores(self):
        profit = Pillar("profitability", "Profitability", metrics=[
            Metric("op_margin", "Operating Margin", 8.0, "%", score=10.0, weight=1.3),
            Metric("roe", "RoE", 20.0, "%", score=87.0, weight=1.1),
        ])
        contaminated = profit.score
        apply_profile(profit, "bank")
        self.assertAlmostEqual(profit.score, 87.0)
        self.assertNotAlmostEqual(profit.score, contaminated)

    def test_default_profile_is_a_noop_on_scores(self):
        profit = Pillar("profitability", "Profitability", metrics=[
            Metric("op_margin", "Operating Margin", 8.0, "%", score=10.0, weight=1.3),
            Metric("net_margin", "Net Margin", 20.0, "%", score=87.0, weight=0.6),
        ])
        before = [(m.key, m.score, m.value) for m in profit.metrics]
        apply_profile(profit, "default")
        after = [(m.key, m.score, m.value) for m in profit.metrics]
        self.assertEqual(before, after)

    def test_bank_engines_null_the_suppressed_keys(self):
        _, _, profit, health = fund_analyse(_bank_bundle())
        v, val_p = val_analyse(_bank_bundle(), FundamentalFacts(fcf=50_000_000_000), 1.0)
        sent = sentiment_analyse(_bank_bundle(), 20.0)
        pillars = (profit, health, val_p, sent)
        found = {m.key: m for p in pillars for m in p.metrics}
        for key in BANK_SUPPRESS:
            if key == "dcf_upside":
                self.assertNotIn("dcf_upside", found)
                continue
            self.assertIn(key, found, key)
            self.assertIsNone(found[key].score, key)
            if key != "ev_ebitda":
                self.assertIsNotNone(found[key].value, key)

    def test_bank_fcf_dcf_is_not_included_in_valuation(self):
        f = FundamentalFacts(
            fcf=50_000_000_000,
            revenue=1_000_000_000_000,
            net_income=200_000_000_000,
            total_debt=80_000_000_000,
            cash=80_000_000_000,
            revenue_series=[1e12, 9e11, 8e11],
        )
        v, p = val_analyse(_bank_bundle(), f, 1.0)
        self.assertIsNone(v.dcf_value)
        self.assertIsNone(v.dcf_upside_pct)
        self.assertNotIn("dcf_upside", {m.key for m in p.metrics})
        self.assertIn("skipped", v.dcf_assumptions)
        self.assertRegex(str(v.dcf_assumptions["skipped"]), r"(?i)bank")

    def test_bank_promoter_holding_is_displayed_but_not_scored(self):
        sent = sentiment_analyse(_bank_bundle(), 20.0)
        m = _metric(sent, "promoter_holding")
        self.assertEqual(m.value, 5.0)
        self.assertIsNone(m.score)
        self.assertNotEqual(m.display, "—")

    def test_bank_inappropriate_red_flags_are_not_triggered(self):
        f, _, _, health = fund_analyse(_bank_bundle())
        risk, _ = risk_analyse(_bank_bundle(), f)
        texts = " ".join(flag["text"] for flag in risk.red_flags).lower()
        ic_note = _metric(health, "interest_cover").note.lower()
        self.assertNotIn("barely covered", ic_note)
        self.assertNotIn("net profit exceeds operating profit", texts)
        self.assertNotIn("limited skin in the game", texts)

    def test_default_profile_companies_keep_existing_scoring(self):
        industrial = _industrial_bundle()
        nbfc = _nbfc_bundle()
        _, _, i_profit, i_health = fund_analyse(industrial)
        _, _, n_profit, n_health = fund_analyse(nbfc)
        i_val_facts, i_val = val_analyse(industrial, FundamentalFacts(
            fcf=50_000_000_000, revenue=1e12, net_income=2e11,
            total_debt=8e10, cash=8e10, revenue_series=[1e12, 9e11, 8e11],
        ), 1.0)
        n_risk, _ = risk_analyse(nbfc, fund_analyse(nbfc)[0])
        i_sent = sentiment_analyse(industrial, 20.0)

        self.assertIsNotNone(_metric(i_profit, "op_margin").score)
        self.assertIsNotNone(_metric(i_health, "interest_cover").score)
        self.assertIsNotNone(_metric(i_health, "ocf_to_pat").score)
        self.assertIsNotNone(_metric(i_health, "fcf_margin").score)
        self.assertIsNotNone(_metric(i_val, "ev_ebitda").score)
        self.assertIsNotNone(i_val_facts.dcf_value)
        self.assertIn("dcf_upside", {m.key for m in i_val.metrics})
        self.assertIsNotNone(_metric(i_sent, "promoter_holding").score)

        n_ic = _metric(n_health, "interest_cover")
        self.assertIsNotNone(n_ic.score)
        self.assertIn("barely covered", n_ic.note.lower())
        texts = " ".join(flag["text"] for flag in n_risk.red_flags).lower()
        self.assertIn("net profit exceeds operating profit", texts)
        self.assertIn("limited skin in the game", texts)

        # Identical statements: NBFC and industrial scores match each other
        # (both default) and differ from the bank profile.
        _, _, b_profit, b_health = fund_analyse(_bank_bundle())
        self.assertAlmostEqual(i_profit.score, n_profit.score)
        self.assertAlmostEqual(i_health.score, n_health.score)
        self.assertNotAlmostEqual(i_profit.score, b_profit.score)
        self.assertIsNone(_metric(b_profit, "op_margin").score)


class TestBankSuppressSet(unittest.TestCase):
    def test_suppress_set_is_exactly_the_agreed_keys(self):
        self.assertEqual(BANK_SUPPRESS, frozenset({
            "op_margin",
            "net_margin",
            "margin_trend",
            "roce",
            "debt_equity",
            "interest_cover",
            "current_ratio",
            "net_debt_ebitda",
            "ev_ebitda",
            "ocf_to_pat",
            "fcf_margin",
            "dcf_upside",
            "promoter_holding",
        }))


if __name__ == "__main__":
    unittest.main()
