"""Risk, earnings-surprise history, and sentiment/ownership.

Risk is scored as its own pillar rather than folded into the others, because a
cheap, fast-growing, heavily-indebted illiquid smallcap should not be allowed to
average its way to a Buy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..providers.base import StockBundle
from .common import Metric, Pillar, band, fmt_money, fmt_turnover, safe_div
from .fundamentals import FundamentalFacts
from .metric_weights import EARNINGS, RISK, SENTIMENT
from .sector import PROFILE_BANK, apply_profile, classify

TRADING_DAYS = 252

# Liquidity bands per market: India in ₹ Cr/day, US in $M/day. The US bar is
# higher because the screenable universe (S&P 500) is far more liquid than the
# Nifty 500 tail this was tuned against.
_LIQUIDITY_BANDS = {
    "IN": [(0.3, 10), (2, 38), (8, 65), (30, 85), (100, 95)],
    "US": [(1, 10), (10, 38), (50, 65), (200, 85), (1000, 95)],
}
# Below this daily turnover, flag thin trading. Same reasoning as the bands.
_LIQUIDITY_FLAG = {"IN": 2.0, "US": 2.0}


# --- risk --------------------------------------------------------------------

@dataclass
class RiskFacts:
    beta: float | None = None
    volatility_pct: float | None = None
    max_drawdown_pct: float | None = None
    # Average daily turnover: ₹ Cr/day for IN, $M/day for US.
    liquidity_per_day: float | None = None
    liquidity_display: str | None = None
    downside_deviation_pct: float | None = None
    red_flags: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def compute_beta(history: pd.DataFrame, benchmark: pd.DataFrame, lookback: int = 500) -> float | None:
    """Beta from aligned daily returns. Computed here because the provider's
    own beta field is unreliable for NSE names."""
    if history is None or benchmark is None or history.empty or benchmark.empty:
        return None
    try:
        a = history["Close"].tail(lookback).pct_change().dropna()
        b = benchmark["Close"].tail(lookback).pct_change().dropna()
        a.index = pd.to_datetime(a.index).tz_localize(None).normalize()
        b.index = pd.to_datetime(b.index).tz_localize(None).normalize()
        joined = pd.concat([a.rename("s"), b.rename("m")], axis=1, join="inner").dropna()
        if len(joined) < 60:
            return None
        var = joined["m"].var()
        if not var:
            return None
        return float(joined["s"].cov(joined["m"]) / var)
    except Exception:
        return None


def risk_analyse(bundle: StockBundle, f: FundamentalFacts) -> tuple[RiskFacts, Pillar]:
    r = RiskFacts()
    p = Pillar("risk", "Risk")
    hist = bundle.history
    market = bundle.market
    profile = classify(bundle.quote.sector, bundle.quote.industry)
    is_bank = profile == PROFILE_BANK

    r.beta = compute_beta(hist, bundle.benchmark_history)

    turnover_raw: float | None = None
    if hist is not None and not hist.empty and len(hist) > 60:
        rets = hist["Close"].pct_change().dropna()
        r.volatility_pct = float(rets.tail(TRADING_DAYS).std() * np.sqrt(TRADING_DAYS) * 100)
        downside = rets[rets < 0]
        if len(downside) > 10:
            r.downside_deviation_pct = float(downside.std() * np.sqrt(TRADING_DAYS) * 100)
        curve = hist["Close"]
        r.max_drawdown_pct = float(((curve / curve.cummax()) - 1).min() * 100)
        if "Volume" in hist:
            turnover_raw = (hist["Close"] * hist["Volume"]).tail(60).mean()
            scale = 1e7 if market == "IN" else 1e6  # ₹ Cr/day vs $M/day
            r.liquidity_per_day = float(turnover_raw / scale) if turnover_raw else None
            r.liquidity_display = fmt_turnover(r.liquidity_per_day, market)

    p.metrics.append(Metric(
        "beta", "Beta vs Index", r.beta, "",
        band(r.beta, [(0.4, 85), (0.7, 78), (1.0, 62), (1.3, 42), (1.8, 20), (2.5, 6)]),
        ("Moves less than the index — defensive." if (r.beta or 1) < 0.85
         else "Amplifies index moves in both directions." if (r.beta or 1) > 1.2 else ""),
        weight=RISK["beta"], higher_is_better=False,
    ))
    p.metrics.append(Metric(
        "volatility", "Annualised Volatility", r.volatility_pct, "%",
        band(r.volatility_pct, [(12, 88), (20, 72), (30, 52), (45, 28), (70, 8)]),
        "", weight=RISK["volatility"], higher_is_better=False,
    ))
    p.metrics.append(Metric(
        "max_drawdown", "Max Drawdown (3Y)", r.max_drawdown_pct, "%",
        band(r.max_drawdown_pct, [(-75, 5), (-55, 20), (-38, 42), (-25, 65), (-12, 88)]),
        (f"Worst peak-to-trough fall was {abs(r.max_drawdown_pct):.0f}% — size the position for that."
         if r.max_drawdown_pct else ""),
        weight=RISK["max_drawdown"], higher_is_better=False,
    ))
    liq_bands = _LIQUIDITY_BANDS.get(market, _LIQUIDITY_BANDS["IN"])
    liq_thin_at = 3.0 if market == "IN" else 5.0  # ₹ Cr vs $M
    liq_metric = Metric(
        "liquidity", "Avg Daily Turnover", r.liquidity_per_day, "",
        band(r.liquidity_per_day, liq_bands),
        ("Thin trading — exiting a position in a hurry will cost you."
         if (r.liquidity_per_day or 99) < liq_thin_at else ""),
        weight=RISK["liquidity"],
    )
    if turnover_raw:
        liq_metric.display_override = f"{fmt_money(turnover_raw, market)}/day"
    p.metrics.append(liq_metric)

    # --- red flags (surfaced separately, not averaged away) ------------------
    if f.equity is not None and f.equity <= 0:
        r.red_flags.append({
            "severity": "high",
            "text": f"Negative net worth ({fmt_money(f.equity, market)}) — accumulated losses exceed "
                    "paid-up capital and reserves. Equity-based ratios are not meaningful.",
        })
    de = safe_div(f.total_debt, f.equity) if (f.equity and f.equity > 0) else None
    if not is_bank and de is not None and de > 2:
        r.red_flags.append({"severity": "high",
                            "text": f"Debt is {de:.1f}x equity — balance sheet is stretched."})
    op_m, net_m = safe_div(f.ebit, f.revenue), safe_div(f.net_income, f.revenue)
    if op_m is not None and op_m > 1.0:
        r.red_flags.append({
            "severity": "high",
            "text": f"Operating margin of {op_m * 100:.0f}% is not achievable from operations — the "
                    "reported profit contains a large one-off. Treat the headline earnings as non-recurring.",
        })
    elif (not is_bank and op_m is not None and net_m is not None
          and net_m > op_m + 0.05):
        r.red_flags.append({
            "severity": "medium",
            "text": "Net profit exceeds operating profit — earnings depend on non-operating income "
                    "or an exceptional item rather than the core business.",
        })
    ocf_ni = safe_div(f.ocf, f.net_income)
    if not is_bank and ocf_ni is not None and ocf_ni < 0.6:
        r.red_flags.append({"severity": "high",
                            "text": f"Operating cash flow is only {ocf_ni:.0%} of reported profit — earnings quality concern."})
    if f.net_income is not None and f.net_income < 0:
        r.red_flags.append({"severity": "high", "text": "Loss-making at the net level."})
    liq_flag_at = _LIQUIDITY_FLAG.get(market, _LIQUIDITY_FLAG["IN"])
    if (r.liquidity_per_day or 99) < liq_flag_at:
        unit = "₹ Cr" if market == "IN" else "$M"
        r.red_flags.append({"severity": "medium",
                            "text": f"Average turnover under {r.liquidity_per_day:.1f} {unit}/day — liquidity risk."})
    # Promoter holding is an India-only concept. In the US, Yahoo's
    # heldPercentInsiders counts officers/directors, who typically hold
    # single-digit stakes even at great companies — flagging that as "limited
    # skin in the game" is wrong, so the check stays India-only.
    promoter = bundle.ownership.promoter_or_insider_pct
    if market == "IN" and not is_bank and promoter is not None and promoter < 25:
        r.red_flags.append({"severity": "medium",
                            "text": f"Promoter/insider holding is only {promoter:.1f}% — limited skin in the game."})
    if bundle.gaps:
        r.red_flags.append({"severity": "low",
                            "text": "Incomplete data from the source: " + ", ".join(sorted(set(bundle.gaps))[:4]) + "."})
    return r, p


# --- earnings ----------------------------------------------------------------

@dataclass
class EarningsFacts:
    surprises: list[dict[str, Any]] = field(default_factory=list)
    beat_rate: float | None = None
    avg_surprise_pct: float | None = None
    next_date: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def earnings_analyse(bundle: StockBundle) -> tuple[EarningsFacts, Pillar]:
    e = EarningsFacts()
    p = Pillar("earnings", "Earnings Momentum")
    df = bundle.earnings_history

    if df is None or df.empty:
        p.notes.append("No earnings surprise history available for this ticker.")
        return e, p

    df = df.copy()
    reported_col = next((c for c in df.columns if "Reported" in str(c)), None)
    surprise_col = next((c for c in df.columns if "Surprise" in str(c)), None)
    est_col = next((c for c in df.columns if "Estimate" in str(c)), None)

    now = pd.Timestamp.now(tz=getattr(df.index, "tz", None))
    future = df[df.index > now]
    if not future.empty:
        e.next_date = str(future.index.min())[:10]

    past = df[df.index <= now]
    if reported_col:
        past = past[past[reported_col].notna()]

    rows = []
    for idx, row in past.head(8).iterrows():
        rows.append({
            "date": str(idx)[:10],
            "estimate": _num(row.get(est_col)) if est_col else None,
            "reported": _num(row.get(reported_col)) if reported_col else None,
            "surprise_pct": _num(row.get(surprise_col)) if surprise_col else None,
        })
    e.surprises = rows

    valid = [r["surprise_pct"] for r in rows[:4] if r["surprise_pct"] is not None]
    if valid:
        e.beat_rate = sum(1 for s in valid if s > 0) / len(valid) * 100
        e.avg_surprise_pct = sum(valid) / len(valid)

    p.metrics.append(Metric(
        "beat_rate", "Beat Rate (last 4)", e.beat_rate, "%",
        band(e.beat_rate, [(0, 15), (25, 32), (50, 55), (75, 80), (100, 92)]),
        (f"Beat consensus in {int(e.beat_rate / 25)} of the last 4 quarters."
         if e.beat_rate is not None else ""),
        weight=EARNINGS["beat_rate"],
    ))
    p.metrics.append(Metric(
        "avg_surprise", "Avg Surprise", e.avg_surprise_pct, "%",
        band(e.avg_surprise_pct, [(-25, 10), (-8, 32), (0, 52), (8, 76), (25, 92)]),
        "", weight=EARNINGS["avg_surprise"],
    ))
    if e.next_date:
        p.notes.append(f"Next results expected around {e.next_date} — an event risk for short-dated positions.")
    return e, p


def _num(v: Any) -> float | None:
    try:
        f = float(v)
        return None if f != f else round(f, 2)
    except (TypeError, ValueError):
        return None


# --- sentiment & ownership ---------------------------------------------------

def sentiment_analyse(bundle: StockBundle, analyst_upside: float | None) -> Pillar:
    p = Pillar("sentiment", "Sentiment & Ownership")
    a = bundle.analysts
    own = bundle.ownership
    market = bundle.market

    rec_scores = {"strong buy": 92, "buy": 78, "outperform": 75,
                  "hold": 50, "neutral": 50, "underperform": 25, "sell": 12}
    rec = (a.recommendation or "").lower().strip()
    p.metrics.append(Metric(
        "analyst_rating", "Street Rating", None, "",
        float(rec_scores[rec]) if rec in rec_scores else None,
        (f"Consensus is '{a.recommendation}' across {a.analyst_count or '?'} analysts."
         if rec else "No analyst coverage found."),
        weight=SENTIMENT["analyst_rating"],
    ))
    p.metrics.append(Metric(
        "analyst_upside", "Upside to Target", analyst_upside, "%",
        band(analyst_upside, [(-25, 10), (-5, 35), (5, 58), (20, 80), (45, 92)]),
        "", weight=SENTIMENT["analyst_upside"],
    ))
    # Ownership semantics differ by market. India: promoter holding is the
    # skin-in-the-game signal and low values are a genuine negative.
    # US: there is no promoter concept — Yahoo's insider bucket counts
    # officers/directors, who typically hold low-single-digit stakes even at
    # great companies. Scoring that bucket punishes normal US ownership, so
    # for the US it is displayed but unscored (weight 0 keeps coverage clean),
    # and institutional ownership carries the ownership read instead.
    if market == "US":
        p.metrics.append(Metric(
            "promoter_holding", "Insider Holding", own.promoter_or_insider_pct, "%",
            None,
            ("US officers/directors typically hold small stakes — this is not "
             "comparable to Indian promoter holding and is not scored. "
             "Institutional ownership below is the ownership signal that matters."),
            weight=0.0,
        ))
    else:
        p.metrics.append(Metric(
            "promoter_holding", "Promoter / Insider Holding", own.promoter_or_insider_pct, "%",
            band(own.promoter_or_insider_pct, [(5, 15), (25, 40), (45, 68), (60, 85), (75, 88)]),
            (f"Promoters hold {own.promoter_or_insider_pct:.1f}%."
             if own.promoter_or_insider_pct is not None else ""),
            weight=SENTIMENT["promoter_holding"],
        ))
    p.metrics.append(Metric(
        "institutional_holding", "Institutional Holding", own.institutions_pct, "%",
        band(own.institutions_pct, [(1, 25), (8, 45), (18, 65), (35, 82), (55, 88)]),
        "", weight=SENTIMENT["institutional_holding"],
    ))
    if bundle.news:
        p.notes.append(f"{len(bundle.news)} recent news items pulled for the AI read.")
    if own.promoter_pledge_pct is None:
        if market == "US":
            p.notes.append(
                "Insider pledging is disclosed in proxy statements (DEF 14A), not here — "
                "check SEC filings before a large position, and watch Form 4s for insider transactions.")
        else:
            p.notes.append("Promoter pledge data not available from this source — check BSE filings before a large position.")
    apply_profile(p, classify(bundle.quote.sector, bundle.quote.industry))
    return p
