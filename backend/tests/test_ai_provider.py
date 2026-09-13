"""AI provider selection and DeepSeek JSON thesis parsing."""
from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.ai import analyst
from app.ai.schemas import Thesis


VALID_THESIS = {
    "headline": "Hold TCS; quality is high but the multiple is full.",
    "business_summary": "TCS sells IT services to global enterprises.",
    "quality_verdict": "Durable franchise with high ROCE.",
    "valuation_verdict": "P/E sits above its own history.",
    "bull_case": ["Deal wins", "Margin defence", "Cash conversion"],
    "bear_case": ["Wage inflation", "Client concentration", "Multiple compression"],
    "key_risks": ["US budget cuts", "Visa policy", "INR spike"],
    "what_to_watch": ["Next quarter TCV", "Attrition", "Large-deal pipeline"],
    "horizon_calls": [
        {
            "horizon": "swing",
            "stance": "Hold",
            "conviction": "Medium",
            "rationale": "Waiting on the next print.",
            "what_would_change_it": "A beat with raised guidance.",
        },
        {
            "horizon": "long",
            "stance": "Buy",
            "conviction": "High",
            "rationale": "Compounder at a fair-to-full price.",
            "what_would_change_it": "Sustained ROCE below cost of capital.",
        },
    ],
    "contrarian_note": "The quant score overweights near-term technicals.",
    "data_caveats": ["No concall transcript"],
}


class TestAiProvider(unittest.TestCase):
    def test_default_provider_is_deepseek_and_ignores_claude_key(self):
        env = {
            "FINLENS_AI": "auto",
            "ANTHROPIC_API_KEY": "sk-ant-not-used",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("DEEPSEEK_API_KEY", None)
            os.environ.pop("FINLENS_PROVIDER", None)
            status = analyst.status()
        self.assertFalse(status["available"])
        self.assertIn("DEEPSEEK_API_KEY", status["reason"])

    def test_status_reports_deepseek_when_key_present(self):
        env = {
            "FINLENS_AI": "auto",
            "FINLENS_PROVIDER": "deepseek",
            "DEEPSEEK_API_KEY": "sk-test-deepseek",
        }
        with patch.dict(os.environ, env, clear=False):
            status = analyst.status()
        self.assertTrue(status["available"])
        self.assertEqual(status["provider"], "deepseek")
        self.assertEqual(status["model"], "deepseek-v4-flash")

    def test_openai_compat_parses_valid_json_thesis(self):
        fake = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(VALID_THESIS)))],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=22),
        )
        env = {
            "FINLENS_AI": "auto",
            "FINLENS_PROVIDER": "deepseek",
            "DEEPSEEK_API_KEY": "sk-test-deepseek",
        }
        with patch.dict(os.environ, env, clear=False), \
             patch.object(analyst, "_openai_complete", return_value=fake):
            out = analyst.generate_thesis({"symbol": "TCS.NS"}, "TCS.NS", "TCS")
        self.assertIsNotNone(out)
        self.assertNotIn("error", out)
        self.assertEqual(out["provider"], "deepseek")
        self.assertEqual(out["model"], "deepseek-v4-flash")
        Thesis.model_validate(out["thesis"])
        self.assertEqual(out["usage"]["input_tokens"], 11)

    def test_openai_compat_schema_mismatch_is_an_error(self):
        fake = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"headline":"nope"}'))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )
        env = {
            "FINLENS_AI": "auto",
            "FINLENS_PROVIDER": "deepseek",
            "DEEPSEEK_API_KEY": "sk-test-deepseek",
        }
        with patch.dict(os.environ, env, clear=False), \
             patch.object(analyst, "_openai_complete", return_value=fake):
            out = analyst.generate_thesis({"symbol": "TCS.NS"}, "TCS.NS", "TCS")
        self.assertIn("error", out)
        self.assertIn("format", out["error"].lower())


if __name__ == "__main__":
    unittest.main()
