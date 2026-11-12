"""Tradebook snapshots persist to MongoDB when FINLENS_MONGODB_URI is set."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.tradebook import store


def _snap(snapshot_id: str = "abc", **overrides) -> dict:
    row = {
        "id": snapshot_id,
        "ticker": "WABAG",
        "company_name": "VA Tech Wabag",
        "created_at": "2026-01-02T00:00:00+00:00",
        "snapshot_price": 100.0,
        "quantity": 1,
        "is_active": True,
        "swing_verdict": "Buy",
        "ai_agreement": "aligned",
    }
    row.update(overrides)
    return row


class MemoryCollection:
    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}

    def replace_one(self, filt, doc, upsert=False):
        key = filt["_id"]
        if key not in self.docs and not upsert:
            return
        stored = dict(doc)
        stored["_id"] = key
        self.docs[key] = stored

    def find_one(self, filt):
        doc = self.docs.get(filt["_id"])
        return dict(doc) if doc else None

    def find(self, filt=None):
        return [dict(doc) for doc in self.docs.values()]


class TradebookMongoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.collection = MemoryCollection()
        self.env = patch.dict(
            os.environ,
            {"FINLENS_MONGODB_URI": "mongodb://example", "FINLENS_DATA_DIR": self.tmp.name},
        )
        self.env.start()
        self.collection_patch = patch.object(store, "collection", return_value=self.collection)
        self.collection_patch.start()

    def tearDown(self):
        self.collection_patch.stop()
        self.env.stop()
        self.tmp.cleanup()

    def test_save_and_get_roundtrip_without_a_json_file(self):
        store.save_snapshot(_snap())
        loaded = store.get_snapshot("abc")
        self.assertEqual(loaded["ticker"], "WABAG")
        self.assertEqual(loaded["quantity"], 1)
        self.assertNotIn("_id", loaded)
        self.assertFalse(list(Path(self.tmp.name).glob("tradebook/*.json")))

    def test_list_filters_and_quantity_update_keeps_entry_price(self):
        store.save_snapshot(_snap("old", created_at="2026-01-01T00:00:00+00:00", swing_verdict="Hold"))
        store.save_snapshot(_snap())
        listed = store.list_snapshots(q="wabag", swing="Buy")
        self.assertEqual([row["id"] for row in listed], ["abc"])
        updated = store.update_quantity("abc", 4)
        self.assertEqual(updated["quantity"], 4)
        self.assertEqual(updated["snapshot_price"], 100.0)
        raw = self.collection.docs["abc"]
        self.assertEqual(raw["snapshot_price"], 100.0)
        self.assertNotIn("price_change", raw)

    def test_close_and_price_refresh_write_only_those_fields(self):
        store.save_snapshot(_snap())
        closed = store.close_snapshot("abc", "sold")
        self.assertFalse(closed["is_active"])
        self.assertEqual(closed["removal_reason"], "sold")
        self.assertEqual(store.list_snapshots(active=True), [])
        history = store.list_snapshots(active=False)
        self.assertEqual(history[0]["id"], "abc")
        store.save_snapshot(_snap("live"))
        rows, missing = store.apply_current_prices({"WABAG": 120.0}, "2026-02-01T00:00:00+00:00")
        self.assertEqual(missing, 0)
        live = next(row for row in rows if row["id"] == "live")
        self.assertEqual(live["current_price"], 120.0)
        self.assertEqual(self.collection.docs["abc"]["current_price"] if "current_price" in self.collection.docs["abc"] else None, None)

    def test_import_copies_json_once(self):
        folder = Path(self.tmp.name) / "tradebook"
        folder.mkdir()
        (folder / "abc.json").write_text(json.dumps(_snap()))
        (folder / "new.json").write_text(json.dumps(_snap("new", ticker="TCS", company_name="TCS")))
        store.save_snapshot(_snap())
        copied = store.import_json_snapshots(folder)
        self.assertEqual(copied, 1)
        self.assertEqual(store.get_snapshot("new")["ticker"], "TCS")
        self.assertEqual(store.get_snapshot("abc")["ticker"], "WABAG")
        self.assertEqual(store.import_json_snapshots(folder), 0)
