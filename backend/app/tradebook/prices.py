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


def parse_quantity(value: Any) -> int:
    """Reject anything that is not a positive whole number."""
    if isinstance(value, bool) or value is None:
        raise ValueError("Quantity must be a positive whole number.")
    if isinstance(value, float):
        if not value.is_integer() or value < 1:
            raise ValueError("Quantity must be a positive whole number.")
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text.isdigit():
            raise ValueError("Quantity must be a positive whole number.")
        value = text
    try:
        qty = int(value)
    except (TypeError, ValueError):
        raise ValueError("Quantity must be a positive whole number.") from None
    if qty < 1:
        raise ValueError("Quantity must be a positive whole number.")
    return qty


def normalize_quantity(value: Any) -> int:
    """Missing/invalid quantity on older positions defaults to 1."""
    try:
        return parse_quantity(value)
    except ValueError:
        return 1


def position_totals(
    snapshot_price: Any,
    current_price: Any,
    quantity: Any,
) -> dict[str, Any]:
    qty = normalize_quantity(quantity)
    try:
        entry = float(snapshot_price)
        invested = round(entry * qty, 2)
    except (TypeError, ValueError):
        invested = None
    current_value = None
    try:
        if current_price is not None:
            current_value = round(float(current_price) * qty, 2)
    except (TypeError, ValueError):
        current_value = None
    pnl = None
    pnl_pct = None
    if invested is not None and current_value is not None:
        pnl = round(current_value - invested, 2)
        if invested != 0:
            pnl_pct = round((current_value / invested - 1) * 100, 2)
    return {
        "quantity": qty,
        "invested": invested,
        "current_value": current_value,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
    }


def attach_price_view(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    change, pct = price_delta(out.get("snapshot_price"), out.get("current_price"))
    out["price_change"] = change
    out["percentage_change"] = pct
    out.update(position_totals(out.get("snapshot_price"), out.get("current_price"), out.get("quantity")))
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
