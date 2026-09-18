"""Orchestrator: one ticker in, one complete analysis out.

Order matters in exactly one place - beta is computed by the risk engine and
consumed by the DCF discount rate, so risk runs before valuation.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from .ai import analyst
from .config import MARKETS
from .engine import fundamentals, percentile, qualitative, scoring, technicals, valuation
from .engine.accumulation import accumulation_from_analysis, public_accumulation_from_ai
from .engine.bank_presentation import fact_pack_bank_fundamentals, public_bank_metrics
from .engine.bank_scoring import apply_bank_metrics
from .engine.sector import PROFILE_BANK, classify
from .providers.bank_metrics import BankMetrics
from .providers.bank_metrics_loader import load_canonical_bank_metrics
from .providers.yf_provider import YFinanceProvider

log = logging.getLogger(__name__)

DISCLAIMER = (
    "Research and education only — not investment advice. "
    "Figures come from a free third-party feed and may be delayed, restated, or wrong. "
    "Verify against the company's filings before risking capital."
)


class UnknownSymbol(Exception):
    """Raised when a query can't be resolved. Carries near-misses so the caller
    can offer 'did you mean' rather than a dead end."""

    def __init__(self, message: str, suggestions: list[dict[str, str]] | None = None):
        super().__init__(message)
        self.message = message
        self.suggestions = suggestions or []


def _provider(market: str):
    if market not in MARKETS:
        raise UnknownSymbol(f"Unsupported market '{market}'.")
    return YFinanceProvider(market)


def _resolve_or_raise(provider, query: str) -> str:
    symbol, suggestions = provider.resolve_with_suggestions(query)
    if symbol:
        return symbol
    if suggestions:
        names = ", ".join(s["symbol"] for s in suggestions[:3])
        raise UnknownSymbol(
            f"No exact match for '{query}'. Did you mean {names}?", suggestions
        )
    raise UnknownSymbol(f"Could not find a listed company matching '{query}'.")


def resolve(query: str, market: str = "IN") -> str:
    return _resolve_or_raise(_provider(market), query)


def _bank_metrics_for_analysis(
    symbol: str,
    sector: str | None,
    industry: str | None,
    provided: BankMetrics | None,
) -> BankMetrics | None:
    """Use caller-supplied metrics, else load official KPIs for classified banks."""
    if provided is not None:
        return provided
    if classify(sector, industry) != PROFILE_BANK:
        return None
    return load_canonical_bank_metrics(symbol)


def analyse(
    query: str,
    market: str = "IN",
    use_ai: bool = True,
    bank_metrics: BankMetrics | None = None,
) -> dict[str, Any]:
    started = time.time()
    provider = _provider(market)

    symbol = _resolve_or_raise(provider, query)
    bundle = provider.fetch(symbol)
    if bundle.quote.price is None:
        raise UnknownSymbol(f"No price data available for '{symbol}'.")

    profile = classify(bundle.quote.sector, bundle.quote.industry)
    bank_metrics = _bank_metrics_for_analysis(
        symbol, bundle.quote.sector, bundle.quote.industry, bank_metrics,
    )

    fund_facts, growth_p, profit_p, health_p = fundamentals.analyse(bundle)
    risk_facts, risk_p = qualitative.risk_analyse(bundle, fund_facts)
    val_facts, val_p = valuation.analyse(
        bundle, fund_facts, risk_facts.beta, bank_metrics=bank_metrics,
    )
    tech_snap, tech_short_p, tech_trend_p = technicals.analyse(bundle.history, bundle.benchmark_history)
    earn_facts, earn_p = qualitative.earnings_analyse(bundle)
    sent_p = qualitative.sentiment_analyse(bundle, val_facts.analyst_upside_pct)

    pillars = {
        p.key: p for p in (growth_p, profit_p, health_p, val_p,
                           tech_short_p, tech_trend_p, earn_p, sent_p, risk_p)
    }

    apply_bank_metrics(pillars, bank_metrics, profile)

    scores = scoring.score_all(pillars, tech_snap, val_facts, bundle.quote.price)
    pros_cons = scoring.build_pros_cons(pillars, risk_facts.red_flags)

    public_banks = public_bank_metrics(bank_metrics) if profile == PROFILE_BANK else None

    cfg = MARKETS[market]
    result: dict[str, Any] = {
        "symbol": symbol,
        "market": market,
        "currency": cfg["currency"],
        "currency_symbol": cfg["symbol"],
        "benchmark": cfg["benchmark_name"],
        "company": {
            "name": bundle.quote.name,
            "sector": bundle.quote.sector,
            "industry": bundle.quote.industry,
            "summary": bundle.quote.business_summary,
            "website": bundle.quote.website,
            "market_cap": bundle.quote.market_cap,
            "market_cap_cr": (bundle.quote.market_cap / 1e7) if bundle.quote.market_cap else None,
        },
        "price": {
            "last": bundle.quote.price,
            "previous_close": bundle.quote.previous_close,
            "day_change_pct": bundle.quote.day_change_pct,
            "week52_high": bundle.quote.week52_high,
            "week52_low": bundle.quote.week52_low,
            "off_52w_high_pct": bundle.quote.off_52w_high_pct,
        },
        "overall": {**scores["overall"], "rank": percentile.rank(scores["overall"]["score"], "overall")},
        "horizons": {
            k: {**v, "rank": percentile.rank(v["score"], k)}
            for k, v in scores["horizons"].items()
        },
        "pros": pros_cons["pros"],
        "cons": pros_cons["cons"],
        "pillars": {k: p.to_dict() for k, p in pillars.items()},
        "fundamentals": fund_facts.to_dict(),
        "valuation": val_facts.to_dict(),
        "technicals": tech_snap.to_dict(),
        "risk": risk_facts.to_dict(),
        "earnings": earn_facts.to_dict(),
        "ownership": {
            "promoter_pct": bundle.ownership.promoter_or_insider_pct,
            "institutions_pct": bundle.ownership.institutions_pct,
            "top_holders": bundle.ownership.top_holders,
        },
        "analysts": {
            "target_mean": bundle.analysts.target_mean,
            "target_high": bundle.analysts.target_high,
            "target_low": bundle.analysts.target_low,
            "recommendation": bundle.analysts.recommendation,
            "count": bundle.analysts.analyst_count,
            "upside_pct": val_facts.analyst_upside_pct,
        },
        "news": bundle.news[:8],
        "data_gaps": sorted(set(bundle.gaps)),
        "disclaimer": DISCLAIMER,
    }
    if public_banks is not None:
        result["bank_metrics"] = public_banks
    elif profile == PROFILE_BANK:
        result["data_gaps"] = sorted(set(result["data_gaps"] + ["bank fundamentals"]))

    result["deterministic_accumulation"] = accumulation_from_analysis(result)

    if not use_ai:
        result["ai"] = None
    else:
        ai_status = analyst.status()
        if not ai_status["available"]:
            # Surface *why* so the UI can prompt for a key instead of silently
            # rendering a quant-only report.
            result["ai"] = {"error": ai_status["reason"]}
        else:
            ai_started = time.time()
            ai = analyst.generate_thesis(_fact_pack(result), symbol, bundle.quote.name)
            if ai:
                ai["latency_ms"] = int((time.time() - ai_started) * 1000)
            result["ai"] = ai
            thesis = (ai or {}).get("thesis") or {}
            opportunity = thesis.get("opportunity") or {}
            result["deterministic_accumulation"] = accumulation_from_analysis(
                result,
                opportunity_category=opportunity.get("category"),
                thesis_breakers=opportunity.get("thesis_breakers"),
            )
            public = public_accumulation_from_ai(thesis.get("accumulation"))
            if public:
                result["accumulation"] = public

    result["elapsed_ms"] = int((time.time() - started) * 1000)
    return result


def _fact_pack(r: dict[str, Any]) -> dict[str, Any]:
    """Trimmed view of the analysis for the model.

    Chart series and raw holder lists are dropped - they cost tokens and add
    nothing the model can reason about.
    """
    tech = {k: v for k, v in r["technicals"].items() if k != "series"}
    pack = {
        "company": r["company"],
        "price": r["price"],
        "quant_scores": {
            "overall": r["overall"],
            "by_horizon": {
                k: {kk: v[kk] for kk in (
                    "score", "verdict", "confidence", "confidence_label",
                    "regime", "entry_quality", "swing_factors",
                ) if kk in v}
                for k, v in r["horizons"].items()
            },
        },
        "pillar_scores": {
            k: {"score": round(p["score"], 1) if p["score"] is not None else None,
                "coverage": round(p["coverage"], 2),
                "metrics": [
                    {"label": m["label"], "value": m["display"],
                     "score": round(m["score"], 1) if m["score"] is not None else None,
                     "note": m["note"]}
                    for m in p["metrics"]
                ],
                "notes": p["notes"]}
            for k, p in r["pillars"].items()
        },
        "fundamentals": {k: v for k, v in r["fundamentals"].items()
                         if k.endswith("_cr") or k in ("eps", "book_value_ps", "fiscal_year",
                                                       "years", "margin_series")},
        "valuation": {k: v for k, v in r["valuation"].items() if k != "pe_history"},
        "pe_history": r["valuation"].get("pe_history"),
        "technicals": tech,
        "risk": r["risk"],
        "earnings": r["earnings"],
        "ownership": {k: v for k, v in r["ownership"].items() if k != "top_holders"},
        "analysts": r["analysts"],
        "recent_news": [{"title": n["title"], "publisher": n["publisher"]} for n in r["news"]],
        "rule_based_pros": r["pros"],
        "rule_based_cons": r["cons"],
        "data_gaps": r["data_gaps"],
    }
    swing = (r.get("horizons") or {}).get("swing") or {}
    if swing.get("swing_factors") or swing.get("regime"):
        pack["swing_setup"] = {
            "score": swing.get("score"),
            "verdict": swing.get("verdict"),
            **(swing.get("swing_factors") or {}),
            "regime": swing.get("regime"),
            "entry_quality": swing.get("entry_quality"),
        }
    bank_pack = fact_pack_bank_fundamentals(r.get("bank_metrics"))
    if bank_pack is not None:
        pack["bank_fundamentals"] = bank_pack
    next_earnings = (r.get("earnings") or {}).get("next_date")
    if next_earnings:
        pack["upcoming_events"] = {
            "next_earnings": next_earnings,
            "note": (
                "Known event. Describe it factually as a near-term catalyst/risk for a "
                "short-dated position. Do not describe this as 'no immediate event risk'."
            ),
        }
    det = r.get("deterministic_accumulation") or {}
    if det.get("state") or det.get("label"):
        pack["deterministic_accumulation"] = {
            "state": det.get("label") or det.get("state"),
            "usage": "debug_context_only",
        }
    return pack
