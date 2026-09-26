"""AI stance logging (forward-return measurement) and the updated
contrarian/backtest prompt guidance. No network, no AI calls."""
from __future__ import annotations

import json
import unittest

from app.ai import stance_log
from app.ai.prompts import build_system_prompt
from app.ai.schemas import Thesis


def _thesis(**over):
    base = {
        "headline": "Buy the franchise; respect the price.",
        "business_summary": "Sells widgets to customers.",
        "quality_verdict": "Good business.",
        "valuation_verdict": "Full multiple.",
        "bull_case": ["Growth", "Margins"],
        "bear_case": ["Cyclicality", "Concentration"],
        "what_to_watch": ["Next earnings"],
        "horizon_calls": [
            {
                "horizon": "swing",
                "stance": "Buy",
                "conviction": "Medium",
                "rationale": "Setup is constructive.",
                "what_would_change_it": "Break of support.",
            },
            {
                "horizon": "long",
                "stance": "Hold",
                "conviction": "High",
                "rationale": "Quality, but price is full.",
                "what_would_change_it": "Sustained derating.",
            },
        ],
        "contrarian_note": "No structural blind spot stands out.",
        "data_caveats": ["No segment data."],
    }
    base.update(over)
    return base


class TestStanceLog(unittest.TestCase):
    def test_record_writes_one_row_per_horizon(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "log.jsonl"
            dest = stance_log.record(
                ticker="ANET",
                name="Arista Networks",
                market="US",
                price=206.55,
                thesis=_thesis(),
                horizons={
                    "swing": {"score": 70.6, "verdict": "Buy"},
                    "long": {"score": 61.2, "verdict": "Hold"},
                },
                provider="deepseek",
                model="deepseek-chat",
                path=p,
            )
            self.assertEqual(dest, p)
            rows = stance_log.read_all(p)
            self.assertEqual(len(rows), 2)
            by_hz = {r["horizon"]: r for r in rows}
            self.assertEqual(by_hz["swing"]["ai_stance"], "Buy")
            self.assertEqual(by_hz["swing"]["quant_verdict"], "Buy")
            self.assertEqual(by_hz["long"]["ai_stance"], "Hold")
            self.assertEqual(by_hz["long"]["ai_conviction"], "High")
            self.assertEqual(by_hz["long"]["market"], "US")
            self.assertEqual(by_hz["long"]["price_at_stance"], 206.55)
            self.assertEqual(by_hz["long"]["provider"], "deepseek")
            # JSONL: each line parses independently
            lines = p.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["ticker"], "ANET")

    def test_record_missing_horizon_calls(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "log.jsonl"
            stance_log.record(
                ticker="TCS", name="TCS", market="IN", price=100.0,
                thesis=_thesis(horizon_calls=[]), path=p,
            )
            rows = stance_log.read_all(p)
            self.assertEqual(len(rows), 2)
            self.assertIsNone(rows[0]["ai_stance"])

    def test_record_never_raises(self):
        # Unwritable destination must not propagate.
        self.assertIsNone(
            stance_log.record(
                ticker="X", name="X", market="IN", price=None,
                thesis=_thesis(), path="/proc/definitely-not-here/log.jsonl",
            )
        )

    def test_read_all_missing_file(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(stance_log.read_all(Path(td) / "nope.jsonl"), [])

    def test_default_path_respects_env(self):
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"FINLENS_DATA_DIR": td}):
                self.assertEqual(stance_log.default_path(), Path(td) / "ai_stance_log.jsonl")


class TestContrarianGuidance(unittest.TestCase):
    def test_system_prompt_bans_dcf_relitigation(self):
        for market in ("IN", "US"):
            prompt = build_system_prompt(market)
            self.assertIn("Do NOT use it to re-argue valuation or the DCF", prompt)

    def test_system_prompt_has_backtest_priorities(self):
        for market in ("IN", "US"):
            prompt = build_system_prompt(market)
            self.assertIn("Growth durability first", prompt)
            self.assertIn("A fallen price is not a thesis", prompt)
            self.assertIn("Do not invert these into rules", prompt)

    def test_schema_description_updated(self):
        desc = Thesis.model_json_schema()["properties"]["contrarian_note"]["description"]
        self.assertIn("Do NOT repeat the valuation/DCF argument", desc)
        self.assertIn("structural blind spot", desc)


if __name__ == "__main__":
    unittest.main()
