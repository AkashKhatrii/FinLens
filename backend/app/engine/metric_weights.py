"""Within-pillar metric weights.

Horizon mix (swing / long) and verdict bands live in scoring.py and
are not changed here. These numbers only decide how much each *displayed*
metric moves its pillar.

Families that measure the same underlying thing share a budget: the
distinctive member keeps full weight; correlated companions are down-weighted
so they cannot outvote it. Metrics stay on the report; they just vote less.
"""

GROWTH = {
    "rev_yoy": 0.7,
    "rev_cagr": 1.5,
    "pat_yoy": 0.8,
    "pat_cagr": 1.6,
    "q_rev_yoy": 0.7,
    "q_pat_yoy": 0.7,
}

PROFIT = {
    "op_margin": 1.3,
    "net_margin": 0.6,
    "margin_trend": 1.1,
    "roe": 1.1,
    "roce": 1.8,
}

HEALTH = {
    "debt_equity": 1.6,
    "net_debt_ebitda": 1.0,
    "interest_cover": 1.3,
    "current_ratio": 0.9,
    "ocf_to_pat": 1.7,
    "fcf_margin": 0.8,
}

VALUATION = {
    "pe": 1.5,
    "pe_vs_history": 1.8,
    "pb": 1.0,
    "ev_ebitda": 1.2,
    "peg": 0.6,
    "earnings_yield_spread": 0.6,
    "dividend_yield": 0.6,
    "dcf_upside": 1.4,
}

TECH_SHORT = {
    "rsi14": 1.4,
    "pct_b": 0.5,
    "vs_sma20": 0.7,
    "ret_1w": 0.5,
    "volume_ratio": 0.9,
}

TECH_TREND = {
    "vs_sma200": 1.6,
    "vs_sma50": 0.7,
    "adx14": 1.0,
    "rs_3m": 1.5,
    "rs_1y": 0.7,
    "week52_position": 0.5,
}

RISK = {
    "beta": 0.6,
    "volatility": 1.2,
    "max_drawdown": 0.8,
    "liquidity": 1.1,
}

EARNINGS = {
    "beat_rate": 1.4,
    "avg_surprise": 0.8,
}

SENTIMENT = {
    "analyst_rating": 1.0,
    "analyst_upside": 0.8,
    "promoter_holding": 1.1,
    "institutional_holding": 0.8,
}
