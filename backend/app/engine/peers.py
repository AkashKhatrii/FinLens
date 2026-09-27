"""Peer selection and lightweight peer snapshots for relative comparison.

Peers come from a build-time universe map (app/data/peer_universe.json): S&P 500
+ Nifty 500 constituents with yfinance industry/sector. Selection is a pure
dict lookup: same industry as the subject, ranked by market-cap proximity.

Each peer gets a LIGHT snapshot only (fundamentals + valuation engines on a
cached bundle) - no technicals, no scoring, no AI. The numbers come from the
SAME engines as the subject's, so the comparison is apples-to-apples by
construction.
"""
from __future__ import annotations

import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import median
from typing import TYPE_CHECKING, Any

from .common import cagr, fmt_money
from . import fundamentals, valuation

if TYPE_CHECKING:
    from ..providers.base import StockBundle

log = logging.getLogger(__name__)

_UNIVERSE_PATH = Path(__file__).resolve().parent.parent / "data" / "peer_universe.json"
_universe_cache: dict[str, list[dict[str, Any]]] | None = None

MAX_PEERS = 5

# Metrics compared per peer. Valuation multiples are point-in-time (cheapness),
# growth/quality are statement-derived (is the cheapness deserved?).
METRICS = (
    "pe", "pb", "ev_ebitda", "dividend_yield",
    "revenue_cagr_3y", "net_margin", "roe",
)


def load_universe(market: str) -> list[dict[str, Any]]:
    """S&P 500 / Nifty 500 industry map for one market ('US' or 'IN')."""
    global _universe_cache
    if _universe_cache is None:
        try:
            raw = json.loads(_UNIVERSE_PATH.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Peer universe unavailable: %s", exc)
            raw = {}
        _universe_cache = {
            "US": raw.get("US", []),
            "IN": raw.get("IN", []),
        }
    return _universe_cache.get((market or "").upper(), [])


def universe_as_of() -> str | None:
    try:
        return json.loads(_UNIVERSE_PATH.read_text()).get("as_of")
    except (OSError, json.JSONDecodeError):
        return None


def _norm_symbol(symbol: str | None) -> str:
    s = (symbol or "").strip().upper()
    for suffix in (".NS", ".BO"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s


def _cap_distance(subject_cap: float | None, peer_cap: Any) -> float:
    """Log distance between market caps; peers without a cap sort last."""
    try:
        if not subject_cap or not peer_cap or float(peer_cap) <= 0:
            return math.inf
        return abs(math.log(float(subject_cap) / float(peer_cap)))
    except (TypeError, ValueError):
        return math.inf


def select_peers(
    industry: str | None,
    sector: str | None,
    subject_symbol: str,
    subject_mcap: float | None,
    market: str,
    n: int = MAX_PEERS,
) -> tuple[list[dict[str, Any]], str]:
    """Pick up to n peers: same industry, ranked by market-cap proximity.

    Falls back to same sector when the industry has < 2 candidates. Returns
    (peers, match_level) where match_level is 'industry', 'sector', or 'none'.
    """
    universe = load_universe(market)
    me = _norm_symbol(subject_symbol)
    industry = (industry or "").strip().lower()
    sector = (sector or "").strip().lower()

    def same_level(row: dict[str, Any], key: str, want: str) -> bool:
        return bool(want) and (row.get(key) or "").strip().lower() == want

    candidates = [r for r in universe
                  if _norm_symbol(r.get("symbol")) != me
                  and same_level(r, "industry", industry)]
    level = "industry"
    if len(candidates) < 2 and sector:
        candidates = [r for r in universe
                      if _norm_symbol(r.get("symbol")) != me
                      and same_level(r, "sector", sector)]
        level = "sector"
    if not candidates:
        return [], "none"
    ranked = sorted(candidates,
                    key=lambda r: (_cap_distance(subject_mcap, r.get("market_cap")),
                                   r.get("symbol") or ""))
    return ranked[: max(0, n)], level


def snapshot_metrics(bundle: "StockBundle", fund_facts: Any, val_facts: Any) -> dict[str, Any]:
    """Extract the comparison metrics from one company's engine facts."""
    eq = getattr(fund_facts, "equity", None)
    ni = getattr(fund_facts, "net_income", None)
    roe = (ni / eq * 100) if eq and ni is not None and eq != 0 else None
    margins = list(getattr(fund_facts, "margin_series", None) or [])
    return {
        "market_cap": getattr(bundle.quote, "market_cap", None),
        "pe": getattr(val_facts, "pe", None),
        "pb": getattr(val_facts, "pb", None),
        "ev_ebitda": getattr(val_facts, "ev_ebitda", None),
        "dividend_yield": getattr(val_facts, "dividend_yield", None),
        "revenue_cagr_3y": cagr(list(getattr(fund_facts, "revenue_series", None) or [])[:4]),
        "net_margin": margins[0] if margins else None,
        "roe": roe,
    }


def peer_snapshot(provider: Any, symbol: str) -> dict[str, Any] | None:
    """Lightweight snapshot of one peer: fetch + fundamentals + valuation."""
    try:
        bundle = provider.fetch(symbol)
    except Exception as exc:
        log.warning("Peer fetch failed for %s: %s", symbol, exc)
        return None
    try:
        fund_facts, _, _, _ = fundamentals.analyse(bundle)
        val_facts, _ = valuation.analyse(bundle, fund_facts, None)
    except Exception as exc:
        log.warning("Peer engine failed for %s: %s", symbol, exc)
        return None
    snap = snapshot_metrics(bundle, fund_facts, val_facts)
    snap["ticker"] = _norm_symbol(symbol)
    snap["name"] = getattr(bundle.quote, "name", None) or _norm_symbol(symbol)
    snap["market_cap_display"] = fmt_money(snap["market_cap"], bundle.market)
    return snap


def _medians(snaps: list[dict[str, Any]]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for m in METRICS:
        vals = [s[m] for s in snaps if isinstance(s.get(m), (int, float))]
        out[m] = round(median(vals), 2) if vals else None
    return out


def analyse_peers(
    bundle: "StockBundle",
    provider: Any,
    fund_facts: Any,
    val_facts: Any,
    n: int = MAX_PEERS,
) -> dict[str, Any]:
    """Select peers and snapshot them (threaded); medians + subject values."""
    quote = bundle.quote
    subject_mcap = getattr(quote, "market_cap", None)
    peers, level = select_peers(
        getattr(quote, "industry", None),
        getattr(quote, "sector", None),
        getattr(quote, "symbol", None) or "",
        subject_mcap,
        bundle.market,
        n,
    )
    snaps: list[dict[str, Any]] = []
    if peers:
        with ThreadPoolExecutor(max_workers=min(len(peers), 5)) as pool:
            futs = {pool.submit(peer_snapshot, provider, p["symbol"]): p for p in peers}
            for fut in as_completed(futs):
                snap = fut.result()
                if snap and any(isinstance(snap.get(m), (int, float)) for m in METRICS):
                    snaps.append(snap)
    # Keep selection order (market-cap proximity), not completion order.
    sel_order = [_norm_symbol(p["symbol"]) for p in peers]
    snaps.sort(key=lambda s: sel_order.index(s["ticker"]) if s["ticker"] in sel_order else 999)

    if len(snaps) < 2:
        return {
            "n": 0,
            "peers": [],
            "note": ("Peer set too thin for relative claims "
                     "(fewer than 2 peers with usable data)."),
        }
    return {
        "as_of": universe_as_of(),
        "industry": getattr(quote, "industry", None) or getattr(quote, "sector", None),
        "match_level": level,  # 'industry' or 'sector' (fallback = broader peers)
        "n": len(snaps),
        "peers": snaps,
        "medians": _medians(snaps),
        "subject": snapshot_metrics(bundle, fund_facts, val_facts),
        "note": ("Compare the subject against peer medians. Any relative claim "
                 "must cite the metric, the peer count, and the industry."),
    }
