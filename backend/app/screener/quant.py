"""Universe scanning helpers. Do not score; consume existing analyse() results."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from statistics import median
from typing import Any, Callable, Iterable

from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger(__name__)

DEFAULT_CONCURRENCY = 4

BUY_VERDICTS = frozenset({"Strong Buy", "Buy"})
HOLD_VERDICTS = frozenset({"Hold"})
REDUCE_AVOID_VERDICTS = frozenset({"Reduce", "Avoid"})


def quant_row_from_analysis(result: dict[str, Any], *, analyzed_at: str | None = None) -> dict[str, Any]:
    """Copy Overall / Swing / Long from an existing analyse() payload. No recalculation."""
    overall = result.get("overall") or {}
    horizons = result.get("horizons") or {}
    swing = horizons.get("swing") or {}
    long = horizons.get("long") or {}
    company = result.get("company") or {}
    price = result.get("price") or {}
    symbol = _display_symbol(result.get("symbol"))
    market = (result.get("market") or "IN").upper()
    href = f"/?q={symbol}" + (f"&market={market}" if market != "IN" else "")
    return {
        "symbol": symbol,
        "name": company.get("name") or symbol,
        "price": price.get("last"),
        "currency_symbol": result.get("currency_symbol") or "₹",
        "overall_score": overall.get("score"),
        "overall_verdict": overall.get("verdict"),
        "overall_verdict_class": overall.get("verdict_class"),
        "swing_score": swing.get("score"),
        "swing_verdict": swing.get("verdict"),
        "swing_verdict_class": swing.get("verdict_class"),
        "long_score": long.get("score"),
        "long_verdict": long.get("verdict"),
        "long_verdict_class": long.get("verdict_class"),
        "analyzed_at": analyzed_at or datetime.now(timezone.utc).isoformat(),
        "error": None,
        "href": href,
    }


def failed_row(
    symbol: str,
    name: str | None = None,
    error: str = "unavailable",
    currency_symbol: str = "₹",
    market: str = "IN",
) -> dict[str, Any]:
    symbol = _display_symbol(symbol)
    href = f"/?q={symbol}" + (f"&market={market}" if (market or "IN").upper() != "IN" else "")
    return {
        "symbol": symbol,
        "name": name or symbol,
        "price": None,
        "currency_symbol": currency_symbol,
        "overall_score": None,
        "overall_verdict": None,
        "overall_verdict_class": None,
        "swing_score": None,
        "swing_verdict": None,
        "swing_verdict_class": None,
        "long_score": None,
        "long_verdict": None,
        "long_verdict_class": None,
        "analyzed_at": None,
        "error": error,
        "href": href,
    }


def analyse_quant_row(
    query: str,
    *,
    market: str = "IN",
    name: str | None = None,
    analyse_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the existing quantitative pipeline with AI disabled, in the given market."""
    from ..analysis import analyse as _analyse, UnknownSymbol
    from ..config import MARKETS

    cur = MARKETS.get(market, MARKETS["IN"])["symbol"]
    fn = analyse_fn or _analyse
    try:
        result = fn(query, market=market, use_ai=False)
        return quant_row_from_analysis(result)
    except UnknownSymbol as exc:
        log.warning("Screener quant unavailable for %s: %s", query, exc.message)
        return failed_row(query, name, error=str(exc.message), currency_symbol=cur, market=market)
    except Exception as exc:
        log.warning("Screener quant failed for %s: %s", query, exc)
        return failed_row(query, name, error=str(exc), currency_symbol=cur, market=market)


def analyse_universe(
    constituents: Iterable[dict[str, str] | Any],
    *,
    market: str = "IN",
    analyse_fn: Callable[..., dict[str, Any]] | None = None,
    max_workers: int = DEFAULT_CONCURRENCY,
) -> list[dict[str, Any]]:
    """Analyze each constituent with bounded concurrency. One failure stays a row."""
    items = []
    seen: set[str] = set()
    for raw in constituents:
        item = _as_constituent(raw)
        if not item["symbol"] or item["symbol"] in seen:
            continue
        seen.add(item["symbol"])
        items.append(item)
    if not items:
        return []
    workers = max(1, min(max_workers, len(items)))

    def _one(item: dict[str, str]) -> dict[str, Any]:
        return analyse_quant_row(
            item["symbol"], market=market, name=item.get("name"), analyse_fn=analyse_fn
        )

    by_symbol: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_one, item): item["symbol"] for item in items}
        for fut in as_completed(futures):
            symbol = futures[fut]
            try:
                by_symbol[symbol] = fut.result()
            except Exception as exc:
                by_symbol[symbol] = failed_row(symbol, error=str(exc))
    # Preserve universe order (one row per constituent).
    return [by_symbol[item["symbol"]] for item in items]


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Descriptive stats only. Not a new investment signal."""
    analyzed = [r for r in rows if r.get("overall_score") is not None]
    scores = [float(r["overall_score"]) for r in analyzed]
    buy = sum(1 for r in analyzed if r.get("overall_verdict") in BUY_VERDICTS)
    hold = sum(1 for r in analyzed if r.get("overall_verdict") in HOLD_VERDICTS)
    reduce_avoid = sum(
        1 for r in analyzed if r.get("overall_verdict") in REDUCE_AVOID_VERDICTS
    )
    return {
        "total": len(rows),
        "analyzed": len(analyzed),
        "buy": buy,
        "hold": hold,
        "reduce_avoid": reduce_avoid,
        "median_overall": median(scores) if scores else None,
    }


def sort_rows(
    rows: list[dict[str, Any]],
    key: str = "overall",
    descending: bool = True,
) -> list[dict[str, Any]]:
    field = {
        "overall": "overall_score",
        "swing": "swing_score",
        "long": "long_score",
    }.get(key, "overall_score")

    def sort_key(row: dict[str, Any]) -> tuple:
        value = row.get(field)
        missing = value is None
        # Missing scores always sort last, regardless of direction.
        numeric = float(value) if value is not None else 0.0
        if descending:
            numeric = -numeric
        return (missing, numeric, row.get("symbol") or "")

    return sorted(rows, key=sort_key)


def lowest_overall_rows(rows: list[dict[str, Any]], n: int = 50) -> list[dict[str, Any]]:
    """Return the n lowest Overall scores. Null scores are excluded; verdicts are ignored."""
    scored = [r for r in rows if r.get("overall_score") is not None]
    ordered = sorted(
        scored,
        key=lambda r: (float(r["overall_score"]), r.get("symbol") or ""),
    )
    return ordered[: max(0, int(n))]


def _display_symbol(symbol: str | None) -> str:
    raw = (symbol or "").strip().upper()
    if raw.endswith(".NS") or raw.endswith(".BO"):
        return raw.rsplit(".", 1)[0]
    return raw


def _as_constituent(item: Any) -> dict[str, str]:
    if isinstance(item, dict):
        symbol = str(item.get("symbol") or "").upper()
        name = str(item.get("name") or symbol)
        return {"symbol": symbol, "name": name}
    symbol = str(getattr(item, "symbol", "")).upper()
    name = str(getattr(item, "name", symbol) or symbol)
    return {"symbol": symbol, "name": name}
