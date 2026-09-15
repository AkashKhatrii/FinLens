"""FastAPI app: JSON API plus the static single-page UI."""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import cache
from .analysis import UnknownSymbol, analyse, resolve
from .ai import analyst
from .config import MARKETS, using_provider
from .providers import nse_symbols

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("finlens")

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="FinLens",
    description="AI-assisted equity research for Indian listed companies.",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
) -> dict[str, Any]:
    """Typeahead over the NSE equity list. Empty query -> empty matches."""
    return {
        "query": q,
        "matches": [{"symbol": l.symbol, "name": l.name} for l in nse_symbols.search(q, limit)],
    }


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


@app.post("/api/cache/clear")
def api_cache_clear(namespace: str | None = None) -> dict[str, Any]:
    return {"cleared": cache.clear(namespace)}


@app.get("/glossary.js")
def glossary_js() -> FileResponse:
    return FileResponse(STATIC_DIR / "glossary.js", media_type="application/javascript")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
