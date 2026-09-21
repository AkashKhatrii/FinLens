"""Nifty 50 quant screener: consume existing analyse() results, never score."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from app.engine.scoring import HORIZONS, OVERALL_BLEND, VERDICT_BANDS
from app.screener.quant import (
    analyse_quant_row,
    analyse_universe,
    failed_row,
    lowest_overall_rows,
    quant_row_from_analysis,
    sort_rows,
    summarize_rows,
)

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def _analysis(
    symbol: str,
    name: str,
    *,
    overall: float,
    overall_verdict: str,
    swing: float,
    swing_verdict: str,
    long: float,
    long_verdict: str,
    price: float = 100.0,
    overall_class: str | None = None,
) -> dict:
    cls = {
        "Strong Buy": "strong-buy",
        "Buy": "buy",
        "Hold": "hold",
        "Reduce": "reduce",
        "Avoid": "avoid",
    }
    return {
        "symbol": symbol,
        "currency_symbol": "₹",
        "company": {"name": name},
        "price": {"last": price},
        "overall": {
            "score": overall,
            "verdict": overall_verdict,
            "verdict_class": overall_class or cls[overall_verdict],
        },
        "horizons": {
            "swing": {
                "score": swing,
                "verdict": swing_verdict,
                "verdict_class": cls[swing_verdict],
            },
            "long": {
                "score": long,
                "verdict": long_verdict,
                "verdict_class": cls[long_verdict],
            },
        },
        "ai": {"thesis": {"headline": "should not leak"}},
        "accumulation": {"state": "Accumulate"},
        "opportunity": {"category": "Established Opportunity"},
    }


class TestQuantRowMapping(unittest.TestCase):
    def test_copies_overall_swing_long_without_transform(self):
        result = _analysis(
            "TESTCO", "Test Co",
            overall=69, overall_verdict="Buy",
            swing=71, swing_verdict="Buy",
            long=68, long_verdict="Buy",
            price=117.5,
        )
        row = quant_row_from_analysis(result)
        self.assertEqual(row["symbol"], "TESTCO")
        self.assertEqual(row["name"], "Test Co")
        self.assertEqual(row["price"], 117.5)
        self.assertEqual(row["overall_score"], 69)
        self.assertEqual(row["overall_verdict"], "Buy")
        self.assertEqual(row["swing_score"], 71)
        self.assertEqual(row["long_score"], 68)
        self.assertEqual(row["href"], "/?q=TESTCO")
        self.assertIsNone(row["error"])
        self.assertNotIn("ai", row)
        self.assertNotIn("accumulation", row)
        self.assertNotIn("opportunity", row)

    def test_yahoo_suffix_is_stripped_for_display_and_click_through(self):
        result = _analysis(
            "INFY.NS", "Infosys Limited",
            overall=61.8, overall_verdict="Hold",
            swing=56.0, swing_verdict="Hold",
            long=65.7, long_verdict="Hold",
        )
        row = quant_row_from_analysis(result)
        self.assertEqual(row["symbol"], "INFY")
        self.assertEqual(row["href"], "/?q=INFY")

    def test_unavailable_scores_remain_null(self):
        row = failed_row("MISSING", "Missing Ltd", error="timeout")
        self.assertIsNone(row["overall_score"])
        self.assertIsNone(row["swing_score"])
        self.assertIsNone(row["long_score"])
        self.assertIsNone(row["price"])
        self.assertEqual(row["symbol"], "MISSING")
        self.assertEqual(row["href"], "/?q=MISSING")


class TestBatchAnalysis(unittest.TestCase):
    def test_exactly_one_result_per_constituent(self):
        constituents = [
            {"symbol": "AAA", "name": "Alpha"},
            {"symbol": "BBB", "name": "Beta"},
            {"symbol": "CCC", "name": "Gamma"},
        ]

        def fake_analyse(q, market="IN", use_ai=True, **kwargs):
            self.assertFalse(use_ai)
            score = {"AAA": 80, "BBB": 55, "CCC": 40}[q]
            verdict = {80: "Strong Buy", 55: "Hold", 40: "Reduce"}[score]
            return _analysis(
                q, q, overall=score, overall_verdict=verdict,
                swing=score, swing_verdict=verdict,
                long=score, long_verdict=verdict,
            )

        rows = analyse_universe(constituents, analyse_fn=fake_analyse, max_workers=2)
        self.assertEqual([r["symbol"] for r in rows], ["AAA", "BBB", "CCC"])
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({r["symbol"] for r in rows}), 3)

    def test_one_failure_does_not_fail_the_batch(self):
        constituents = [
            {"symbol": "OK1", "name": "Ok One"},
            {"symbol": "BAD", "name": "Broken"},
            {"symbol": "OK2", "name": "Ok Two"},
        ]

        def fake_analyse(q, market="IN", use_ai=True, **kwargs):
            if q == "BAD":
                raise RuntimeError("provider timeout")
            return _analysis(
                q, q, overall=60, overall_verdict="Hold",
                swing=60, swing_verdict="Hold",
                long=60, long_verdict="Hold",
            )

        rows = analyse_universe(constituents, analyse_fn=fake_analyse, max_workers=3)
        self.assertEqual(len(rows), 3)
        by_symbol = {r["symbol"]: r for r in rows}
        self.assertEqual(by_symbol["OK1"]["overall_score"], 60)
        self.assertIsNone(by_symbol["BAD"]["overall_score"])
        self.assertIsNotNone(by_symbol["BAD"]["error"])
        self.assertEqual(by_symbol["OK2"]["overall_score"], 60)

    def test_never_requests_ai(self):
        seen = []

        def fake_analyse(q, market="IN", use_ai=True, **kwargs):
            seen.append(use_ai)
            return _analysis(
                q, q, overall=66, overall_verdict="Buy",
                swing=66, swing_verdict="Buy",
                long=66, long_verdict="Buy",
            )

        analyse_quant_row("ZZZ", analyse_fn=fake_analyse)
        analyse_universe(
            [{"symbol": "AAA", "name": "A"}],
            analyse_fn=fake_analyse,
            max_workers=1,
        )
        self.assertTrue(seen)
        self.assertTrue(all(flag is False for flag in seen))

    def test_screener_module_does_not_call_the_analyst(self):
        src = Path(__file__).resolve().parents[1] / "app" / "screener" / "quant.py"
        text = src.read_text()
        self.assertNotIn("analyst.", text)
        self.assertNotIn("use_ai=True", text)
        self.assertIn("use_ai=False", text)


class TestSortingAndSummary(unittest.TestCase):
    def setUp(self):
        self.rows = [
            quant_row_from_analysis(_analysis(
                "LOW", "Low", overall=40, overall_verdict="Reduce",
                swing=80, swing_verdict="Strong Buy",
                long=30, long_verdict="Avoid", price=10,
            )),
            quant_row_from_analysis(_analysis(
                "MID", "Mid", overall=60, overall_verdict="Hold",
                swing=50, swing_verdict="Hold",
                long=70, long_verdict="Buy", price=20,
            )),
            quant_row_from_analysis(_analysis(
                "HIGH", "High", overall=80, overall_verdict="Strong Buy",
                swing=40, swing_verdict="Reduce",
                long=90, long_verdict="Strong Buy", price=30,
            )),
            failed_row("GAP", "Gap Co"),
        ]

    def test_default_sort_is_overall_descending_with_nulls_last(self):
        ordered = sort_rows(self.rows, "overall", descending=True)
        self.assertEqual([r["symbol"] for r in ordered], ["HIGH", "MID", "LOW", "GAP"])

    def test_sort_swing_and_long(self):
        swing_desc = sort_rows(self.rows, "swing", descending=True)
        self.assertEqual([r["symbol"] for r in swing_desc[:3]], ["LOW", "MID", "HIGH"])
        long_asc = sort_rows(self.rows, "long", descending=False)
        self.assertEqual([r["symbol"] for r in long_asc[:3]], ["LOW", "MID", "HIGH"])

    def test_buy_hold_reduce_summary_and_median(self):
        stats = summarize_rows(self.rows)
        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["analyzed"], 3)
        self.assertEqual(stats["buy"], 1)
        self.assertEqual(stats["hold"], 1)
        self.assertEqual(stats["reduce_avoid"], 1)
        self.assertEqual(stats["median_overall"], 60)


class TestScoringUnchangedAndBankPathIntact(unittest.TestCase):
    def test_individual_stock_scoring_constants_are_untouched(self):
        self.assertEqual(OVERALL_BLEND, {"swing": 0.40, "long": 0.60})
        self.assertEqual(HORIZONS["swing"]["weights"]["technical_trend"], 0.26)
        self.assertEqual(HORIZONS["long"]["weights"]["profitability"], 0.22)
        self.assertEqual(VERDICT_BANDS[0][:2], (80, "Strong Buy"))

    def test_quant_row_goes_through_existing_analyse(self):
        with patch("app.analysis.analyse") as mocked:
            mocked.return_value = _analysis(
                "BANKX", "Bank X",
                overall=61, overall_verdict="Hold",
                swing=55, swing_verdict="Hold",
                long=66, long_verdict="Buy",
            )
            row = analyse_quant_row("BANKX")
            mocked.assert_called_once()
            kwargs = mocked.call_args.kwargs
            self.assertFalse(kwargs.get("use_ai", True))
            self.assertEqual(row["overall_score"], 61)
            self.assertEqual(row["long_score"], 66)

    def test_click_through_and_ui_are_quant_only(self):
        html = (STATIC / "index.html").read_text()
        self.assertIn("niftyIndexName", html)
        self.assertIn("openNifty50", html)
        self.assertIn("selectNiftyIndex('NIFTY50')", html)
        self.assertIn("selectNiftyIndex('NIFTY100')", html)
        self.assertIn("selectNiftyIndex('LOW_SCORE')", html)
        self.assertIn("viewNiftyStock", html)
        self.assertIn("/api/screener/quant", html)
        self.assertIn("ai=false", html)
        self.assertIn("`/api/screener/quant?q=${encodeURIComponent(c.symbol)}`", html)
        nifty_js = html[html.find("async loadNifty"): html.find("viewNiftyStock")]
        self.assertNotIn("ai=true", nifty_js)
        self.assertNotIn("runThesis", nifty_js)
        self.assertNotIn("/api/analyse", nifty_js)
        self.assertIn("/api/indexes/' + encodeURIComponent(id) + '/constituents'", html)

    def test_index_switch_keeps_nifty50_url_and_adds_nifty100(self):
        html = (STATIC / "index.html").read_text()
        self.assertIn("params.has('nifty50')", html)
        self.assertIn("params.has('nifty100')", html)
        self.assertIn("params.has('lowscore')", html)
        self.assertIn("param: 'nifty50'", html)
        self.assertIn("param: 'nifty100'", html)
        self.assertIn("param: 'lowscore'", html)
        self.assertIn("Nifty 50", html)
        self.assertIn("Nifty 100", html)
        self.assertIn("Low-Score Validation", html)
        self.assertIn("50 lowest Overall scores from the current Nifty 500 universe.", html)
        self.assertIn("openNifty('NIFTY50')", html)
        self.assertIn("openNifty('NIFTY100')", html)
        self.assertIn("openNifty('LOW_SCORE')", html)
        self.assertIn("indexId: 'NIFTY500'", html)

    def test_click_through_href_points_at_existing_stock_page(self):
        row = quant_row_from_analysis(_analysis(
            "TESTCO", "Test Co", overall=69, overall_verdict="Buy",
            swing=71, swing_verdict="Buy", long=68, long_verdict="Buy",
        ))
        self.assertEqual(row["href"], "/?q=TESTCO")
        html = (STATIC / "index.html").read_text()
        self.assertIn("viewNiftyStock(row.symbol)", html)
        start = html.find("viewNiftyStock(symbol)")
        self.assertGreater(start, 0)
        self.assertIn("this.run()", html[start:start + 250])

    def test_bank_quantitative_path_still_runs_when_ai_is_off(self):
        analysis_src = (
            Path(__file__).resolve().parents[1] / "app" / "analysis.py"
        ).read_text()
        self.assertLess(
            analysis_src.index("apply_bank_metrics"),
            analysis_src.index("if not use_ai:"),
        )
        screener_src = (
            Path(__file__).resolve().parents[1] / "app" / "screener" / "quant.py"
        ).read_text()
        self.assertNotIn("nifty50", screener_src.lower())
        self.assertNotIn("skip_bank", screener_src)

    def test_scoring_engine_has_no_nifty_branch(self):
        engine = Path(__file__).resolve().parents[1] / "app" / "engine"
        for name in ("scoring.py", "bank_scoring.py"):
            text = (engine / name).read_text().lower()
            self.assertNotIn("nifty50", text)
            self.assertNotIn("if nifty", text)


class TestSummaryAndDuplicates(unittest.TestCase):
    def test_even_count_median_is_midpoint(self):
        rows = [
            quant_row_from_analysis(_analysis(
                "A", "A", overall=40, overall_verdict="Reduce",
                swing=40, swing_verdict="Reduce", long=40, long_verdict="Reduce",
            )),
            quant_row_from_analysis(_analysis(
                "B", "B", overall=80, overall_verdict="Strong Buy",
                swing=80, swing_verdict="Strong Buy", long=80, long_verdict="Strong Buy",
            )),
        ]
        self.assertEqual(summarize_rows(rows)["median_overall"], 60)

    def test_duplicate_constituents_yield_one_row(self):
        constituents = [
            {"symbol": "AAA", "name": "Alpha"},
            {"symbol": "AAA", "name": "Alpha Dup"},
            {"symbol": "BBB", "name": "Beta"},
        ]
        calls = []

        def fake_analyse(q, market="IN", use_ai=True, **kwargs):
            calls.append(q)
            return _analysis(
                q, q, overall=70, overall_verdict="Buy",
                swing=70, swing_verdict="Buy", long=70, long_verdict="Buy",
            )

        rows = analyse_universe(constituents, analyse_fn=fake_analyse, max_workers=2)
        self.assertEqual([r["symbol"] for r in rows], ["AAA", "BBB"])
        self.assertEqual(calls, ["AAA", "BBB"])


class TestLowestOverallSelection(unittest.TestCase):
    def _row(self, symbol, overall, verdict, *, swing=90, long=90):
        return quant_row_from_analysis(_analysis(
            symbol, symbol,
            overall=overall, overall_verdict=verdict,
            swing=swing, swing_verdict="Strong Buy",
            long=long, long_verdict="Strong Buy",
        ))

    def test_selects_n_lowest_overall_only(self):
        rows = []
        for i in range(60):
            score = 10 + i
            verdict = "Avoid" if score < 35 else "Reduce" if score < 50 else "Hold" if score < 66 else "Buy"
            rows.append(self._row(f"C{i:02d}", score, verdict, swing=99, long=99))
        rows.append(failed_row("MISSING", "Missing"))
        selected = lowest_overall_rows(rows, n=50)
        self.assertEqual(len(selected), 50)
        self.assertEqual([r["symbol"] for r in selected], [f"C{i:02d}" for i in range(50)])
        self.assertTrue(all(r["overall_score"] is not None for r in selected))
        self.assertNotIn("C59", [r["symbol"] for r in selected])
        self.assertNotIn("MISSING", [r["symbol"] for r in selected])

    def test_selection_ignores_verdict_and_other_scores(self):
        rows = [
            self._row("LOWBUY", 20, "Buy", swing=10, long=10),
            self._row("HIGHAVOID", 90, "Avoid", swing=5, long=5),
            self._row("MIDHOLD", 40, "Hold", swing=1, long=1),
        ]
        selected = lowest_overall_rows(rows, n=2)
        self.assertEqual([r["symbol"] for r in selected], ["LOWBUY", "MIDHOLD"])
        self.assertEqual(selected[0]["overall_verdict"], "Buy")
        self.assertNotIn("HIGHAVOID", [r["symbol"] for r in selected])

    def test_changing_overall_score_changes_membership(self):
        rows = [
            self._row("AAA", 30, "Reduce"),
            self._row("BBB", 40, "Reduce"),
            self._row("CCC", 50, "Hold"),
        ]
        first = {r["symbol"] for r in lowest_overall_rows(rows, n=2)}
        self.assertEqual(first, {"AAA", "BBB"})
        rows[0] = self._row("AAA", 80, "Buy")
        second = {r["symbol"] for r in lowest_overall_rows(rows, n=2)}
        self.assertEqual(second, {"BBB", "CCC"})

    def test_does_not_hardcode_tickers_or_force_reduce(self):
        src = Path(__file__).resolve().parents[1] / "app" / "screener" / "quant.py"
        text = src.read_text()
        self.assertIn("overall_score", text)
        fn = text[text.find("def lowest_overall_rows"): text.find("def _display_symbol")]
        self.assertNotIn("Reduce", fn)
        self.assertNotIn("Avoid", fn)
        self.assertNotIn("RELIANCE", fn)
        html = (STATIC / "index.html").read_text()
        self.assertIn("lowestOverallRows", html)
        method = html[html.find("lowestOverallRows(rows, n)"): html.find("sortNiftyRows(rows)")]
        self.assertIn("overall_score", method)


class TestScreenerApi(unittest.TestCase):
    def test_unknown_index_is_404(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        res = client.get("/api/indexes/NIFTY200/constituents")
        self.assertEqual(res.status_code, 404)

    def test_nifty50_and_nifty100_constituent_endpoints(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.providers.index_constituents import Constituent, IndexUniverse

        def universe(index_id: str, name: str) -> IndexUniverse:
            return IndexUniverse(
                index_id=index_id,
                name=name,
                constituents=[
                    Constituent("AAA", "Alpha"),
                    Constituent("BBB", "Beta"),
                ],
                source_url=f"https://archives.nseindia.com/content/indices/ind_{index_id.lower()}list.csv",
            )

        client = TestClient(app)
        for index_id, name in (("NIFTY50", "Nifty 50"), ("NIFTY100", "Nifty 100"), ("NIFTY500", "Nifty 500")):
            with patch("app.main.get_index_constituents", return_value=universe(index_id, name)):
                res = client.get(f"/api/indexes/{index_id}/constituents")
            self.assertEqual(res.status_code, 200, index_id)
            body = res.json()
            self.assertEqual(body["index"], index_id)
            self.assertEqual(body["name"], name)
            self.assertEqual(body["count"], 2)
            self.assertEqual([c["symbol"] for c in body["constituents"]], ["AAA", "BBB"])

    def test_quant_endpoint_never_requests_ai(self):
        from fastapi.testclient import TestClient
        from app.main import app

        with patch("app.analysis.analyse") as mocked:
            mocked.return_value = _analysis(
                "AAA", "Alpha",
                overall=69, overall_verdict="Buy",
                swing=71, swing_verdict="Buy",
                long=68, long_verdict="Buy",
                price=117.5,
            )
            client = TestClient(app)
            res = client.get("/api/screener/quant", params={"q": "AAA"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["overall_score"], 69)
        self.assertEqual(body["swing_score"], 71)
        self.assertEqual(body["long_score"], 68)
        self.assertEqual(body["href"], "/?q=AAA")
        self.assertNotIn("ai", body)
        mocked.assert_called_once()
        self.assertFalse(mocked.call_args.kwargs.get("use_ai", True))


if __name__ == "__main__":
    unittest.main()
