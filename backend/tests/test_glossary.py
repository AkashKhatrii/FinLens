"""Glossary keys should resolve for every scored metric and the UI labels."""
from pathlib import Path

GLOSSARY_JS = Path(__file__).resolve().parents[1] / "app" / "static" / "glossary.js"

METRIC_KEYS = [
    "rev_yoy", "rev_cagr", "pat_yoy", "pat_cagr", "q_rev_yoy", "q_pat_yoy",
    "op_margin", "net_margin", "margin_trend", "roe", "roce",
    "debt_equity", "net_debt_ebitda", "interest_cover", "current_ratio",
    "ocf_to_pat", "fcf_margin",
    "pe", "pe_vs_history", "pb", "ev_ebitda", "peg", "earnings_yield_spread",
    "dividend_yield", "dcf_upside",
    "rsi14", "pct_b", "vs_sma20", "ret_1w", "ret_1m", "volume_ratio",
    "vs_sma200", "vs_sma50", "adx14", "rs_3m", "rs_1y", "week52_position",
    "beta", "volatility", "max_drawdown", "liquidity",
    "beat_rate", "avg_surprise",
    "analyst_rating", "analyst_upside", "promoter_holding", "institutional_holding",
    "loan_growth", "deposit_growth", "nii_growth", "casa_trend", "casa",
    "nim", "roa", "cost_income",
    "gnpa", "nnpa", "pcr", "credit_cost", "slippages",
    "restructured_loans", "sma_or_stressed_assets", "cet1", "car",
    "writeoffs", "recoveries",
]

UI_LABELS = [
    "overall", "short", "swing", "long", "confidence",
    "growth", "profitability", "health", "valuation",
    "technical_short", "technical_trend", "earnings", "sentiment", "risk",
    "stop", "target", "R:R", "Technical Stop", "Technical Target", "Risk/Reward",
    "DCF", "50-DMA", "200-DMA",
    "1M", "1Y", "P/E", "5Y median P/E", "P/B", "EV/EBITDA", "PEG",
    "Div yield", "DCF value", "Beta", "Volatility", "Max drawdown",
    "Turnover/day", "Strong Buy", "Buy", "Hold", "Reduce", "Avoid",
    "Investment View", "Opportunity", "Established Opportunity", "Emerging Opportunity",
    "Watch", "No Opportunity",
    "Accumulation", "Accumulate", "Accumulate Gradually", "Watch for Accumulation",
    "Do Not Accumulate",
    "regime", "entryquality",
    "mcap", "52W high", "Score", "Metric",
]


def _load_glossary():
    src = GLOSSARY_JS.read_text()
    ns: dict = {}
    exec(  # the file is JS; parse keys the same way the UI does
        "def norm(s):\n"
        "    import re\n"
        "    return re.sub(r'[^a-z0-9]+', '', str(s or '').lower())\n",
        ns,
    )
    glossary = {}
    for line in src.splitlines():
        line = line.strip()
        if not line.startswith("put(["):
            continue
        # put(["a", "b"], "Title",
        inner = line[len("put([") :]
        keys_part, _, _ = inner.partition("],")
        keys = [k.strip().strip('"').strip("'") for k in keys_part.split(",") if k.strip()]
        entry = object()
        for k in keys:
            glossary[ns["norm"](k)] = entry
    return glossary, ns["norm"]


def test_glossary_covers_metrics_and_ui_labels():
    glossary, norm = _load_glossary()
    missing = [k for k in METRIC_KEYS + UI_LABELS if glossary.get(norm(k)) is None]
    assert missing == [], f"glossary missing keys: {missing}"
