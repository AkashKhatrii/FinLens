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
    horizon: Literal["swing", "long"]
    stance: Stance = Field(description="Your call for this holding period.")
    conviction: Conviction
    rationale: str = Field(description="2-3 sentences. Cite specific numbers from the fact pack.")
    what_would_change_it: str = Field(
        description="The single concrete observation that would flip this call. Use a qualitative "
                    "condition unless a numerical threshold is explicitly supplied in the fact pack, "
                    "company guidance, a disclosed target, or a FinLens technical reference level."
    )
    agreement: Literal["aligned", "qualified", "disagrees"] | None = Field(
        default=None,
        description="Swing only. aligned = same call as Quant and no material contradiction "
                    "(ordinary caveats stay aligned: moderate ADX, neutral volume, elevated beta/"
                    "volatility, ordinary pullback/extension). qualified = same direction with "
                    "material setup uncertainty. disagrees = stance changes the Swing direction "
                    "and a material reason is given. Leave null on Long. Prefer aligned over "
                    "qualified for ordinary caveats; prefer qualified over disagrees.",
    )
    qualification: str | None = Field(
        default=None,
        description="Swing only. If qualified or disagrees, the material reason. "
                    "RSI, Bollinger, or PE alone is not a reason. Moderate ADX, neutral volume, "
                    "high beta/volatility, high valuation, DCF, or ordinary extension are not "
                    "standalone disagreement reasons.",
    )


class Thesis(BaseModel):
    headline: str = Field(description="One sentence, under 20 words, that a busy investor could act on.")
    business_summary: str = Field(
        description="2 sentences in plain English: what the company sells, to whom, and how it makes money."
    )
    quality_verdict: str = Field(
        description="Is this a good business? Address durability of returns, competitive position, "
                    "and capital allocation. 2-3 sentences."
    )
    valuation_verdict: str = Field(
        description="Is the current price reasonable? Reference the key multiples and the DCF read. 2-3 sentences."
    )
    bull_case: list[str] = Field(
        description="2-3 specific, evidence-backed points. Do not invent numerical thresholds "
                    "or peer comparisons that are not in the fact pack."
    )
    bear_case: list[str] = Field(
        description="2-3 specific, evidence-backed points, including risks that could permanently "
                    "impair capital. Do not invent numerical thresholds "
                    "or peer comparisons that are not in the fact pack."
    )
    what_to_watch: list[str] = Field(
        description="Up to 3 concrete, checkable things from the fact pack: upcoming supplied events "
                    "or reported metrics. Do not invent numerical thresholds, trigger levels, or "
                    "peer comparisons that are not in the fact pack."
    )
    horizon_calls: list[HorizonCall] = Field(
        description="Exactly two entries, one each for swing and long."
    )
    contrarian_note: str = Field(
        description="Where the quantitative score is most likely to be wrong about this specific company, "
                    "and why. Be concrete, not hedging boilerplate."
    )
    data_caveats: list[str] = Field(
        description="Up to 3 things in the fact pack that were missing or looked unreliable and limited your read."
    )
