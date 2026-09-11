"""Provider-agnostic data contract.

Every engine downstream consumes a `StockBundle` and nothing else. Swapping
yfinance for a paid feed (EODHD, Kite Connect, FMP) means writing one new
`Provider` and changing a single line in `registry.py` - no engine changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import pandas as pd


@dataclass
class Quote:
    symbol: str
    name: str
    exchange: str = ""
    currency: str = "INR"
    price: float | None = None
    previous_close: float | None = None
    day_change_pct: float | None = None
    market_cap: float | None = None
    sector: str = ""
    industry: str = ""
    business_summary: str = ""
    website: str = ""
    week52_high: float | None = None
    week52_low: float | None = None
    avg_volume: float | None = None
    shares_outstanding: float | None = None
    float_shares: float | None = None

    @property
    def off_52w_high_pct(self) -> float | None:
        if self.price and self.week52_high:
            return (self.price / self.week52_high - 1) * 100
        return None

    @property
    def above_52w_low_pct(self) -> float | None:
        if self.price and self.week52_low:
            return (self.price / self.week52_low - 1) * 100
        return None


@dataclass
class Statements:
    """Raw financial statements. Columns are period-end dates, newest first."""

    income_annual: pd.DataFrame = field(default_factory=pd.DataFrame)
    income_quarterly: pd.DataFrame = field(default_factory=pd.DataFrame)
    balance_annual: pd.DataFrame = field(default_factory=pd.DataFrame)
    balance_quarterly: pd.DataFrame = field(default_factory=pd.DataFrame)
    cashflow_annual: pd.DataFrame = field(default_factory=pd.DataFrame)
    cashflow_quarterly: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def has_annual(self) -> bool:
        return not self.income_annual.empty and not self.balance_annual.empty


@dataclass
class Ownership:
    promoter_or_insider_pct: float | None = None
    institutions_pct: float | None = None
    top_holders: list[dict[str, Any]] = field(default_factory=list)
    # Filled by the India filings provider when available.
    promoter_pledge_pct: float | None = None
    promoter_trend: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AnalystView:
    target_mean: float | None = None
    target_high: float | None = None
    target_low: float | None = None
    recommendation: str = ""
    analyst_count: int | None = None


@dataclass
class StockBundle:
    """Everything the engines need about one company, from all sources."""

    market: str
    quote: Quote
    statements: Statements
    history: pd.DataFrame = field(default_factory=pd.DataFrame)
    benchmark_history: pd.DataFrame = field(default_factory=pd.DataFrame)
    ownership: Ownership = field(default_factory=Ownership)
    analysts: AnalystView = field(default_factory=AnalystView)
    earnings_history: pd.DataFrame = field(default_factory=pd.DataFrame)
    news: list[dict[str, Any]] = field(default_factory=list)
    filings: list[dict[str, Any]] = field(default_factory=list)
    info: dict[str, Any] = field(default_factory=dict)
    # Anything a provider could not supply, so scoring can discount confidence
    # instead of silently treating missing data as neutral.
    gaps: list[str] = field(default_factory=list)


class Provider(Protocol):
    market: str

    def resolve(self, query: str) -> str | None:
        """Map a user query ('TCS', 'reliance') to a canonical ticker."""

    def fetch(self, symbol: str) -> StockBundle:
        """Fetch everything for one canonical ticker."""


# --- statement row lookup ----------------------------------------------------
# Row labels drift between providers, sectors, and even filings of the same
# company. Never index a statement DataFrame by a hardcoded string.

def pick_row(df: pd.DataFrame, *candidates: str) -> pd.Series | None:
    """Return the first matching statement row, tolerant of label drift.

    Tries exact (case-insensitive) match across all candidates first, then
    falls back to substring matching. Returns None if nothing matches.
    """
    if df is None or df.empty:
        return None

    index_map = {str(i).strip().lower(): i for i in df.index}

    for cand in candidates:
        key = cand.strip().lower()
        if key in index_map:
            return df.loc[index_map[key]]

    for cand in candidates:
        key = cand.strip().lower()
        for label_lower, label in index_map.items():
            if key in label_lower:
                return df.loc[label]
    return None


def latest(series: pd.Series | None, n: int = 0) -> float | None:
    """Nth most recent non-null value of a statement row (n=0 is latest)."""
    if series is None:
        return None
    clean = series.dropna()
    if len(clean) <= n:
        return None
    try:
        return float(clean.iloc[n])
    except (TypeError, ValueError):
        return None


def series_values(series: pd.Series | None, limit: int = 5) -> list[float]:
    """Most-recent-first list of floats, for growth/trend maths."""
    if series is None:
        return []
    clean = series.dropna()
    out: list[float] = []
    for v in clean.iloc[:limit]:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out
