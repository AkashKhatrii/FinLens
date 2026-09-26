"""Shared scoring primitives.

Every engine emits `Metric`s. A Metric carries both the raw number (for the UI)
and a 0-100 score (for the weighted verdict), plus a plain-English note that
becomes evidence for the pros/cons list and for the LLM thesis.

Metrics whose inputs are missing score `None` rather than 0. Scoring skips them
and reports coverage, so a company with thin data gets low *confidence* instead
of a wrongly low *score* - the single most important correctness property here.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Sequence

from ..config import MARKETS


def currency_symbol_for(market: str) -> str:
    """Display currency for a market code ('IN' -> ₹, 'US' -> $)."""
    return MARKETS.get(market, MARKETS["IN"])["symbol"]


def fmt_money(value: float | None, market: str = "IN") -> str:
    """Large money amounts in the market's own scale.

    India thinks in crores; the US thinks in millions/billions/trillions.
    Rendering a US market cap as '₹... Cr' is how the old code produced
    nonsense like a $-denominated DCF labelled in rupees.
    """
    if value is None:
        return "—"
    sym = currency_symbol_for(market)
    if market == "IN":
        return f"{sym}{value / 1e7:,.0f} Cr"
    av = abs(value)
    if av >= 1e12:
        return f"{sym}{value / 1e12:,.2f}T"
    if av >= 1e9:
        return f"{sym}{value / 1e9:,.1f}B"
    if av >= 1e6:
        return f"{sym}{value / 1e6:,.0f}M"
    return f"{sym}{value:,.0f}"


def fmt_price(value: float | None, market: str = "IN") -> str:
    """Per-share prices with the market's currency symbol."""
    if value is None:
        return "—"
    return f"{currency_symbol_for(market)}{value:,.2f}"


@dataclass
class Metric:
    key: str
    label: str
    value: float | None
    unit: str = ""
    score: float | None = None          # 0-100, None when inputs are missing
    note: str = ""
    weight: float = 1.0
    higher_is_better: bool = True
    peer: float | None = None           # sector/own-history reference, if known
    display_override: str = ""          # when set, display returns this verbatim
                                       # (for market-specific money formatting)

    @property
    def verdict(self) -> str:
        if self.score is None:
            return "unknown"
        if self.score >= 70:
            return "good"
        if self.score >= 45:
            return "ok"
        return "bad"

    @property
    def display(self) -> str:
        if self.display_override:
            return self.display_override
        if self.value is None:
            return "—"
        v = self.value
        if self.unit == "%":
            return f"{v:,.1f}%"
        if self.unit == "x":
            return f"{v:,.2f}x"
        if self.unit == "cr":
            return f"₹{v:,.0f} Cr"
        if self.unit == "₹":
            return f"₹{v:,.2f}"
        if abs(v) >= 100:
            return f"{v:,.0f}"
        return f"{v:,.2f}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["verdict"] = self.verdict
        d["display"] = self.display
        return d


@dataclass
class Pillar:
    key: str
    label: str
    metrics: list[Metric] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def score(self) -> float | None:
        scored = [m for m in self.metrics if m.score is not None]
        if not scored:
            return None
        total_w = sum(m.weight for m in scored)
        if total_w == 0:
            return None
        return sum(m.score * m.weight for m in scored) / total_w

    @property
    def coverage(self) -> float:
        """Fraction of this pillar's weight that we actually had data for."""
        if not self.metrics:
            return 0.0
        total = sum(m.weight for m in self.metrics)
        have = sum(m.weight for m in self.metrics if m.score is not None)
        return have / total if total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "score": self.score,
            "coverage": self.coverage,
            "metrics": [m.to_dict() for m in self.metrics],
            "notes": self.notes,
        }


def band(value: float | None, points: Sequence[tuple[float, float]]) -> float | None:
    """Piecewise-linear score from (threshold, score) points, ascending by x.

    Interpolating rather than stepping avoids the cliff where ROE 14.9% scores
    35 and 15.0% scores 55. Descending score sequences express
    lower-is-better metrics, so one function covers both directions.
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):  # NaN / inf guard
        return None

    pts = sorted(points, key=lambda p: p[0])
    if v <= pts[0][0]:
        return float(pts[0][1])
    if v >= pts[-1][0]:
        return float(pts[-1][1])

    for (x0, s0), (x1, s1) in zip(pts, pts[1:]):
        if x0 <= v <= x1:
            if x1 == x0:
                return float(s1)
            t = (v - x0) / (x1 - x0)
            return float(s0 + t * (s1 - s0))
    return float(pts[-1][1])


def safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    try:
        if b == 0:
            return None
        return float(a) / float(b)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def pct_change(new: float | None, old: float | None) -> float | None:
    """Percent change, guarding the sign flip that makes growth meaningless.

    Going from a loss to a profit is real news, but '(-50 -> 100) = -300%' is
    not a number any analyst would quote, so we return None and let the note
    explain it instead.
    """
    if new is None or old is None or old == 0:
        return None
    if old < 0:
        return None
    return (new / old - 1) * 100


def cagr(values: Sequence[float], years: int | None = None) -> float | None:
    """CAGR from a most-recent-first series. Undefined if the base is <= 0."""
    if not values or len(values) < 2:
        return None
    latest_v, oldest_v = values[0], values[-1]
    n = years if years is not None else len(values) - 1
    if oldest_v <= 0 or latest_v <= 0 or n <= 0:
        return None
    try:
        return ((latest_v / oldest_v) ** (1 / n) - 1) * 100
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def trend_slope_pct(values: Sequence[float]) -> float | None:
    """Direction of a most-recent-first series, as % of the mean level.

    Used for 'are margins expanding or compressing' without over-reading a
    single noisy quarter.
    """
    if not values or len(values) < 3:
        return None
    series = list(reversed(values))  # oldest -> newest
    n = len(series)
    mean_x = (n - 1) / 2
    mean_y = sum(series) / n
    denom = sum((i - mean_x) ** 2 for i in range(n))
    if denom == 0 or mean_y == 0:
        return None
    slope = sum((i - mean_x) * (y - mean_y) for i, y in enumerate(series)) / denom
    return (slope / abs(mean_y)) * 100
