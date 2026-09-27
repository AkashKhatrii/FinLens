"""Business-context engine: statement-derived facts a human analyst would always
check before writing a thesis, but which the quant pillars don't cover.

Everything is computed from the raw statements (never from `.info`
convenience fields, which are unreliable for NSE names) or passed through
from provider fetches. Banks skip industrial metrics (interest coverage,
receivables days) - the bank-metrics path owns those.

Design rules:
- Every field is Optional-friendly: None means "unknown", never zero.
- YoY quarter matching is by date (within ~6 weeks), never by position:
  yfinance quarterly columns have gaps, so columns[4] is regularly not
  "four quarters ago".
- Nothing here scores anything. It is evidence for the LLM thesis, which
  interprets it under the market-specific prompt sections.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..providers.base import Statements, StockBundle, latest, pick_row, series_values
from .common import cagr, safe_div
from .sector import PROFILE_BANK, classify


@dataclass
class BusinessContext:
    """Plain numbers for the AI fact pack. See module docstring."""

    # Last 4 reported quarters, newest first:
    # [{"period": "2026-06-30", "revenue_yoy_pct": x, "margin_pct": y}]
    quarterly: list[dict[str, Any]] = field(default_factory=list)
    # True when the average revenue YoY of the last 2 quarters exceeds the
    # average of the 2 before them; None when fewer than 4 quarters available.
    growth_accelerating: bool | None = None

    # Share-count shrinkage = buybacks net of issuance, in percent.
    buyback_yield_1y_pct: float | None = None
    buyback_yield_3y_pct: float | None = None  # annualised
    shares_trend: list[dict[str, Any]] = field(default_factory=list)

    # Stock-based compensation, latest annual.
    sbc: float | None = None
    sbc_to_revenue_pct: float | None = None
    sbc_to_ocf_pct: float | None = None

    # Balance-sheet stress (non-banks only).
    interest_coverage: float | None = None
    receivables_days: float | None = None
    receivables_days_trend: list[float | None] = field(default_factory=list)
    # Operating cash flow / net income: sustained < 0.8 is an accruals flag.
    ocf_to_net_income: float | None = None

    # Dividend record, from the provider's per-share history.
    dividend_annual: list[dict[str, Any]] = field(default_factory=list)
    dividend_ttm_per_share: float | None = None
    dividend_cuts_10y: int | None = None
    dividend_cagr_5y_pct: float | None = None
    dividend_payout_on_fcf_pct: float | None = None
    # Trailing dividend yield + 1y net buyback yield.
    shareholder_yield_pct: float | None = None

    # Market signals, passed through from provider fetches.
    insider: dict[str, Any] = field(default_factory=dict)
    short_interest: dict[str, Any] = field(default_factory=dict)
    promoter_trend: list[dict[str, Any]] = field(default_factory=list)
    forward_eps: float | None = None
    forward_pe: float | None = None
    forward_eps_growth_vs_ttm_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _dated_values(row: pd.Series | None) -> list[tuple[pd.Timestamp, float]]:
    """(date, value) pairs, newest first, for a statement row."""
    if row is None:
        return []
    clean = row.dropna()
    if clean.empty:
        return []
    try:
        dates = pd.to_datetime(pd.Index(clean.index))
    except Exception:
        return []
    vals = []
    for i, d in enumerate(dates):
        try:
            vals.append((d, float(clean.iloc[i])))
        except (TypeError, ValueError):
            continue
    vals.sort(key=lambda t: t[0], reverse=True)
    return vals


def _yoy_for(d: pd.Timestamp, vals: list[tuple[pd.Timestamp, float]]) -> float | None:
    """Year-on-year change for the quarter ending at d, matched by date."""
    cur = next((v for dt, v in vals if dt == d), None)
    if cur is None:
        return None
    target = d - pd.Timedelta(days=365)
    best_v, best_gap = None, pd.Timedelta(days=45)
    for dt, v in vals:
        gap = abs(dt - target)
        if gap <= best_gap:
            best_v, best_gap = v, gap
    if best_v is None or best_v == 0:
        return None
    return (cur / best_v - 1) * 100


def _quarterly_momentum(st: Statements) -> tuple[list[dict[str, Any]], bool | None]:
    rev_row = pick_row(st.income_quarterly, "Total Revenue", "Operating Revenue")
    ni_row = pick_row(
        st.income_quarterly, "Net Income Common Stockholders", "Net Income",
        "Net Income Continuous Operations",
    )
    rev = _dated_values(rev_row)
    ni = {d: v for d, v in _dated_values(ni_row)}
    out: list[dict[str, Any]] = []
    for d, r in rev[:4]:
        yoy = _yoy_for(d, rev)
        # Match net income to the same quarter by date, not position.
        ni_v, best_gap = None, pd.Timedelta(days=45)
        for nd, nv in ni.items():
            gap = abs(nd - d)
            if gap <= best_gap:
                ni_v, best_gap = nv, gap
        margin = (ni_v / r * 100) if (ni_v is not None and r) else None
        out.append({
            "period": d.strftime("%Y-%m-%d"),
            "revenue_yoy_pct": round(yoy, 1) if yoy is not None else None,
            "margin_pct": round(margin, 1) if margin is not None else None,
        })
    accelerating: bool | None = None
    yoys = [q["revenue_yoy_pct"] for q in out if q["revenue_yoy_pct"] is not None]
    if len(yoys) >= 4:
        accelerating = sum(yoys[:2]) / 2 > sum(yoys[2:4]) / 2
    return out, accelerating


def _buyback_yields(st: Statements) -> tuple[float | None, float | None, list[dict]]:
    shares_row = pick_row(
        st.balance_annual, "Ordinary Shares Number", "Share Issued",
        "Total Common Shares Outstanding",
    )
    vals = series_values(shares_row, 4)
    trend: list[dict[str, Any]] = []
    cols = list(shares_row.dropna().index[:5]) if shares_row is not None else []
    for i, v in enumerate(vals[:5]):
        period = str(cols[i])[:10] if i < len(cols) else None
        trend.append({"period": period, "shares": v})
    y1 = y3 = None
    if len(vals) >= 2 and vals[1]:
        y1 = (vals[1] - vals[0]) / vals[1] * 100
    if len(vals) >= 4 and vals[3] and vals[0] > 0:
        # Annualised shrinkage over 3 years; positive = net buybacks.
        y3 = (1 - (vals[0] / vals[3]) ** (1 / 3)) * 100
    return (
        round(y1, 2) if y1 is not None else None,
        round(y3, 2) if y3 is not None else None,
        trend,
    )


def _receivables(st: Statements) -> tuple[float | None, list[float | None]]:
    rec_row = pick_row(
        st.balance_annual, "Accounts Receivable", "Receivable",
        "Net Receivables",
    )
    rev_row = pick_row(st.income_annual, "Total Revenue", "Operating Revenue")
    rec = series_values(rec_row, 5)
    rev = series_values(rev_row, 5)
    days = safe_div(rec[0], rev[0]) * 365 if rec and rev else None
    trend = [
        round(safe_div(r, rv) * 365, 1) if (r is not None and rv) else None
        for r, rv in zip(rec, rev)
    ]
    return (round(days, 1) if days is not None else None, trend)


def _dividend_record(
    dividend_annual: list[dict[str, Any]],
    dividend_ttm: float | None,
    fcf: float | None,
    shares_outstanding: float | None,
    market_cap: float | None,
) -> dict[str, Any]:
    from datetime import date

    current_year = date.today().year
    # The latest calendar year is usually still in progress: its partial sum
    # looks like a "cut" against the prior full year. Only complete years
    # count for cuts, raises, and CAGR.
    complete = [d for d in (dividend_annual or []) if d.get("year", 0) < current_year]
    amts = [d["amount"] for d in complete if d.get("amount")]
    cuts = raises = None
    cagr_5y = None
    if len(amts) >= 2:
        cuts = sum(1 for a, b in zip(amts[:-1], amts[1:]) if b < a and a > 0)
        raises = sum(1 for a, b in zip(amts[:-1], amts[1:]) if b > a)
    if len(amts) >= 6 and amts[-6] and amts[-6] > 0:
        try:
            # cagr() wants a most-recent-first series; amts is oldest-first.
            # It already returns a percent.
            cagr_5y = round(cagr(list(reversed(amts[-6:])), 5), 1)
        except Exception:
            cagr_5y = None
    payout = None
    if dividend_ttm and fcf and shares_outstanding:
        payout = safe_div(dividend_ttm * shares_outstanding, fcf) * 100
    return {
        "annual": dividend_annual or [],
        "ttm_per_share": dividend_ttm,
        "cuts_10y": cuts,
        "raises_10y": raises,
        "cagr_5y_pct": cagr_5y,
        "payout_on_fcf_pct": round(payout, 1) if payout is not None else None,
    }


def _insider_direction(summary: dict[str, Any]) -> dict[str, Any]:
    if not summary:
        return {}
    out = dict(summary)
    buys = summary.get("buy_shares_6m") or 0
    sells = summary.get("sell_shares_6m") or 0
    if buys or sells:
        if buys > sells * 2:
            out["net_direction"] = "net buying"
        elif sells > buys * 2:
            out["net_direction"] = "net selling"
        else:
            out["net_direction"] = "mixed"
    return out


def analyse(bundle: StockBundle) -> BusinessContext:
    """Build the business-context evidence block for one company."""
    st = bundle.statements
    info = bundle.info or {}
    ctx = BusinessContext()
    is_bank = classify(bundle.quote.sector, bundle.quote.industry) == PROFILE_BANK

    inc, bal, cf = st.income_annual, st.balance_annual, st.cashflow_annual

    # Quarterly momentum: what the trailing annual numbers hide.
    ctx.quarterly, ctx.growth_accelerating = _quarterly_momentum(st)

    # Capital return: the other half of shareholder yield.
    y1, y3, trend = _buyback_yields(st)
    ctx.buyback_yield_1y_pct = y1
    ctx.buyback_yield_3y_pct = y3
    ctx.shares_trend = trend

    revenue = latest(pick_row(inc, "Total Revenue", "Operating Revenue"))
    ctx.sbc = latest(pick_row(cf, "Stock Based Compensation"))
    if ctx.sbc is not None and revenue:
        ctx.sbc_to_revenue_pct = round(ctx.sbc / revenue * 100, 2)
    ocf = latest(pick_row(cf, "Operating Cash Flow"))
    if ctx.sbc is not None and ocf:
        ctx.sbc_to_ocf_pct = round(ctx.sbc / ocf * 100, 1)

    # Balance-sheet stress (industrial companies only).
    if not is_bank:
        ebit = latest(pick_row(inc, "EBIT", "Operating Income"))
        interest = latest(pick_row(
            inc, "Interest Expense", "Interest Expense Non Operating"))
        if ebit is not None and interest and interest > 0:
            ctx.interest_coverage = round(ebit / interest, 1)
        ctx.receivables_days, ctx.receivables_days_trend = _receivables(st)

    net_income = latest(pick_row(
        inc, "Net Income Common Stockholders", "Net Income",
        "Net Income Continuous Operations"))
    if ocf is not None and net_income:
        ctx.ocf_to_net_income = round(ocf / net_income, 2)

    # Dividend record: governance signal in India, yield component everywhere.
    fcf = latest(pick_row(cf, "Free Cash Flow"))
    div = _dividend_record(
        bundle.dividend_annual, bundle.dividend_ttm, fcf,
        bundle.quote.shares_outstanding, bundle.quote.market_cap)
    ctx.dividend_annual = div["annual"]
    ctx.dividend_ttm_per_share = div["ttm_per_share"]
    ctx.dividend_cuts_10y = div["cuts_10y"]
    ctx.dividend_cagr_5y_pct = div["cagr_5y_pct"]
    ctx.dividend_payout_on_fcf_pct = div["payout_on_fcf_pct"]
    if (div["ttm_per_share"] and bundle.quote.market_cap
            and bundle.quote.shares_outstanding):
        div_yield = (div["ttm_per_share"] * bundle.quote.shares_outstanding
                     / bundle.quote.market_cap * 100)
        sh_yield = div_yield + (ctx.buyback_yield_1y_pct or 0)
        ctx.shareholder_yield_pct = round(sh_yield, 2)

    # Market signals.
    ctx.insider = _insider_direction(bundle.insider_summary)
    ctx.short_interest = dict(bundle.short_interest or {})
    ctx.promoter_trend = list((bundle.ownership.promoter_trend or []))[:8]

    # Forward expectations: the bar the price has to clear.
    eps_ttm = latest(pick_row(inc, "Basic EPS", "Diluted EPS"))
    fwd_eps = info.get("forwardEps")
    try:
        ctx.forward_eps = float(fwd_eps) if fwd_eps is not None else None
    except (TypeError, ValueError):
        ctx.forward_eps = None
    fwd_pe = info.get("forwardPE")
    try:
        ctx.forward_pe = round(float(fwd_pe), 1) if fwd_pe is not None else None
    except (TypeError, ValueError):
        ctx.forward_pe = None
    if ctx.forward_eps is not None and eps_ttm:
        ctx.forward_eps_growth_vs_ttm_pct = round(
            (ctx.forward_eps / eps_ttm - 1) * 100, 1)

    return ctx
