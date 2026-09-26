"""FastAPI app: JSON API plus the static single-page UI."""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .access import PasswordGateMiddleware
from . import cache
from .analysis import UnknownSymbol, analyse, resolve
from .ai import analyst
from .config import MARKETS, using_provider
from .providers import nse_symbols
from .providers.index_constituents import get_index_constituents
from .screener import analyse_quant_row
from .tradebook import (
    apply_current_prices,
    close_snapshot,
    get_snapshot,
    last_refreshed_at,
    list_snapshots,
    parse_quantity,
    save_snapshot,
    snapshot_from_analysis,
    summarize,
    update_quantity,
)
from .tradebook.prices import fetch_last_prices

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("finlens")

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="FinLens",
    description="AI-assisted equity research for Indian (NSE/BSE) and US listed companies.",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(PasswordGateMiddleware)


def jsonable(obj: Any) -> Any:
    """Recursively make a payload JSON-safe.

    Two real hazards here: pandas/numpy scalars are not serialisable, and NaN
    or inf serialise to bare `NaN`/`Infinity` tokens that `JSON.parse` rejects
    in the browser. Both become `null`.
    """
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        obj = float(obj)
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return [jsonable(v) for v in obj.tolist()]
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [jsonable(v) for v in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "ai": analyst.provider_catalog(),
        "markets": list(MARKETS.keys()),
    }


@app.get("/api/search")
def api_search(
    q: str = Query("", max_length=80),
    limit: int = Query(8, ge=1, le=15),
    market: str = Query("IN"),
) -> dict[str, Any]:
    """Typeahead over the NSE equity list. Empty query -> empty matches.

    Only India has a local equity master; other markets resolve through the
    provider's own search at analyse time, so typeahead returns nothing there.
    """
    matches = (
        [{"symbol": l.symbol, "name": l.name} for l in nse_symbols.search(q, limit)]
        if (market or "IN").upper() == "IN"
        else []
    )
    return {"query": q, "market": (market or "IN").upper(), "matches": matches}


@app.get("/api/resolve")
def api_resolve(q: str = Query(..., min_length=1), market: str = "IN") -> dict[str, Any]:
    try:
        return {"query": q, "symbol": resolve(q, market)}
    except UnknownSymbol as exc:
        raise HTTPException(
            status_code=404,
            detail={"message": exc.message, "suggestions": exc.suggestions},
        )


@app.get("/api/analyse")
def api_analyse(
    q: str = Query(..., min_length=1, description="Ticker or company name, e.g. TCS"),
    market: str = Query("IN"),
    ai: bool = Query(False, description="Include the AI-generated thesis. Off by default; the UI requests it on demand."),
    provider: str | None = Query(None, description="AI provider for this request: deepseek or claude."),
) -> JSONResponse:
    try:
        with using_provider(provider):
            result = analyse(q, market=market, use_ai=ai)
    except UnknownSymbol as exc:
        raise HTTPException(
            status_code=404,
            detail={"message": exc.message, "suggestions": exc.suggestions},
        )
    except Exception as exc:
        log.exception("Analysis failed for %r", q)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}")
    return JSONResponse(content=jsonable(result))


@app.get("/api/indexes/{index_id}/constituents")
def api_index_constituents(index_id: str) -> JSONResponse:
    """Current index membership. Does not score or call the AI."""
    try:
        universe = get_index_constituents(index_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        log.exception("Could not load constituents for %r", index_id)
        raise HTTPException(status_code=502, detail=f"Could not load index constituents: {exc}")
    return JSONResponse(content=jsonable(universe.to_dict()))


@app.get("/api/screener/quant")
def api_screener_quant(
    q: str = Query(..., min_length=1, description="Ticker or company name"),
    market: str = Query("IN"),
) -> JSONResponse:
    """One quantitative Overall/Swing/Long row. Never calls the AI."""
    if (market or "IN").upper() not in MARKETS:
        raise HTTPException(status_code=400, detail=f"Unsupported market '{market}'.")
    row = analyse_quant_row(q, market=market)
    return JSONResponse(content=jsonable(row))


@app.post("/api/cache/clear")
def api_cache_clear(namespace: str | None = None) -> dict[str, Any]:
    return {"cleared": cache.clear(namespace)}


@app.post("/api/tradebook")
def api_tradebook_create(analysis: dict[str, Any]) -> JSONResponse:
    """Record the supplied analysis. Does not fetch data, score, or call the AI."""
    try:
        snap = snapshot_from_analysis(analysis)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return JSONResponse(content=jsonable(save_snapshot(snap)))


@app.get("/api/tradebook")
def api_tradebook_list(
    q: str | None = Query(None, max_length=80),
    swing: str | None = Query(None),
    agreement: str | None = Query(None),
    active: bool = Query(True),
) -> dict[str, Any]:
    rows = list_snapshots(q=q, swing=swing, agreement=agreement, active=active)
    return {
        "snapshots": jsonable(rows),
        "summary": summarize(rows),
        "last_refreshed": last_refreshed_at(rows),
    }


@app.post("/api/tradebook/refresh-prices")
def api_tradebook_refresh_prices() -> dict[str, Any]:
    """Refresh market prices only. Does not analyse, score, or call the AI."""
    from datetime import datetime, timezone

    active = list_snapshots(active=True)
    tickers = [row.get("ticker") for row in active if row.get("ticker")]
    quotes = fetch_last_prices(tickers)
    as_of = datetime.now(timezone.utc).isoformat()
    rows, unavailable = apply_current_prices(quotes, as_of)
    return {
        "snapshots": jsonable(rows),
        "summary": summarize(rows),
        "last_refreshed": last_refreshed_at(rows) or as_of,
        "unavailable": unavailable,
    }


@app.post("/api/tradebook/{snapshot_id}/remove")
def api_tradebook_remove(snapshot_id: str) -> JSONResponse:
    snap = close_snapshot(snapshot_id, "removed")
    if snap is None:
        raise HTTPException(status_code=404, detail="Snapshot not found.")
    return JSONResponse(content=jsonable(snap))


@app.post("/api/tradebook/{snapshot_id}/sell")
def api_tradebook_sell(snapshot_id: str) -> JSONResponse:
    snap = close_snapshot(snapshot_id, "sold")
    if snap is None:
        raise HTTPException(status_code=404, detail="Snapshot not found.")
    return JSONResponse(content=jsonable(snap))


@app.patch("/api/tradebook/{snapshot_id}/quantity")
def api_tradebook_quantity(
    snapshot_id: str,
    payload: dict[str, Any] = Body(...),
) -> JSONResponse:
    """Update lots only. Does not change entry price, scores, or signals."""
    try:
        qty = parse_quantity((payload or {}).get("quantity"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    snap = update_quantity(snapshot_id, qty)
    if snap is None:
        raise HTTPException(status_code=404, detail="Snapshot not found.")
    return JSONResponse(content=jsonable(snap))


@app.get("/api/tradebook/{snapshot_id}")
def api_tradebook_get(snapshot_id: str) -> JSONResponse:
    snap = get_snapshot(snapshot_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="Snapshot not found.")
    return JSONResponse(content=jsonable(snap))


@app.get("/glossary.js")
def glossary_js() -> FileResponse:
    return FileResponse(STATIC_DIR / "glossary.js", media_type="application/javascript")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
