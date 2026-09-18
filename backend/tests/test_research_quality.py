"""General research-output quality: evidence, explanations, bank units.

No ticker-specific expected verdicts. Cases are classes of situations.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.ai.prompts import SYSTEM_PROMPT
from app.ai.schemas import Thesis
from app.engine.bank_presentation import fact_pack_bank_fundamentals, public_bank_metrics
from app.engine.bank_scoring import apply_bank_metrics
from app.engine.common import Metric, Pillar
from app.engine.explanations import is_clean_investor_text, investor_facing_bullet
from app.engine.fundamentals import operating_leverage_note
from app.engine.scoring import build_pros_cons
from app.engine.sector import PROFILE_BANK
from app.providers.bank_kpi import (
    canonical_amount_value,
    infer_amount_unit,
    validate_ai_candidates,
)
from app.providers.bank_metrics import BankMetric, BankMetrics, MetricProvenance
from app.providers.pdf_text import PdfPage
from test_bank_scoring import _bank_metrics, _pillars_from_bundle
from test_sector_bank import _bank_bundle

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
PROMPTS = Path(__file__).resolve().parents[1] / "app" / "ai" / "prompts.py"


def _prompt() -> str:
    return SYSTEM_PROMPT.lower()


class TestUnsupportedNumericalThresholds(unittest.TestCase):
    """A. Invented future thresholds are forbidden; B. supplied ones remain allowed."""

    def test_prompt_forbids_invented_future_thresholds_across_fields(self):
        text = _prompt()
        self.assertIn("must not invent numerical thresholds", text)
        self.assertIn("opportunity", text)
        self.assertIn("accumulation", text)
        self.assertIn("thesis_breakers", text)
        self.assertIn("what_to_watch", text)
        self.assertIn("bull_case", text)
        self.assertIn("bear_case", text)
        self.assertIn("gnpa above 4%", text)
        self.assertIn("a material deterioration in asset quality would weaken the thesis", text)
        self.assertIn("roe needs to reach 15%", text)
        self.assertIn("sustained improvement in roe and profitability would strengthen the thesis", text)

    def test_schema_does_not_invite_invented_watch_thresholds(self):
        dumped = str(Thesis.model_json_schema()).lower()
        self.assertIn("do not invent numerical thresholds", dumped)
        self.assertNotIn("checkable things: upcoming events, metrics, thresholds", dumped)

    def test_supplied_guidance_may_still_be_cited(self):
        text = _prompt()
        self.assertIn("company guidance", text)
        self.assertIn("management's stated guidance is x", text)
        self.assertIn("do not turn ai's own judgment into a fabricated company target", text)
        self.assertIn("explicitly supplied analyst/consensus estimate", text)


class TestPeerComparisonDiscipline(unittest.TestCase):
    """C. No peer ranking without data. D. Allowed when peer data is supplied."""

    def test_prompt_forbids_unsupported_peer_comparisons(self):
        text = _prompt()
        for phrase in (
            "best-in-class",
            "worst-in-class",
            "better than peers",
            "worse than peers",
            "ahead of peers",
            "behind peers",
            "closer to peers",
            "premium/discount to peers",
            "sector-leading",
            "industry average",
        ):
            self.assertIn(phrase, text, phrase)
        self.assertIn("unless the relevant comparison data is explicitly supplied", text)
        self.assertIn("do not invent or assume peer values", text)
        self.assertIn("company's own historical evidence", text)

    def test_prompt_allows_peer_comparison_when_fact_pack_has_peer_data(self):
        text = _prompt()
        self.assertIn("if peer data exists", text)
        self.assertIn("supplied peer median", text)


class TestExplanationGarbage(unittest.TestCase):
    """E. Raw extraction fragments never become investor-facing bullets."""

    def test_malformed_extraction_fragments_are_rejected(self):
        garbage = [
            "90.28% 90.30% ... June'26 PCR%- (excl TWO)",
            "NNPA % PCR (Inc. TWO) % SLIPPAGE RATIO 0.28% 97.23% 0.68%",
            "Particulars Sep'23 Mar'24 Mar'25 Dec'25 Mar'26 Jun'26",
            "PCR 90.28% 90.28% 90.30%",
            "GNPA NNPA PCR SLIPPAGE",
            "Source: Investor Presentation Table 12",
        ]
        for blob in garbage:
            self.assertFalse(is_clean_investor_text(blob), blob)

    def test_clean_factual_sentences_are_kept(self):
        self.assertTrue(is_clean_investor_text("GNPA is 1.17%."))
        self.assertTrue(is_clean_investor_text("Revenue grew 12.4% YoY."))
        self.assertTrue(is_clean_investor_text("The stock is 4.2% above its 50-DMA."))

    def test_bank_excerpt_notes_do_not_enter_public_pros(self):
        metrics = _bank_metrics(pcr=90.3, gnpa=1.17)
        metrics.pcr = BankMetric(
            key="pcr", label="PCR", value=90.3, unit="%",
            provenance=MetricProvenance(
                source_title="Q1 FY27 Investor Presentation",
                source_url="https://example.bank/ir.pdf",
                source_type="investor_presentation",
                excerpt="90.28% 90.30% ... June'26 PCR%- (excl TWO)",
                raw_label="PCR%- (excl TWO)",
            ),
        )
        pillars = _pillars_from_bundle(_bank_bundle())
        apply_bank_metrics(pillars, metrics, PROFILE_BANK)
        pcr = next(m for m in pillars["health"].metrics if m.key == "pcr")
        self.assertNotIn("June'26", pcr.note)
        self.assertNotIn("90.28% 90.30%", pcr.note)
        result = build_pros_cons(pillars, [])
        blob = " ".join(result["pros"] + result["cons"])
        self.assertNotIn("June'26", blob)
        self.assertNotIn("PCR%-", blob)
        self.assertNotIn("90.28% 90.30%", blob)

    def test_garbage_metric_note_falls_back_to_normalized_sentence_or_omit(self):
        dirty = Metric(
            "pcr", "PCR", 90.3, "%", score=92,
            note="NNPA % PCR (Inc. TWO) % SLIPPAGE RATIO 0.28% 97.23% 0.68%",
        )
        text = investor_facing_bullet(dirty)
        self.assertIsNotNone(text)
        self.assertNotIn("SLIPPAGE", text)
        self.assertIn("90.3", text)
        self.assertIn("PCR", text)

    def test_vague_unbacked_commentary_is_omitted(self):
        vague = Metric("growth", "Growth", None, "", score=80, note="growth is cheap")
        self.assertIsNone(investor_facing_bullet(vague))
        momentum = Metric("rsi14", "RSI", None, "", score=78, note="strong momentum")
        self.assertIsNone(investor_facing_bullet(momentum))


class TestOperatingLeverage(unittest.TestCase):
    """F/G. Profit CAGR > revenue CAGR is not automatically operating leverage."""

    def test_depressed_base_does_not_imply_operating_leverage(self):
        note = operating_leverage_note(
            rev_cagr=8.0,
            pat_cagr=45.0,
            margin_series=[6.0, 5.5, 4.0, 3.0, 1.5],
            profit_series=[50.0, 40.0, 20.0, 8.0, 2.0],
        )
        self.assertTrue(note is None or "operating leverage" not in note.lower())

    def test_higher_profit_cagr_with_declining_margins_is_not_leverage(self):
        note = operating_leverage_note(
            rev_cagr=6.0,
            pat_cagr=18.0,
            margin_series=[8.0, 10.0, 12.0, 14.0, 16.0],
            profit_series=[40.0, 42.0, 44.0, 45.0, 30.0],
        )
        self.assertTrue(note is None or "operating leverage" not in note.lower())

    def test_insufficient_margin_history_does_not_claim_leverage(self):
        note = operating_leverage_note(
            rev_cagr=7.0,
            pat_cagr=20.0,
            margin_series=[12.0, 10.0],
            profit_series=[40.0, 30.0],
        )
        self.assertTrue(note is None or "operating leverage" not in note.lower())

    def test_sustained_margin_expansion_can_be_described_as_leverage(self):
        note = operating_leverage_note(
            rev_cagr=10.0,
            pat_cagr=18.0,
            margin_series=[16.0, 14.0, 12.0, 10.0, 8.0],
            profit_series=[80.0, 60.0, 45.0, 32.0, 24.0],
        )
        self.assertIsNotNone(note)
        self.assertIn("operating leverage", note.lower())


class TestBankUnitNormalization(unittest.TestCase):
    """H. Source units convert to a canonical internal amount unit."""

    def test_representative_amount_conversions(self):
        cases = [
            (2235.0, "crore", 22.35),
            (16.73, "₹ bn", 16.73),
            (1.0, "lakh crore", 1000.0),
            (5000.0, "million", 5.0),
            (2.0, "trillion", 2000.0),
            (100.0, "lakh", 0.01),
        ]
        for value, unit, expected in cases:
            got = canonical_amount_value(value, unit)
            self.assertAlmostEqual(got, expected, places=6, msg=f"{value} {unit}")

    def test_evidence_crore_is_not_assumed_to_be_billion(self):
        self.assertEqual(
            infer_amount_unit("₹ bn", "Write-offs of 2,235 crore during the quarter", 2235.0),
            "crore",
        )
        self.assertEqual(
            infer_amount_unit("₹ bn", "Recoveries of 16.73 billion", 16.73),
            "billion",
        )

    def test_validated_crore_amount_is_stored_in_canonical_unit(self):
        pages = [PdfPage(number=2, text="Write-offs of 2,235 crore")]
        result = validate_ai_candidates(
            {"candidates": [{
                "metric": "writeoffs",
                "value": 2235,
                "unit": "crore",
                "period": "Q1 FY27",
                "basis": "point_in_time",
                "evidence": "Write-offs of 2,235 crore",
                "page": 2,
                "confidence": 0.9,
                "raw_label": "Write-offs",
            }]},
            pages,
        )
        self.assertEqual(result.facts[0].unit, "₹ bn")
        self.assertAlmostEqual(result.facts[0].value, 22.35, places=4)
        self.assertEqual(result.facts[0].source_unit, "crore")

    def test_public_display_uses_canonical_unit(self):
        metrics = _bank_metrics(writeoffs=(22.35, "₹ bn"))
        public = public_bank_metrics(metrics)
        by_key = {m["key"]: m for g in public["groups"] for m in g["metrics"]}
        self.assertIn("22.35", by_key["writeoffs"]["display"])
        self.assertIn("bn", by_key["writeoffs"]["display"].lower())
        self.assertNotIn("2,235", by_key["writeoffs"]["display"])


class TestCanonicalKpiPresentation(unittest.TestCase):
    """I. Public output shows the canonical KPI, with a concise basis when needed."""

    def test_competing_pcr_candidates_are_not_both_published(self):
        metrics = BankMetrics(ticker="TESTBANK", period="Q1 FY27")
        metrics.pcr = BankMetric(
            key="pcr", label="PCR", value=90.3, unit="%",
            measurement=None,
            provenance=MetricProvenance(
                source_title="Q1 FY27 Investor Presentation",
                source_url="https://example.bank/ir.pdf",
                source_type="investor_presentation",
                excerpt="PCR 90.3% (excl TWO); PCR (Inc. TWO) 97.23%",
                raw_label="PCR (excl TWO)",
            ),
        )
        public = public_bank_metrics(metrics)
        blob = json.dumps(public)
        self.assertIn("90.3", blob)
        self.assertNotIn("97.23", blob)
        pcr = next(m for g in public["groups"] for m in g["metrics"] if m["key"] == "pcr")
        self.assertIsNotNone(pcr.get("basis"))
        self.assertIn("excluding technical write-offs", pcr["basis"].lower())

    def test_fact_pack_identifies_definition_without_raw_candidates(self):
        metrics = BankMetrics(ticker="TESTBANK", period="Q1 FY27")
        metrics.pcr = BankMetric(
            key="pcr", label="PCR", value=90.3, unit="%",
            provenance=MetricProvenance(
                source_title="IR",
                source_url="https://example.bank/ir.pdf",
                source_type="investor_presentation",
                excerpt="headline",
                raw_label="PCR (excl TWO)",
            ),
        )
        packed = fact_pack_bank_fundamentals(public_bank_metrics(metrics))
        pcr = packed["groups"]["Asset Quality"]["PCR"]
        self.assertIn("90.3", pcr)
        self.assertIn("excluding technical write-offs", pcr.lower())
        self.assertNotIn("97.23", pcr)


class TestEventRiskLanguage(unittest.TestCase):
    """J. A known upcoming event is a catalyst/risk, not 'no immediate event risk'."""

    def test_prompt_forbids_no_immediate_event_risk_when_date_is_supplied(self):
        text = _prompt()
        self.assertIn("no immediate event risk", text)
        self.assertIn("next earnings event is around", text)
        self.assertIn("do not invent exact event dates", text)
        self.assertIn("near-term catalyst/risk for a short-dated position", text)

    def test_fact_pack_surfaces_supplied_earnings_date(self):
        from app.analysis import _fact_pack
        from test_bank_presentation import _stub_result

        pack = _fact_pack(_stub_result(earnings={"beat_rate": 50, "next_date": "2026-10-15"}))
        self.assertEqual(pack["earnings"]["next_date"], "2026-10-15")
        self.assertIn("upcoming_events", pack)
        self.assertEqual(pack["upcoming_events"]["next_earnings"], "2026-10-15")
        note = pack["upcoming_events"]["note"].lower()
        self.assertIn("do not describe this as", note)
        self.assertIn("no immediate event risk", note)


class TestAccumulationIndependence(unittest.TestCase):
    """K. AI Accumulation remains independent of Long and Opportunity."""

    def test_prompt_keeps_accumulation_independent(self):
        text = _prompt()
        self.assertIn("independently determine accumulation", text)
        self.assertIn("do not copy long, swing, opportunity", text)
        self.assertIn("long hold does not mean watch for accumulation by default", text)
        html = (STATIC / "index.html").read_text()
        self.assertNotIn("Quantitative Long", html)
        self.assertIn("accumulation: data.accumulation", html)


class TestMissingBankKpisAreUncertainty(unittest.TestCase):
    """L. Missing bank KPIs are a data gap, not automatic deterioration."""

    def test_prompt_treats_missing_bank_kpis_as_uncertainty(self):
        text = _prompt()
        self.assertIn("missing bank kpi is not a negative signal", text)
        self.assertIn("missing bank-specific fundamentals are a data gap", text)
        self.assertIn("not evidence of weakness", text)


class TestQuantVsAiLabels(unittest.TestCase):
    def test_ui_distinguishes_model_score_from_ai_view(self):
        html = (STATIC / "index.html").read_text()
        self.assertIn("Model score", html)
        self.assertIn("AI view", html)
        self.assertIn("Model agreement", html)
        self.assertNotIn("Quant agreement", html)
        self.assertNotIn("Quantitative Long", html)


class TestNoTickerSpecificRules(unittest.TestCase):
    def test_new_quality_rules_are_not_ticker_gated(self):
        src = PROMPTS.read_text().lower()
        for ticker in ("if ticker ==", "pnbho", "suzlon", "wabag"):
            self.assertNotIn(ticker, src)
        from app.engine import explanations, fundamentals
        from app.providers import bank_kpi
        for module in (explanations, fundamentals, bank_kpi):
            blob = Path(module.__file__).read_text().lower()
            self.assertNotIn("if ticker", blob)
            self.assertNotIn("pnb.", blob)


if __name__ == "__main__":
    unittest.main()
