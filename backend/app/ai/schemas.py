"""Pydantic schema the model is forced to fill.

Using a schema rather than free text is what makes the AI output renderable:
the UI binds to fields, not to paragraphs it has to parse.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Stance = Literal["Strong Buy", "Buy", "Hold", "Reduce", "Avoid"]
Conviction = Literal["High", "Medium", "Low"]


class HorizonCall(BaseModel):
    horizon: Literal["short", "swing", "long"]
    stance: Stance = Field(description="Your call for this holding period.")
    conviction: Conviction
    rationale: str = Field(description="2-3 sentences. Cite specific numbers from the fact pack.")
    what_would_change_it: str = Field(
        description="The single concrete observation that would flip this call."
    )


class Thesis(BaseModel):
    headline: str = Field(description="One sentence, under 20 words, that a busy investor could act on.")
    business_summary: str = Field(
        description="2-3 sentences in plain English: what the company sells, to whom, and how it makes money."
    )
    quality_verdict: str = Field(
        description="Is this a good business? Address durability of returns, competitive position, "
                    "and capital allocation. 2-4 sentences."
    )
    valuation_verdict: str = Field(
        description="Is the current price reasonable? Reference the multiples and the DCF. 2-4 sentences."
    )
    bull_case: list[str] = Field(description="3-5 specific, evidence-backed points.")
    bear_case: list[str] = Field(description="3-5 specific, evidence-backed points.")
    key_risks: list[str] = Field(description="3-5 risks that could permanently impair capital.")
    what_to_watch: list[str] = Field(
        description="3-5 concrete, checkable things: upcoming events, metrics, thresholds."
    )
    horizon_calls: list[HorizonCall] = Field(
        description="Exactly three entries, one each for short, swing and long."
    )
    contrarian_note: str = Field(
        description="Where the quantitative score is most likely to be wrong about this specific company, "
                    "and why. Be concrete, not hedging boilerplate."
    )
    data_caveats: list[str] = Field(
        description="Anything in the fact pack that was missing or looked unreliable and limited your read."
    )
