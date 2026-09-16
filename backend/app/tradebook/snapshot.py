"""Build an immutable recommendation snapshot from an already-computed analysis.

This module must not import or call `analyse`. It only copies fields.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def snapshot_from_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(analysis, dict):
        raise ValueError("Analysis payload must be an object.")
    ticker = analysis.get("symbol")
    price = ((analysis.get("price") or {}).get("last"))
    if not ticker:
        raise ValueError("Analysis is missing a ticker.")
    if price is None:
        raise ValueError("Analysis is missing a snapshot price.")

    company = analysis.get("company") or {}
    overall = analysis.get("overall") or {}
    horizons = analysis.get("horizons") or {}
    swing = horizons.get("swing") or {}
    long_h = horizons.get("long") or {}
    plan = swing.get("plan") or {}
    factors = swing.get("swing_factors") or {}
    technicals = dict(analysis.get("technicals") or {})
    technicals.pop("series", None)

    thesis, ai_meta = _thesis(analysis.get("ai"))
    swing_call = _horizon_call(thesis, "swing") if thesis else None
    opportunity = (thesis or {}).get("opportunity") if thesis else None

    created = datetime.now(timezone.utc).isoformat()
    return {
        "id": uuid4().hex,
        "ticker": str(ticker),
        "company_name": company.get("name"),
        "exchange": _exchange(analysis.get("market")),
        "sector": company.get("sector"),
        "created_at": created,
        "snapshot_price": price,
        "overall_score": overall.get("score"),
        "overall_verdict": overall.get("verdict"),
        "swing_score": swing.get("score"),
        "swing_verdict": swing.get("verdict"),
        "swing_confidence": swing.get("confidence"),
        "swing_regime": swing.get("regime"),
        "swing_entry_quality": swing.get("entry_quality"),
        "technical_stop": plan.get("stop_loss"),
        "technical_target": plan.get("target"),
        "risk_reward": plan.get("risk_reward"),
        "long_score": long_h.get("score"),
        "long_verdict": long_h.get("verdict"),
        "long_confidence": long_h.get("confidence"),
        "opportunity_category": None if not opportunity else opportunity.get("category"),
        "opportunity_risk": None if not opportunity else opportunity.get("risk_level"),
        "opportunity_bet": None if not opportunity else opportunity.get("the_bet"),
        "opportunity_needs_to_happen": None if not opportunity else opportunity.get("needs_to_happen"),
        "opportunity_thesis_breakers": None if not opportunity else opportunity.get("thesis_breakers"),
        "ai_available": thesis is not None,
        "ai_provider": None if not thesis else ai_meta.get("provider"),
        "ai_model": None if not thesis else ai_meta.get("model"),
        "ai_swing_verdict": None if not swing_call else swing_call.get("stance"),
        "ai_agreement": None if not swing_call else swing_call.get("agreement"),
        "ai_reasoning": None if not swing_call else swing_call.get("rationale"),
        "ai_flips_if": None if not swing_call else swing_call.get("what_would_change_it"),
        "quant_evidence": _quant_evidence(swing, factors, plan, technicals),
        "metrics_snapshot": technicals,
        "is_active": True,
        "removed_at": None,
        "removal_reason": None,
        "current_price": None,
        "current_price_as_of": None,
    }


def _exchange(market: Any) -> str | None:
    if market == "IN":
        return "NSE"
    if market:
        return str(market)
    return None


def _thesis(ai: Any) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not isinstance(ai, dict) or ai.get("error") or not ai.get("thesis"):
        return None, {}
    thesis = ai.get("thesis")
    if not isinstance(thesis, dict):
        return None, {}
    return thesis, {"provider": ai.get("provider"), "model": ai.get("model")}


def _horizon_call(thesis: dict[str, Any], horizon: str) -> dict[str, Any] | None:
    for call in thesis.get("horizon_calls") or []:
        if isinstance(call, dict) and call.get("horizon") == horizon:
            return call
    return None


def _quant_evidence(swing: dict, factors: dict, plan: dict, technicals: dict) -> dict[str, Any]:
    return {
        "score": swing.get("score"),
        "verdict": swing.get("verdict"),
        "confidence": swing.get("confidence"),
        "regime": swing.get("regime"),
        "entry_quality": swing.get("entry_quality"),
        "trend": factors.get("trend"),
        "momentum": factors.get("momentum"),
        "relative_strength": factors.get("relative_strength"),
        "setup": factors.get("setup"),
        "volume": factors.get("volume"),
        "rsi14": technicals.get("rsi14"),
        "adx14": technicals.get("adx14"),
        "pct_b": technicals.get("pct_b"),
        "volume_ratio": technicals.get("volume_ratio"),
        "sma20": technicals.get("sma20"),
        "sma50": technicals.get("sma50"),
        "sma200": technicals.get("sma200"),
        "returns": technicals.get("returns"),
        "rs": technicals.get("relative_strength"),
        "technical_stop": plan.get("stop_loss"),
        "technical_target": plan.get("target"),
        "risk_reward": plan.get("risk_reward"),
    }
