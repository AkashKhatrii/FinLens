"""Tradebook 1: immutable recommendation snapshots. No analysis rerun."""
from __future__ import annotations

import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.tradebook.snapshot import snapshot_from_analysis


def _analysis(**overrides) -> dict:
    base = {
        "symbol": "WABAG",
        "market": "IN",
        "company": {
            "name": "VA Tech Wabag",
            "sector": "Utilities",
            "industry": "Water",
        },
        "price": {"last": 2127.90},
        "overall": {"score": 62.0, "verdict": "Hold", "verdict_class": "hold"},
        "horizons": {
            "swing": {
                "score": 71.0,
                "verdict": "Buy",
                "verdict_class": "buy",
                "confidence": 84.0,
                "confidence_label": "High",
                "regime": "Healthy Pullback",
                "entry_quality": "Attractive",
                "swing_factors": {
                    "trend": "Bullish",
                    "momentum": "Positive",
                    "relative_strength": "Positive",
                    "setup": "Pullback",
                    "volume": "Neutral",
                },
                "plan": {
                    "stop_loss": 1980.0,
                    "target": 2350.0,
                    "risk_reward": 1.5,
                    "guidance": "Hold while the 50-DMA holds.",
                },
            },
            "long": {
                "score": 58.0,
                "verdict": "Hold",
                "verdict_class": "hold",
                "confidence": 76.0,
                "confidence_label": "High",
            },
        },
        "technicals": {
            "rsi14": 52.0,
            "adx14": 20.3,
            "pct_b": 0.42,
            "volume_ratio": 1.0,
            "sma20": 2110.0,
            "sma50": 2050.0,
            "sma200": 1880.0,
            "returns": {"1m": 5.0, "3m": 10.0},
            "relative_strength": {"3m": 4.2},
            "series": [1, 2, 3],
        },
        "pillars": {
            "growth": {
                "key": "growth", "label": "Growth", "score": 60.0, "coverage": 1.0,
                "metrics": [{"label": "Revenue YoY", "display": "12%", "score": 60.0, "note": ""}],
                "notes": [],
            }
        },
        "fundamentals": {"roe": 14.0},
        "valuation": {"pe": 28.0, "pe_history": [20, 22]},
        "ai": {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "thesis": {
                "horizon_calls": [
                    {
                        "horizon": "swing",
                        "stance": "Buy",
                        "conviction": "High",
                        "rationale": "Trend and momentum remain favorable after the pullback.",
                        "what_would_change_it": "A break of the 50-DMA.",
                        "agreement": "aligned",
                        "qualification": None,
                    },
                    {
                        "horizon": "long",
                        "stance": "Hold",
                        "conviction": "Medium",
                        "rationale": "Quality is fine but the price is not a Long Buy.",
                        "what_would_change_it": "A cheaper valuation with unchanged quality.",
                    },
                ],
                "opportunity": {
                    "category": "Established Opportunity",
                    "risk_level": "Medium",
                    "the_bet": "Water infrastructure compounding.",
                    "needs_to_happen": "Order book conversion continues.",
                    "thesis_breakers": ["Sustained margin collapse"],
                },
            },
        },
    }
    merge_keys = {"company", "price", "horizons", "technicals", "overall"}
    for key, value in overrides.items():
        if key in merge_keys and isinstance(value, dict) and isinstance(base.get(key), dict):
            merged = deepcopy(base[key])
            merged.update(value)
            base[key] = merged
        else:
            base[key] = value
    return base


class TradebookApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"FINLENS_DATA_DIR": self.tmp.name})
        self.env.start()
        self.analyse_patch = patch("app.analysis.analyse")
        self.analyse = self.analyse_patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.analyse_patch.stop()
        self.env.stop()
        self.tmp.cleanup()

    def test_create_snapshot_captures_core_fields(self):
        res = self.client.post("/api/tradebook", json=_analysis())
        self.assertEqual(res.status_code, 200, res.text)
        snap = res.json()
        self.assertEqual(snap["ticker"], "WABAG")
        self.assertEqual(snap["company_name"], "VA Tech Wabag")
        self.assertEqual(snap["sector"], "Utilities")
        self.assertEqual(snap["snapshot_price"], 2127.9)
        self.assertTrue(snap["created_at"])
        self.assertTrue(snap["id"])
        self.assertEqual(snap["overall_score"], 62.0)
        self.assertEqual(snap["overall_verdict"], "Hold")
        self.assertEqual(snap["swing_score"], 71.0)
        self.assertEqual(snap["swing_verdict"], "Buy")
        self.assertEqual(snap["swing_confidence"], 84.0)
        self.assertEqual(snap["swing_regime"], "Healthy Pullback")
        self.assertEqual(snap["swing_entry_quality"], "Attractive")
        self.assertEqual(snap["swing_trend"], "Bullish")
        self.assertEqual(snap["quantity"], 1)
        self.assertEqual(snap["technical_stop"], 1980.0)
        self.assertEqual(snap["technical_target"], 2350.0)
        self.assertEqual(snap["risk_reward"], 1.5)
        self.assertEqual(snap["long_score"], 58.0)
        self.assertEqual(snap["long_verdict"], "Hold")
        self.assertEqual(snap["long_confidence"], 76.0)
        self.assertEqual(snap["opportunity_category"], "Established Opportunity")
        self.assertEqual(snap["opportunity_risk"], "Medium")
        self.assertEqual(snap["opportunity_bet"], "Water infrastructure compounding.")
        self.assertEqual(snap["opportunity_needs_to_happen"], "Order book conversion continues.")
        self.assertEqual(snap["opportunity_thesis_breakers"], ["Sustained margin collapse"])
        self.assertTrue(snap["ai_available"])
        self.assertEqual(snap["ai_provider"], "deepseek")
        self.assertEqual(snap["ai_model"], "deepseek-v4-flash")
        self.assertEqual(snap["ai_swing_verdict"], "Buy")
        self.assertEqual(snap["ai_agreement"], "aligned")
        self.assertIn("pullback", snap["ai_reasoning"].lower())
        self.assertEqual(snap["ai_flips_if"], "A break of the 50-DMA.")
        self.analyse.assert_not_called()

    def test_ai_unavailable_does_not_fabricate_fields(self):
        payload = _analysis(ai=None)
        snap = self.client.post("/api/tradebook", json=payload).json()
        self.assertFalse(snap["ai_available"])
        self.assertIsNone(snap["ai_provider"])
        self.assertIsNone(snap["ai_swing_verdict"])
        self.assertIsNone(snap["ai_agreement"])
        self.assertIsNone(snap["opportunity_category"])

    def test_ai_error_is_treated_as_unavailable(self):
        snap = self.client.post("/api/tradebook", json=_analysis(ai={"error": "no key"})).json()
        self.assertFalse(snap["ai_available"])
        self.assertIsNone(snap["ai_reasoning"])

    def test_quant_and_metrics_evidence_are_preserved(self):
        snap = self.client.post("/api/tradebook", json=_analysis()).json()
        evidence = snap["quant_evidence"]
        metrics = snap["metrics_snapshot"]
        self.assertEqual(evidence["regime"], "Healthy Pullback")
        self.assertEqual(evidence["trend"], "Bullish")
        self.assertEqual(evidence["rsi14"], 52.0)
        self.assertNotIn("series", metrics)
        self.assertEqual(metrics["rsi14"], 52.0)
        self.assertEqual(metrics["adx14"], 20.3)

    def test_list_and_get_return_stored_snapshots(self):
        created = self.client.post("/api/tradebook", json=_analysis()).json()
        listing = self.client.get("/api/tradebook").json()
        self.assertEqual(listing["summary"]["total"], 1)
        self.assertEqual(listing["summary"]["swing_buys"], 1)
        self.assertEqual(listing["summary"]["ai_aligned"], 1)
        self.assertEqual(len(listing["snapshots"]), 1)
        fetched = self.client.get(f"/api/tradebook/{created['id']}").json()
        self.assertEqual(fetched["id"], created["id"])
        self.assertEqual(fetched["swing_score"], 71.0)
        self.assertEqual(fetched["ai_reasoning"], created["ai_reasoning"])

    def test_empty_tradebook(self):
        listing = self.client.get("/api/tradebook").json()
        self.assertEqual(listing["snapshots"], [])
        self.assertEqual(listing["summary"]["total"], 0)

    def test_second_snapshot_does_not_overwrite_the_first(self):
        first = self.client.post("/api/tradebook", json=_analysis()).json()
        later = _analysis()
        later["price"] = {"last": 2250.0}
        later["horizons"] = deepcopy(later["horizons"])
        later["horizons"]["swing"]["score"] = 64.0
        later["horizons"]["swing"]["verdict"] = "Hold"
        second = self.client.post("/api/tradebook", json=later).json()
        self.assertNotEqual(first["id"], second["id"])
        stored = self.client.get(f"/api/tradebook/{first['id']}").json()
        self.assertEqual(stored["snapshot_price"], 2127.9)
        self.assertEqual(stored["swing_verdict"], "Buy")
        self.assertEqual(stored["swing_score"], 71.0)
        listing = self.client.get("/api/tradebook").json()
        self.assertEqual(listing["summary"]["total"], 2)

    def test_duplicate_posts_create_separate_snapshots(self):
        """No analysis id exists, so identical posts are allowed rather than overwritten."""
        a = self.client.post("/api/tradebook", json=_analysis()).json()
        b = self.client.post("/api/tradebook", json=_analysis()).json()
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(self.client.get("/api/tradebook").json()["summary"]["total"], 2)

    def test_no_update_endpoint(self):
        created = self.client.post("/api/tradebook", json=_analysis()).json()
        res = self.client.put(f"/api/tradebook/{created['id']}", json={"swing_verdict": "Hold"})
        self.assertEqual(res.status_code, 405)
        stored = self.client.get(f"/api/tradebook/{created['id']}").json()
        self.assertEqual(stored["swing_verdict"], "Buy")

    def test_filters(self):
        self.client.post("/api/tradebook", json=_analysis())
        other = _analysis()
        other["symbol"] = "TCS"
        other["company"] = {"name": "TCS", "sector": "IT"}
        other["horizons"] = deepcopy(other["horizons"])
        other["horizons"]["swing"]["verdict"] = "Hold"
        other["ai"]["thesis"]["horizon_calls"][0]["agreement"] = "disagrees"
        other["ai"]["thesis"]["horizon_calls"][0]["stance"] = "Hold"
        self.client.post("/api/tradebook", json=other)
        by_ticker = self.client.get("/api/tradebook", params={"q": "WABAG"}).json()
        self.assertEqual(by_ticker["summary"]["total"], 1)
        self.assertEqual(by_ticker["snapshots"][0]["ticker"], "WABAG")
        by_swing = self.client.get("/api/tradebook", params={"swing": "Hold"}).json()
        self.assertEqual(by_swing["snapshots"][0]["ticker"], "TCS")
        by_ai = self.client.get("/api/tradebook", params={"agreement": "disagrees"}).json()
        self.assertEqual(by_ai["summary"]["ai_disagreed"], 1)

    def test_quant_buy_ai_hold_disagreement_is_preserved(self):
        payload = _analysis()
        payload["ai"]["thesis"]["horizon_calls"][0]["stance"] = "Hold"
        payload["ai"]["thesis"]["horizon_calls"][0]["agreement"] = "disagrees"
        payload["ai"]["thesis"]["horizon_calls"][0]["rationale"] = "Event risk tomorrow."
        snap = self.client.post("/api/tradebook", json=payload).json()
        self.assertEqual(snap["swing_verdict"], "Buy")
        self.assertEqual(snap["swing_score"], 71.0)
        self.assertEqual(snap["ai_swing_verdict"], "Hold")
        self.assertEqual(snap["ai_agreement"], "disagrees")
        self.assertEqual(snap["ai_reasoning"], "Event risk tomorrow.")

    def test_missing_snapshot_is_404(self):
        res = self.client.get("/api/tradebook/does-not-exist")
        self.assertEqual(res.status_code, 404)

    def test_snapshot_builder_does_not_call_analyse(self):
        with patch("app.analysis.analyse") as analyse:
            snap = snapshot_from_analysis(_analysis())
            self.assertEqual(snap["ticker"], "WABAG")
            analyse.assert_not_called()


class TradebookIsolationTest(unittest.TestCase):
    def test_scoring_does_not_import_tradebook(self):
        src = Path(__file__).resolve().parents[1] / "app" / "engine" / "scoring.py"
        self.assertNotIn("tradebook", src.read_text())

    def test_analysis_does_not_import_tradebook(self):
        src = Path(__file__).resolve().parents[1] / "app" / "analysis.py"
        self.assertNotIn("tradebook", src.read_text())

    def test_ui_has_tradebook_journal_and_add_action(self):
        html = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text()
        self.assertIn("Add to Tradebook", html)
        self.assertIn("Recommendation Journal", html)
        self.assertIn("Price at recommendation", html)
        self.assertIn("No recommendations recorded yet.", html)
        self.assertIn("Recommendation recorded", html)
        self.assertIn("addToTradebook", html)
        method = html.split("addToTradebook", 1)[1][:1200]
        self.assertNotIn("/api/analyse", method)

    def test_ui_has_compact_rows_quantity_and_red_sell(self):
        html = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text()
        self.assertIn("Refresh Prices", html)
        self.assertIn("Last refreshed", html)
        self.assertNotIn("View Analysis", html)
        self.assertIn("viewAnalysis(row.ticker)", html)
        self.assertIn("nudgeTradebookQuantity", html)
        self.assertIn("commitTradebookQuantity", html)
        self.assertIn("/api/tradebook/' + encodeURIComponent(row.id) + '/quantity'", html)
        self.assertIn("text-red-500", html)
        self.assertIn("askTradebookAction('sell', row)", html)
        self.assertIn("v-on:click.stop", html)
        self.assertIn("tradebookEntryLine", html)
        self.assertIn("swing_entry_quality", html)
        self.assertIn("fmtStamp(row.created_at)", html)
        self.assertIn("tradebookAge(row.created_at)", html)
        self.assertIn(">Added</th>", html)
        self.assertIn("from Tradebook?", html)
        self.assertIn("Mark as sold", html)
        method = html.split("viewAnalysis(ticker)", 1)[1][:800]
        self.assertIn("this.run()", method)
        refresh = html.split("async refreshTradebookPrices()", 1)[1][:1200]
        self.assertNotIn("/api/analyse", refresh)
        self.assertIn("/api/tradebook/refresh-prices", refresh)
        qty = html.split("async setTradebookQuantity", 1)[1][:900]
        self.assertNotIn("/api/analyse", qty)


class TradebookPricesAndCloseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"FINLENS_DATA_DIR": self.tmp.name})
        self.env.start()
        self.analyse_patch = patch("app.analysis.analyse")
        self.analyse = self.analyse_patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.analyse_patch.stop()
        self.env.stop()
        self.tmp.cleanup()

    def _create(self, **overrides):
        return self.client.post("/api/tradebook", json=_analysis(**overrides)).json()

    def test_refresh_updates_current_price_not_snapshot_price(self):
        created = self._create()
        with patch("app.main.fetch_last_prices", return_value={"WABAG": 2215.30}) as fetch:
            res = self.client.post("/api/tradebook/refresh-prices")
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertTrue(body["last_refreshed"])
        row = body["snapshots"][0]
        self.assertEqual(row["snapshot_price"], 2127.9)
        self.assertEqual(row["current_price"], 2215.3)
        self.assertAlmostEqual(row["price_change"], 87.4, places=2)
        self.assertAlmostEqual(row["percentage_change"], 4.11, places=2)
        self.assertEqual(row["swing_verdict"], "Buy")
        self.assertEqual(row["swing_score"], 71.0)
        fetch.assert_called()
        self.analyse.assert_not_called()
        stored = self.client.get(f"/api/tradebook/{created['id']}").json()
        self.assertEqual(stored["snapshot_price"], 2127.9)
        self.assertEqual(stored["current_price"], 2215.3)
        self.assertEqual(stored["swing_score"], 71.0)
        self.assertEqual(stored["long_verdict"], "Hold")
        self.assertEqual(stored["opportunity_category"], "Established Opportunity")
        self.assertEqual(stored["ai_agreement"], "aligned")

    def test_refresh_does_not_call_ai_or_analyse(self):
        self._create()
        with patch("app.main.fetch_last_prices", return_value={"WABAG": 2215.30}), \
             patch("app.ai.analyst.generate_thesis") as thesis:
            self.client.post("/api/tradebook/refresh-prices")
        self.analyse.assert_not_called()
        thesis.assert_not_called()

    def test_one_failed_price_does_not_fail_refresh(self):
        self._create()
        other = _analysis()
        other["symbol"] = "TCS"
        other["company"] = {"name": "TCS", "sector": "IT"}
        self.client.post("/api/tradebook", json=other)
        with patch("app.main.fetch_last_prices", return_value={"WABAG": 2215.30, "TCS": None}):
            body = self.client.post("/api/tradebook/refresh-prices").json()
        self.assertEqual(body["unavailable"], 1)
        by_ticker = {row["ticker"]: row for row in body["snapshots"]}
        self.assertEqual(by_ticker["WABAG"]["current_price"], 2215.3)
        self.assertIsNone(by_ticker["TCS"]["current_price"])
        self.assertEqual(by_ticker["WABAG"]["snapshot_price"], 2127.9)

    def test_failed_refresh_does_not_clear_a_known_current_price(self):
        created = self._create()
        with patch("app.main.fetch_last_prices", return_value={"WABAG": 2215.30}):
            self.client.post("/api/tradebook/refresh-prices")
        with patch("app.main.fetch_last_prices", return_value={"WABAG": None}):
            body = self.client.post("/api/tradebook/refresh-prices").json()
        self.assertEqual(body["snapshots"][0]["current_price"], 2215.3)
        stored = self.client.get(f"/api/tradebook/{created['id']}").json()
        self.assertEqual(stored["current_price"], 2215.3)
        self.assertEqual(stored["snapshot_price"], 2127.9)

    def test_remove_hides_from_active_list_and_preserves_history(self):
        created = self._create()
        with patch("app.main.fetch_last_prices", return_value={"WABAG": 2215.30}):
            self.client.post("/api/tradebook/refresh-prices")
        res = self.client.post(f"/api/tradebook/{created['id']}/remove")
        self.assertEqual(res.status_code, 200, res.text)
        closed = res.json()
        self.assertFalse(closed["is_active"])
        self.assertEqual(closed["removal_reason"], "removed")
        self.assertTrue(closed["removed_at"])
        self.assertEqual(closed["snapshot_price"], 2127.9)
        self.assertEqual(closed["swing_verdict"], "Buy")
        self.assertEqual(closed["swing_score"], 71.0)
        listing = self.client.get("/api/tradebook").json()
        self.assertEqual(listing["snapshots"], [])
        self.assertEqual(listing["summary"]["total"], 0)
        stored = self.client.get(f"/api/tradebook/{created['id']}").json()
        self.assertEqual(stored["snapshot_price"], 2127.9)
        self.assertEqual(stored["swing_score"], 71.0)
        self.assertEqual(stored["current_price"], 2215.3)
        history = self.client.get("/api/tradebook", params={"active": "false"}).json()
        self.assertEqual(len(history["snapshots"]), 1)
        self.assertEqual(history["snapshots"][0]["removal_reason"], "removed")

    def test_sell_marks_sold_and_preserves_recommendation(self):
        created = self._create()
        res = self.client.post(f"/api/tradebook/{created['id']}/sell")
        self.assertEqual(res.status_code, 200, res.text)
        closed = res.json()
        self.assertFalse(closed["is_active"])
        self.assertEqual(closed["removal_reason"], "sold")
        self.assertEqual(closed["swing_verdict"], "Buy")
        self.assertEqual(closed["long_verdict"], "Hold")
        self.assertEqual(self.client.get("/api/tradebook").json()["snapshots"], [])
        stored = self.client.get(f"/api/tradebook/{created['id']}").json()
        self.assertEqual(stored["ai_swing_verdict"], "Buy")
        self.assertEqual(stored["opportunity_category"], "Established Opportunity")

    def test_wabag_refresh_then_remove_regression(self):
        created = self._create()
        with patch("app.main.fetch_last_prices", return_value={"WABAG": 2215.30}):
            refreshed = self.client.post("/api/tradebook/refresh-prices").json()["snapshots"][0]
        self.assertEqual(refreshed["snapshot_price"], 2127.9)
        self.assertEqual(refreshed["current_price"], 2215.3)
        self.assertAlmostEqual(refreshed["price_change"], 87.4, places=2)
        self.assertAlmostEqual(refreshed["percentage_change"], 4.11, places=2)
        self.client.post(f"/api/tradebook/{created['id']}/remove")
        stored = self.client.get(f"/api/tradebook/{created['id']}").json()
        self.assertFalse(stored["is_active"])
        self.assertEqual(stored["snapshot_price"], 2127.9)
        self.assertEqual(stored["swing_verdict"], "Buy")
        self.assertEqual(stored["swing_score"], 71.0)

    def test_fetch_last_prices_uses_yfinance_provider(self):
        from app.tradebook.prices import fetch_last_prices
        with patch("app.providers.yf_provider.YFinanceProvider.last_prices", return_value={"WABAG": 2215.3}) as last:
            out = fetch_last_prices(["WABAG", "WABAG"])
        last.assert_called_once_with(["WABAG"])
        self.assertEqual(out["WABAG"], 2215.3)


class TradebookQuantityAndPnlTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"FINLENS_DATA_DIR": self.tmp.name})
        self.env.start()
        self.analyse_patch = patch("app.analysis.analyse")
        self.analyse = self.analyse_patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.analyse_patch.stop()
        self.env.stop()
        self.tmp.cleanup()

    def _create(self, **overrides):
        return self.client.post("/api/tradebook", json=_analysis(**overrides)).json()

    def test_quantity_defaults_to_one_and_scales_pnl(self):
        created = self._create()
        self.assertEqual(created["quantity"], 1)
        with patch("app.main.fetch_last_prices", return_value={"WABAG": 2215.30}):
            row = self.client.post("/api/tradebook/refresh-prices").json()["snapshots"][0]
        self.assertEqual(row["snapshot_price"], 2127.9)
        self.assertAlmostEqual(row["invested"], 2127.9, places=2)
        self.assertAlmostEqual(row["current_value"], 2215.3, places=2)
        updated = self.client.patch(
            f"/api/tradebook/{created['id']}/quantity", json={"quantity": 10},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        body = updated.json()
        self.assertEqual(body["quantity"], 10)
        self.assertEqual(body["snapshot_price"], 2127.9)
        self.assertEqual(body["current_price"], 2215.3)
        self.assertEqual(body["swing_verdict"], "Buy")
        self.assertEqual(body["overall_verdict"], "Hold")
        self.assertEqual(body["long_verdict"], "Hold")
        self.assertAlmostEqual(body["invested"], 21279.0, places=2)
        self.assertAlmostEqual(body["current_value"], 22153.0, places=2)
        self.assertAlmostEqual(body["pnl"], 874.0, places=2)
        self.assertAlmostEqual(body["pnl_pct"], 4.11, places=2)
        stored = self.client.get(f"/api/tradebook/{created['id']}").json()
        self.assertEqual(stored["quantity"], 10)
        self.assertEqual(stored["snapshot_price"], 2127.9)
        listing = self.client.get("/api/tradebook").json()
        self.assertAlmostEqual(listing["summary"]["invested"], 21279.0, places=2)
        self.assertAlmostEqual(listing["summary"]["current_value"], 22153.0, places=2)
        self.assertAlmostEqual(listing["summary"]["pnl"], 874.0, places=2)
        self.analyse.assert_not_called()

    def test_invalid_quantity_is_rejected(self):
        created = self._create()
        for bad in (0, -3, 1.5, "abc", None):
            res = self.client.patch(
                f"/api/tradebook/{created['id']}/quantity", json={"quantity": bad},
            )
            self.assertEqual(res.status_code, 400, bad)
        stored = self.client.get(f"/api/tradebook/{created['id']}").json()
        self.assertEqual(stored["quantity"], 1)

    def test_quantity_update_does_not_change_entry_signals(self):
        created = self._create()
        later = self.client.patch(
            f"/api/tradebook/{created['id']}/quantity", json={"quantity": 4},
        ).json()
        self.assertEqual(later["overall_score"], 62.0)
        self.assertEqual(later["swing_score"], 71.0)
        self.assertEqual(later["swing_verdict"], "Buy")
        self.assertEqual(later["long_score"], 58.0)
        self.assertEqual(later["swing_regime"], "Healthy Pullback")
        self.assertEqual(later["swing_trend"], "Bullish")
        self.assertEqual(later["opportunity_category"], "Established Opportunity")
        self.assertEqual(later["created_at"], created["created_at"])

    def test_legacy_position_without_quantity_defaults_to_one(self):
        import json
        from pathlib import Path

        created = self._create()
        path = Path(self.tmp.name) / "tradebook" / f"{created['id']}.json"
        raw = json.loads(path.read_text())
        self.assertIn("quantity", raw)
        del raw["quantity"]
        del raw["swing_trend"]
        path.write_text(json.dumps(raw))
        stored = self.client.get(f"/api/tradebook/{created['id']}").json()
        self.assertEqual(stored["quantity"], 1)
        self.assertAlmostEqual(stored["invested"], 2127.9, places=2)
        self.assertEqual(stored["snapshot_price"], 2127.9)
        self.assertEqual(stored["swing_verdict"], "Buy")
        self.assertEqual(stored["quant_evidence"]["trend"], "Bullish")

    def test_entry_signals_survive_a_later_different_analysis(self):
        first = self._create()
        later = _analysis()
        later["overall"] = {"score": 40.0, "verdict": "Reduce", "verdict_class": "reduce"}
        later["horizons"] = deepcopy(later["horizons"])
        later["horizons"]["swing"]["score"] = 35.0
        later["horizons"]["swing"]["verdict"] = "Reduce"
        later["horizons"]["long"]["score"] = 44.0
        later["horizons"]["long"]["verdict"] = "Reduce"
        later["ai"]["thesis"]["opportunity"]["category"] = "No Opportunity"
        second = self.client.post("/api/tradebook", json=later).json()
        stored = self.client.get(f"/api/tradebook/{first['id']}").json()
        self.assertEqual(stored["overall_verdict"], "Hold")
        self.assertEqual(stored["swing_verdict"], "Buy")
        self.assertEqual(stored["long_verdict"], "Hold")
        self.assertEqual(stored["opportunity_category"], "Established Opportunity")
        self.assertEqual(second["overall_verdict"], "Reduce")
        self.assertEqual(second["opportunity_category"], "No Opportunity")


if __name__ == "__main__":
    unittest.main()
