"""Stage 5: Short/Swing is a technical setup, not an RSI/PE vote."""
from __future__ import annotations

import unittest

from app.ai.prompts import SYSTEM_PROMPT
from app.ai.schemas import Thesis
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
from app.engine.scoring import HORIZONS, OVERALL_BLEND, VERDICT_BANDS, score_all
from app.engine.swing_regime import classify_swing
from app.engine.technicals import TechnicalSnapshot, _build_short, _build_trend


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


def _mid_pillars(overrides: dict[str, float] | None = None) -> dict[str, Pillar]:
    overrides = overrides or {}
    out: dict[str, Pillar] = {}
    for key, weights in PILLAR_WEIGHTS.items():
        p = Pillar(key, key.replace("_", " ").title())
        for mk, w in weights.items():
            score = overrides[mk] if mk in overrides else 62.0
            p.metrics.append(Metric(mk, mk, 1.0, "", score=score, weight=w))
        out[key] = p
    return out


def _bullish_snap(**kwargs) -> TechnicalSnapshot:
    base = dict(
        price=100.0,
        sma20=97.0,
        sma50=94.0,
        sma200=88.0,
        rsi14=68.0,
        pct_b=0.80,
        adx14=28.0,
        volume_ratio=1.15,
        golden_cross=True,
        sma50_slope_pct=1.8,
        sma200_slope_pct=0.6,
        returns={"1w": 1.4, "1m": 6.5, "3m": 11.0, "6m": 18.0, "1y": 22.0},
        relative_strength={"1w": 0.4, "1m": 3.0, "3m": 8.4, "1y": 12.0},
        week52_position=72.0,
    )
    base.update(kwargs)
    return TechnicalSnapshot(**base)


def _bearish_snap(**kwargs) -> TechnicalSnapshot:
    base = dict(
        price=80.0,
        sma20=86.0,
        sma50=92.0,
        sma200=98.0,
        rsi14=25.0,
        pct_b=0.08,
        adx14=30.0,
        volume_ratio=1.05,
        golden_cross=False,
        sma50_slope_pct=-2.2,
        sma200_slope_pct=-0.8,
        returns={"1w": -3.5, "1m": -8.0, "3m": -14.0, "6m": -18.0, "1y": -22.0},
        relative_strength={"1w": -1.0, "1m": -5.0, "3m": -9.0, "1y": -15.0},
        week52_position=22.0,
    )
    base.update(kwargs)
    return TechnicalSnapshot(**base)


def _score_from_snap(snap: TechnicalSnapshot, extra: dict[str, float] | None = None) -> dict:
    short = Pillar("technical_short", "Short-Term Setup")
    trend = Pillar("technical_trend", "Trend & Relative Strength")
    _build_short(snap, short)
    _build_trend(snap, trend)
    pillars = _mid_pillars(extra)
    pillars["technical_short"] = short
    pillars["technical_trend"] = trend
    return score_all(pillars, snap, _Val(), snap.price)


class TestSwingRegime(unittest.TestCase):
    def test_bullish_rsi_68_is_not_a_sell_signal(self):
        ctx = classify_swing(_bullish_snap())
        self.assertEqual(ctx["trend"], "Bullish")
        self.assertEqual(ctx["momentum"], "Positive")
        self.assertEqual(ctx["relative_strength"], "Positive")
        self.assertIn(ctx["entry_quality"], ("Normal", "Extended"))
        self.assertNotEqual(ctx["regime"], "Oversold Downtrend")

    def test_bullish_rsi_75_is_extended_not_bearish(self):
        ctx = classify_swing(_bullish_snap(rsi14=75.0, pct_b=0.92, sma20=88.0))
        self.assertEqual(ctx["trend"], "Bullish")
        self.assertEqual(ctx["entry_quality"], "Extended")
        self.assertIn(ctx["regime"], ("Bullish but Extended", "Bullish Momentum", "Bullish Trend"))

    def test_bearish_rsi_25_is_not_a_buy_setup(self):
        ctx = classify_swing(_bearish_snap())
        self.assertEqual(ctx["trend"], "Bearish")
        self.assertEqual(ctx["momentum"], "Negative")
        self.assertEqual(ctx["entry_quality"], "Weak")
        self.assertIn(ctx["regime"], ("Oversold Downtrend", "Bearish Trend", "Bearish Momentum"))

    def test_healthy_pullback_is_attractive(self):
        ctx = classify_swing(_bullish_snap(
            rsi14=52.0, pct_b=0.42, sma20=99.0, returns={"1w": -1.2, "1m": 5.0, "3m": 10.0},
        ))
        self.assertEqual(ctx["trend"], "Bullish")
        self.assertEqual(ctx["entry_quality"], "Attractive")
        self.assertEqual(ctx["regime"], "Healthy Pullback")

    def test_entry_quality_is_separate_from_regime(self):
        extended = classify_swing(_bullish_snap(rsi14=77.0, sma20=85.0, pct_b=0.95))
        pullback = classify_swing(_bullish_snap(rsi14=52.0, sma20=99.0, pct_b=0.40))
        self.assertEqual(extended["trend"], pullback["trend"])
        self.assertNotEqual(extended["entry_quality"], pullback["entry_quality"])


class TestSwingScoring(unittest.TestCase):
    def test_rsi_68_does_not_force_hold_in_a_bullish_setup(self):
        result = _score_from_snap(_bullish_snap())
        swing = result["horizons"]["swing"]
        self.assertGreaterEqual(swing["score"], 66)
        self.assertIn(swing["verdict"], ("Buy", "Strong Buy"))

    def test_rsi_75_can_remain_buy_with_extended_entry(self):
        snap = _bullish_snap(rsi14=75.0, pct_b=0.92, sma20=88.0)
        result = _score_from_snap(snap)
        swing = result["horizons"]["swing"]
        self.assertIn(swing["verdict"], ("Buy", "Strong Buy"))
        self.assertEqual(swing["entry_quality"], "Extended")
        self.assertNotEqual(swing["verdict"], swing["entry_quality"])

    def test_oversold_bearish_is_not_automatically_buy(self):
        result = _score_from_snap(_bearish_snap())
        swing = result["horizons"]["swing"]
        self.assertLess(swing["score"], 66)
        self.assertNotIn(swing["verdict"], ("Buy", "Strong Buy"))

    def test_healthy_pullback_is_a_favorable_swing(self):
        result = _score_from_snap(_bullish_snap(
            rsi14=52.0, pct_b=0.42, sma20=99.0,
            returns={"1w": -1.0, "1m": 5.5, "3m": 10.0},
        ))
        swing = result["horizons"]["swing"]
        self.assertGreaterEqual(swing["score"], 66)
        self.assertEqual(swing["entry_quality"], "Attractive")

    def test_high_pe_does_not_automatically_downgrade_bullish_swing(self):
        cheap = _score_from_snap(_bullish_snap(), {"pe": 82.0, "pe_vs_history": 80.0})
        expensive = _score_from_snap(_bullish_snap(), {"pe": 38.0, "pe_vs_history": 36.0})
        self.assertIn(cheap["horizons"]["swing"]["verdict"], ("Buy", "Strong Buy"))
        self.assertIn(expensive["horizons"]["swing"]["verdict"], ("Buy", "Strong Buy"))
        self.assertGreater(cheap["horizons"]["long"]["score"], expensive["horizons"]["long"]["score"])

    def test_low_pe_does_not_rescue_a_bearish_setup(self):
        result = _score_from_snap(_bearish_snap(), {"pe": 90.0, "pe_vs_history": 88.0, "dcf_upside": 90.0})
        self.assertNotIn(result["horizons"]["swing"]["verdict"], ("Buy", "Strong Buy"))

    def test_swing_context_is_on_swing_only(self):
        result = _score_from_snap(_bullish_snap())
        self.assertTrue(result["horizons"]["swing"].get("regime"))
        self.assertTrue(result["horizons"]["swing"].get("entry_quality"))
        self.assertIsNone(result["horizons"]["long"].get("regime"))
        self.assertIsNone(result["horizons"]["long"].get("entry_quality"))

    def test_long_verdict_bands_and_blend_are_unchanged(self):
        self.assertEqual(OVERALL_BLEND, {"swing": 0.40, "long": 0.60})
        self.assertEqual(HORIZONS["long"]["weights"]["profitability"], 0.22)
        self.assertEqual(HORIZONS["long"]["weights"]["valuation"], 0.20)
        self.assertEqual(HORIZONS["swing"]["weights"]["technical_trend"], 0.26)
        self.assertEqual(VERDICT_BANDS[1][:2], (66, "Buy"))

    def test_rsi_metric_score_stays_constructive_at_68_in_an_uptrend(self):
        short = Pillar("technical_short", "Short")
        _build_short(_bullish_snap(), short)
        rsi = next(m for m in short.metrics if m.key == "rsi14")
        self.assertGreaterEqual(rsi.score, 60)

    def test_rsi_25_in_a_downtrend_is_not_scored_as_a_buy(self):
        short = Pillar("technical_short", "Short")
        _build_short(_bearish_snap(), short)
        rsi = next(m for m in short.metrics if m.key == "rsi14")
        self.assertLess(rsi.score, 50)


class TestSwingAiContract(unittest.TestCase):
    def test_swing_horizon_call_has_agreement(self):
        field = Thesis.model_fields["horizon_calls"]
        self.assertIn("swing", str(Thesis.model_json_schema()))
        schema = Thesis.model_json_schema()
        defs = schema.get("$defs") or schema.get("definitions") or {}
        call = defs.get("HorizonCall") or {}
        props = call.get("properties") or {}
        self.assertIn("agreement", props)
        text = str(props["agreement"]).lower()
        self.assertIn("aligned", text)
        self.assertIn("qualified", text)
        self.assertIn("disagrees", text)

    def test_prompt_forbids_rsi_or_pe_as_the_sole_swing_override(self):
        lower = SYSTEM_PROMPT.lower()
        self.assertIn("must not independently recalculate", lower)
        self.assertIn("rsi is overbought", lower)
        self.assertIn("p/e is high", lower)
        self.assertIn("aligned", lower)
        self.assertIn("qualified", lower)
        self.assertIn("disagrees", lower)
        self.assertIn("entry quality", lower)

    def test_prompt_does_not_tell_swing_to_emphasize_pe(self):
        swing_block = SYSTEM_PROMPT.split("**Long: 1–3+ years**")[0].lower()
        self.assertIn("must not independently recalculate", swing_block)
        self.assertIn("high pe does not make swing hold", swing_block)

    def test_long_and_opportunity_prompt_anchors_remain(self):
        lower = SYSTEM_PROMPT.lower()
        self.assertIn("established opportunity", lower)
        self.assertIn("emerging opportunity", lower)
        self.assertIn("entry/setup is secondary for long", lower)


class TestSwingAgreementDiscipline(unittest.TestCase):
    """Stage 5.1: AI interprets Quant; ordinary caveats stay aligned."""

    def test_wabag_style_healthy_pullback_is_high_confidence_buy(self):
        snap = _bullish_snap(
            rsi14=52.0,
            pct_b=0.42,
            sma20=99.0,
            adx14=20.3,
            volume_ratio=1.0,
            returns={"1w": -1.2, "1m": 5.0, "3m": 10.0, "6m": 18.0, "1y": 22.0},
        )
        result = _score_from_snap(snap, {"beta": 38.0, "volatility": 40.0})
        swing = result["horizons"]["swing"]
        self.assertIn(swing["verdict"], ("Buy", "Strong Buy"))
        self.assertEqual(swing["regime"], "Healthy Pullback")
        self.assertEqual(swing["entry_quality"], "Attractive")
        self.assertEqual(swing["confidence_label"], "High")

    def test_prompt_keeps_ordinary_caveats_aligned(self):
        swing_block = SYSTEM_PROMPT.split("**Long: 1–3+ years**")[0].lower()
        self.assertIn("should not by themselves turn aligned into qualified", swing_block)
        for caveat in (
            "moderate adx",
            "neutral volume",
            "elevated beta",
            "elevated volatility",
            "ordinary pullback",
        ):
            self.assertIn(caveat, swing_block)

    def test_prompt_forbids_standalone_directional_overrides(self):
        swing_block = SYSTEM_PROMPT.split("**Long: 1–3+ years**")[0].lower()
        self.assertIn(
            "do not downgrade a quant swing buy to hold merely because",
            swing_block,
        )
        self.assertIn("adx is moderate", swing_block)
        self.assertIn("volume is neutral", swing_block)
        self.assertIn("beta is high", swing_block)
        self.assertIn("volatility is high", swing_block)
        self.assertIn(
            "do not upgrade a bearish/weak setup merely because rsi is oversold",
            swing_block,
        )

    def test_prompt_allows_qualified_only_for_material_uncertainty(self):
        swing_block = SYSTEM_PROMPT.split("**Long: 1–3+ years**")[0].lower()
        self.assertIn("material setup uncertainty", swing_block)
        self.assertIn("disagrees", swing_block)
        self.assertIn("changes the swing direction", swing_block)
        self.assertIn("genuine technical contradiction", swing_block)

    def test_schema_agreement_prefers_aligned_for_ordinary_caveats(self):
        schema = Thesis.model_json_schema()
        defs = schema.get("$defs") or schema.get("definitions") or {}
        props = (defs.get("HorizonCall") or {}).get("properties") or {}
        agreement = str(props["agreement"]).lower()
        qualification = str(props.get("qualification", "")).lower()
        self.assertIn("ordinary caveats stay aligned", agreement)
        self.assertIn("material setup uncertainty", agreement)
        self.assertIn("changes the swing direction", agreement)
        self.assertIn("rsi, bollinger, or pe alone is not a reason", qualification)

    def test_prompt_forbids_unsupported_historical_causal_claims(self):
        lower = SYSTEM_PROMPT.lower()
        self.assertIn("do not invent historical relationships", lower)
        self.assertIn("historically precedes", lower)
        self.assertIn("peg is mechanically low", lower)

    def test_prompt_labels_swing_levels_as_technical_not_fundamental(self):
        lower = SYSTEM_PROMPT.lower()
        self.assertIn("technical stop", lower)
        self.assertIn("technical target", lower)
        self.assertIn("do not mix the swing technical target", lower)

    def test_ui_uses_technical_stop_target_labels(self):
        from pathlib import Path
        html = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text()
        self.assertIn('label="Technical Stop"', html)
        self.assertIn('label="Technical Target"', html)
        self.assertIn('label="Risk/Reward"', html)


class TestSwingAiIndependencePrompt(unittest.TestCase):
    """Quant is evidence; AI forms its own Swing view without score thresholds."""

    def setUp(self):
        self.text = SYSTEM_PROMPT
        self.lower = SYSTEM_PROMPT.lower()
        self.swing = SYSTEM_PROMPT.split("**Long: 1–3+ years**")[0].lower()

    def test_quant_is_evidence_not_an_instruction(self):
        self.assertIn("not instructions", self.swing)
        self.assertIn("not the ai's prior answer", self.swing)
        self.assertIn("important evidence", self.swing)

    def test_ai_must_independently_form_swing_view(self):
        self.assertIn("own honest swing", self.swing)
        self.assertIn("complete fact pack", self.swing)
        self.assertIn("independently interpret", self.swing)

    def test_ai_should_normally_agree_when_evidence_is_coherent(self):
        self.assertIn("when ai should agree with quant", self.swing)
        self.assertIn("often reasonably be buy", self.swing)
        self.assertIn("often reasonably be hold", self.swing)
        self.assertIn("often reasonably be reduce", self.swing)
        self.assertIn("not because the prompt requires agreement", self.swing)

    def test_ai_may_disagree_on_material_contradiction(self):
        self.assertIn("when ai may disagree with quant", self.swing)
        self.assertIn("specific, material, evidence-based reason", self.swing)
        self.assertIn("what evidence makes the quant swing conclusion materially incomplete", self.swing)

    def test_no_arbitrary_quant_score_threshold(self):
        self.assertIn("no arbitrary numerical threshold", self.swing)
        self.assertIn("ai cannot disagree above x score", self.swing)
        self.assertIn("ai must agree above x score", self.swing)
        self.assertIn("does not prohibit disagreement", self.swing)

    def test_high_rsi_alone_cannot_force_hold(self):
        self.assertIn("high rsi in a strong uptrend is not automatically bearish", self.swing)
        self.assertIn("rsi being high", self.swing)

    def test_low_rsi_alone_cannot_force_buy(self):
        self.assertIn("low rsi in a downtrend is not automatically bullish", self.swing)
        self.assertIn("rsi being low", self.swing)

    def test_high_pe_alone_cannot_force_hold(self):
        self.assertIn("high p/e is valuation context, not automatically a reason to reject a swing buy", self.swing)

    def test_dcf_below_price_alone_cannot_force_hold(self):
        self.assertIn("dcf below the current price is not automatically a reason to reject a swing buy", self.swing)

    def test_moderate_adx_or_neutral_volume_cannot_force_disagreement(self):
        self.assertIn("moderate adx or neutral volume should normally affect conviction", self.swing)
        self.assertIn("rather than force a different stance", self.swing)
        self.assertIn("should not automatically cause an ai disagreement", self.swing)

    def test_confidence_can_differ_without_changing_direction(self):
        self.assertIn("may reduce its confidence without changing its swing stance", self.swing)
        self.assertIn("do not convert every uncertainty into hold", self.swing)
        self.assertIn("if it only reduces conviction, keep the directional stance", self.swing)

    def test_agreement_semantics(self):
        self.assertIn("`aligned` does not require identical confidence", self.swing)
        self.assertIn("quant buy / high confidence + ai buy / medium confidence can still be `aligned`", self.swing)
        self.assertIn("quant buy + ai hold because of a material upcoming event can be `disagrees`", self.swing)
        self.assertIn("should not automatically produce `qualified`", self.swing)

    def test_unsupported_peer_claims_are_prohibited(self):
        self.assertIn("best-in-class", self.lower)
        self.assertIn("near best-in-class", self.lower)
        self.assertIn("do not infer peer superiority", self.lower)
        self.assertIn("pnb's currently reported asset-quality metrics are strong", self.lower)

    def test_cannot_invent_precise_future_thresholds(self):
        self.assertIn("nim must stay above 2.50%", self.lower)
        self.assertIn("credit cost must remain below 0.40%", self.lower)
        self.assertIn("do not manufacture precise future thresholds", self.lower)
        self.assertIn("long buy would require credit costs to remain controlled", self.lower)

    def test_company_guidance_may_be_used_when_explicit(self):
        self.assertIn("management's stated guidance is x", self.lower)
        self.assertIn("do not turn ai's own judgment into a fabricated company target", self.lower)

    def test_news_must_not_be_presented_as_certain_outcomes(self):
        self.assertIn("reuters reported that pnb expects", self.lower)
        self.assertIn("do not present an expected future outcome as a fact", self.lower)
        self.assertIn("pnb will deliver faster fy28 growth", self.lower)

    def test_long_remains_independent(self):
        long_block = self.text.split("**Long: 1–3+ years**")[1].split("## Opportunity")[0].lower()
        self.assertIn("is this a good company/business worth owning", long_block)
        self.assertIn("a weak short-term chart should not by itself invalidate", long_block)
        self.assertIn("not driven by rsi, bollinger, moving averages, or short-term price action", self.lower)

    def test_opportunity_remains_independent_and_long_term(self):
        self.assertIn("Do not use short-term price trends, technical indicators, or entry timing to determine Opportunity.", self.text)
        self.assertIn("not a third horizon", self.lower)
        self.assertIn("do not use swing technicals to justify opportunity", self.lower)

    def test_bank_specific_evidence_rules_remain(self):
        self.assertIn("bank_fundamentals", self.lower)
        self.assertIn("should not automatically override a technical swing setup", self.lower)
        self.assertIn("one quarter of bank kpi data is not automatically a trend", self.lower)
        self.assertIn("missing bank kpi data is not evidence of weakness", self.lower)


if __name__ == "__main__":
    unittest.main()
