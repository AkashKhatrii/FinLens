"""Growth-leaders screen: CAN SLIM-inspired checklist, not a new horizon score."""
from __future__ import annotations

import unittest
from pathlib import Path

from app.engine.scoring import HORIZONS, OVERALL_BLEND, VERDICT_BANDS
from app.screener.leaders import LETTERS, leaders_from_analysis, sort_leader_rows
from app.screener.quant import failed_row, quant_row_from_analysis, sort_rows


def _analysis(symbol="LEAD", *, overall=61.0, pillars=None, technicals=None, ownership=None):
    return {
        "symbol": symbol,
        "currency_symbol": "₹",
        "company": {"name": symbol},
        "price": {"last": 100.0},
        "overall": {"score": overall, "verdict": "Hold", "verdict_class": "hold"},
        "horizons": {
            "swing": {"score": 55, "verdict": "Hold", "verdict_class": "hold"},
            "long": {"score": 65, "verdict": "Hold", "verdict_class": "hold"},
        },
        "pillars": pillars or {},
        "technicals": technicals or {},
        "ownership": ownership or {},
    }


def _pillars(**values):
    metrics = [{"key": k, "value": v} for k, v in values.items()]
    return {"growth": {"metrics": metrics}}


class TestLeadersDoesNotRescore(unittest.TestCase):
    def test_blend_and_bands_unchanged(self):
        self.assertEqual(OVERALL_BLEND, {"swing": 0.40, "long": 0.60})
        self.assertEqual(HORIZONS["swing"]["weights"]["technical_trend"], 0.26)
        self.assertEqual(tuple(VERDICT_BANDS[0]), (80, "Strong Buy", "strong-buy"))

    def test_module_does_not_import_score_all(self):
        src = Path(__file__).resolve().parents[1] / "app" / "screener" / "leaders.py"
        text = src.read_text()
        self.assertNotIn("score_all", text)
        self.assertNotIn("OVERALL_BLEND", text)


class TestLeadersFromAnalysis(unittest.TestCase):
    def test_passes_letters_on_growth_leader_inputs(self):
        result = _analysis(
            pillars=_pillars(q_pat_yoy=28, pat_cagr=22, roe=19),
            technicals={
                "week52_position": 88,
                "volume_ratio": 1.5,
                "relative_strength": {"3m": 6.0},
            },
            ownership={"institutions_pct": 28},
        )
        view = leaders_from_analysis(result)
        self.assertEqual(view["letters_passed"], 6)
        self.assertEqual(view["letters_scored"], 6)
        self.assertTrue(all(view["letters"][k]["pass"] for k in LETTERS))
        self.assertGreaterEqual(view["leader_score"], 70)
        self.assertNotEqual(view["leader_score"], result["overall"]["score"])

    def test_laggard_fails_relative_strength_and_highs(self):
        result = _analysis(
            overall=72,
            pillars=_pillars(q_pat_yoy=-5, pat_cagr=3, roe=8),
            technicals={
                "week52_position": 20,
                "volume_ratio": 0.7,
                "relative_strength": {"3m": -12.0},
            },
            ownership={"institutions_pct": 4},
        )
        view = leaders_from_analysis(result)
        self.assertEqual(view["letters_passed"], 0)
        self.assertFalse(view["letters"]["L"]["pass"])
        self.assertFalse(view["letters"]["C"]["pass"])
        self.assertEqual(result["overall"]["score"], 72)

    def test_missing_metrics_are_skipped_not_failed(self):
        view = leaders_from_analysis(_analysis())
        self.assertEqual(view["letters_scored"], 0)
        self.assertIsNone(view["leader_score"])
        self.assertTrue(all(v["pass"] is None for v in view["letters"].values()))

    def test_m_is_not_a_letter(self):
        self.assertEqual(LETTERS, ("C", "A", "N", "S", "L", "I"))

    def test_quant_row_keeps_scores_and_attaches_leaders(self):
        result = _analysis(
            overall=58.2,
            pillars=_pillars(q_pat_yoy=30, pat_cagr=18),
            technicals={"week52_position": 90, "volume_ratio": 1.3, "relative_strength": {"3m": 2}},
            ownership={"institutions_pct": 20},
        )
        row = quant_row_from_analysis(result)
        self.assertEqual(row["overall_score"], 58.2)
        self.assertIn("leaders", row)
        self.assertGreaterEqual(row["leaders"]["letters_passed"], 5)

    def test_failed_row_has_empty_leaders_not_failed_letters(self):
        row = failed_row("GAP")
        self.assertIsNone(row["leaders"]["leader_score"])
        self.assertTrue(all(v["pass"] is None for v in row["leaders"]["letters"].values()))

    def test_sort_puts_more_letters_first(self):
        weak = quant_row_from_analysis(_analysis(
            "WEAK",
            overall=81,
            pillars=_pillars(q_pat_yoy=2),
            technicals={"relative_strength": {"3m": -8}},
        ))
        strong = quant_row_from_analysis(_analysis(
            "STRG",
            overall=49,
            pillars=_pillars(q_pat_yoy=40, pat_cagr=25, roe=20),
            technicals={"week52_position": 92, "volume_ratio": 1.8, "relative_strength": {"3m": 10}},
            ownership={"institutions_pct": 30},
        ))
        ordered = sort_leader_rows([weak, strong])
        self.assertEqual([r["symbol"] for r in ordered], ["STRG", "WEAK"])
        self.assertEqual([r["symbol"] for r in sort_rows([weak, strong], "leaders")], ["STRG", "WEAK"])
        self.assertGreater(strong["overall_score"], 40)
        self.assertLess(strong["overall_score"], weak["overall_score"])

    def test_annual_falls_back_to_roe_when_cagr_missing(self):
        view = leaders_from_analysis(_analysis(pillars=_pillars(roe=19)))
        self.assertTrue(view["letters"]["A"]["pass"])
        fail = leaders_from_analysis(_analysis(pillars=_pillars(roe=8)))
        self.assertFalse(fail["letters"]["A"]["pass"])


class TestLeadersUI(unittest.TestCase):
    def test_growth_leaders_tab_is_separate_from_quant_scores(self):
        html = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text()
        self.assertIn("selectNiftyIndex('LEADERS')", html)
        self.assertIn("params.has('leaders')", html)
        self.assertIn("param: 'leaders'", html)
        self.assertIn("Growth Leaders", html)
        self.assertIn("Market (M) skipped", html)
        self.assertIn("/api/screener/quant", html)
        nifty_js = html[html.find("async loadNifty"): html.find("viewNiftyStock")]
        self.assertNotIn("ai=true", nifty_js)
        self.assertIn("/api/screener/quant?q=${encodeURIComponent(c.symbol)}", html)
        self.assertIn("&market=${encodeURIComponent(spec.market || 'IN')}", html)


if __name__ == "__main__":
    unittest.main()
