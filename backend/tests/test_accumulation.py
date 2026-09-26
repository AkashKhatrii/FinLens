"""Accumulation is a qualitative wealth-creation layer, not a horizon or score."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.engine.accumulation import accumulation_from_analysis, classify_accumulation
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
        self.assertLess(analysis.find("deterministic_accumulation"), analysis.find("if not use_ai"))

    def test_public_accumulation_is_the_deterministic_engine_view(self):
        engine = accumulation_from_analysis(_result(long_verdict="Hold"))
        self.assertEqual(engine["label"], "Watch for Accumulation")
        analysis = ANALYSIS.read_text()
        self.assertIn('result["accumulation"] = result["deterministic_accumulation"]', analysis)
        self.assertNotIn("public_accumulation_from_ai", analysis)


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
    def test_prompt_defines_no_ai_accumulation_view(self):
        text = PROMPTS.read_text()
        lower = text.lower()
        self.assertNotIn("## accumulation", lower)
        self.assertNotIn("independently determine accumulation", lower)
        self.assertIn("exactly two entries", lower)
        self.assertIn("data gap", lower)

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
    """The AI thesis no longer carries accumulation/opportunity views."""

    def test_thesis_has_no_accumulation_or_opportunity_fields(self):
        from app.ai.schemas import Thesis

        self.assertNotIn("accumulation", Thesis.model_fields)
        self.assertNotIn("opportunity", Thesis.model_fields)
        self.assertNotIn("key_risks", Thesis.model_fields)
        self.assertIn("bear_case", Thesis.model_fields)
        self.assertIn("horizon_calls", Thesis.model_fields)

    def test_existing_theses_without_removed_fields_still_validate(self):
        from app.ai.schemas import Thesis

        thesis = Thesis.model_validate({
            "headline": "Hold for now; wait for stronger reported economics.",
            "business_summary": "A listed Indian company whose economics are in the fact pack.",
            "quality_verdict": "Business quality is mixed on current evidence.",
            "valuation_verdict": "Valuation is not obviously excessive on the supplied multiples.",
            "bull_case": ["Growth is intact", "Balance sheet is usable", "Valuation is reasonable"],
            "bear_case": ["Returns are still mediocre", "Execution risk remains", "Coverage is thin"],
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
            "contrarian_note": "The score cannot see trajectory that is only partly in the numbers.",
            "data_caveats": ["No concall transcript"],
        })
        self.assertEqual(thesis.horizon_calls[1].stance, "Hold")


class TestAccumulationIsDeterministic(unittest.TestCase):
    """The accumulation panel is driven by the deterministic engine, not the AI."""

    def test_fact_pack_has_no_accumulation_block(self):
        from app.analysis import _fact_pack

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
        })
        pack = _fact_pack(payload)
        self.assertNotIn("accumulation", json.dumps(pack).lower())

    def test_prompt_does_not_instruct_ai_accumulation(self):
        lower = PROMPTS.read_text().lower()
        self.assertNotIn("independently determine accumulation", lower)
        self.assertNotIn("do not copy long, swing, opportunity", lower)

    def test_prompt_treats_missing_bank_kpis_as_uncertainty(self):
        lower = PROMPTS.read_text().lower()
        self.assertIn("missing bank-specific fundamentals are a data gap", lower)
        self.assertIn("not evidence of weakness", lower)

    def test_prompt_forbids_invented_numerical_thresholds(self):
        lower = PROMPTS.read_text().lower()
        self.assertIn("must not invent numerical thresholds", lower)
        self.assertIn("two to three consecutive quarters of x%", lower)

    def test_dynamic_headings_cover_all_four_states(self):
        html = (STATIC / "index.html").read_text()
        self.assertIn("accumulationWhyHeading", html)
        self.assertIn("'Accumulate': 'Why accumulate?'", html)
        self.assertIn("'Accumulate Gradually': 'Why accumulate gradually?'", html)
        self.assertIn("'Watch for Accumulation': 'Why wait?'", html)
        self.assertIn("'Do Not Accumulate': 'Why not accumulate?'", html)


class TestAccumulationPublicWiring(unittest.TestCase):
    """The deterministic accumulation view must reach the public result the UI reads."""

    def test_deterministic_accumulation_is_the_public_result(self):
        engine = accumulation_from_analysis(_result(long_verdict="Hold"))
        result = {
            "deterministic_accumulation": engine,
            "accumulation": engine,
        }
        self.assertEqual(result["accumulation"]["label"], "Watch for Accumulation")
        analysis = ANALYSIS.read_text()
        self.assertIn('result["accumulation"] = result["deterministic_accumulation"]', analysis)

    def test_run_thesis_copies_public_accumulation_onto_the_result(self):
        html = (STATIC / "index.html").read_text()
        thesis_fn = html.split("async runThesis()", 1)[1].split("reset()", 1)[0]
        self.assertIn("accumulation:", thesis_fn)
        self.assertIn("data.accumulation", thesis_fn)
        self.assertNotIn("deterministic_accumulation", thesis_fn)

    def test_ui_card_reads_public_accumulation_state_or_label(self):
        html = (STATIC / "index.html").read_text()
        card = html.split("<!-- Accumulation")[1].split("<!-- Chart + pillars")[0]
        self.assertIn("v-if=\"result.accumulation\"", card)
        self.assertIn("accumulationWhyHeading", card)
        self.assertIn("result.accumulation.rationale", card)
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
