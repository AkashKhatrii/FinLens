"""Timestamped log of AI horizon stances for forward-return measurement.

Every successfully generated thesis records one row per horizon call
(swing + long). A separate report script joins these rows against later
prices to measure whether AI stances actually predicted returns.

Append-only JSONL; each row is self-contained. Logging must never break
analysis, so record() swallows all errors and returns None on failure.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT


def default_path() -> Path:
    """Same data-dir convention as the tradebook journal: $FINLENS_DATA_DIR,
    defaulting to backend/.data (gitignored)."""
    root = Path(os.getenv("FINLENS_DATA_DIR", str(PROJECT_ROOT / ".data")))
    return root / "ai_stance_log.jsonl"


def _stance(thesis: dict[str, Any], horizon: str) -> dict[str, Any]:
    for call in thesis.get("horizon_calls") or []:
        if call.get("horizon") == horizon:
            return {"stance": call.get("stance"), "conviction": call.get("conviction")}
    return {"stance": None, "conviction": None}


def record(
    *,
    ticker: str,
    name: str,
    market: str,
    price: float | None,
    thesis: dict[str, Any],
    horizons: dict[str, Any] | None = None,
    provider: str | None = None,
    model: str | None = None,
    path: Path | str | None = None,
) -> Path | None:
    """Append one JSONL row per AI horizon call. Never raises."""
    try:
        dest = Path(path) if path else default_path()
        dest.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc)
        rows = []
        for hz in ("swing", "long"):
            s = _stance(thesis, hz)
            q = (horizons or {}).get(hz) or {}
            rows.append(
                {
                    "ts_utc": ts.isoformat(),
                    "date": ts.date().isoformat(),
                    "ticker": ticker,
                    "name": name,
                    "market": (market or "IN").upper(),
                    "horizon": hz,
                    "ai_stance": s["stance"],
                    "ai_conviction": s["conviction"],
                    "quant_score": q.get("score"),
                    "quant_verdict": q.get("verdict"),
                    "price_at_stance": price,
                    "provider": provider,
                    "model": model,
                }
            )
        with dest.open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        return dest
    except Exception:
        return None


def read_all(path: Path | str | None = None) -> list[dict[str, Any]]:
    dest = Path(path) if path else default_path()
    if not dest.exists():
        return []
    rows = []
    for line in dest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows
