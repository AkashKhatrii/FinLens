"""Canonical BankMetrics appear in analysis, UI payload, and AI fact pack.

Scoring weights are not changed here. No live PDF or network.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.analysis import _fact_pack
from app.engine.bank_presentation import (
    BANK_PUBLIC_GROUPS,
    BANK_PUBLIC_LABELS,
    fact_pack_bank_fundamentals,
    public_bank_metrics,
)
from app.engine.bank_scoring import (
    BANK_GROWTH_WEIGHTS,
    BANK_HEALTH_WEIGHTS,
    BANK_PROFIT_WEIGHTS,
)
from app.engine.scoring import HORIZONS, OVERALL_BLEND, VERDICT_BANDS
from app.providers.bank_metrics import BankMetric, BankMetrics, MetricProvenance
from test_bank_scoring import AXIS, HDFC, ICICI, SBI, _bank_metrics


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"

DEBUG_LEAKS = (
    "raw_facts", "resolution_reason", "candidate_page", "rejected",
    "ambiguous", "confidence", "QAB vs MEB", "average vs EOP",
)


def _metric(key: str, value: float, unit: str = "%", **kwargs) -> BankMetric:
    return BankMetric(key=key, label=key, value=value, unit=unit, period="Q1 FY27", **kwargs)


def _stub_result(**overrides) -> dict:
    empty_pillar = {
        "key": "growth", "label": "Growth", "score": 50.0, "coverage": 1.0,
        "metrics": [{"label": "Revenue YoY", "display": "12.0%", "score": 50.0, "note": ""}],
        "notes": [],
    }
    base = {
        "company": {"name": "Test", "sector": "Financial Services", "industry": "Banks - Regional"},
        "price": {"last": 100.0},
        "overall": {"score": 60.0, "verdict": "Hold"},
        "horizons": {
            "swing": {"score": 50.0, "verdict": "Hold", "confidence": 70.0, "confidence_label": "Medium"},
            "long": {"score": 66.0, "verdict": "Buy", "confidence": 70.0, "confidence_label": "Medium"},
        },
        "pillars": {"growth": empty_pillar},
        "fundamentals": {"eps": 20.0, "fiscal_year": "FY26", "years": [], "margin_series": []},
        "valuation": {"pe": 20.0, "pb": 3.0, "pe_history": []},
        "technicals": {"rsi14": 55, "series": [1, 2, 3]},
        "risk": {"beta": 1.0, "red_flags": []},
        "earnings": {"beat_rate": 50},
        "ownership": {"promoter_pct": 5.0, "top_holders": [{"name": "x"}]},
        "analysts": {"recommendation": "buy"},
        "news": [{"title": "Hello", "publisher": "NSE", "url": "https://example.com"}],
        "pros": ["ok"],
        "cons": [],
        "data_gaps": [],
    }
    base.update(overrides)
    return base


class TestPublicBankMetricsMapping(unittest.TestCase):
    def test_canonical_values_use_user_labels_and_percent_display(self):
        metrics = _bank_metrics(
            gnpa=1.17, nnpa=0.40, pcr=70.0, nim=3.26, roa=1.85, roe=13.8,
            nii_growth=6.7, loan_growth=15.4, deposit_growth=14.7, casa=32.0,
            car=19.6, cet1=17.4, cost_income=39.2,
        )
        public = public_bank_metrics(metrics)
        self.assertIsNotNone(public)
        by_key = {m["key"]: m for g in public["groups"] for m in g["metrics"]}
        self.assertEqual(by_key["gnpa"]["label"], "GNPA")
        self.assertEqual(by_key["gnpa"]["display"], "1.17%")
        self.assertEqual(by_key["pcr"]["display"], "70.0%")
        self.assertEqual(by_key["nim"]["display"], "3.26%")
        self.assertEqual(by_key["roa"]["label"], "ROA")
        self.assertEqual(by_key["roe"]["label"], "ROE")
        self.assertEqual(by_key["car"]["label"], "CAR / CRAR")
        self.assertEqual(by_key["cost_income"]["label"], "Cost / Income")
        self.assertEqual(by_key["casa"]["label"], "CASA")
        self.assertNotIn("%", by_key["gnpa"]["display"].replace("1.17%", "", 1))

    def test_groups_match_the_product_layout(self):
        labels = [label for _, label, _ in BANK_PUBLIC_GROUPS]
        self.assertEqual(
            labels,
            ["Asset Quality", "Profitability", "Growth & Deposits", "Capital", "Other"],
        )
        self.assertEqual(BANK_PUBLIC_LABELS["credit_cost"], "Credit Cost")
        self.assertEqual(BANK_PUBLIC_LABELS["writeoffs"], "Write-offs")

    def test_missing_metrics_are_omitted_not_zeroed(self):
        metrics = _bank_metrics(nim=3.26)
        public = public_bank_metrics(metrics)
        keys = {m["key"] for g in public["groups"] for m in g["metrics"]}
        self.assertEqual(keys, {"nim"})
        blob = json.dumps(public)
        self.assertNotIn('"loan_growth"', blob)
        self.assertNotIn("0.00%", blob)
        self.assertNotIn('"value": 0', blob)

    def test_none_bank_metrics_returns_none(self):
        self.assertIsNone(public_bank_metrics(None))
        empty = BankMetrics(ticker="X")
        self.assertIsNone(public_bank_metrics(empty))

    def test_debug_fields_are_not_in_the_public_payload(self):
        metrics = BankMetrics(ticker="HDFCBANK", period="Q1 FY27")
        metrics.gnpa = _metric(
            "gnpa", 1.17,
            resolution_reason="chose headline GNPA",
            confidence=0.91,
            provenance=MetricProvenance(
                source_title="Q1 FY27 Investor Presentation",
                source_url="https://www.hdfcbank.com/ir.pdf",
                source_type="investor_presentation",
                excerpt="GNPA at 1.17%",
            ),
        )
        metrics.raw_facts = []
        metrics.rejected = ["specific PCR"]
        public = public_bank_metrics(metrics)
        blob = json.dumps(public)
        for leak in DEBUG_LEAKS:
            self.assertNotIn(leak, blob, leak)
        gnpa = public["groups"][0]["metrics"][0]
        self.assertEqual(gnpa["source"], "Q1 FY27 Investor Presentation")
        self.assertNotIn("excerpt", gnpa)
        self.assertNotIn("confidence", gnpa)

    def test_amount_units_are_not_shown_as_percent(self):
        metrics = _bank_metrics(writeoffs=(16.73, "₹ bn"), recoveries=(40.0, "₹ bn"))
        public = public_bank_metrics(metrics)
        by_key = {m["key"]: m for g in public["groups"] for m in g["metrics"]}
        self.assertIn("16.73", by_key["writeoffs"]["display"])
        self.assertNotIn("%", by_key["writeoffs"]["display"])
        self.assertIn("bn", by_key["writeoffs"]["display"].lower())


class TestFactPack(unittest.TestCase):
    def test_bank_fundamentals_appear_without_debug_fields(self):
        public = public_bank_metrics(HDFC)
        result = _stub_result(bank_metrics=public)
        pack = _fact_pack(result)
        self.assertIn("bank_fundamentals", pack)
        bank_blob = json.dumps(pack["bank_fundamentals"])
        for leak in DEBUG_LEAKS:
            self.assertNotIn(leak, bank_blob, leak)
        blob = json.dumps(pack)
        groups = pack["bank_fundamentals"]["groups"]
        self.assertEqual(groups["Asset Quality"]["GNPA"], "1.17%")
        self.assertEqual(groups["Profitability"]["NIM"], "3.26%")
        self.assertEqual(groups["Growth & Deposits"]["Loan Growth"], "15.4%")
        self.assertEqual(groups["Capital"]["CET1"], "17.4%")
        self.assertNotIn("raw_facts", pack)
        self.assertNotIn("resolution_reason", blob)

    def test_non_bank_fact_pack_omits_bank_fundamentals(self):
        pack = _fact_pack(_stub_result())
        self.assertNotIn("bank_fundamentals", pack)
        self.assertEqual(
            set(pack),
            {
                "company", "price", "quant_scores", "pillar_scores",
                "fundamentals", "valuation", "pe_history", "technicals",
                "risk", "earnings", "ownership", "analysts", "recent_news",
                "rule_based_pros", "rule_based_cons", "data_gaps",
            },
        )
        self.assertNotIn("series", pack["technicals"])

    def test_fact_pack_helper_skips_empty_groups(self):
        packed = fact_pack_bank_fundamentals(public_bank_metrics(_bank_metrics(nim=3.26)))
        self.assertEqual(list(packed["groups"]), ["Profitability"])
        self.assertEqual(packed["groups"]["Profitability"]["NIM"], "3.26%")


class TestAiPromptContext(unittest.TestCase):
    def test_research_prompt_treats_bank_kpis_as_canonical_facts(self):
        from app.ai.prompts import SYSTEM_PROMPT

        text = SYSTEM_PROMPT.lower()
        self.assertIn("bank_fundamentals", text)
        for term in ("gnpa", "nnpa", "nim", "casa", "cet1", "cost/income", "credit cost"):
            self.assertIn(term, text, term)
        self.assertIn("single quarter", text)
        self.assertIn("does not automatically establish a trend", text)
        self.assertIn("not a negative signal", text)
        self.assertNotIn("weight of 1.0", text)
        self.assertIn("ev/ebitda", text)
        self.assertIn("fcf dcf", text)


class TestScoringUnchanged(unittest.TestCase):
    def test_horizon_blend_and_bank_pillar_weights_are_untouched(self):
        self.assertEqual(OVERALL_BLEND, {"swing": 0.40, "long": 0.60})
        self.assertEqual(HORIZONS["swing"]["weights"]["technical_trend"], 0.26)
        self.assertEqual(HORIZONS["long"]["weights"]["profitability"], 0.22)
        self.assertEqual(VERDICT_BANDS[0][:2], (80, "Strong Buy"))
        self.assertEqual(BANK_GROWTH_WEIGHTS["loan_growth"], 1.00)
        self.assertEqual(BANK_PROFIT_WEIGHTS["roa"], 1.20)
        self.assertEqual(BANK_HEALTH_WEIGHTS["nnpa"], 0.70)


class TestUiSurface(unittest.TestCase):
    def test_index_has_a_bank_fundamentals_section(self):
        html = (STATIC / "index.html").read_text()
        self.assertIn("Bank Fundamentals", html)
        self.assertIn("result.bank_metrics", html)
        self.assertNotIn("raw_facts", html)
        self.assertNotIn("resolution_reason", html)


class TestFourBankFixtures(unittest.TestCase):
    def test_canonical_metrics_appear_in_result_and_fact_pack(self):
        for fixture in (HDFC, ICICI, SBI, AXIS):
            public = public_bank_metrics(fixture)
            self.assertIsNotNone(public, fixture.ticker)
            pack = _fact_pack(_stub_result(bank_metrics=public))
            self.assertIn("bank_fundamentals", pack)
            bank_blob = json.dumps(pack["bank_fundamentals"])
            for leak in DEBUG_LEAKS:
                self.assertNotIn(leak, bank_blob, f"{fixture.ticker} {leak}")
            if fixture.gnpa is not None:
                self.assertIn("GNPA", pack["bank_fundamentals"]["groups"]["Asset Quality"])


if __name__ == "__main__":
    unittest.main()
