"""Accumulation is a qualitative wealth-creation layer, not a horizon or score."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.engine.accumulation import (
    accumulation_from_analysis,
    classify_accumulation,
    public_accumulation_from_ai,
)
from app.engine.bank_scoring import BANK_GROWTH_WEIGHTS, BANK_HEALTH_WEIGHTS, BANK_PROFIT_WEIGHTS
from app.engine.scoring import HORIZONS, OVERALL_BLEND, VERDICT_BANDS
from app.engine.metric_weights import VALUATION


SCORING = Path(__file__).resolve().parents[1] / "app" / "engine" / "scoring.py"
ANALYSIS = Path(__file__).resolve().parents[1] / "app" / "analysis.py"
STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
PROMPTS = Path(__file__).resolve().parents[1] / "app" / "ai" / "prompts.py"

INDUSTRIAL_LEAKS = ("fcf", "ev/ebitda", "ev-ebitda", "cash conversion", "operating margin")


def _pillar(key: str, score: float | None, metrics: list[dict] | None = None, coverage: float = 1.0) -> dict:
    return {
        "key": key,
        "label": key.title(),
        "score": score,
        "coverage": coverage if score is not None else 0.0,
        "metrics": metrics or [],
        "notes": [],
    }


def _result(
    *,
    long_verdict: str = "Hold",
    long_score: float = 58.0,
    swing_verdict: str = "Hold",
    swing_score: float = 50.0,
    profit: float | None = 68.0,
    health: float | None = 70.0,
    growth: float | None = 62.0,
    valuation: float | None = 45.0,
    extra_pillars: dict | None = None,
    bank_metrics: dict | None = None,
    technicals: dict | None = None,
    price: dict | None = None,
    fundamentals: dict | None = None,
    valuation_facts: dict | None = None,
) -> dict:
    pillars = {
        "profitability": _pillar("profitability", profit, [
            {"label": "ROE", "display": "18.0%", "score": profit, "note": "Returns on equity."},
            {"label": "ROCE", "display": "16.0%", "score": profit, "note": "Returns on capital."},
        ]),
        "health": _pillar("health", health, [
            {"label": "Debt/Equity", "display": "0.2x", "score": health, "note": "Low leverage."},
        ]),
        "growth": _pillar("growth", growth, [
            {"label": "Revenue YoY", "display": "12.0%", "score": growth, "note": ""},
        ]),
        "valuation": _pillar("valuation", valuation, [
            {"label": "P/E", "display": "28.0x", "score": valuation, "note": ""},
        ]),
        "technical_short": _pillar("technical_short", 80.0, [
            {"label": "RSI(14)", "display": "72", "score": 80.0, "note": "Overbought."},
        ]),
    }
    if extra_pillars:
        pillars.update(extra_pillars)
    return {
        "horizons": {
            "swing": {"score": swing_score, "verdict": swing_verdict, "confidence": 70.0},
            "long": {"score": long_score, "verdict": long_verdict, "confidence": 70.0},
        },
        "overall": {"score": 0.4 * swing_score + 0.6 * long_score, "verdict": "Hold", "blend": {"swing": 0.40, "long": 0.60}},
        "pillars": pillars,
        "bank_metrics": bank_metrics,
        "technicals": technicals or {"rsi14": 72, "pct_b": 0.9, "series": [1, 2, 3]},
        "price": price or {"last": 80.0, "week52_high": 100.0, "off_52w_high_pct": -20.0},
        "fundamentals": fundamentals or {"roe": 18.0, "roce": 16.0},
        "valuation": valuation_facts or {"pe": 28.0, "dcf_value": 50.0},
        "data_gaps": [],
    }


def _bank_public() -> dict:
    return {
        "period": "Q1 FY27",
        "groups": [{
            "key": "asset_quality",
            "label": "Asset Quality",
            "metrics": [
                {"key": "gnpa", "label": "GNPA", "display": "1.17%"},
                {"key": "nnpa", "label": "NNPA", "display": "0.40%"},
                {"key": "credit_cost", "label": "Credit Cost", "display": "0.35%"},
            ],
        }, {
            "key": "profitability",
            "label": "Profitability",
            "metrics": [
                {"key": "nim", "label": "NIM", "display": "3.26%"},
                {"key": "roa", "label": "ROA", "display": "1.85%"},
                {"key": "roe", "label": "ROE", "display": "13.8%"},
            ],
        }, {
            "key": "capital",
            "label": "Capital",
            "metrics": [{"key": "cet1", "label": "CET1", "display": "17.4%"}],
        }],
    }


def _joined(view: dict) -> str:
    parts = [view.get("rationale") or "", view.get("context") or ""]
    parts.extend(view.get("accumulation_reasons") or [])
    parts.extend(view.get("monitor_conditions") or [])
    return " ".join(parts).lower()


class TestAccumulationClassifier(unittest.TestCase):
    def test_long_buy_established_opportunity_is_accumulate(self):
        view = accumulation_from_analysis(
            _result(long_verdict="Buy", long_score=72.0),
            opportunity_category="Established Opportunity",
        )
        self.assertEqual(view["state"], "ACCUMULATE")
        self.assertEqual(view["label"], "Accumulate")
        self.assertIsNone(view.get("score"))
        self.assertTrue(view["accumulation_reasons"])

    def test_long_hold_established_strong_business_is_accumulate_gradually(self):
        view = accumulation_from_analysis(
            _result(long_verdict="Hold", long_score=58.0, profit=78.0, health=74.0),
            opportunity_category="Established Opportunity",
        )
        self.assertEqual(view["label"], "Accumulate Gradually")
        self.assertIn("long-term", _joined(view))

    def test_long_hold_established_with_uncertainty_is_accumulate_gradually(self):
        view = accumulation_from_analysis(
            _result(long_verdict="Hold", long_score=55.0, profit=62.0, health=58.0, valuation=28.0),
            opportunity_category="Established Opportunity",
        )
        self.assertEqual(view["label"], "Accumulate Gradually")

    def test_long_hold_emerging_is_watch_for_accumulation(self):
        view = accumulation_from_analysis(
            _result(long_verdict="Hold"),
            opportunity_category="Emerging Opportunity",
        )
        self.assertEqual(view["label"], "Watch for Accumulation")

    def test_long_hold_no_opportunity_is_do_not_accumulate(self):
        view = accumulation_from_analysis(
            _result(long_verdict="Hold"),
            opportunity_category="No Opportunity",
        )
        self.assertEqual(view["label"], "Do Not Accumulate")

    def test_long_reduce_is_do_not_accumulate(self):
        view = accumulation_from_analysis(
            _result(long_verdict="Reduce", long_score=38.0, profit=40.0, health=42.0),
            opportunity_category="Established Opportunity",
        )
        self.assertEqual(view["label"], "Do Not Accumulate")

    def test_long_avoid_is_do_not_accumulate(self):
        view = accumulation_from_analysis(
            _result(long_verdict="Avoid", long_score=32.0, profit=30.0, health=28.0),
            opportunity_category="No Opportunity",
        )
        self.assertEqual(view["label"], "Do Not Accumulate")

    def test_falling_price_alone_cannot_create_accumulate(self):
        view = accumulation_from_analysis(
            _result(
                long_verdict="Avoid",
                profit=30.0,
                health=28.0,
                price={"last": 80.0, "week52_high": 100.0, "off_52w_high_pct": -20.0},
            ),
            opportunity_category="No Opportunity",
        )
        self.assertEqual(view["label"], "Do Not Accumulate")
        self.assertNotIn("20%", _joined(view))
        self.assertNotIn("52-week", _joined(view))
        self.assertNotIn("fallen", _joined(view))

    def test_rsi_alone_cannot_create_accumulate(self):
        view = accumulation_from_analysis(
            _result(
                long_verdict="Avoid",
                profit=25.0,
                health=25.0,
                swing_verdict="Buy",
                swing_score=80.0,
                technicals={"rsi14": 28.0, "pct_b": 0.05},
            ),
        )
        self.assertEqual(view["label"], "Do Not Accumulate")
        self.assertNotIn("rsi", _joined(view))

    def test_strong_technicals_cannot_override_broken_long(self):
        view = accumulation_from_analysis(
            _result(
                long_verdict="Avoid",
                swing_verdict="Buy",
                swing_score=85.0,
                profit=22.0,
                health=20.0,
                technicals={"rsi14": 30.0, "adx14": 40.0},
            ),
            opportunity_category="No Opportunity",
        )
        self.assertEqual(view["label"], "Do Not Accumulate")

    def test_cheap_valuation_alone_cannot_create_accumulate(self):
        view = accumulation_from_analysis(
            _result(
                long_verdict="Avoid",
                profit=28.0,
                health=24.0,
                valuation=90.0,
                valuation_facts={"pe": 6.0, "dcf_value": 200.0},
            ),
            opportunity_category="No Opportunity",
        )
        self.assertEqual(view["label"], "Do Not Accumulate")

    def test_strong_business_expensive_valuation_is_accumulate_gradually(self):
        view = accumulation_from_analysis(
            _result(long_verdict="Buy", long_score=74.0, profit=82.0, health=80.0, valuation=22.0),
            opportunity_category="Established Opportunity",
        )
        self.assertEqual(view["label"], "Accumulate Gradually")

    def test_expensive_valuation_alone_cannot_create_do_not_accumulate(self):
        view = accumulation_from_analysis(
            _result(long_verdict="Hold", profit=80.0, health=78.0, growth=70.0, valuation=18.0),
            opportunity_category="Established Opportunity",
        )
        self.assertEqual(view["label"], "Accumulate Gradually")
        self.assertNotEqual(view["label"], "Do Not Accumulate")

    def test_missing_data_is_watch_not_a_negative_score(self):
        view = accumulation_from_analysis(
            _result(long_verdict="Hold", profit=None, health=None, growth=None, valuation=None),
        )
        self.assertEqual(view["label"], "Watch for Accumulation")
        self.assertIsNone(view.get("score"))
        self.assertNotEqual(view["label"], "Do Not Accumulate")

    def test_bank_accumulation_uses_bank_fundamentals(self):
        view = accumulation_from_analysis(
            _result(long_verdict="Hold", bank_metrics=_bank_public()),
            opportunity_category="Established Opportunity",
        )
        text = _joined(view)
        self.assertTrue(any(token in text for token in ("gnpa", "nim", "roa", "cet1", "asset quality")))
        self.assertEqual(view["label"], "Accumulate Gradually")

    def test_industrial_metrics_do_not_leak_into_bank_accumulation(self):
        view = accumulation_from_analysis(
            _result(
                long_verdict="Hold",
                bank_metrics=_bank_public(),
                extra_pillars={
                    "profitability": _pillar("profitability", 18, [
                        {"key": "roce", "label": "ROCE", "display": "6.0%", "score": 18, "verdict": "bad",
                         "note": "ROCE has deteriorated materially over multiple periods."},
                        {"key": "margin_trend", "label": "Margin Trend", "display": "-8.0%", "score": 12, "verdict": "bad",
                         "note": "Margins compressing year on year."},
                    ]),
                    "health": _pillar("health", 20, [
                        {"key": "ocf_to_pat", "label": "Operating Cash Flow / Profit", "display": "0.2x",
                         "score": 16, "verdict": "bad",
                         "note": "Cash conversion is weakening versus reported profit."},
                        {"key": "fcf_margin", "label": "FCF", "display": "-4.0%", "score": 14, "verdict": "bad",
                         "note": "Burning cash after capex."},
                    ]),
                },
            ),
            opportunity_category="Established Opportunity",
        )
        text = _joined(view)
        for leak in INDUSTRIAL_LEAKS:
            self.assertNotIn(leak, text, leak)
        self.assertNotIn("roce", text)
        self.assertEqual(view["label"], "Accumulate Gradually")
        self.assertEqual(view["deterioration"], "none")

    def test_explanation_is_evidence_backed_and_avoids_invented_thresholds(self):
        view = accumulation_from_analysis(
            _result(long_verdict="Hold"),
            opportunity_category="Established Opportunity",
            thesis_breakers=["Asset quality deteriorates again"],
        )
        self.assertGreaterEqual(len(view["accumulation_reasons"]), 1)
        self.assertGreaterEqual(len(view["monitor_conditions"]), 1)
        text = _joined(view)
        self.assertNotIn("below 12.5%", text)
        self.assertNotIn("must stay above", text)
        self.assertIn("asset quality deteriorates again", text)
        self.assertNotIn("buy small amounts every month", text)

    def test_states_are_qualitative_not_numeric(self):
        view = classify_accumulation(
            long_verdict="Hold",
            pillars={"profitability": _pillar("profitability", 70.0)},
            opportunity_category="Established Opportunity",
        )
        self.assertIn(view["state"], {
            "ACCUMULATE", "ACCUMULATE_GRADUALLY", "WATCH_FOR_ACCUMULATION", "DO_NOT_ACCUMULATE",
        })
        self.assertNotIn("score", view)
        self.assertNotIn(view["label"], ("Buy", "Hold", "Reduce", "Avoid"))

    def test_hold_established_material_deterioration_is_downgraded(self):
        view = accumulation_from_analysis(
            _result(
                long_verdict="Hold",
                extra_pillars={
                    "profitability": _pillar("profitability", 28, [
                        {"key": "margin_trend", "label": "Margin Trend", "display": "-6.0%", "score": 18,
                         "verdict": "bad", "note": "Margins compressing year on year."},
                        {"key": "roce", "label": "ROCE", "display": "7.0%", "score": 22, "verdict": "bad",
                         "note": "ROCE has deteriorated materially over multiple periods."},
                    ]),
                    "health": _pillar("health", 30, [
                        {"key": "ocf_to_pat", "label": "Operating Cash Flow / Profit", "display": "0.3x",
                         "score": 20, "verdict": "bad",
                         "note": "Cash conversion is weakening versus reported profit."},
                    ]),
                },
            ),
            opportunity_category="Established Opportunity",
        )
        self.assertEqual(view["label"], "Watch for Accumulation")
        self.assertEqual(view["deterioration"], "material")
        self.assertNotEqual(view["label"], "Accumulate Gradually")

    def test_one_bad_quarter_is_not_automatically_downgraded(self):
        view = accumulation_from_analysis(
            _result(
                long_verdict="Hold",
                extra_pillars={
                    "growth": _pillar("growth", 40, [
                        {"key": "q_pat_yoy", "label": "Latest Quarter Profit (YoY)", "display": "-22.0%",
                         "score": 8, "verdict": "bad", "note": "Latest-quarter profit is down."},
                        {"key": "q_rev_yoy", "label": "Latest Quarter Revenue (YoY)", "display": "-11.0%",
                         "score": 12, "verdict": "bad", "note": "Latest-quarter revenue is down."},
                    ]),
                },
            ),
            opportunity_category="Established Opportunity",
        )
        self.assertEqual(view["label"], "Accumulate Gradually")
        self.assertEqual(view["deterioration"], "none")

    def test_emerging_with_demonstrated_improvement_can_be_accumulate_gradually(self):
        view = accumulation_from_analysis(
            _result(
                long_verdict="Hold",
                extra_pillars={
                    "profitability": _pillar("profitability", 76, [
                        {"key": "margin_trend", "label": "Margin Trend", "display": "5.0%", "score": 80,
                         "verdict": "good", "note": "Margins expanding year on year."},
                    ]),
                    "growth": _pillar("growth", 78, [
                        {"key": "pat_cagr", "label": "Profit CAGR", "display": "19.0%", "score": 78,
                         "verdict": "good", "note": "Profit is compounding faster than revenue."},
                    ]),
                },
            ),
            opportunity_category="Emerging Opportunity",
        )
        self.assertEqual(view["label"], "Accumulate Gradually")
        self.assertEqual(view["deterioration"], "none")

    def test_quality_cutoff_alone_does_not_determine_state(self):
        high = accumulation_from_analysis(
            _result(long_verdict="Hold", profit=80.0, health=82.0, growth=78.0),
        )
        self.assertEqual(high["label"], "Watch for Accumulation")
        low_established = accumulation_from_analysis(
            _result(long_verdict="Hold", profit=40.0, health=42.0, growth=38.0),
            opportunity_category="Established Opportunity",
        )
        self.assertEqual(low_established["label"], "Accumulate Gradually")
        self.assertNotEqual(low_established["label"], "Do Not Accumulate")

    def test_material_deterioration_can_downgrade_long_buy(self):
        view = accumulation_from_analysis(
            _result(
                long_verdict="Buy",
                long_score=72.0,
                extra_pillars={
                    "profitability": _pillar("profitability", 30, [
                        {"key": "margin_trend", "label": "Margin Trend", "display": "-7.0%", "score": 16,
                         "verdict": "bad", "note": "Margins compressing year on year."},
                        {"key": "pat_cagr", "label": "Profit CAGR", "display": "-4.0%", "score": 18,
                         "verdict": "bad", "note": "Profit CAGR has deteriorated over multiple years."},
                    ]),
                },
            ),
            opportunity_category="Established Opportunity",
        )
        self.assertEqual(view["label"], "Watch for Accumulation")
        self.assertEqual(view["deterioration"], "material")

    def test_swing_buy_cannot_create_accumulate(self):
        view = accumulation_from_analysis(
            _result(long_verdict="Hold", swing_verdict="Buy", swing_score=82.0),
            opportunity_category="Emerging Opportunity",
        )
        self.assertEqual(view["label"], "Watch for Accumulation")
        self.assertNotEqual(view["label"], "Accumulate")

    def test_drawdown_does_not_change_established_accumulation(self):
        base = accumulation_from_analysis(
            _result(long_verdict="Hold"),
            opportunity_category="Established Opportunity",
        )
        down = accumulation_from_analysis(
            _result(
                long_verdict="Hold",
                price={"last": 80.0, "week52_high": 100.0, "off_52w_high_pct": -20.0},
            ),
            opportunity_category="Established Opportunity",
        )
        self.assertEqual(base["label"], "Accumulate Gradually")
        self.assertEqual(down["label"], base["label"])
        self.assertNotIn("20%", _joined(down))
        self.assertNotIn("drawdown", _joined(down))

    def test_bank_deterioration_uses_bank_kpis(self):
        view = accumulation_from_analysis(
            _result(
                long_verdict="Hold",
                valuation=88.0,
                bank_metrics={
                    "period": "Q1 FY27",
                    "groups": [{
                        "key": "asset_quality",
                        "label": "Asset Quality",
                        "metrics": [
                            {"key": "gnpa", "label": "GNPA", "display": "6.1%", "score": 18, "verdict": "bad",
                             "note": "GNPA is worsening across periods."},
                            {"key": "credit_cost", "label": "Credit Cost", "display": "1.9%", "score": 16,
                             "verdict": "bad", "note": "Credit cost is rising."},
                            {"key": "slippages", "label": "Slippages", "display": "3.2%", "score": 14,
                             "verdict": "bad", "note": "Slippages are worsening."},
                        ],
                    }, {
                        "key": "profitability",
                        "label": "Profitability",
                        "metrics": [
                            {"key": "roa", "label": "ROA", "display": "0.35%", "score": 15, "verdict": "bad",
                             "note": "Return on assets is declining."},
                        ],
                    }],
                },
            ),
            opportunity_category="Established Opportunity",
        )
        self.assertEqual(view["deterioration"], "material")
        self.assertEqual(view["label"], "Watch for Accumulation")
        text = _joined(view)
        self.assertTrue(any(token in text for token in ("gnpa", "credit cost", "slippages", "roa", "asset quality")))
        for leak in INDUSTRIAL_LEAKS:
            self.assertNotIn(leak, text, leak)

    def test_classifier_still_runs_when_ai_is_off(self):
        view = accumulation_from_analysis(_result(long_verdict="Buy"))
        self.assertEqual(view["label"], "Accumulate")
        analysis = ANALYSIS.read_text()
        self.assertIn("deterministic_accumulation", analysis)
        self.assertIn("public_accumulation_from_ai", analysis)
        self.assertLess(analysis.find("deterministic_accumulation"), analysis.find("if not use_ai"))

    def test_public_accumulation_follows_ai_not_deterministic_engine(self):
        engine = accumulation_from_analysis(
            _result(long_verdict="Hold"),
            opportunity_category="Established Opportunity",
        )
        self.assertEqual(engine["label"], "Accumulate Gradually")
        public = public_accumulation_from_ai({
            "state": "Watch for Accumulation",
            "rationale": "The franchise is interesting, but earnings durability is not yet proven.",
            "approach": "Sustained improvement in returns and cash conversion would make gradual accumulation more compelling.",
        })
        self.assertEqual(public["label"], "Watch for Accumulation")
        self.assertEqual(public["source"], "ai")
        self.assertNotIn("Quantitative Long", public["rationale"])
        self.assertNotIn("ai_disagreement", public)
        analysis = ANALYSIS.read_text()
        self.assertIn("public_accumulation_from_ai", analysis)
        self.assertNotIn("reconcile_ai_accumulation", analysis)


class TestAccumulationDoesNotTouchExistingScores(unittest.TestCase):
    def test_swing_long_blend_and_opportunity_remain_unchanged(self):
        self.assertEqual(list(HORIZONS), ["swing", "long"])
        self.assertEqual(OVERALL_BLEND, {"swing": 0.40, "long": 0.60})
        self.assertEqual(HORIZONS["swing"]["weights"]["technical_trend"], 0.26)
        self.assertEqual(HORIZONS["long"]["weights"]["profitability"], 0.22)
        self.assertEqual(VERDICT_BANDS[0][:2], (80, "Strong Buy"))
        self.assertEqual(BANK_GROWTH_WEIGHTS["loan_growth"], 1.00)
        self.assertEqual(BANK_PROFIT_WEIGHTS["roa"], 1.20)
        self.assertEqual(BANK_HEALTH_WEIGHTS["nnpa"], 0.70)
        self.assertEqual(VALUATION["pe"], 1.5)
        self.assertNotIn("accumulation", HORIZONS)
        self.assertNotIn("accumulation", OVERALL_BLEND)
        self.assertNotIn("opportunity", HORIZONS)

    def test_scoring_engine_does_not_compute_accumulation(self):
        text = SCORING.read_text().lower()
        self.assertNotIn("accumulation", text)
        self.assertNotIn("opportunity", text)

    def test_analysis_still_has_no_opportunity_view(self):
        analysis = ANALYSIS.read_text()
        self.assertNotIn("OpportunityView", analysis)
        self.assertNotIn("early_opportunity", analysis)


class TestAccumulationPromptAndUi(unittest.TestCase):
    def test_prompt_defines_accumulation_separately_from_horizons(self):
        text = PROMPTS.read_text()
        lower = text.lower()
        self.assertIn("accumulation", lower)
        self.assertIn("not a fourth horizon", lower)
        self.assertIn("not a trading signal", lower)
        self.assertIn("should not simply copy long", lower)
        self.assertIn("exactly two entries", lower)
        self.assertIn("debug context only", lower)
        self.assertIn("do not copy it", lower)
        self.assertNotIn("explain the fact-pack accumulation", lower)
        self.assertNotIn("do not silently replace", lower)
        self.assertIn("roe needs to reach 15%", lower)
        self.assertIn("data gap", lower)
        self.assertIn("profit cagr is only 3.6%", lower)

    def test_ui_has_accumulation_section(self):
        html = (STATIC / "index.html").read_text()
        self.assertIn("Accumulation", html)
        self.assertIn("Why accumulate", html)
        self.assertIn("Why wait?", html)
        self.assertIn("Why not accumulate?", html)
        self.assertIn("Why accumulate gradually?", html)
        self.assertIn("result.accumulation", html)
        self.assertIn("does not mean", html.lower())
        self.assertNotIn("Quantitative Long", html)
        self.assertNotIn("Quantitative Accumulation", html)
        self.assertNotIn("emerging fundamental concern", html)
        self.assertNotIn("base Long and Opportunity mapping", html)


class TestAccumulationSchema(unittest.TestCase):
    def test_thesis_accumulation_is_optional_so_existing_theses_still_validate(self):
        from app.ai.schemas import Thesis

        thesis = Thesis.model_validate({
            "headline": "Hold for now; wait for stronger reported economics.",
            "business_summary": "A listed Indian company whose economics are in the fact pack.",
            "quality_verdict": "Business quality is mixed on current evidence.",
            "valuation_verdict": "Valuation is not obviously excessive on the supplied multiples.",
            "bull_case": ["Growth is intact", "Balance sheet is usable", "Valuation is reasonable"],
            "bear_case": ["Returns are still mediocre", "Execution risk remains", "Coverage is thin"],
            "key_risks": ["Execution fails", "Cycle turns", "Valuation rerates higher"],
            "what_to_watch": ["Next quarter growth", "Margin direction", "Leverage"],
            "horizon_calls": [
                {
                    "horizon": "swing", "stance": "Hold", "conviction": "Medium",
                    "rationale": "Setup is not compelling.",
                    "what_would_change_it": "A material change in the cited evidence.",
                },
                {
                    "horizon": "long", "stance": "Hold", "conviction": "Medium",
                    "rationale": "Current evidence is not yet a conventional Buy.",
                    "what_would_change_it": "A material change in the cited evidence.",
                },
            ],
            "opportunity": {
                "category": "Watch",
                "rationale": "Evidence is mixed; wait for confirmation.",
                "the_bet": "Taking a position would amount to waiting for clearer evidence.",
                "needs_to_happen": "Reported economics need to improve with confirmation.",
                "catalysts": ["Next results print"],
                "thesis_breakers": ["The cited improvement reverses"],
                "risk_level": "Medium",
            },
            "contrarian_note": "The score cannot see trajectory that is only partly in the numbers.",
            "data_caveats": ["No concall transcript"],
        })
        self.assertIsNone(thesis.accumulation)

    def test_schema_has_qualitative_accumulation_states(self):
        from app.ai.schemas import Thesis
        schema = Thesis.model_json_schema()
        dumped = str(schema).lower()
        self.assertIn("accumulate gradually", dumped)
        self.assertIn("watch for accumulation", dumped)
        self.assertIn("do not accumulate", dumped)
        self.assertIn("approach", dumped)
        self.assertNotIn("explain the fact-pack accumulation", dumped)
        self.assertNotIn("do not silently replace", dumped)


class TestAccumulationIsAiOwned(unittest.TestCase):
    def test_ai_accumulation_can_differ_from_long_hold(self):
        public = public_accumulation_from_ai({
            "state": "Accumulate Gradually",
            "rationale": "The franchise is proven and cash conversion is healthy, but valuation leaves less room for a large entry.",
            "approach": "A less demanding multiple, with the business case intact, would make a larger entry more reasonable.",
        })
        self.assertEqual(public["label"], "Accumulate Gradually")
        self.assertNotEqual(public["label"], "Hold")

    def test_ai_accumulation_can_differ_from_established_opportunity(self):
        public = public_accumulation_from_ai({
            "state": "Watch for Accumulation",
            "rationale": "The long-term opportunity is interesting, but earnings durability is not yet proven.",
            "approach": "Repeated evidence that returns and asset quality are stable would make gradual accumulation more compelling.",
        })
        self.assertEqual(public["label"], "Watch for Accumulation")

    def test_fact_pack_omits_deterministic_accumulation_rationale(self):
        from app.analysis import _fact_pack

        engine = accumulation_from_analysis(
            _result(long_verdict="Hold"),
            opportunity_category="Established Opportunity",
        )
        self.assertIn("Quantitative Long", " ".join(engine.get("accumulation_reasons") or []))
        payload = _result(long_verdict="Hold")
        payload.update({
            "company": {"name": "Test", "sector": "Industrials"},
            "overall": {"score": 60.0, "verdict": "Hold"},
            "risk": {"beta": 1.0, "red_flags": []},
            "earnings": {"beat_rate": 50},
            "ownership": {"promoter_pct": 5.0, "top_holders": []},
            "analysts": {"recommendation": "hold"},
            "news": [],
            "pros": [],
            "cons": [],
            "deterministic_accumulation": engine,
        })
        pack = _fact_pack(payload)
        dumped = json.dumps(pack)
        lower = dumped.lower()
        self.assertNotIn("accumulation", pack)
        self.assertIn("deterministic_accumulation", pack)
        self.assertEqual(pack["deterministic_accumulation"].get("usage"), "debug_context_only")
        self.assertNotIn("rationale", pack["deterministic_accumulation"])
        self.assertNotIn("accumulation_reasons", pack["deterministic_accumulation"])
        self.assertNotIn("Quantitative Long", dumped)
        self.assertNotIn("emerging fundamental concern", lower)
        self.assertNotIn("base Long and Opportunity mapping", dumped)

    def test_prompt_does_not_instruct_copying_deterministic_accumulation(self):
        lower = PROMPTS.read_text().lower()
        self.assertIn("debug context only", lower)
        self.assertIn("not an instruction", lower)
        self.assertNotIn("explain the fact-pack accumulation.state", lower)
        self.assertNotIn("if you disagree with the deterministic", lower)

    def test_prompt_treats_mixed_evidence_as_tension_not_automatic_deterioration(self):
        lower = PROMPTS.read_text().lower()
        self.assertIn("forcing the situation into a deterioration narrative", lower)
        self.assertIn("profit cagr is only 3.6%", lower)
        self.assertIn("durability remains uncertain", lower)

    def test_prompt_treats_missing_bank_kpis_as_uncertainty(self):
        lower = PROMPTS.read_text().lower()
        self.assertIn("missing bank-specific fundamentals are a data gap", lower)
        self.assertIn("not evidence of weakness", lower)

    def test_prompt_forbids_invented_numerical_recovery_thresholds(self):
        lower = PROMPTS.read_text().lower()
        self.assertIn("roe needs to reach 15%", lower)
        self.assertIn("two to three quarters above 15% roe", lower)
        self.assertIn("do not invent numerical thresholds", lower)

    def test_dynamic_headings_cover_all_four_states(self):
        html = (STATIC / "index.html").read_text()
        self.assertIn("accumulationWhyHeading", html)
        self.assertIn("'Accumulate': 'Why accumulate?'", html)
        self.assertIn("'Accumulate Gradually': 'Why accumulate gradually?'", html)
        self.assertIn("'Watch for Accumulation': 'Why wait?'", html)
        self.assertIn("'Do Not Accumulate': 'Why not accumulate?'", html)

    def test_schema_accumulation_view_requires_approach_not_engine_explanation(self):
        from app.ai.schemas import AccumulationView
        view = AccumulationView.model_validate({
            "state": "Accumulate Gradually",
            "rationale": "Proven franchise, but valuation argues for a measured approach.",
            "approach": "A less demanding multiple would make a larger entry more reasonable.",
        })
        self.assertEqual(view.state, "Accumulate Gradually")
        self.assertEqual(view.approach.startswith("A less demanding"), True)
        dumped = str(AccumulationView.model_json_schema()).lower()
        self.assertNotIn("explain the fact-pack accumulation", dumped)
        self.assertNotIn("silently replace", dumped)


class TestAccumulationPublicWiring(unittest.TestCase):
    """AI accumulation must reach the public result the UI actually reads."""

    def test_valid_ai_accumulation_reaches_public_result(self):
        public = public_accumulation_from_ai({
            "state": "Watch for Accumulation",
            "rationale": "Earnings durability is not yet proven.",
            "approach": "Repeated evidence of stable returns would make gradual accumulation more compelling.",
        })
        result = {"ai": {"thesis": {"accumulation": {"state": "Watch for Accumulation"}}}}
        result["accumulation"] = public
        self.assertEqual(result["accumulation"]["state"], "Watch for Accumulation")
        self.assertEqual(result["accumulation"]["rationale"], "Earnings durability is not yet proven.")
        self.assertEqual(result["accumulation"]["approach"].startswith("Repeated evidence"), True)
        self.assertNotIn("Quantitative Long", result["accumulation"]["rationale"])

    def test_serialized_result_contains_ai_accumulation_when_ai_returns_it(self):
        public = public_accumulation_from_ai({
            "state": "Accumulate Gradually",
            "rationale": "Proven franchise, but valuation argues for patience.",
            "approach": "A less demanding multiple would make a larger entry more reasonable.",
        })
        payload = json.dumps({"accumulation": public})
        loaded = json.loads(payload)["accumulation"]
        self.assertEqual(loaded["state"], "Accumulate Gradually")
        self.assertIn("rationale", loaded)
        self.assertIn("approach", loaded)

    def test_deterministic_accumulation_is_not_substituted_as_public_result(self):
        engine = accumulation_from_analysis(
            _result(long_verdict="Hold"),
            opportunity_category="Established Opportunity",
        )
        public = public_accumulation_from_ai({
            "state": "Watch for Accumulation",
            "rationale": "Improvement is not yet durable.",
            "approach": "Wait for confirmation in reported returns.",
        })
        result = {
            "deterministic_accumulation": engine,
            "accumulation": public,
        }
        self.assertEqual(result["accumulation"]["state"], "Watch for Accumulation")
        self.assertNotEqual(result["accumulation"]["rationale"], engine["rationale"])
        self.assertNotIn("Quantitative Long", result["accumulation"]["rationale"])
        analysis = ANALYSIS.read_text()
        self.assertIn('result["accumulation"] = public', analysis)
        self.assertNotIn('result["accumulation"] = accumulation_from_analysis', analysis)
        self.assertNotIn('result["accumulation"] = result["deterministic_accumulation"]', analysis)

    def test_run_thesis_copies_public_accumulation_onto_the_result(self):
        html = (STATIC / "index.html").read_text()
        thesis_fn = html.split("async runThesis()", 1)[1].split("reset()", 1)[0]
        self.assertIn("accumulation:", thesis_fn)
        self.assertIn("data.accumulation", thesis_fn)
        self.assertNotIn("deterministic_accumulation", thesis_fn)
        self.assertNotIn("this.result = { ...this.result, ai: data.ai || { error: 'No thesis returned.' } };", thesis_fn)

    def test_ui_card_reads_public_accumulation_state_or_label(self):
        html = (STATIC / "index.html").read_text()
        card = html.split("<!-- Accumulation")[1].split("<!-- Chart + pillars")[0]
        self.assertIn("v-if=\"result.accumulation\"", card)
        self.assertIn("accumulationWhyHeading", card)
        self.assertIn("result.accumulation.rationale", card)
        self.assertIn("result.accumulation.approach", card)
        self.assertIn("accumulationLabel", html)

    def test_ui_headings_for_all_four_public_states(self):
        html = (STATIC / "index.html").read_text()
        heading_fn = html.split("accumulationWhyHeading(label)", 1)[1].split("verdictPill", 1)[0]
        self.assertIn("'Accumulate': 'Why accumulate?'", heading_fn)
        self.assertIn("'Accumulate Gradually': 'Why accumulate gradually?'", heading_fn)
        self.assertIn("'Watch for Accumulation': 'Why wait?'", heading_fn)
        self.assertIn("'Do Not Accumulate': 'Why not accumulate?'", heading_fn)


if __name__ == "__main__":
    unittest.main()
