"""Tradebook journal.

JSON files under FINLENS_DATA_DIR when FINLENS_MONGODB_URI is unset.
MongoDB Atlas (or any MongoDB) when that URI is set. Documents are the
snapshots themselves; the id is the document _id.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT
from .prices import attach_price_view, parse_quantity

_client: Any = None


def mongo_enabled() -> bool:
    return bool((os.getenv("FINLENS_MONGODB_URI") or "").strip())


def collection():
    """Tradebook collection. Database name comes from the URI, else finlens."""
    global _client
    uri = (os.getenv("FINLENS_MONGODB_URI") or "").strip()
    if not uri:
        raise RuntimeError("FINLENS_MONGODB_URI is not set")
    if _client is None:
        from pymongo import MongoClient

        _client = MongoClient(uri, serverSelectionTimeoutMS=8000)
    explicit = (os.getenv("FINLENS_MONGODB_DB") or "").strip()
    db = _client[explicit] if explicit else _client.get_default_database(default="finlens")
    return db["tradebook"]


def data_dir() -> Path:
    root = Path(os.getenv("FINLENS_DATA_DIR", str(PROJECT_ROOT / ".data")))
    path = root / "tradebook"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _without_id(doc: dict[str, Any]) -> dict[str, Any]:
    row = dict(doc)
    row.pop("_id", None)
    return row


def _read_raw(snapshot_id: str) -> dict[str, Any] | None:
    if mongo_enabled():
        doc = collection().find_one({"_id": snapshot_id})
        return _without_id(doc) if doc else None
    path = data_dir() / f"{snapshot_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _write_raw(snapshot: dict[str, Any]) -> dict[str, Any]:
    if mongo_enabled():
        doc = dict(snapshot)
        doc.pop("_id", None)
        collection().replace_one({"_id": snapshot["id"]}, {**doc, "_id": snapshot["id"]}, upsert=True)
        return snapshot
    path = data_dir() / f"{snapshot['id']}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snapshot, indent=2, default=str))
    tmp.replace(path)
    return snapshot


def _all_raw() -> list[dict[str, Any]]:
    if mongo_enabled():
        return [_without_id(doc) for doc in collection().find({})]
    rows = []
    for path in data_dir().glob("*.json"):
        try:
            rows.append(json.loads(path.read_text()))
        except (OSError, json.JSONDecodeError):
            continue
    return rows


def save_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return _write_raw(snapshot)


def get_snapshot(snapshot_id: str) -> dict[str, Any] | None:
    raw = _read_raw(snapshot_id)
    if raw is None:
        return None
    return attach_price_view(raw)


def list_snapshots(
    q: str | None = None,
    swing: str | None = None,
    agreement: str | None = None,
    active: bool | None = True,
) -> list[dict[str, Any]]:
    rows = _all_raw()
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
    snap = _read_raw(snapshot_id)
    if snap is None:
        return None
    snap["is_active"] = False
    snap["removed_at"] = datetime.now(timezone.utc).isoformat()
    snap["removal_reason"] = reason
    return attach_price_view(save_snapshot(snap))


def update_quantity(snapshot_id: str, quantity: int) -> dict[str, Any] | None:
    """Change lots only. Never rewrites entry price or recommendation fields."""
    qty = parse_quantity(quantity)
    snap = _read_raw(snapshot_id)
    if snap is None:
        return None
    snap["quantity"] = qty
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
        raw = _read_raw(row["id"])
        if raw is None:
            continue
        raw["current_price"] = price
        raw["current_price_as_of"] = as_of
        save_snapshot(raw)
    return list_snapshots(active=True), unavailable


def import_json_snapshots(directory: Path | None = None) -> int:
    """Copy JSON snapshots into MongoDB. Existing ids are left untouched."""
    if not mongo_enabled():
        return 0
    folder = directory or data_dir()
    if not folder.exists():
        return 0
    copied = 0
    for path in sorted(folder.glob("*.json")):
        try:
            snap = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        snapshot_id = snap.get("id")
        if not snapshot_id or _read_raw(snapshot_id):
            continue
        _write_raw(snap)
        copied += 1
    return copied


def last_refreshed_at(rows: list[dict[str, Any]]) -> str | None:
    stamps = [row.get("current_price_as_of") for row in rows if row.get("current_price_as_of")]
    return max(stamps) if stamps else None


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    buys = {"Buy", "Strong Buy"}
    invested = 0.0
    current_value = 0.0
    for row in rows:
        if row.get("invested") is not None:
            invested += float(row["invested"])
        if row.get("current_value") is not None:
            current_value += float(row["current_value"])
        elif row.get("invested") is not None:
            current_value += float(row["invested"])
    invested = round(invested, 2)
    current_value = round(current_value, 2)
    pnl = round(current_value - invested, 2)
    pnl_pct = round((current_value / invested - 1) * 100, 2) if invested else None
    return {
        "total": len(rows),
        "swing_buys": sum(1 for row in rows if row.get("swing_verdict") in buys),
        "swing_holds": sum(1 for row in rows if row.get("swing_verdict") == "Hold"),
        "swing_reduces": sum(1 for row in rows if row.get("swing_verdict") == "Reduce"),
        "ai_aligned": sum(1 for row in rows if row.get("ai_agreement") == "aligned"),
        "ai_disagreed": sum(1 for row in rows if row.get("ai_agreement") == "disagrees"),
        "invested": invested,
        "current_value": current_value,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
    }
