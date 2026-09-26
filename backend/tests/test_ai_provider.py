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


class TestProviderOverride(unittest.TestCase):
    def test_resolve_provider_accepts_claude_without_changing_env_default(self):
        from app.config import resolve_provider

        env = {"FINLENS_PROVIDER": "deepseek"}
        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(resolve_provider(), "deepseek")
            self.assertEqual(resolve_provider("claude"), "claude")
            self.assertEqual(resolve_provider("CLAUDE"), "claude")
            self.assertEqual(resolve_provider("nope"), "deepseek")

    def test_using_provider_overrides_provider_key_for_the_request(self):
        from app.config import provider_key, using_provider

        env = {"FINLENS_PROVIDER": "deepseek"}
        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(provider_key(), "deepseek")
            with using_provider("claude"):
                self.assertEqual(provider_key(), "claude")
            self.assertEqual(provider_key(), "deepseek")

    def test_status_can_report_claude_while_env_default_is_deepseek(self):
        env = {
            "FINLENS_AI": "auto",
            "FINLENS_PROVIDER": "deepseek",
            "DEEPSEEK_API_KEY": "sk-test-deepseek",
            "ANTHROPIC_API_KEY": "sk-ant-test",
        }
        with patch.dict(os.environ, env, clear=False), \
             patch.object(analyst, "_get_anthropic_client", return_value=object()), \
             patch.object(analyst, "_claude_has_credentials", return_value=True):
            default = analyst.status()
            claude = analyst.status("claude")
            catalog = analyst.provider_catalog()
        self.assertEqual(default["provider"], "deepseek")
        self.assertTrue(default["available"])
        self.assertEqual(claude["provider"], "claude")
        self.assertTrue(claude["available"])
        keys = [p["key"] for p in catalog["providers"]]
        self.assertEqual(keys, ["deepseek", "claude"])
        by_key = {p["key"]: p for p in catalog["providers"]}
        self.assertTrue(by_key["deepseek"]["available"])
        self.assertTrue(by_key["claude"]["available"])

    def test_generate_thesis_uses_claude_when_provider_is_overridden(self):
        from app.config import using_provider

        fake = {
            "thesis": VALID_THESIS,
            "provider": "claude",
            "model": "claude-opus-5",
            "usage": {"input_tokens": 1, "output_tokens": 1, "cache_read": 0, "cache_write": 0},
        }
        env = {
            "FINLENS_AI": "auto",
            "FINLENS_PROVIDER": "deepseek",
            "DEEPSEEK_API_KEY": "sk-test-deepseek",
            "ANTHROPIC_API_KEY": "sk-ant-test",
        }
        with patch.dict(os.environ, env, clear=False), \
             patch.object(analyst, "_get_anthropic_client", return_value=object()), \
             patch.object(analyst, "_claude_has_credentials", return_value=True), \
             patch.object(analyst, "_claude_thesis", return_value=fake) as claude_call, \
             patch.object(analyst, "_openai_compat_thesis") as deepseek_call:
            with using_provider("claude"):
                out = analyst.generate_thesis({"symbol": "TCS.NS"}, "TCS.NS", "TCS")
        self.assertEqual(out["provider"], "claude")
        claude_call.assert_called_once()
        deepseek_call.assert_not_called()

    def test_claude_auth_failure_is_an_error_not_a_silent_empty_thesis(self):
        import anthropic
        import httpx2
        from app.config import using_provider

        req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        resp = httpx2.Response(401, request=req)
        err = anthropic.AuthenticationError(
            "API key is invalid.",
            response=resp,
            body={"error": {"type": "authentication_error", "message": "API key is invalid."}},
        )

        class FakeMessages:
            def parse(self, **kwargs):
                raise err

        env = {
            "FINLENS_AI": "auto",
            "FINLENS_PROVIDER": "deepseek",
            "DEEPSEEK_API_KEY": "sk-test-deepseek",
            "ANTHROPIC_API_KEY": "sk-ant-test",
        }
        with patch.dict(os.environ, env, clear=False), \
             patch.object(analyst, "_get_anthropic_client", return_value=SimpleNamespace(messages=FakeMessages())), \
             patch.object(analyst, "_claude_has_credentials", return_value=True):
            with using_provider("claude"):
                out = analyst.generate_thesis({"symbol": "TCS.NS"}, "TCS.NS", "TCS")
        self.assertIsNotNone(out)
        self.assertIn("error", out)
        self.assertIn("rejected", out["error"].lower())
        self.assertNotIn("thesis", out)

    def test_claude_thesis_disables_thinking(self):
        captured = {}

        class FakeMessages:
            def parse(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    stop_reason="end_turn",
                    parsed_output=Thesis.model_validate(VALID_THESIS),
                    usage=SimpleNamespace(
                        input_tokens=1,
                        output_tokens=1,
                        cache_read_input_tokens=0,
                        cache_creation_input_tokens=0,
                    ),
                )

        with patch.object(analyst, "_get_anthropic_client", return_value=SimpleNamespace(messages=FakeMessages())):
            out = analyst._claude_thesis("{}", "TCS.NS", "TCS", "claude-opus-5")
        self.assertNotIn("error", out)
        self.assertEqual(captured["thinking"], {"type": "disabled"})
        self.assertEqual(captured["output_config"]["effort"], "high")
        self.assertLessEqual(captured["max_tokens"], 8192)

    def test_claude_client_sends_workspace_header_when_configured(self):
        analyst._anthropic_client = None
        env = {
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "ANTHROPIC_WORKSPACE_ID": "wrkspc_test",
        }
        try:
            with patch.dict(os.environ, env, clear=False), \
                 patch.object(analyst.anthropic, "Anthropic", return_value=object()) as ctor:
                analyst._get_anthropic_client()
            self.assertEqual(
                ctor.call_args.kwargs["default_headers"]["anthropic-workspace-id"],
                "wrkspc_test",
            )
        finally:
            analyst._anthropic_client = None

    def test_claude_falls_back_to_claude_api_key_when_anthropic_key_is_missing(self):
        from app.config import anthropic_api_key

        env = {"CLAUDE_API_KEY": "sk-ant-cursor"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
            self.assertEqual(anthropic_api_key(), "sk-ant-cursor")
            self.assertTrue(analyst._claude_has_credentials())

    def test_anthropic_api_key_is_preferred_over_claude_api_key(self):
        from app.config import anthropic_api_key

        env = {
            "ANTHROPIC_API_KEY": "sk-ant-env",
            "CLAUDE_API_KEY": "sk-ant-cursor",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(anthropic_api_key(), "sk-ant-env")


class TestUiProviderSwitch(unittest.TestCase):
    def test_index_has_a_provider_selector(self):
        from pathlib import Path

        html = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text()
        self.assertIn('v-model="aiProvider"', html)
        self.assertIn("aiProviders", html)
        self.assertIn("provider=", html)
        self.assertIn("DeepSeek", html)
        self.assertIn("Claude", html)


if __name__ == "__main__":
    unittest.main()
