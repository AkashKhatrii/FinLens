"""Peer selection, snapshots, medians, and fact-pack wiring. No network."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.ai import prompts
from app.engine import peers
from app.engine.valuation import ValuationFacts
from app.engine.fundamentals import FundamentalFacts


def _universe(rows):
    return [{"symbol": r[0], "name": r[0], "industry": r[1], "sector": r[2],
             "market_cap": r[3]} for r in rows]


class TestSelectPeers(unittest.TestCase):
    def setUp(self):
        peers._universe_cache = {
            "US": _universe([
                ("AAPL", "Consumer Electronics", "Technology", 3_000_000_000_000),
                ("MSFT", "Software - Infrastructure", "Technology", 2_800_000_000_000),
                ("GOOGL", "Internet Content & Information", "Communication Services", 2_000_000_000_000),
                ("DELL", "Computer Hardware", "Technology", 80_000_000_000),
                ("HPQ", "Computer Hardware", "Technology", 30_000_000_000),
                ("LOGI", "Computer Hardware", "Technology", 15_000_000_000),
            ]),
            "IN": [],
        }

    def tearDown(self):
        peers._universe_cache = None

    def test_same_industry_ranked_by_cap_proximity(self):
        got, level = peers.select_peers("Computer Hardware", "Technology", "DELL",
                                        80_000_000_000, "US", n=5)
        self.assertEqual(level, "industry")
        tickers = [r["symbol"] for r in got]
        # Subject excluded; closest market caps first.
        self.assertNotIn("DELL", tickers)
        self.assertEqual(tickers, ["HPQ", "LOGI"])

    def test_sector_fallback_when_industry_thin(self):
        got, level = peers.select_peers("Consumer Electronics", "Technology", "AAPL",
                                        3_000_000_000_000, "US", n=5)
        self.assertEqual(level, "sector")
        tickers = [r["symbol"] for r in got]
        self.assertNotIn("AAPL", tickers)
        # MSFT is the closest Technology name by market cap.
        self.assertEqual(tickers[0], "MSFT")

    def test_no_match_returns_none_level(self):
        got, level = peers.select_peers("Oil & Gas", "Energy", "XOM",
                                        500_000_000_000, "US", n=5)
        self.assertEqual((got, level), ([], "none"))

    def test_n_caps_results(self):
        got, _ = peers.select_peers("Computer Hardware", "Technology", "DELL",
                                    80_000_000_000, "US", n=1)
        self.assertEqual(len(got), 1)

    def test_missing_universe_file_is_thin_not_crash(self):
        peers._universe_cache = {"US": [], "IN": []}
        got, level = peers.select_peers("Software", "Technology", "MSFT",
                                        1_000_000_000_000, "US")
        self.assertEqual((got, level), ([], "none"))


class TestSnapshotMetrics(unittest.TestCase):
    def test_extracts_comparison_metrics(self):
        fund = FundamentalFacts(
            net_income=100.0, equity=500.0,
            revenue_series=[1000.0, 900.0, 800.0, 700.0],
            margin_series=[10.0, 9.0, 8.0],
        )
        val = ValuationFacts(pe=20.0, pb=4.0, ev_ebitda=12.0,
                             dividend_yield=1.5)
        bundle = SimpleNamespace(quote=SimpleNamespace(market_cap=1_000_000_000),
                                 market="US")
        m = peers.snapshot_metrics(bundle, fund, val)
        self.assertEqual(m["pe"], 20.0)
        self.assertEqual(m["pb"], 4.0)
        self.assertEqual(m["ev_ebitda"], 12.0)
        self.assertEqual(m["dividend_yield"], 1.5)
        self.assertEqual(m["roe"], 20.0)
        self.assertEqual(m["net_margin"], 10.0)
        # 3y CAGR of [1000, 900, 800, 700]: (1000/700)^(1/3)-1 ≈ 12.6%
        self.assertAlmostEqual(m["revenue_cagr_3y"], 12.62, places=1)

    def test_none_safe(self):
        m = peers.snapshot_metrics(SimpleNamespace(quote=SimpleNamespace(market_cap=None), market="US"),
                                   FundamentalFacts(), ValuationFacts())
        self.assertIsNone(m["roe"])
        self.assertIsNone(m["revenue_cagr_3y"])
        self.assertIsNone(m["pe"])


class TestMedians(unittest.TestCase):
    def test_median_ignores_missing(self):
        snaps = [{"pe": 10.0}, {"pe": 20.0}, {"pe": None}, {"pb": 3.0}]
        med = peers._medians(snaps)
        self.assertEqual(med["pe"], 15.0)
        self.assertEqual(med["pb"], 3.0)
        self.assertIsNone(med["ev_ebitda"])


class TestAnalysePeers(unittest.TestCase):
    def setUp(self):
        peers._universe_cache = {
            "US": _universe([
                ("DELL", "Computer Hardware", "Technology", 80_000_000_000),
                ("HPQ", "Computer Hardware", "Technology", 30_000_000_000),
                ("LOGI", "Computer Hardware", "Technology", 15_000_000_000),
            ]),
            "IN": [],
        }

    def tearDown(self):
        peers._universe_cache = None

    def _bundle(self):
        quote = SimpleNamespace(symbol="DELL", name="Dell", industry="Computer Hardware",
                                sector="Technology", market_cap=80_000_000_000)
        return SimpleNamespace(quote=quote, market="US")

    def test_thin_peer_set_returns_note(self):
        peers._universe_cache = {"US": [], "IN": []}
        out = peers.analyse_peers(self._bundle(), object(),
                                  FundamentalFacts(), ValuationFacts())
        self.assertEqual(out["n"], 0)
        self.assertEqual(out["peers"], [])
        self.assertIn("too thin", out["note"])

    def test_full_flow_with_stubbed_engines(self):
        def fake_bundle(symbol):
            q = SimpleNamespace(symbol=symbol, name=symbol.title(),
                                industry="Computer Hardware", sector="Technology",
                                market_cap=30_000_000_000)
            return SimpleNamespace(quote=q, market="US")

        provider = SimpleNamespace(fetch=fake_bundle)
        fund = FundamentalFacts(net_income=50.0, equity=500.0,
                               revenue_series=[500.0, 450.0, 400.0, 350.0],
                               margin_series=[8.0])
        val = ValuationFacts(pe=15.0, pb=3.0)
        with patch.object(peers.fundamentals, "analyse",
                          return_value=(fund, None, None, None)), \
             patch.object(peers.valuation, "analyse",
                          return_value=(val, None)):
            out = peers.analyse_peers(self._bundle(), provider, fund, val, n=5)
        self.assertEqual(out["n"], 2)
        self.assertEqual(out["match_level"], "industry")
        self.assertEqual([p["ticker"] for p in out["peers"]], ["HPQ", "LOGI"])
        self.assertIn("pe", out["medians"])
        self.assertEqual(out["subject"]["pe"], 15.0)
        for p in out["peers"]:
            self.assertTrue(p["market_cap_display"])


class TestFactPackWiring(unittest.TestCase):
    def _minimal_r(self):
        return {
            "company": {"name": "Dell", "summary": "x"},
            "price": {"last": 100.0},
            "news": [],
            "business_context": {},
            "overall": {}, "horizons": {}, "pillars": {},
            "fundamentals": {}, "valuation": {},
            "technicals": {}, "risk": {}, "earnings": {},
            "ownership": {}, "analysts": {}, "data_gaps": [],
            "peers": {
                "as_of": "2026-09-27T00:00:00+00:00",
                "industry": "Computer Hardware",
                "match_level": "industry",
                "n": 2,
                "peers": [{"ticker": "HPQ", "name": "HP", "market_cap": 1,
                           "market_cap_display": "$1", "pe": 10.0, "pb": 2.0,
                           "ev_ebitda": 8.0, "dividend_yield": 2.0,
                           "revenue_cagr_3y": 5.0, "net_margin": 7.0, "roe": 15.0}],
                "medians": {"pe": 10.0},
                "subject": {"pe": 12.0},
                "note": "Compare the subject against peer medians.",
            },
        }

    def test_peers_in_fact_pack(self):
        from app.analysis import _fact_pack
        pack = _fact_pack(self._minimal_r())
        self.assertIn("peers", pack)
        self.assertEqual(pack["peers"]["n"], 2)
        self.assertEqual(pack["peers"]["peers"][0]["ticker"], "HPQ")

    def test_thin_peers_omitted_from_fact_pack(self):
        from app.analysis import _fact_pack
        r = self._minimal_r()
        r["peers"] = {"n": 0, "peers": [], "note": "too thin"}
        pack = _fact_pack(r)
        self.assertNotIn("peers", pack)


class TestPeerPrompt(unittest.TestCase):
    def test_11c_present_in_both_markets(self):
        for market in ("IN", "US"):
            prompt = prompts.build_system_prompt(market)
            self.assertIn("### 11c. Peer comparison", prompt)
            self.assertIn("apples-to-apples by construction", prompt)

    def test_relative_claim_carve_out(self):
        prompt = prompts.build_system_prompt("IN")
        self.assertIn("cite the metric, the peer count, and the industry", prompt)
        self.assertIn("never generalize", prompt.lower())
