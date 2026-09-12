"""Fundamental engine: growth, profitability, and balance-sheet strength.

Everything is computed from the raw statements rather than read off `.info`,
because for NSE tickers the convenience fields are frequently null or stale
(Reliance returns `returnOnEquity: None` and a beta of 0.15).

Annual figures drive the ratios - they are complete and audited. Quarterly data
is used only for the most recent quarter's YoY comparison, and even then the
prior-year quarter is located *by date*, never by position: yfinance quarterly
columns have gaps, so `columns[4]` is regularly not "four quarters ago".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..providers.base import Statements, StockBundle, latest, pick_row, series_values
from .common import Metric, Pillar, band, cagr, pct_change, safe_div, trend_slope_pct
from .metric_weights import GROWTH, HEALTH, PROFIT
from .sector import PROFILE_BANK, apply_profile, classify

CRORE = 1e7


@dataclass
class FundamentalFacts:
    """Plain numbers, for the UI table and as evidence for the LLM thesis."""

    revenue: float | None = None
    revenue_prev: float | None = None
    net_income: float | None = None
    ebit: float | None = None
    ebitda: float | None = None
    equity: float | None = None
    total_debt: float | None = None
    cash: float | None = None
    ocf: float | None = None
    fcf: float | None = None
    capex: float | None = None
    eps: float | None = None
    book_value_ps: float | None = None
    fiscal_year: str = ""
    # Set when the reported result is dominated by a one-off. Valuation reads
    # this to suppress earnings-based multiples, which would otherwise make a
    # distressed company look cheap on non-recurring profit.
    earnings_exceptional: bool = False
    revenue_series: list[float] = field(default_factory=list)
    profit_series: list[float] = field(default_factory=list)
    margin_series: list[float] = field(default_factory=list)
    years: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        for k in ("revenue", "revenue_prev", "net_income", "ebit", "ebitda",
                  "equity", "total_debt", "cash", "ocf", "fcf", "capex"):
            if d.get(k) is not None:
                d[f"{k}_cr"] = d[k] / CRORE
        return d


def _yoy_quarter(df: pd.DataFrame, *labels: str) -> tuple[float | None, float | None]:
    """(latest quarter, same quarter last year) matched by date, not position."""
    row = pick_row(df, *labels)
    if row is None:
        return None, None
    clean = row.dropna()
    if clean.empty:
        return None, None

    try:
        dates = pd.to_datetime(pd.Index(clean.index))
    except Exception:
        return (float(clean.iloc[0]), None)

    newest = dates.max()
    current = float(clean.iloc[list(dates).index(newest)])

    target = newest - pd.Timedelta(days=365)
    # Accept a match within ~6 weeks of the year-ago date; otherwise report None
    # rather than silently comparing against the wrong quarter.
    best_i, best_gap = None, pd.Timedelta(days=45)
    for i, d in enumerate(dates):
        gap = abs(d - target)
        if gap <= best_gap:
            best_i, best_gap = i, gap
    prior = float(clean.iloc[best_i]) if best_i is not None else None
    return current, prior


def extract(st: Statements) -> FundamentalFacts:
    f = FundamentalFacts()
    inc, bal, cf = st.income_annual, st.balance_annual, st.cashflow_annual

    rev_row = pick_row(inc, "Total Revenue", "Operating Revenue")
    ni_row = pick_row(inc, "Net Income Common Stockholders", "Net Income",
                      "Net Income Continuous Operations")

    f.revenue = latest(rev_row)
    f.revenue_prev = latest(rev_row, 1)
    f.net_income = latest(ni_row)
    f.ebit = latest(pick_row(inc, "EBIT", "Operating Income"))
    f.ebitda = latest(pick_row(inc, "EBITDA", "Normalized EBITDA"))
    f.eps = latest(pick_row(inc, "Basic EPS", "Diluted EPS"))

    f.equity = latest(pick_row(bal, "Stockholders Equity", "Common Stock Equity",
                               "Total Equity Gross Minority Interest"))
    f.total_debt = latest(pick_row(bal, "Total Debt", "Long Term Debt And Capital Lease Obligation"))
    f.cash = latest(pick_row(bal, "Cash And Cash Equivalents",
                             "Cash Cash Equivalents And Short Term Investments"))

    f.ocf = latest(pick_row(cf, "Operating Cash Flow"))
    f.fcf = latest(pick_row(cf, "Free Cash Flow"))
    f.capex = latest(pick_row(cf, "Capital Expenditure"))

    shares = latest(pick_row(bal, "Ordinary Shares Number", "Share Issued"))
    f.book_value_ps = safe_div(f.equity, shares)

    f.revenue_series = series_values(rev_row, 5)
    f.profit_series = series_values(ni_row, 5)
    f.margin_series = [
        (p / r * 100) for p, r in zip(f.profit_series, f.revenue_series) if r
    ]
    if not inc.empty:
        f.years = [str(c)[:10] for c in inc.columns[:5]]
        f.fiscal_year = f.years[0] if f.years else ""
    return f


def analyse(bundle: StockBundle) -> tuple[FundamentalFacts, Pillar, Pillar, Pillar]:
    st = bundle.statements
    f = extract(st)
    info = bundle.info
    profile = classify(bundle.quote.sector, bundle.quote.industry)

    growth = Pillar("growth", "Growth")
    profit = Pillar("profitability", "Profitability & Returns")
    health = Pillar("health", "Balance Sheet & Cash")

    if not st.has_annual:
        for p in (growth, profit, health):
            p.notes.append("Annual financial statements unavailable from the data source.")
        return f, growth, profit, health

    # --- growth --------------------------------------------------------------
    rev_yoy = pct_change(f.revenue, f.revenue_prev)
    growth.metrics.append(Metric(
        "rev_yoy", "Revenue Growth (YoY)", rev_yoy, "%",
        band(rev_yoy, [(-20, 5), (-5, 25), (0, 42), (8, 62), (15, 78), (25, 90), (45, 95)]),
        _growth_note("Revenue", rev_yoy), weight=GROWTH["rev_yoy"],
    ))
    rev_cagr = cagr(f.revenue_series)
    growth.metrics.append(Metric(
        "rev_cagr", f"Revenue CAGR ({max(len(f.revenue_series) - 1, 0)}Y)", rev_cagr, "%",
        band(rev_cagr, [(-10, 8), (0, 30), (6, 52), (12, 72), (20, 88), (35, 95)]),
        "", weight=GROWTH["rev_cagr"],
    ))
    pat_yoy = pct_change(f.net_income, latest(pick_row(st.income_annual,
                        "Net Income Common Stockholders", "Net Income"), 1))
    growth.metrics.append(Metric(
        "pat_yoy", "Net Profit Growth (YoY)", pat_yoy, "%",
        band(pat_yoy, [(-35, 5), (-10, 25), (0, 45), (10, 65), (20, 82), (40, 94)]),
        _growth_note("Net profit", pat_yoy), weight=GROWTH["pat_yoy"],
    ))
    pat_cagr = cagr(f.profit_series)
    growth.metrics.append(Metric(
        "pat_cagr", f"Profit CAGR ({max(len(f.profit_series) - 1, 0)}Y)", pat_cagr, "%",
        band(pat_cagr, [(-10, 8), (0, 30), (8, 55), (15, 75), (25, 90), (40, 96)]),
        "", weight=GROWTH["pat_cagr"],
    ))

    q_rev, q_rev_prev = _yoy_quarter(st.income_quarterly, "Total Revenue", "Operating Revenue")
    q_rev_yoy = pct_change(q_rev, q_rev_prev)
    growth.metrics.append(Metric(
        "q_rev_yoy", "Latest Quarter Revenue (YoY)", q_rev_yoy, "%",
        band(q_rev_yoy, [(-20, 8), (-5, 30), (0, 48), (10, 70), (20, 86), (35, 94)]),
        "Most recent reported quarter vs the same quarter last year.", weight=GROWTH["q_rev_yoy"],
    ))
    q_pat, q_pat_prev = _yoy_quarter(st.income_quarterly, "Net Income Common Stockholders", "Net Income")
    q_pat_yoy = pct_change(q_pat, q_pat_prev)
    growth.metrics.append(Metric(
        "q_pat_yoy", "Latest Quarter Profit (YoY)", q_pat_yoy, "%",
        band(q_pat_yoy, [(-35, 8), (-10, 28), (0, 48), (12, 70), (25, 88), (45, 95)]),
        "", weight=GROWTH["q_pat_yoy"],
    ))
    if f.revenue_series and f.profit_series and rev_cagr is not None and pat_cagr is not None:
        if pat_cagr > rev_cagr + 3:
            growth.notes.append("Profit is compounding faster than revenue — operating leverage is working.")
        elif pat_cagr < rev_cagr - 3:
            growth.notes.append("Profit is growing slower than revenue — margins are being squeezed.")

    # --- profitability -------------------------------------------------------
    op_margin = safe_div(f.ebit, f.revenue)
    op_margin = op_margin * 100 if op_margin is not None else None
    net_margin = safe_div(f.net_income, f.revenue)
    net_margin = net_margin * 100 if net_margin is not None else None

    # An operating margin above 100% cannot come from operations - it means a
    # one-off (asset sale, waiver, write-back) is sitting in the EBIT line.
    # Scoring it as world-class profitability is how a distressed company ends
    # up looking like a compounder.
    exceptional = op_margin is not None and op_margin > 100
    f.earnings_exceptional = exceptional
    if exceptional:
        profit.notes.append(
            f"Operating margin of {op_margin:.0f}% is not attainable from operations — the "
            "result contains a large exceptional item. Profitability metrics are suppressed."
        )
        op_margin = None

    profit.metrics.append(Metric(
        "op_margin", "Operating Margin", op_margin, "%",
        band(op_margin, [(0, 10), (5, 32), (10, 52), (16, 72), (25, 88), (40, 95)]),
        "", weight=PROFIT["op_margin"],
    ))
    if exceptional:
        net_margin = None
    elif (profile != PROFILE_BANK
          and op_margin is not None and net_margin is not None
          and net_margin > op_margin + 5):
        profit.notes.append(
            "Net margin exceeds operating margin — the bottom line is being driven by "
            "non-operating income or a one-off, not by the core business."
        )
    profit.metrics.append(Metric(
        "net_margin", "Net Margin", net_margin, "%",
        band(net_margin, [(0, 10), (3, 30), (7, 50), (12, 70), (20, 87), (30, 95)]),
        "", weight=PROFIT["net_margin"],
    ))
    margin_trend = None if exceptional else trend_slope_pct(f.margin_series)
    profit.metrics.append(Metric(
        "margin_trend", "Margin Trend", margin_trend, "%",
        band(margin_trend, [(-12, 12), (-4, 35), (0, 55), (4, 75), (12, 90)]),
        ("Margins expanding year on year." if (margin_trend or 0) > 1
         else "Margins compressing year on year." if (margin_trend or 0) < -1
         else "Margins broadly stable."),
        weight=PROFIT["margin_trend"],
    ))
    # Negative shareholders' equity makes every equity-denominated ratio
    # invert: D/E goes negative (scoring as "debt-free"), P/B goes negative
    # (scoring as "cheap"), ROE flips sign. None of those are meaningful, so
    # they are suppressed and surfaced as a red flag instead.
    equity_ok = f.equity is not None and f.equity > 0

    roe = safe_div(f.net_income, f.equity) if equity_ok else None
    roe = roe * 100 if roe is not None else (
        info.get("returnOnEquity") * 100
        if (equity_ok and info.get("returnOnEquity")) else None
    )
    profit.metrics.append(Metric(
        "roe", "Return on Equity", roe, "%",
        band(roe, [(0, 8), (8, 30), (13, 52), (18, 74), (25, 90), (40, 97)]),
        _roe_note(roe), weight=PROFIT["roe"],
    ))
    # ROCE is the ratio Indian analysts anchor on: EBIT over capital employed.
    total_assets = latest(pick_row(st.balance_annual, "Total Assets"))
    current_liab = latest(pick_row(st.balance_annual, "Current Liabilities"))
    capital_employed = (total_assets - current_liab) if (total_assets and current_liab) else None
    if capital_employed is not None and capital_employed <= 0:
        capital_employed = None
    roce = None if exceptional else safe_div(f.ebit, capital_employed)
    roce = roce * 100 if roce is not None else None
    profit.metrics.append(Metric(
        "roce", "Return on Capital Employed", roce, "%",
        band(roce, [(0, 8), (8, 30), (13, 52), (18, 75), (25, 90), (40, 97)]),
        ("Earning well above a realistic ~12% cost of capital."
         if (roce or 0) >= 18 else
         "Returns are below what the capital costs — value is being destroyed, not created."
         if (roce is not None and roce < 10) else ""),
        weight=PROFIT["roce"],
    ))

    # --- balance sheet & cash ------------------------------------------------
    de = safe_div(f.total_debt, f.equity) if equity_ok else None
    if de is None and equity_ok and info.get("debtToEquity"):
        de = info["debtToEquity"] / 100
    health.metrics.append(Metric(
        "debt_equity", "Debt / Equity", de, "x",
        band(de, [(0, 98), (0.25, 88), (0.5, 74), (1.0, 52), (1.8, 28), (3.0, 8)]),
        _debt_note(de) if equity_ok else "Net worth is negative — the ratio is not meaningful.",
        weight=HEALTH["debt_equity"], higher_is_better=False,
    ))
    if not equity_ok and f.equity is not None:
        health.notes.append(
            f"Shareholders' equity is negative (₹{f.equity / CRORE:,.0f} Cr). Accumulated losses "
            "exceed capital, so equity-based ratios are suppressed rather than scored."
        )
    net_debt = (f.total_debt - f.cash) if (f.total_debt is not None and f.cash is not None) else None
    nd_ebitda = safe_div(net_debt, f.ebitda)
    health.metrics.append(Metric(
        "net_debt_ebitda", "Net Debt / EBITDA", nd_ebitda, "x",
        band(nd_ebitda, [(-1, 97), (0, 92), (1, 78), (2, 60), (3.5, 32), (5, 8)]),
        ("Net cash on the balance sheet." if (nd_ebitda or 0) < 0
         else "Leverage is high enough to matter in a downturn." if (nd_ebitda or 0) > 3 else ""),
        weight=HEALTH["net_debt_ebitda"], higher_is_better=False,
    ))
    interest = pick_row(st.income_annual, "Interest Expense")
    icr = safe_div(f.ebit, abs(latest(interest)) if latest(interest) else None)
    health.metrics.append(Metric(
        "interest_cover", "Interest Coverage", icr, "x",
        band(icr, [(1, 5), (2.5, 30), (4, 52), (8, 76), (15, 92)]),
        ("Interest is barely covered by operating profit — a genuine solvency risk."
         if (icr is not None and icr < 2.5) else ""),
        weight=HEALTH["interest_cover"],
    ))
    cur_assets = latest(pick_row(st.balance_annual, "Current Assets"))
    current_ratio = safe_div(cur_assets, current_liab)
    health.metrics.append(Metric(
        "current_ratio", "Current Ratio", current_ratio, "x",
        band(current_ratio, [(0.5, 12), (1.0, 42), (1.5, 70), (2.2, 82), (4, 62)]),
        "", weight=HEALTH["current_ratio"],
    ))
    # Earnings quality: profit that never becomes cash is the classic accounting red flag.
    ocf_ni = safe_div(f.ocf, f.net_income)
    health.metrics.append(Metric(
        "ocf_to_pat", "Operating Cash Flow / Profit", ocf_ni, "x",
        band(ocf_ni, [(0, 5), (0.5, 28), (0.8, 58), (1.0, 78), (1.5, 90), (3, 80)]),
        ("Reported profit is converting into real cash."
         if (ocf_ni or 0) >= 0.9 else
         "Profit is not converting into cash — check receivables and revenue recognition."
         if (ocf_ni is not None and ocf_ni < 0.7) else ""),
        weight=HEALTH["ocf_to_pat"],
    ))
    fcf_margin = safe_div(f.fcf, f.revenue)
    fcf_margin = fcf_margin * 100 if fcf_margin is not None else None
    health.metrics.append(Metric(
        "fcf_margin", "Free Cash Flow Margin", fcf_margin, "%",
        band(fcf_margin, [(-10, 8), (0, 35), (4, 58), (10, 78), (18, 92)]),
        ("Burning cash after capex." if (fcf_margin is not None and fcf_margin < 0) else ""),
        weight=HEALTH["fcf_margin"],
    ))
    apply_profile(growth, profile)
    apply_profile(profit, profile)
    apply_profile(health, profile)
    return f, growth, profit, health


def _growth_note(label: str, v: float | None) -> str:
    if v is None:
        return ""
    if v >= 20:
        return f"{label} up {v:.1f}% — well ahead of nominal GDP."
    if v >= 8:
        return f"{label} up {v:.1f}% — steady."
    if v >= 0:
        return f"{label} up only {v:.1f}% — close to flat in real terms."
    return f"{label} down {abs(v):.1f}% — contracting."


def _roe_note(v: float | None) -> str:
    if v is None:
        return ""
    if v >= 20:
        return f"ROE of {v:.1f}% — high-quality compounder territory."
    if v >= 13:
        return f"ROE of {v:.1f}% — respectable."
    return f"ROE of {v:.1f}% — below what an index fund needs to beat."


def _debt_note(v: float | None) -> str:
    if v is None:
        return ""
    if v <= 0.25:
        return "Effectively debt-free."
    if v <= 0.7:
        return f"Comfortable leverage at {v:.2f}x equity."
    if v <= 1.5:
        return f"Meaningful debt at {v:.2f}x equity — watch interest costs."
    return f"Heavily levered at {v:.2f}x equity — a key risk."
