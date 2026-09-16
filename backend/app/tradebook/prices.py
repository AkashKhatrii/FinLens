"""Latest market prices for Tradebook. Quote only — no analysis, AI, or scoring."""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def price_delta(snapshot_price: Any, current_price: Any) -> tuple[float | None, float | None]:
    try:
        base = float(snapshot_price)
        current = float(current_price)
    except (TypeError, ValueError):
        return None, None
    if base == 0:
        return None, None
    change = round(current - base, 2)
    pct = round((current / base - 1) * 100, 2)
    return change, pct


def attach_price_view(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    change, pct = price_delta(out.get("snapshot_price"), out.get("current_price"))
    out["price_change"] = change
    out["percentage_change"] = pct
    return out


def fetch_last_prices(tickers: list[str], market: str = "IN") -> dict[str, float | None]:
    """Batch last prices via the existing yfinance provider. Never calls analyse()."""
    from ..providers.yf_provider import YFinanceProvider

    unique = []
    seen: set[str] = set()
    for ticker in tickers:
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        unique.append(ticker)
    if not unique:
        return {}
    return YFinanceProvider(market).last_prices(unique)
