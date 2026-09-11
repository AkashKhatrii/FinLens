"""Valuation engine: multiples, own-history P/E band, and a two-stage DCF.

The most useful single output here is not the absolute P/E but the P/E *relative
to the company's own history* - "expensive" only means anything against a
reference. We reconstruct that band by pairing each annual EPS with the share
price on that statement date.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any

import pandas as pd

from ..config import MARKETS
from ..providers.base import StockBundle, latest, pick_row
from .common import Metric, Pillar, band, cagr, safe_div
from .fundamentals import FundamentalFacts
from .metric_weights import VALUATION


@dataclass
class ValuationFacts:
    pe: float | None = None
    pe_median_5y: float | None = None
    pe_history: list[dict[str, Any]] = field(default_factory=list)
    pb: float | None = None
    ev_ebitda: float | None = None
    ps: float | None = None
    peg: float | None = None
    dividend_yield: float | None = None
    earnings_yield: float | None = None
    bond_yield: float | None = None
    dcf_value: float | None = None
    dcf_upside_pct: float | None = None
    dcf_assumptions: dict[str, Any] = field(default_factory=dict)
    analyst_upside_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _price_on(history: pd.DataFrame, when: Any) -> float | None:
    """Close price on/just before a statement date."""
    if history is None or history.empty:
        return None
    try:
        target = pd.Timestamp(when)
        idx = history.index
        if getattr(idx, "tz", None) is not None:
            target = target.tz_localize(idx.tz) if target.tzinfo is None else target.tz_convert(idx.tz)
        prior = history.loc[:target]
        if prior.empty:
            return None
        return float(prior["Close"].iloc[-1])
    except Exception:
        return None


def _pe_band(bundle: StockBundle) -> tuple[list[dict[str, Any]], float | None]:
    """Historical P/E from annual EPS paired with the price on that date."""
    inc = bundle.statements.income_annual
    eps_row = pick_row(inc, "Basic EPS", "Diluted EPS")
    if eps_row is None or bundle.history is None or bundle.history.empty:
        return [], None

    points: list[dict[str, Any]] = []
    for col in inc.columns[:6]:
        try:
            eps = float(eps_row.get(col))
        except (TypeError, ValueError):
            continue
        if eps is None or eps != eps or eps <= 0:
            continue
        px = _price_on(bundle.history, col)
        if not px:
            continue
        points.append({"date": str(col)[:10], "eps": round(eps, 2),
                       "price": round(px, 2), "pe": round(px / eps, 2)})

    pes = [p["pe"] for p in points]
    return points, (median(pes) if len(pes) >= 2 else None)


def analyse(bundle: StockBundle, f: FundamentalFacts, beta: float | None) -> tuple[ValuationFacts, Pillar]:
    cfg = MARKETS[bundle.market]
    v = ValuationFacts()
    p = Pillar("valuation", "Valuation")
    info = bundle.info
    price = bundle.quote.price
    mcap = bundle.quote.market_cap

    eps = info.get("trailingEps") or f.eps
    v.pe = info.get("trailingPE") or safe_div(price, eps)
    v.pe_history, v.pe_median_5y = _pe_band(bundle)
    v.pb = info.get("priceToBook") or safe_div(price, f.book_value_ps)
    v.ev_ebitda = info.get("enterpriseToEbitda")
    v.ps = safe_div(mcap, f.revenue)
    v.bond_yield = cfg["risk_free_rate"] * 100

    # A negative multiple is not a cheap multiple. Loss-making earnings or
    # negative book value leave these undefined; left in, the band scorer reads
    # them as deeply attractive (a -4.6x P/B scored 92 before this guard).
    v.pe = v.pe if (v.pe is not None and v.pe > 0) else None
    # Earnings dominated by a one-off make every earnings multiple a trap:
    # "4.5x trailing earnings" reads as cheap when the E is non-recurring.
    if f.earnings_exceptional:
        v.pe = None
        p.notes.append(
            "Earnings-based multiples are suppressed: the reported profit contains a "
            "large exceptional item, so P/E and earnings yield would be misleading."
        )
    v.pb = v.pb if (v.pb is not None and v.pb > 0) else None
    v.ev_ebitda = v.ev_ebitda if (v.ev_ebitda is not None and v.ev_ebitda > 0) else None
    v.ps = v.ps if (v.ps is not None and v.ps > 0) else None

    if v.pe:
        v.earnings_yield = 100 / v.pe

    # Dividend rate (₹/share) is unambiguous; the yield field's units drift
    # between yfinance versions, so only use it as a fallback.
    div_rate = info.get("dividendRate")
    if div_rate and price:
        v.dividend_yield = float(div_rate) / price * 100
    elif info.get("dividendYield") is not None:
        raw = float(info["dividendYield"])
        v.dividend_yield = raw if raw > 1 else raw * 100

    # PEG needs a forward-ish growth rate; prefer multi-year profit CAGR and
    # fall back to the provider's single-year earnings growth.
    growth_for_peg = cagr(f.profit_series)
    if growth_for_peg is None and info.get("earningsGrowth") is not None:
        growth_for_peg = float(info["earningsGrowth"]) * 100
    if v.pe and growth_for_peg and growth_for_peg > 0:
        v.peg = v.pe / growth_for_peg

    if bundle.analysts.target_mean and price:
        v.analyst_upside_pct = (bundle.analysts.target_mean / price - 1) * 100

    _dcf(v, bundle, f, beta, cfg)

    # --- metrics -------------------------------------------------------------
    p.metrics.append(Metric(
        "pe", "P/E (trailing)", v.pe, "x",
        band(v.pe, [(5, 92), (12, 80), (20, 62), (30, 42), (45, 22), (70, 6)]),
        _pe_note(v.pe, v.pe_median_5y), weight=VALUATION["pe"], higher_is_better=False,
        peer=v.pe_median_5y,
    ))
    if v.pe and v.pe_median_5y:
        rel = (v.pe / v.pe_median_5y - 1) * 100
        p.metrics.append(Metric(
            "pe_vs_history", "P/E vs Own 5Y Median", rel, "%",
            band(rel, [(-45, 94), (-20, 80), (0, 60), (20, 38), (50, 16), (100, 4)]),
            (f"Trading {abs(rel):.0f}% {'below' if rel < 0 else 'above'} its own "
             f"5-year median P/E of {v.pe_median_5y:.1f}x."),
            weight=VALUATION["pe_vs_history"], higher_is_better=False,
        ))
    p.metrics.append(Metric(
        "pb", "Price / Book", v.pb, "x",
        band(v.pb, [(0.6, 92), (1.5, 76), (3, 56), (6, 34), (10, 14), (18, 4)]),
        "", weight=VALUATION["pb"], higher_is_better=False,
    ))
    p.metrics.append(Metric(
        "ev_ebitda", "EV / EBITDA", v.ev_ebitda, "x",
        band(v.ev_ebitda, [(4, 92), (8, 76), (13, 56), (20, 32), (30, 12)]),
        "", weight=VALUATION["ev_ebitda"], higher_is_better=False,
    ))
    p.metrics.append(Metric(
        "peg", "PEG Ratio", v.peg, "x",
        band(v.peg, [(0.4, 94), (1.0, 74), (1.5, 54), (2.5, 30), (4, 10)]),
        ("Growth is cheap relative to the multiple." if (v.peg or 9) < 1
         else "Paying up for growth." if (v.peg or 0) > 2 else ""),
        weight=VALUATION["peg"], higher_is_better=False,
    ))
    if v.earnings_yield is not None and v.bond_yield:
        spread = v.earnings_yield - v.bond_yield
        p.metrics.append(Metric(
            "earnings_yield_spread", "Earnings Yield − 10Y G-Sec", spread, "%",
            band(spread, [(-6, 8), (-3, 28), (0, 50), (3, 74), (7, 92)]),
            (f"Earnings yield {v.earnings_yield:.1f}% vs {v.bond_yield:.1f}% on the 10-year "
             f"— {'equity is being paid for the risk' if spread > 0 else 'the bond pays more than the earnings'}."),
            weight=VALUATION["earnings_yield_spread"],
        ))
    p.metrics.append(Metric(
        "dividend_yield", "Dividend Yield", v.dividend_yield, "%",
        band(v.dividend_yield, [(0, 40), (0.5, 50), (1.5, 65), (3, 80), (6, 85)]),
        "", weight=VALUATION["dividend_yield"],
    ))
    if v.dcf_upside_pct is not None:
        p.metrics.append(Metric(
            "dcf_upside", "DCF Upside", v.dcf_upside_pct, "%",
            band(v.dcf_upside_pct, [(-50, 5), (-20, 25), (0, 50), (25, 76), (60, 92)]),
            (f"Two-stage DCF fair value ≈ ₹{v.dcf_value:,.0f} vs ₹{price:,.0f} spot."
             if v.dcf_value else ""),
            weight=VALUATION["dcf_upside"],
        ))
    if v.analyst_upside_pct is not None:
        p.notes.append(
            f"Street target ₹{bundle.analysts.target_mean:,.0f} "
            f"({v.analyst_upside_pct:+.1f}%) across {bundle.analysts.analyst_count or '?'} analysts."
        )
    return v, p


def _dcf(v: ValuationFacts, bundle: StockBundle, f: FundamentalFacts,
         beta: float | None, cfg: dict[str, Any]) -> None:
    """Two-stage FCF DCF. Deliberately conservative and fully transparent.

    Skipped entirely when free cash flow is negative - a DCF on a cash-burning
    company produces a confident-looking number with no information in it.
    """
    shares = bundle.quote.shares_outstanding or latest(
        pick_row(bundle.statements.balance_annual, "Ordinary Shares Number", "Share Issued")
    )
    base_fcf = f.fcf
    if not base_fcf or base_fcf <= 0 or not shares:
        v.dcf_assumptions = {"skipped": "Free cash flow is negative or unavailable."}
        return

    b = min(max(beta or 1.0, 0.7), 1.6)
    discount = max(cfg["risk_free_rate"] + b * cfg["equity_risk_premium"], 0.10)

    hist_growth = cagr(f.revenue_series)
    g1 = min(max((hist_growth or 8.0) / 100, 0.02), 0.15)   # stage 1, capped at 15%
    g_term = 0.05                                            # long-run nominal India

    pv, fcf = 0.0, base_fcf
    for year in range(1, 6):
        # Fade stage-1 growth linearly toward terminal so there is no cliff.
        g = g1 + (g_term - g1) * (year - 1) / 5
        fcf *= (1 + g)
        pv += fcf / ((1 + discount) ** year)

    terminal = fcf * (1 + g_term) / (discount - g_term)
    pv += terminal / ((1 + discount) ** 5)

    net_debt = ((f.total_debt or 0) - (f.cash or 0))
    equity_value = pv - net_debt
    if equity_value <= 0:
        v.dcf_assumptions = {"skipped": "Debt exceeds discounted cash flows."}
        return

    v.dcf_value = equity_value / shares
    if bundle.quote.price:
        v.dcf_upside_pct = (v.dcf_value / bundle.quote.price - 1) * 100
    v.dcf_assumptions = {
        "base_fcf_cr": round(base_fcf / 1e7),
        "stage1_growth_pct": round(g1 * 100, 1),
        "terminal_growth_pct": round(g_term * 100, 1),
        "discount_rate_pct": round(discount * 100, 1),
        "beta_used": round(b, 2),
        "horizon_years": 5,
    }


def _pe_note(pe: float | None, med: float | None) -> str:
    if pe is None:
        return "No meaningful P/E — the company is loss-making or EPS is unavailable."
    if med:
        rel = pe / med - 1
        if rel < -0.2:
            return f"{pe:.1f}x against a 5-year median of {med:.1f}x — cheap versus its own history."
        if rel > 0.25:
            return f"{pe:.1f}x against a 5-year median of {med:.1f}x — richly valued versus its own history."
        return f"{pe:.1f}x, in line with its 5-year median of {med:.1f}x."
    return f"Trading at {pe:.1f}x trailing earnings."
