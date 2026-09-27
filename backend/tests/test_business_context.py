"""Tests for the business-context engine, the new provider fetches, the
enriched AI fact pack, and the market-specific prompt swap."""
from __future__ import annotations

import pandas as pd

from app.engine import business_context as bc
from app.providers.base import Ownership, Quote, Statements, StockBundle


def _annual(rows: dict[str, list]) -> pd.DataFrame:
    cols = pd.to_datetime(
        ["2026-03-31", "2025-03-31", "2024-03-31", "2023-03-31", "2022-03-31"]
    )
    return pd.DataFrame({label: vals for label, vals in rows.items()}, index=cols).T


def _quarterly(rows: dict[str, list]) -> pd.DataFrame:
    cols = pd.to_datetime([
        "2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30",
        "2025-06-30", "2025-03-31", "2024-12-31", "2024-09-30",
    ])
    return pd.DataFrame({label: vals for label, vals in rows.items()}, index=cols).T


def _bundle(**over) -> StockBundle:
    income = _annual({
        "Total Revenue": [1000.0, 900.0, 800.0, 700.0, 600.0],
        "Net Income": [100.0, 90.0, 80.0, 70.0, 60.0],
        "EBIT": [150.0, 140.0, 130.0, 120.0, 110.0],
        "Interest Expense": [10.0, 10.0, 10.0, 10.0, 10.0],
        "Basic EPS": [10.0, 9.0, 8.0, 7.0, 6.0],
    })
    balance = _annual({
        "Accounts Receivable": [120.0, 100.0, 90.0, 80.0, 70.0],
        "Ordinary Shares Number": [95.0, 100.0, 100.0, 105.0, 110.0],
    })
    cashflow = _annual({
        "Operating Cash Flow": [130.0, 120.0, 110.0, 100.0, 90.0],
        "Free Cash Flow": [90.0, 85.0, 80.0, 75.0, 70.0],
        "Stock Based Compensation": [20.0, 18.0, 15.0, 12.0, 10.0],
    })
    q_income = _quarterly({
        "Total Revenue": [280.0, 260.0, 250.0, 240.0, 230.0, 220.0, 210.0, 200.0],
        "Net Income": [30.0, 28.0, 26.0, 25.0, 24.0, 23.0, 22.0, 21.0],
    })
    st = Statements(
        income_annual=income, balance_annual=balance, cashflow_annual=cashflow,
        income_quarterly=q_income,
    )
    quote = Quote(
        symbol="TEST", name="Test Co", sector="Technology",
        industry="Software", market_cap=10_000.0, shares_outstanding=95.0,
    )
    return StockBundle(
        market="IN", quote=quote, statements=st,
        dividend_annual=[
            {"year": y, "amount": a}
            for y, a in zip(
                range(2017, 2027),
                [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 2.0],
            )
        ],
        dividend_ttm=2.0,
        info={"forwardEps": 12.0, "forwardPE": 20.0},
        **over,
    )


def test_quarterly_momentum_yoy_by_date():
    ctx = bc.analyse(_bundle())
    assert len(ctx.quarterly) == 4
    # 2026-06-30 revenue 280 vs 2025-06-30 revenue 230 -> +21.7%
    assert ctx.quarterly[0]["period"] == "2026-06-30"
    assert ctx.quarterly[0]["revenue_yoy_pct"] == round((280 / 230 - 1) * 100, 1)
    # margin = 30/280
    assert ctx.quarterly[0]["margin_pct"] == round(30 / 280 * 100, 1)


def test_growth_accelerating_flag():
    ctx = bc.analyse(_bundle())
    # YoYs: +21.7, +18.2, +19.0, +20.0 -> last-two avg (19.95) < prior-two (19.5)? No:
    # last two: 21.7, 18.2 -> 19.95; prior two: 19.0, 20.0 -> 19.5 -> accelerating
    assert ctx.growth_accelerating is True


def test_buyback_yields_from_shrinking_share_count():
    ctx = bc.analyse(_bundle())
    # 100 -> 95 shares = 5% shrinkage over 1y
    assert ctx.buyback_yield_1y_pct == 5.0
    # 110 -> 95 over 3y annualised: (1 - (95/105)**(1/3)) * 100
    # (series_values takes 4 points, so the 3y base is the 4th value, 105)
    assert ctx.buyback_yield_3y_pct == round((1 - (95 / 105) ** (1 / 3)) * 100, 2)
    assert len(ctx.shares_trend) == 4


def test_interest_coverage_and_receivables():
    ctx = bc.analyse(_bundle())
    assert ctx.interest_coverage == 15.0  # 150 / 10
    assert ctx.receivables_days == round(120 / 1000 * 365, 1)
    assert ctx.receivables_days_trend[0] == round(120 / 1000 * 365, 1)


def test_sbc_ratios():
    ctx = bc.analyse(_bundle())
    assert ctx.sbc == 20.0
    assert ctx.sbc_to_revenue_pct == 2.0
    assert ctx.sbc_to_ocf_pct == round(20 / 130 * 100, 1)


def test_ocf_to_net_income():
    ctx = bc.analyse(_bundle())
    assert ctx.ocf_to_net_income == 1.3  # 130 / 100


def test_dividend_record_no_cuts():
    ctx = bc.analyse(_bundle())
    assert ctx.dividend_cuts_10y == 0
    assert ctx.dividend_cagr_5y_pct is not None
    # latest dps 2.0 * 95 shares / 10000 mcap = 1.9% yield; + 5% buyback
    assert ctx.shareholder_yield_pct == round(2.0 * 95 / 10_000 * 100 + 5.0, 2)
    # payout on FCF: 2.0*95 / 90
    assert ctx.dividend_payout_on_fcf_pct == round(2.0 * 95 / 90 * 100, 1)


def test_dividend_cut_detected():
    b = _bundle()
    b.dividend_annual = [
        {"year": 2023, "amount": 2.0},
        {"year": 2024, "amount": 1.5},
        {"year": 2025, "amount": 1.5},
    ]
    ctx = bc.analyse(b)
    assert ctx.dividend_cuts_10y == 1


def test_partial_current_year_is_not_a_cut():
    # 2026 is the current (incomplete) year: its partial sum must not read
    # as a dividend cut against the last full year.
    from datetime import date
    cy = date.today().year
    b = _bundle()
    b.dividend_annual = [
        {"year": cy - 2, "amount": 1.5},
        {"year": cy - 1, "amount": 1.8},
        {"year": cy, "amount": 0.9},
    ]
    b.dividend_ttm = 1.8
    ctx = bc.analyse(b)
    assert ctx.dividend_cuts_10y == 0


def test_bank_skips_industrial_metrics():
    b = _bundle()
    b.quote.sector = "Financial Services"
    b.quote.industry = "Banks - Diversified"
    ctx = bc.analyse(b)
    assert ctx.interest_coverage is None
    assert ctx.receivables_days is None
    # SBC still applies to banks
    assert ctx.sbc == 20.0


def test_insider_direction():
    b = _bundle(insider_summary={
        "buys_6m": 3, "buy_shares_6m": 10000,
        "sells_6m": 1, "sell_shares_6m": 1000, "recent": [],
    })
    ctx = bc.analyse(b)
    assert ctx.insider["net_direction"] == "net buying"
    b2 = _bundle(insider_summary={
        "buys_6m": 0, "buy_shares_6m": 0,
        "sells_6m": 2, "sell_shares_6m": 5000, "recent": [],
    })
    assert bc.analyse(b2).insider["net_direction"] == "net selling"


def test_forward_eps_growth():
    ctx = bc.analyse(_bundle())
    assert ctx.forward_eps == 12.0
    assert ctx.forward_pe == 20.0
    assert ctx.forward_eps_growth_vs_ttm_pct == 20.0  # 12 vs 10


def test_short_interest_passthrough():
    b = _bundle(short_interest={"pct_float": 8.5, "days_to_cover": 3.2})
    ctx = bc.analyse(b)
    assert ctx.short_interest == {"pct_float": 8.5, "days_to_cover": 3.2}


def test_empty_statements_degrade_gracefully():
    b = _bundle()
    b.statements = Statements()
    ctx = bc.analyse(b)
    assert ctx.quarterly == []
    assert ctx.growth_accelerating is None
    assert ctx.buyback_yield_1y_pct is None
    assert ctx.interest_coverage is None


# --- provider fetches --------------------------------------------------------


def _fake_ticker(**attrs):
    return type("FakeTicker", (), attrs)()


def test_provider_insider_summary_parses():
    from app.providers.yf_provider import YFinanceProvider
    p = YFinanceProvider.__new__(YFinanceProvider)
    df = pd.DataFrame({
        "Transaction Date": ["2026-08-01", "2026-07-01", "2026-06-01"],
        "Transaction Text": ["Purchase", "Sale", "Purchase"],
        "Shares": [1000, 400, 500],
    })
    out = p._fetch_insider_summary(_fake_ticker(insider_transactions=df), [])
    assert out["buys_6m"] == 2
    assert out["buy_shares_6m"] == 1500
    assert out["sells_6m"] == 1
    assert out["sell_shares_6m"] == 400
    assert len(out["recent"]) == 3


def test_provider_insider_summary_unrecognised_shape_is_gap():
    from app.providers.yf_provider import YFinanceProvider
    p = YFinanceProvider.__new__(YFinanceProvider)
    gaps: list[str] = []
    out = p._fetch_insider_summary(
        _fake_ticker(insider_transactions=pd.DataFrame({"a": [1]})), gaps)
    assert out == {}
    assert "insider transactions" in gaps


def test_provider_dividends_annual_and_ttm():
    from app.providers.yf_provider import YFinanceProvider
    p = YFinanceProvider.__new__(YFinanceProvider)
    idx = pd.to_datetime(["2026-03-15", "2025-03-15", "2025-09-15", "2024-03-15"])
    div = pd.Series([1.0, 0.5, 0.5, 1.0], index=idx)
    annual, ttm = p._fetch_dividends(_fake_ticker(dividends=div), [])
    assert annual == [
        {"year": 2024, "amount": 1.0},
        {"year": 2025, "amount": 1.0},
        {"year": 2026, "amount": 1.0},
    ]
    # TTM = payments in the last 365 days from "now" (2026-09-26):
    # cutoff is 2025-09-26, so only the 2026-03-15 payment (1.0) counts;
    # the 2025-09-15 payment falls 11 days outside the window.
    assert ttm == 1.0


def test_provider_dividends_handles_tz_aware_index():
    # Yahoo returns a tz-aware index; the TTM cutoff is tz-naive.
    # Comparing the two raised TypeError and silently dropped all dividends
    # (regression caught 2026-09-27 on live AAPL data).
    from app.providers.yf_provider import YFinanceProvider
    p = YFinanceProvider.__new__(YFinanceProvider)
    idx = pd.to_datetime(["2026-03-15", "2025-09-15"]).tz_localize("America/New_York")
    div = pd.Series([1.0, 0.5], index=idx)
    annual, ttm = p._fetch_dividends(_fake_ticker(dividends=div), [])
    assert len(annual) == 2
    assert ttm == 1.0


def test_provider_short_interest():
    from app.providers.yf_provider import YFinanceProvider
    p = YFinanceProvider.__new__(YFinanceProvider)
    out = p._fetch_short_interest({"shortPercentOfFloat": 0.085, "shortRatio": 3.24})
    assert out == {"pct_float": 8.5, "days_to_cover": 3.2}
    assert p._fetch_short_interest({}) == {}


# --- fact pack wiring --------------------------------------------------------


def _fake_result() -> dict:
    return {
        "as_of": {"analysis_date": "2026-09-27", "price_date": "2026-09-26",
                  "fiscal_year": "2026-03-31"},
        "company": {"name": "X", "summary": "s"},
        "price": {"last": 100.0},
        "overall": {}, "horizons": {}, "pillars": {},
        "fundamentals": {"revenue_cr": 100.0},
        "valuation": {"pe_ratio": 20.0},
        "technicals": {"rsi": 55.0},
        "risk": {}, "earnings": {
            "beat_rate": 75.0,
            "surprises": [
                {"date": "2026-06-30", "estimate": 10.0, "reported": 11.0,
                 "surprise_pct": 10.0},
            ] * 8,
        },
        "ownership": {}, "analysts": {}, "data_gaps": [],
        "news": [
            {"title": "X launches Y", "publisher": "Reuters",
             "published": "2026-09-20", "summary": "s" * 300},
        ],
        "business_context": {"buyback_yield_1y_pct": 5.0},
    }


def test_fact_pack_carries_new_sections():
    from app.analysis import _fact_pack
    pack = _fact_pack(_fake_result())
    assert pack["as_of"]["analysis_date"] == "2026-09-27"
    assert pack["business_context"] == {"buyback_yield_1y_pct": 5.0}
    assert pack["news"][0]["title"] == "X launches Y"
    assert len(pack["news"][0]["summary"]) <= 200
    # surprise detail kept, capped at 6
    assert len(pack["earnings"]["recent_surprises"]) == 6
    assert "surprises" not in pack["earnings"]


def test_fact_pack_tolerates_missing_new_sections():
    from app.analysis import _fact_pack
    r = _fake_result()
    del r["news"]
    del r["business_context"]
    del r["as_of"]
    r["earnings"] = None
    pack = _fact_pack(r)
    assert pack["news"] == []
    assert pack["business_context"] == {}
    assert pack["as_of"] == {}
    assert pack["earnings"] == {}


def test_debate_pack_inherits_new_sections():
    from app.analysis import _debate_fact_pack
    pack = _debate_fact_pack(_fake_result())
    assert pack["business_context"] == {"buyback_yield_1y_pct": 5.0}
    assert pack["news"][0]["title"] == "X launches Y"


# --- prompt market swap ------------------------------------------------------


def test_prompt_market_swap():
    from app.ai.prompts import _INDIA_SECTION, SYSTEM_PROMPT, build_system_prompt
    # The constant must appear verbatim in SYSTEM_PROMPT or the US swap
    # silently keeps the India section (regression caught 2026-09-27).
    assert _INDIA_SECTION in SYSTEM_PROMPT
    us = build_system_prompt("US")
    assert "US-specific judgement" in us
    assert "India-specific judgement" not in us
    assert "buyback_yield_1y_pct" in us
    inn = build_system_prompt("IN")
    assert "India-specific judgement" in inn
    assert "US-specific judgement" not in inn
    assert "Dividend cuts matter" in inn
