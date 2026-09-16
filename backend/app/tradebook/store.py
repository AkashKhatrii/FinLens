"""JSON-file journal. Separate from the TTL cache so clearing cache cannot erase history."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT
from .prices import attach_price_view


def data_dir() -> Path:
    root = Path(os.getenv("FINLENS_DATA_DIR", str(PROJECT_ROOT / ".data")))
    path = root / "tradebook"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    path = data_dir() / f"{snapshot['id']}.json"
    tmp = path.with_suffix(".tmp")
    payload = json.dumps(snapshot, indent=2, default=str)
    tmp.write_text(payload)
    tmp.replace(path)
    return snapshot


def get_snapshot(snapshot_id: str) -> dict[str, Any] | None:
    path = data_dir() / f"{snapshot_id}.json"
    if not path.exists():
        return None
    return attach_price_view(json.loads(path.read_text()))


def list_snapshots(
    q: str | None = None,
    swing: str | None = None,
    agreement: str | None = None,
    active: bool | None = True,
) -> list[dict[str, Any]]:
    rows = []
    for path in data_dir().glob("*.json"):
        try:
            rows.append(json.loads(path.read_text()))
        except (OSError, json.JSONDecodeError):
            continue
    rows.sort(key=lambda row: row.get("created_at") or "", reverse=True)
    if active is True:
        rows = [row for row in rows if row.get("is_active", True)]
    elif active is False:
        rows = [row for row in rows if not row.get("is_active", True)]
    needle = (q or "").strip().lower()
    if needle:
        rows = [
            row for row in rows
            if needle in str(row.get("ticker") or "").lower()
            or needle in str(row.get("company_name") or "").lower()
        ]
    if swing:
        rows = [row for row in rows if row.get("swing_verdict") == swing]
    if agreement:
        rows = [row for row in rows if row.get("ai_agreement") == agreement]
    return [attach_price_view(row) for row in rows]


def close_snapshot(snapshot_id: str, reason: str) -> dict[str, Any] | None:
    path = data_dir() / f"{snapshot_id}.json"
    if not path.exists():
        return None
    snap = json.loads(path.read_text())
    snap["is_active"] = False
    snap["removed_at"] = datetime.now(timezone.utc).isoformat()
    snap["removal_reason"] = reason
    return attach_price_view(save_snapshot(snap))


def apply_current_prices(
    quotes: dict[str, float | None],
    as_of: str,
) -> tuple[list[dict[str, Any]], int]:
    """Update tracking prices on active snapshots. Never writes recommendation fields."""
    unavailable = 0
    for row in list_snapshots(active=True):
        ticker = row.get("ticker")
        price = quotes.get(ticker) if ticker else None
        if price is None:
            unavailable += 1
            continue
        raw = json.loads((data_dir() / f"{row['id']}.json").read_text())
        raw["current_price"] = price
        raw["current_price_as_of"] = as_of
        save_snapshot(raw)
    return list_snapshots(active=True), unavailable


def last_refreshed_at(rows: list[dict[str, Any]]) -> str | None:
    stamps = [row.get("current_price_as_of") for row in rows if row.get("current_price_as_of")]
    return max(stamps) if stamps else None


def summarize(rows: list[dict[str, Any]]) -> dict[str, int]:
    buys = {"Buy", "Strong Buy"}
    return {
        "total": len(rows),
        "swing_buys": sum(1 for row in rows if row.get("swing_verdict") in buys),
        "swing_holds": sum(1 for row in rows if row.get("swing_verdict") == "Hold"),
        "swing_reduces": sum(1 for row in rows if row.get("swing_verdict") == "Reduce"),
        "ai_aligned": sum(1 for row in rows if row.get("ai_agreement") == "aligned"),
        "ai_disagreed": sum(1 for row in rows if row.get("ai_agreement") == "disagrees"),
    }
