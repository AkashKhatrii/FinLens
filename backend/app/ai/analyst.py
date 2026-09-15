"""Turns the fact pack into a structured thesis.

DeepSeek is the default (OpenAI-compatible JSON mode). Claude remains available
when FINLENS_PROVIDER=claude. With no credentials the endpoint still returns
the full quantitative analysis and omits a usable `ai` block.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import anthropic
import openai
from openai import OpenAI
from pydantic import ValidationError

from ..config import (
    AI_ENABLED,
    ANTHROPIC_EFFORT,
    PROVIDERS,
    anthropic_api_key,
    anthropic_workspace_id,
    provider_key,
    provider_model,
    resolve_provider,
)
from .prompts import SYSTEM_PROMPT, build_json_user_prompt, build_user_prompt
from .schemas import Thesis

log = logging.getLogger(__name__)

NO_DEEPSEEK = (
    "No DeepSeek credentials found. Set DEEPSEEK_API_KEY in backend/.env "
    "to enable the AI thesis."
)
NO_CLAUDE = (
    "No Anthropic credentials found. Set ANTHROPIC_API_KEY in backend/.env "
    "(or run `ant auth login`) to enable the AI thesis."
)

_anthropic_client: anthropic.Anthropic | None = None
_openai_clients: dict[str, OpenAI] = {}


def _get_anthropic_client() -> anthropic.Anthropic | None:
    global _anthropic_client
    if _anthropic_client is None:
        try:
            kwargs: dict[str, Any] = {}
            key = anthropic_api_key()
            if key:
                kwargs["api_key"] = key
            workspace = anthropic_workspace_id()
            if workspace:
                kwargs["default_headers"] = {"anthropic-workspace-id": workspace}
            _anthropic_client = anthropic.Anthropic(**kwargs)
        except Exception as exc:
            log.warning("Anthropic client unavailable: %s", exc)
            return None
    return _anthropic_client


def _claude_has_credentials() -> bool:
    if anthropic_api_key() or os.getenv("ANTHROPIC_AUTH_TOKEN"):
        return True
    client = _get_anthropic_client()
    if client is not None and (getattr(client, "api_key", None) or getattr(client, "auth_token", None)):
        return True
    return (Path.home() / ".config" / "anthropic").exists()


def _openai_client(spec: dict[str, Any]) -> OpenAI:
    key = spec["api_key_env"]
    if key not in _openai_clients:
        _openai_clients[key] = OpenAI(
            api_key=os.getenv(key),
            base_url=spec["base_url"],
            timeout=spec.get("timeout", 60.0),
        )
    return _openai_clients[key]


def _status_for(key: str) -> dict[str, Any]:
    spec = PROVIDERS[key]
    model = provider_model(key)
    if not AI_ENABLED:
        return {
            "available": False,
            "reason": "AI disabled via FINLENS_AI=off.",
            "provider": key,
            "model": None,
            "label": spec["label"],
        }
    if spec["kind"] == "anthropic":
        if _get_anthropic_client() is None:
            return {"available": False, "reason": "Anthropic SDK could not be initialised.",
                    "provider": key, "model": None, "label": spec["label"]}
        if not _claude_has_credentials():
            return {"available": False, "reason": NO_CLAUDE, "provider": key, "model": None,
                    "label": spec["label"]}
        return {"available": True, "reason": "", "provider": key, "model": model, "label": spec["label"]}
    if not os.getenv(spec["api_key_env"]):
        reason = NO_DEEPSEEK if key == "deepseek" else (
            f"No {spec['label']} credentials found. Set {spec['api_key_env']} in backend/.env."
        )
        return {"available": False, "reason": reason, "provider": key, "model": None,
                "label": spec["label"]}
    return {"available": True, "reason": "", "provider": key, "model": model, "label": spec["label"]}


def status(provider: str | None = None) -> dict[str, Any]:
    if not AI_ENABLED:
        return {
            "available": False,
            "reason": "AI disabled via FINLENS_AI=off.",
            "provider": None,
            "model": None,
        }
    key = resolve_provider(provider) if provider else provider_key()
    return _status_for(key)


def provider_catalog() -> dict[str, Any]:
    current = status()
    listing = [
        {
            "key": key,
            "label": spec["label"],
            "available": item["available"],
            "model": item.get("model"),
            "reason": item.get("reason") or "",
        }
        for key, spec in PROVIDERS.items()
        for item in (_status_for(key),)
    ]
    return {**current, "default": resolve_provider(), "providers": listing}


def available() -> bool:
    return bool(status()["available"])


def _claude_parse_options(max_tokens: int = 8192) -> dict[str, Any]:
    """Opus 5 thinks by default; that can stall a thesis for minutes.

    Thinking can only be turned off at effort high or below.
    """
    effort = ANTHROPIC_EFFORT if ANTHROPIC_EFFORT in {"low", "medium", "high"} else "high"
    return {
        "max_tokens": max_tokens,
        "thinking": {"type": "disabled"},
        "output_config": {"effort": effort},
        "timeout": 120.0,
    }


def generate_thesis(fact_pack: dict[str, Any], ticker: str, name: str) -> dict[str, Any] | None:
    if not AI_ENABLED:
        return None
    st = status()
    if not st["available"]:
        return None

    key = st["provider"]
    spec = PROVIDERS[key]
    model = st["model"]
    payload = json.dumps(fact_pack, indent=2, sort_keys=True, default=str)

    if spec["kind"] == "anthropic":
        return _claude_thesis(payload, ticker, name, model)
    return _openai_compat_thesis(spec, payload, ticker, name, key, model)


def _openai_complete(*, client: OpenAI, model: str, messages: list[dict[str, str]], max_tokens: int):
    return client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        extra_body={"thinking": {"type": "disabled"}},
    )


def _parse_json_object(text: str) -> dict:
    """Jobscan-style: strip fences, then take the first {...} block if needed."""
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise
        obj = json.loads(cleaned[start : end + 1])
    if not isinstance(obj, dict):
        raise json.JSONDecodeError("expected a JSON object", cleaned, 0)
    return obj


def _openai_compat_thesis(
    spec: dict[str, Any], payload: str, ticker: str, name: str, provider: str, model: str,
) -> dict[str, Any]:
    client = _openai_client(spec)
    user = build_json_user_prompt(payload, ticker, name, Thesis.model_json_schema())
    try:
        response = _openai_complete(
            client=client,
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            max_tokens=8192,
        )
    except openai.AuthenticationError:
        log.warning("%s credentials rejected.", spec["label"])
        return {"error": f"{spec['label']} credentials were rejected."}
    except openai.RateLimitError as exc:
        log.warning("Rate limited by %s: %s", spec["label"], exc)
        return {"error": "Rate limited by the AI provider. The quantitative analysis below is unaffected."}
    except openai.APITimeoutError:
        log.warning("%s request timed out.", spec["label"])
        return {"error": "The AI provider timed out. Try again, or set FINLENS_AI=off for quant-only."}
    except openai.APIStatusError as exc:
        log.warning("%s API error %s: %s", spec["label"], exc.status_code, exc.message)
        if exc.status_code == 402:
            return {"error": "DeepSeek account has insufficient balance. Add credit and retry."}
        return {"error": f"AI provider returned {exc.status_code}."}
    except openai.APIConnectionError:
        log.warning("Network error reaching %s.", spec["label"])
        return {"error": "Could not reach the AI provider."}
    except Exception as exc:
        log.exception("Thesis generation failed: %s", exc)
        return {"error": f"Thesis generation failed: {exc}"}

    content = ""
    if response.choices:
        msg = response.choices[0].message
        # Thinking-on-by-default can leave content empty and put JSON in
        # reasoning_content; jobscan falls back the same way.
        content = (getattr(msg, "content", None) or getattr(msg, "reasoning_content", None) or "")
    if not str(content).strip():
        return {"error": "The AI response was empty."}

    try:
        thesis = Thesis.model_validate(_parse_json_object(str(content)))
    except (ValidationError, json.JSONDecodeError, ValueError) as exc:
        log.warning("Thesis JSON did not match schema: %s", exc)
        return {"error": "The AI response did not match the expected format."}

    usage = response.usage
    return {
        "thesis": thesis.model_dump(),
        "provider": provider,
        "model": model,
        "usage": {
            "input_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
            "output_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
            "cache_read": 0,
            "cache_write": 0,
        },
    }


def _claude_thesis(payload: str, ticker: str, name: str, model: str) -> dict[str, Any] | None:
    client = _get_anthropic_client()
    if client is None:
        return None
    try:
        response = client.messages.parse(
            model=model,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": build_user_prompt(payload, ticker, name)}],
            output_format=Thesis,
            **_claude_parse_options(),
        )
    except anthropic.AuthenticationError:
        log.warning("Anthropic credentials rejected.")
        return {"error": "Claude credentials were rejected. Check ANTHROPIC_API_KEY in backend/.env."}
    except anthropic.RateLimitError as exc:
        log.warning("Rate limited by Anthropic: %s", exc)
        return {"error": "Rate limited by the AI provider. The quantitative analysis below is unaffected."}
    except anthropic.APITimeoutError:
        log.warning("Anthropic request timed out.")
        return {"error": "Claude timed out. Try again, or switch back to DeepSeek."}
    except anthropic.APIStatusError as exc:
        log.warning("Anthropic API error %s: %s", exc.status_code, exc.message)
        if exc.status_code == 400 and "workspace" in (exc.message or "").lower():
            return {"error": "This Claude API key needs a workspace ID. Set ANTHROPIC_WORKSPACE_ID in backend/.env, or create a workspace-scoped key in the Anthropic console."}
        return {"error": f"AI provider returned {exc.status_code}."}
    except anthropic.APIConnectionError:
        log.warning("Network error reaching Anthropic.")
        return {"error": "Could not reach the AI provider."}
    except TypeError as exc:
        if "authentication" in str(exc).lower():
            log.warning("No Anthropic credentials resolved.")
            return {"error": NO_CLAUDE}
        log.exception("Thesis generation failed: %s", exc)
        return {"error": f"Thesis generation failed: {exc}"}
    except Exception as exc:
        log.exception("Thesis generation failed: %s", exc)
        return {"error": "The AI response did not match the expected format."}

    if response.stop_reason == "refusal":
        return {"error": "The model declined to produce a view on this request."}

    thesis: Thesis | None = response.parsed_output
    if thesis is None:
        return {"error": "No structured output returned."}

    usage = response.usage
    return {
        "thesis": thesis.model_dump(),
        "provider": "claude",
        "model": model,
        "usage": {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read": getattr(usage, "cache_read_input_tokens", 0),
            "cache_write": getattr(usage, "cache_creation_input_tokens", 0),
        },
    }
