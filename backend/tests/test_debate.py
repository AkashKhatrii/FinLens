"""Tests for the optional bull/bear debate: schemas, prompts, and the runner."""
import json
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.ai.schemas import DebateOpening, DebateRebuttal
from app.ai import analyst
from app.ai.prompts import (
    build_debate_opening_prompt,
    build_debate_rebuttal_prompt,
    build_debate_system_prompt,
)


def test_opening_schema_accepts_both_sides():
    o = DebateOpening(side="bull", points=["Revenue grew 20% YoY.", "ROCE 25%."])
    assert o.side == "bull" and len(o.points) == 2
    DebateOpening(side="bear", points=["P/E 60x vs 4% earnings yield."])


def test_opening_schema_rejects_bad_side():
    with pytest.raises(ValidationError):
        DebateOpening(side="neutral", points=["x"])


def test_rebuttal_schema():
    r = DebateRebuttal(side="bear", rebuttal="The growth claim ignores base effects.")
    assert r.side == "bear"


def test_debate_system_prompt_roles():
    bull = build_debate_system_prompt("IN", "bull")
    bear = build_debate_system_prompt("IN", "bear")
    assert "bull advocate" in bull and "bear advocate" not in bull
    assert "bear advocate" in bear
    assert "Promoter" in bull  # India market section
    us = build_debate_system_prompt("US", "bull")
    assert "buyback" in us.lower() or "shareholder yield" in us.lower()


def test_debate_opening_prompt_is_json_shaped():
    schema = DebateOpening.model_json_schema()
    p = build_debate_opening_prompt('{"a": 1}', "ANET", "Arista", schema, "US", "bull")
    assert "json" in p and "bull" in p and "ANET" in p
    assert json.dumps(schema, indent=2)[:40] in p


def test_debate_rebuttal_prompt_carries_opponent_points():
    schema = DebateRebuttal.model_json_schema()
    p = build_debate_rebuttal_prompt(
        '{"a": 1}', "ANET", "Arista", schema, "US", "bull",
        ["Margins are expanding."],
    )
    assert "json" in p and "Margins are expanding." in p
    assert "bear advocate" in p  # names the opponent


_OK_STATUS = {"available": True, "provider": "deepseek", "model": "deepseek-chat"}


def _fake_call(*, spec, model, provider_key, system, user, schema_model):
    side = "bull" if "the bull case" in user or "the bull advocate" in user else "bear"
    if schema_model is DebateOpening:
        return DebateOpening(side=side, points=[f"{side} point one.", f"{side} point two."])
    return DebateRebuttal(side=side, rebuttal=f"{side} rebuttal text.")


def test_run_debate_happy_path():
    with (
        patch.object(analyst, "status", return_value=_OK_STATUS),
        patch.object(analyst, "_debate_single_call", side_effect=_fake_call),
    ):
        out = analyst.run_debate({"price": 100}, "ANET", "Arista", "US")
    assert "error" not in out
    d = out["debate"]
    assert d["bull"]["points"] == ["bull point one.", "bull point two."]
    assert d["bear"]["points"] == ["bear point one.", "bear point two."]
    assert d["bull"]["rebuttal"] == "bull rebuttal text."
    assert d["errors"] == []
    assert out["provider"] == "deepseek"


def test_run_debate_unavailable_ai():
    with patch.object(analyst, "status", return_value={"available": False, "reason": "no key"}):
        out = analyst.run_debate({}, "ANET", "Arista", "US")
    assert out["error"] == "no key"


def test_run_debate_partial_failure_keeps_working_side():
    def flaky(*, spec, model, provider_key, system, user, schema_model):
        side = "bull" if "the bull case" in user or "the bull advocate" in user else "bear"
        if schema_model is DebateOpening and side == "bear":
            raise RuntimeError("boom")
        if schema_model is DebateOpening:
            return DebateOpening(side=side, points=[f"{side} point."])
        return DebateRebuttal(side=side, rebuttal=f"{side} rebuttal.")

    with (
        patch.object(analyst, "status", return_value=_OK_STATUS),
        patch.object(analyst, "_debate_single_call", side_effect=flaky),
    ):
        out = analyst.run_debate({"price": 100}, "ANET", "Arista", "US")
    d = out["debate"]
    assert d["bull"]["points"] == ["bull point."]
    assert d["bear"]["points"] == []  # failed side degrades gracefully
    assert any("bear opening failed" in e for e in d["errors"])
