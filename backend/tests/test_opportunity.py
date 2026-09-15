"""Stage 4D: Established vs Emerging long-term Opportunity.

No live AI, network, or PDF. Scoring weights must stay frozen.
"""
from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app.analysis import _fact_pack
from app.engine.bank_scoring import (
    BANK_GROWTH_WEIGHTS,
    BANK_HEALTH_WEIGHTS,
    BANK_PROFIT_WEIGHTS,
)
from app.engine.scoring import HORIZONS, OVERALL_BLEND, VERDICT_BANDS
from app.engine.metric_weights import VALUATION
from test_bank_presentation import _stub_result
from test_bank_scoring import HDFC


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
SCORING = Path(__file__).resolve().parents[1] / "app" / "engine" / "scoring.py"
ANALYSIS = Path(__file__).resolve().parents[1] / "app" / "analysis.py"

OPPORTUNITY_CATEGORIES = (
    "Established Opportunity",
    "Emerging Opportunity",
    "Watch",
    "No Opportunity",
)
RETIRED_CATEGORIES = ("Strong Opportunity", "Early Opportunity")


def _horizon(horizon: str, stance: str, rationale: str = "Evidence from the fact pack.") -> dict:
    return {
        "horizon": horizon,
        "stance": stance,
        "conviction": "Medium",
        "rationale": rationale,
        "what_would_change_it": "A material change in the cited evidence.",
    }


def _opportunity(
    category: str = "Watch",
    rationale: str = "Evidence is mixed; wait for confirmation.",
    the_bet: str = "Taking a position would amount to waiting for clearer evidence.",
    needs_to_happen: str = "Reported economics need to improve with confirmation.",
    catalysts: list[str] | None = None,
    thesis_breakers: list[str] | None = None,
    risk_level: str = "Medium",
) -> dict:
    return {
        "category": category,
        "rationale": rationale,
        "the_bet": the_bet,
        "needs_to_happen": needs_to_happen,
        "catalysts": catalysts or ["Next results print"],
        "thesis_breakers": thesis_breakers or ["The cited improvement reverses"],
        "risk_level": risk_level,
    }


def _thesis(*, long_stance: str = "Hold", swing_stance: str = "Hold",
            opportunity: dict | None = None, **overrides) -> dict:
    payload = {
        "headline": "Hold for now; wait for stronger reported economics.",
        "business_summary": "A listed Indian company whose economics are in the fact pack.",
        "quality_verdict": "Business quality is mixed on current evidence.",
        "valuation_verdict": "Valuation is not obviously excessive on the supplied multiples.",
        "bull_case": ["Growth is intact", "Balance sheet is usable", "Valuation is reasonable"],
        "bear_case": ["Returns are still mediocre", "Execution risk remains", "Coverage is thin"],
        "key_risks": ["Execution fails", "Cycle turns", "Valuation rerates higher"],
        "what_to_watch": ["Next quarter growth", "Margin direction", "Leverage"],
        "horizon_calls": [
            _horizon("swing", swing_stance, "Setup is not compelling over the next few months."),
            _horizon("long", long_stance, "Current evidence is not yet a conventional Buy."),
        ],
        "contrarian_note": "The score cannot see trajectory that is only partly in the numbers.",
        "data_caveats": ["No concall transcript"],
        "opportunity": opportunity or _opportunity(),
    }
    payload.update(overrides)
    return payload


# The original product gap: Long Hold is not the same as "do not invest".
HOLD_IMPROVING_EMERGING = _thesis(
    long_stance="Hold",
    swing_stance="Hold",
    headline="Hold on current numbers; emerging long-term case if the business itself gets stronger.",
    quality_verdict="Current profitability is still mediocre versus established peers.",
    valuation_verdict="Valuation is not obviously punitive on the supplied multiples.",
    opportunity=_opportunity(
        category="Emerging Opportunity",
        rationale=(
            "Current fundamentals remain mixed, so the Long rating stays Hold. "
            "The investment thesis depends on the business itself becoming stronger — margins, "
            "returns and asset quality are not yet proven. That is Emerging, not Established."
        ),
        the_bet="Future earnings power becomes materially stronger than today's reported results if the transformation continues.",
        needs_to_happen="Profitability and asset quality keep improving; credit costs stay controlled.",
        catalysts=["Continued improvement in reported returns", "Stable asset quality at subsequent prints"],
        thesis_breakers=["Asset quality deteriorates again", "Profitability fails to improve"],
        risk_level="High",
    ),
)

HERO_ESTABLISHED = _thesis(
    long_stance="Buy",
    swing_stance="Hold",
    headline="Buy the proven franchise; EV is extra optionality, not the whole case.",
    quality_verdict="ROCE 31.9% and ROE 26.6% on a debt-free, cash-generative ICE two-wheeler franchise.",
    valuation_verdict="Valuation is secondary to the already-proven core economics.",
    opportunity=_opportunity(
        category="Established Opportunity",
        rationale=(
            "The core two-wheeler business is already proven: ROCE 31.9%, ROE 26.6%, debt-free, "
            "cash conversion 1.45x. EV/Ather is additional unproven optionality. Unproven initiatives "
            "do not make a proven company Emerging."
        ),
        the_bet="The core franchise continues to compound; electrification is upside if it works, not the foundation.",
        needs_to_happen="Core margins and competitive position remain healthy; EV investments earn acceptable returns over time.",
        catalysts=["Preserved core economics", "Disciplined capital allocation into EV"],
        thesis_breakers=["Core ICE economics structurally deteriorate", "Capital allocation into EV becomes value-destructive"],
        risk_level="Medium",
    ),
)


class TestOpportunitySchema(unittest.TestCase):
    def test_opportunity_is_a_required_thesis_field(self):
        from app.ai.schemas import Thesis

        self.assertIn("opportunity", Thesis.model_fields)
        incomplete = _thesis()
        incomplete.pop("opportunity")
        with self.assertRaises(ValidationError):
            Thesis.model_validate(incomplete)

    def test_categories_are_the_controlled_set(self):
        from app.ai.schemas import OpportunityView, Thesis

        self.assertEqual(
            set(OpportunityView.model_fields["category"].annotation.__args__),
            set(OPPORTUNITY_CATEGORIES),
        )
        for category in OPPORTUNITY_CATEGORIES:
            Thesis.model_validate(_thesis(opportunity=_opportunity(category=category)))

    def test_long_opportunity_is_not_a_category_or_horizon(self):
        from app.ai.schemas import HorizonCall, OpportunityView

        with self.assertRaises(ValidationError):
            OpportunityView.model_validate(_opportunity(category="Long Opportunity"))
        with self.assertRaises(ValidationError):
            HorizonCall.model_validate(_horizon("opportunity", "Hold"))

    def test_retired_category_names_are_rejected(self):
        from app.ai.schemas import OpportunityView

        for category in RETIRED_CATEGORIES:
            with self.assertRaises(ValidationError):
                OpportunityView.model_validate(_opportunity(category=category))

    def test_schema_fields_remain_the_opportunity_contract(self):
        from app.ai.schemas import OpportunityView, Thesis

        self.assertEqual(
            list(OpportunityView.model_fields),
            ["category", "rationale", "the_bet", "needs_to_happen",
             "catalysts", "thesis_breakers", "risk_level"],
        )
        self.assertIn("opportunity", Thesis.model_fields)
        self.assertNotIn("opportunity_score", Thesis.model_fields)

    def test_hold_improving_company_can_be_emerging_opportunity(self):
        from app.ai.schemas import Thesis

        thesis = Thesis.model_validate(HOLD_IMPROVING_EMERGING)
        self.assertEqual(thesis.horizon_calls[1].horizon, "long")
        self.assertEqual(thesis.horizon_calls[1].stance, "Hold")
        self.assertEqual(thesis.opportunity.category, "Emerging Opportunity")
        self.assertEqual(thesis.opportunity.risk_level, "High")


class TestOpportunityScenarios(unittest.TestCase):
    def _parse(self, payload: dict):
        from app.ai.schemas import Thesis
        return Thesis.model_validate(payload)

    def test_hero_like_proven_core_plus_unproven_optionality_is_established(self):
        thesis = self._parse(HERO_ESTABLISHED)
        self.assertEqual(thesis.horizon_calls[1].stance, "Buy")
        self.assertEqual(thesis.opportunity.category, "Established Opportunity")
        self.assertEqual(thesis.opportunity.risk_level, "Medium")
        self.assertIn("optionality", thesis.opportunity.rationale.lower())
        self.assertNotIn("Emerging", thesis.opportunity.category)

    def test_proven_compounder_is_established_opportunity(self):
        thesis = self._parse(_thesis(
            long_stance="Buy",
            swing_stance="Hold",
            opportunity=_opportunity(
                category="Established Opportunity",
                rationale="Current evidence already supports owning the business at this valuation.",
                the_bet="An investor is buying an already-supported business, not a turnaround.",
                needs_to_happen="The current quality and valuation case remains intact.",
                risk_level="Low",
            ),
        ))
        self.assertEqual(thesis.horizon_calls[1].stance, "Buy")
        self.assertEqual(thesis.opportunity.category, "Established Opportunity")

    def test_improving_but_unproven_is_emerging_opportunity(self):
        thesis = self._parse(HOLD_IMPROVING_EMERGING)
        self.assertEqual(thesis.horizon_calls[1].stance, "Hold")
        self.assertEqual(thesis.opportunity.category, "Emerging Opportunity")

    def test_interesting_but_insufficient_evidence_is_watch(self):
        thesis = self._parse(_thesis(
            long_stance="Hold",
            opportunity=_opportunity(
                category="Watch",
                rationale="The company is interesting but the improvement case still leans on assumptions.",
                the_bet="Waiting for X/Y/Z to improve before taking a position.",
                risk_level="Medium",
            ),
        ))
        self.assertEqual(thesis.opportunity.category, "Watch")

    def test_deteriorating_company_is_no_opportunity(self):
        thesis = self._parse(_thesis(
            long_stance="Avoid",
            swing_stance="Reduce",
            opportunity=_opportunity(
                category="No Opportunity",
                rationale="Fundamentals are deteriorating and the risk/reward does not justify a position.",
                the_bet="There is no sufficiently compelling investment case at present.",
                thesis_breakers=["Stabilisation in the cited deterioration"],
                risk_level="High",
            ),
        ))
        self.assertEqual(thesis.horizon_calls[1].stance, "Avoid")
        self.assertEqual(thesis.opportunity.category, "No Opportunity")

    def test_high_quality_with_poor_chart_can_still_be_strong_opportunity(self):
        thesis = self._parse(_thesis(
            long_stance="Buy",
            swing_stance="Reduce",
            opportunity=_opportunity(
                category="Established Opportunity",
                rationale=(
                    "The business is already a proven compounder. A weak short-term chart does not erase "
                    "the multi-year value-creation case."
                ),
                the_bet="Continued compounding of an already high-quality franchise.",
                risk_level="Low",
            ),
        ))
        self.assertEqual(thesis.horizon_calls[0].stance, "Reduce")
        self.assertEqual(thesis.horizon_calls[1].stance, "Buy")
        self.assertEqual(thesis.opportunity.category, "Established Opportunity")
        self.assertNotIn("RSI", thesis.opportunity.rationale)
        self.assertNotIn("oversold", thesis.opportunity.rationale.lower())

    def test_long_reduce_plus_early_opportunity_requires_turnaround_evidence(self):
        thesis = self._parse(_thesis(
            long_stance="Reduce",
            opportunity=_opportunity(
                category="Emerging Opportunity",
                rationale=(
                    "Current reported economics are weak, so Long stays Reduce. "
                    "A turnaround is only Emerging Opportunity because asset quality and operating efficiency "
                    "in the fact pack already show improvement, which could make today's weakness temporary."
                ),
                the_bet="The cited deterioration proves transitory and future earnings power recovers.",
                needs_to_happen="The improvement in the cited metrics continues rather than reversing.",
                risk_level="High",
            ),
        ))
        self.assertEqual(thesis.horizon_calls[1].stance, "Reduce")
        self.assertEqual(thesis.opportunity.category, "Emerging Opportunity")
        self.assertIn("temporary", thesis.opportunity.rationale.lower())

    def test_technicals_or_a_fallen_stock_are_not_an_opportunity_thesis(self):
        technical = self._parse(_thesis(
            long_stance="Hold",
            opportunity=_opportunity(
                category="No Opportunity",
                rationale=(
                    "The business case is not established. Short-term technical improvement is not a "
                    "long-term Opportunity thesis."
                ),
                the_bet="There is no credible multi-year path to better economics on the available evidence.",
            ),
        ))
        self.assertEqual(technical.opportunity.category, "No Opportunity")
        self.assertNotRegex(technical.opportunity.rationale, r"\bRSI\b")

        fallen = self._parse(_thesis(
            long_stance="Hold",
            opportunity=_opportunity(
                category="No Opportunity",
                rationale="The share price has fallen, but there is no evidence the business is becoming better.",
                the_bet="A lower price alone does not create future shareholder value.",
            ),
        ))
        self.assertEqual(fallen.opportunity.category, "No Opportunity")

    def test_valuation_does_not_by_itself_set_opportunity(self):
        expensive = self._parse(_thesis(
            long_stance="Buy",
            opportunity=_opportunity(
                category="Established Opportunity",
                rationale=(
                    "The long-term business opportunity remains compelling. Current valuation leaves less "
                    "room for execution mistakes, but that does not erase the multi-year thesis."
                ),
                the_bet="The franchise continues to compound even if the multiple is full.",
                risk_level="Medium",
            ),
        ))
        self.assertEqual(expensive.opportunity.category, "Established Opportunity")
        self.assertIn("valuation", expensive.opportunity.rationale.lower())

        cheap = self._parse(_thesis(
            long_stance="Hold",
            opportunity=_opportunity(
                category="Watch",
                rationale="A low multiple is not itself an Opportunity; the future business thesis is still unproven.",
                the_bet="Waiting for an evidence-backed path from today's economics to future value creation.",
            ),
        ))
        self.assertEqual(cheap.opportunity.category, "Watch")

    def test_bank_fixture_can_carry_canonical_opportunity_reasoning(self):
        from app.ai.schemas import Thesis
        from app.engine.bank_presentation import fact_pack_bank_fundamentals, public_bank_metrics

        pack = _fact_pack(_stub_result(
            bank_metrics=public_bank_metrics(HDFC),
            company={"name": "HDFC Bank", "sector": "Financial Services", "industry": "Banks - Private"},
        ))
        self.assertIn("bank_fundamentals", pack)
        groups = pack["bank_fundamentals"]["groups"]
        self.assertIn("Asset Quality", groups)
        self.assertIn("Profitability", groups)

        thesis = Thesis.model_validate(_thesis(
            long_stance="Buy",
            opportunity=_opportunity(
                category="Established Opportunity",
                rationale=(
                    f"Canonical bank facts show GNPA {HDFC.gnpa.value}% and ROA {HDFC.roa.value}%. "
                    "The opportunity case uses asset quality, NIM, ROA/ROE and capital."
                ),
                the_bet="Owning a bank whose current canonical economics already support the case.",
            ),
        ))
        self.assertNotIn("FCF", thesis.opportunity.rationale)
        self.assertNotIn("EV/EBITDA", thesis.opportunity.rationale)
        self.assertIn("GNPA", thesis.opportunity.rationale)

    def test_non_bank_thesis_remains_valid(self):
        from app.ai.schemas import Thesis

        pack = _fact_pack(_stub_result(
            company={"name": "TCS", "sector": "Technology", "industry": "Information Technology Services"},
        ))
        self.assertNotIn("bank_fundamentals", pack)
        Thesis.model_validate(_thesis(
            long_stance="Buy",
            opportunity=_opportunity(category="Established Opportunity", risk_level="Low"),
        ))

    def test_schema_does_not_invite_invented_future_numbers(self):
        from app.ai.schemas import OpportunityView

        text = json.dumps(OpportunityView.model_json_schema()).lower()
        self.assertIn("do not invent", text)
        self.assertIn("future roe", text)
        self.assertIn("future eps", text)
        self.assertIn("price target", text)
        self.assertIn("rsi", text)
        self.assertIn("entry timing", text)
        self.assertNotIn("forecast the share price", text)

    def test_generate_thesis_does_not_rewrite_long_when_opportunity_is_emerging(self):
        from types import SimpleNamespace

        from app.ai import analyst
        from app.ai.schemas import Thesis
        from app.config import PROVIDERS

        payload = deepcopy(HOLD_IMPROVING_EMERGING)
        fake = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )
        with patch.object(analyst, "_openai_complete", return_value=fake), \
             patch.object(analyst, "_openai_client", return_value=object()):
            out = analyst._openai_compat_thesis(
                PROVIDERS["deepseek"], "{}", "IDFCFIRSTB.NS", "IDFC First Bank",
                "deepseek", "test-model",
            )
        thesis = Thesis.model_validate(out["thesis"])
        self.assertEqual(thesis.horizon_calls[1].stance, "Hold")
        self.assertEqual(thesis.opportunity.category, "Emerging Opportunity")


class TestOpportunityPrompt(unittest.TestCase):
    def test_prompt_defines_long_term_forward_looking_opportunity(self):
        from app.ai.prompts import SYSTEM_PROMPT

        text = SYSTEM_PROMPT
        lower = text.lower()
        self.assertIn(
            "Opportunity is a long-term forward-looking investment judgment. It asks whether the "
            "company could become a substantially better business and create attractive shareholder "
            "value over several years, even if today's fundamentals are not yet strong enough for "
            "a conventional Long Buy.",
            text,
        )
        self.assertIn(
            "Do not use short-term price trends, technical indicators, or entry timing to determine Opportunity.",
            text,
        )
        self.assertIn("Do not require current fundamentals to already qualify as Buy.", text)
        self.assertIn(
            "Do not confuse potential with speculation. Require an evidence-backed path from today's "
            "business to future value creation.",
            text,
        )
        self.assertIn("not a third horizon", lower)
        self.assertIn("not a numeric score", lower)
        self.assertIn("not an entry-price signal", lower)
        self.assertNotIn("Long Opportunity", text)
        self.assertIn("exactly two entries", lower)
        self.assertIn("improving by itself is not enough", lower)
        self.assertIn("future ROE", text)
        self.assertIn("future EPS", text)
        self.assertIn("single quarter", lower)
        self.assertIn("does not automatically establish a trend", lower)
        self.assertIn("Established Opportunity", text)
        self.assertIn("Emerging Opportunity", text)
        self.assertNotIn("Strong Opportunity", text)
        self.assertNotIn("Early Opportunity", text)
        self.assertIn("current economic foundation", lower)
        self.assertIn("not fully proven", lower)
        self.assertIn("unproven optionality", lower)
        self.assertIn("does not automatically make", lower)

    def test_prompt_keeps_three_distinct_questions(self):
        from app.ai.prompts import SYSTEM_PROMPT

        self.assertIn("next few months", SYSTEM_PROMPT.lower())
        self.assertIn("1–3+ years", SYSTEM_PROMPT)
        self.assertIn("Could this become a very attractive long-term investment", SYSTEM_PROMPT)
        self.assertIn("Do not change Long", SYSTEM_PROMPT)

    def test_prompt_forbids_technicals_and_cheapness_as_opportunity(self):
        from app.ai.prompts import SYSTEM_PROMPT

        lower = SYSTEM_PROMPT.lower()
        self.assertIn("the stock is cheap", lower)
        self.assertIn("the stock has fallen", lower)
        self.assertIn("p/e is high, therefore no opportunity", lower)
        self.assertIn("low p/e does not automatically", lower)
        self.assertIn("wait for a better entry", lower)
        self.assertIn("bank_fundamentals", lower)
        for term in ("rsi", "bollinger", "moving averages", "adx"):
            self.assertIn(term, lower, term)


class TestOpportunityDoesNotTouchScores(unittest.TestCase):
    def test_quantitative_horizons_remain_swing_and_long(self):
        self.assertEqual(list(HORIZONS), ["swing", "long"])
        self.assertEqual(OVERALL_BLEND, {"swing": 0.40, "long": 0.60})
        self.assertEqual(HORIZONS["swing"]["weights"]["technical_trend"], 0.26)
        self.assertEqual(HORIZONS["long"]["weights"]["profitability"], 0.22)
        self.assertEqual(VERDICT_BANDS[0][:2], (80, "Strong Buy"))
        self.assertEqual(BANK_GROWTH_WEIGHTS["loan_growth"], 1.00)
        self.assertEqual(BANK_PROFIT_WEIGHTS["roa"], 1.20)
        self.assertEqual(BANK_HEALTH_WEIGHTS["nnpa"], 0.70)
        self.assertEqual(VALUATION["pe"], 1.5)
        self.assertNotIn("opportunity", HORIZONS)
        self.assertNotIn("opportunity", OVERALL_BLEND)

    def test_scoring_and_analysis_engines_do_not_compute_opportunity(self):
        scoring = SCORING.read_text()
        analysis = ANALYSIS.read_text()
        self.assertNotIn("Emerging Opportunity", scoring)
        self.assertNotIn("Established Opportunity", scoring)
        self.assertNotIn("opportunity", scoring.lower())
        self.assertNotIn("OpportunityView", analysis)
        self.assertNotIn("early_opportunity", analysis)

    def test_fact_pack_has_no_opportunity_score(self):
        pack = _fact_pack(_stub_result())
        self.assertNotIn("opportunity", pack)
        self.assertIn("quant_scores", pack)
        self.assertEqual(set(pack["quant_scores"]["by_horizon"]), {"swing", "long"})


class TestOpportunityUi(unittest.TestCase):
    def test_thesis_panel_has_investment_view_not_a_scorecard(self):
        html = (STATIC / "index.html").read_text()
        self.assertIn("Investment View", html)
        self.assertIn("ai.opportunity", html)
        self.assertIn("Established Opportunity", html)
        self.assertIn("Emerging Opportunity", html)
        self.assertIn("long-term forward-looking", html.lower())
        self.assertNotIn("Long Opportunity", html)
        self.assertNotIn("result.pillars.opportunity", html)
        self.assertNotIn("result.horizons.opportunity", html)
        # Quantitative scorecards remain swing/long only.
        self.assertIn('v-for="(h,k,i) in result.horizons"', html)
        self.assertIn("Blend of 40%", html)
        self.assertNotIn("score-ring", html.split("Investment View")[1].split("<!-- Valuation")[0])

    def test_glossary_covers_opportunity_terms(self):
        src = (STATIC / "glossary.js").read_text().lower()
        for term in ("opportunity", "established opportunity", "emerging opportunity",
                     "no opportunity", "long-term forward-looking"):
            self.assertIn(term, src, term)


if __name__ == "__main__":
    unittest.main()
