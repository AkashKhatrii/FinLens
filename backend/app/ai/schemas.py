"""Pydantic schema the model is forced to fill.

Using a schema rather than free text is what makes the AI output renderable:
the UI binds to fields, not to paragraphs it has to parse.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Stance = Literal["Strong Buy", "Buy", "Hold", "Reduce", "Avoid"]
Conviction = Literal["High", "Medium", "Low"]
OpportunityCategory = Literal[
    "Established Opportunity", "Emerging Opportunity", "Watch", "No Opportunity",
]
OpportunityRisk = Literal["High", "Medium", "Low"]


class HorizonCall(BaseModel):
    horizon: Literal["swing", "long"]
    stance: Stance = Field(description="Your call for this holding period.")
    conviction: Conviction
    rationale: str = Field(description="2-3 sentences. Cite specific numbers from the fact pack.")
    what_would_change_it: str = Field(
        description="The single concrete observation that would flip this call."
    )


class OpportunityView(BaseModel):
    """Long-term forward-looking investment thesis. Not a horizon, score, or entry signal."""

    category: OpportunityCategory = Field(
        description="One of: Established Opportunity, Emerging Opportunity, Watch, No Opportunity. "
                    "Long-term forward-looking judgment over several years. Not a score, not a third "
                    "holding period, and not an entry-price signal. Do not use RSI, Bollinger Bands, "
                    "moving averages, ADX, or entry timing. Unproven optionality on a proven core "
                    "is Established, not Emerging."
    )
    rationale: str = Field(
        description="2-4 sentences. Why this category as a multi-year business thesis. Distinguish "
                    "current state from the forward-looking thesis. Cite fact-pack evidence. "
                    "Do not invent numbers. Do not use RSI or other short-term technicals. "
                    "A single period is not a proven trend."
    )
    the_bet: str = Field(
        description="The long-term hypothesis: what could make this business substantially better. "
                    "Do not invent future ROE, future EPS, price targets, probabilities, or other "
                    "unsourced forecasts. Do not use entry timing."
    )
    needs_to_happen: str = Field(
        description="Observable developments required for the long-term thesis. Qualitative is "
                    "required when the fact pack has no forward figures. Do not invent numbers."
    )
    catalysts: list[str] = Field(
        description="1-3 evidence-backed reasons the long-term case could continue. Do not invent events. "
                    "Do not list RSI, moving averages, or other short-term technicals."
    )
    thesis_breakers: list[str] = Field(
        description="1-3 evidence-backed conditions that would invalidate this long-term opportunity thesis."
    )
    risk_level: OpportunityRisk = Field(
        description="Uncertainty versus a conventional Long Buy of an already-proven business. "
                    "Emerging Opportunity is typically High because the case depends on the business "
                    "itself becoming stronger. Established Opportunity is typically Medium when the "
                    "core is proven but future initiatives are uncertain."
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
        description="Exactly two entries, one each for swing and long. Opportunity is a separate field, not a third horizon_call."
    )
    opportunity: OpportunityView = Field(
        description="Long-term forward-looking investment thesis. Does not replace or modify the Long call. "
                    "Not an entry-price signal and not driven by RSI or other short-term technicals."
    )
    contrarian_note: str = Field(
        description="Where the quantitative score is most likely to be wrong about this specific company, "
                    "and why. Be concrete, not hedging boilerplate."
    )
    data_caveats: list[str] = Field(
        description="Anything in the fact pack that was missing or looked unreliable and limited your read."
    )
