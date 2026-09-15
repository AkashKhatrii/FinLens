"""Short/Swing regime and entry quality from the existing technical snapshot.

This is not a second score. It labels the setup the Swing score already encodes:
trend, momentum, relative strength, pullback/extension, and volume confirmation.
RSI and Bollinger never decide the regime by themselves.
"""
from __future__ import annotations

from typing import Any

ENTRY_QUALITY = ("Attractive", "Normal", "Extended", "Weak")
TREND_LABELS = ("Bullish", "Neutral", "Bearish")
MOMENTUM_LABELS = ("Positive", "Neutral", "Negative")


def _pct(price: float | None, sma: float | None) -> float | None:
    if not price or not sma:
        return None
    return (price / sma - 1) * 100


def classify_trend(snap) -> str:
    price = getattr(snap, "price", None)
    votes_up = 0
    votes_down = 0
    for sma in (getattr(snap, "sma20", None), getattr(snap, "sma50", None), getattr(snap, "sma200", None)):
        if price and sma:
            if price > sma:
                votes_up += 1
            elif price < sma:
                votes_down += 1
    s20, s50, s200 = getattr(snap, "sma20", None), getattr(snap, "sma50", None), getattr(snap, "sma200", None)
    if s20 and s50 and s200:
        if s20 > s50 > s200:
            votes_up += 1
        elif s20 < s50 < s200:
            votes_down += 1
    if getattr(snap, "golden_cross", None) is True:
        votes_up += 1
    elif getattr(snap, "golden_cross", None) is False:
        votes_down += 1
    slope50 = getattr(snap, "sma50_slope_pct", None)
    slope200 = getattr(snap, "sma200_slope_pct", None)
    if slope50 is not None:
        votes_up += slope50 > 0
        votes_down += slope50 < 0
    if slope200 is not None:
        votes_up += slope200 > 0
        votes_down += slope200 < 0
    if votes_up >= 4 and votes_up > votes_down:
        return "Bullish"
    if votes_down >= 4 and votes_down > votes_up:
        return "Bearish"
    return "Neutral"


def classify_momentum(snap) -> str:
    returns = getattr(snap, "returns", None) or {}
    r1m, r3m, r1w = returns.get("1m"), returns.get("3m"), returns.get("1w")
    pos = neg = 0
    if r1m is not None:
        pos += int(r1m > 1)
        neg += int(r1m < -1)
    if r3m is not None:
        pos += int(r3m > 2)
        neg += int(r3m < -2)
    # One-week is confirmation only; it cannot outvote 1–3 month evidence.
    if r1w is not None and abs(r1w) >= 4:
        pos += int(r1w > 0)
        neg += int(r1w < 0)
    if pos >= 2 and pos > neg:
        return "Positive"
    if neg >= 2 and neg > pos:
        return "Negative"
    return "Neutral"


def classify_relative_strength(snap) -> str:
    rs = getattr(snap, "relative_strength", None) or {}
    rs3 = rs.get("3m")
    if rs3 is None:
        return "Neutral"
    if rs3 > 2:
        return "Positive"
    if rs3 < -2:
        return "Negative"
    return "Neutral"


def classify_volume(snap) -> str:
    ratio = getattr(snap, "volume_ratio", None)
    if ratio is None:
        return "Neutral"
    if ratio >= 1.15:
        return "Confirming"
    if ratio < 0.8:
        return "Thin"
    return "Neutral"


def _is_extended(snap) -> bool:
    rsi = getattr(snap, "rsi14", None)
    pct_b = getattr(snap, "pct_b", None)
    vs20 = _pct(getattr(snap, "price", None), getattr(snap, "sma20", None))
    return (
        (rsi is not None and rsi >= 70)
        or (pct_b is not None and pct_b >= 0.85)
        or (vs20 is not None and vs20 >= 8)
    )


def _is_pullback(snap, trend: str) -> bool:
    if trend != "Bullish":
        return False
    rsi = getattr(snap, "rsi14", None)
    pct_b = getattr(snap, "pct_b", None)
    vs20 = _pct(getattr(snap, "price", None), getattr(snap, "sma20", None))
    if rsi is None or vs20 is None:
        return False
    return 42 <= rsi <= 60 and -3 <= vs20 <= 5 and (pct_b is None or pct_b < 0.75)


def classify_entry(snap, trend: str, momentum: str) -> str:
    if trend == "Bearish" or (trend != "Bullish" and momentum == "Negative"):
        return "Weak"
    if _is_pullback(snap, trend):
        return "Attractive"
    if trend == "Bullish" and _is_extended(snap):
        return "Extended"
    if trend == "Bullish":
        return "Normal"
    return "Normal" if momentum != "Negative" else "Weak"


def classify_regime(snap, trend: str, momentum: str, entry: str) -> str:
    rsi = getattr(snap, "rsi14", None)
    adx = getattr(snap, "adx14", None)
    if _is_pullback(snap, trend):
        return "Healthy Pullback"
    if trend == "Bullish" and entry == "Extended":
        return "Bullish but Extended"
    if trend == "Bullish" and momentum == "Positive":
        return "Bullish Trend" if (adx or 0) >= 25 else "Bullish Momentum"
    if trend == "Bullish":
        return "Bullish Trend"
    if trend == "Bearish" and rsi is not None and rsi <= 30:
        return "Oversold Downtrend"
    if trend == "Bearish" and momentum == "Negative":
        return "Bearish Momentum"
    if trend == "Bearish":
        return "Bearish Trend"
    if trend == "Neutral" and rsi is not None and rsi < 30 and momentum != "Negative":
        return "Potential Reversal"
    if trend == "Bearish":
        return "Weak/Breakdown"
    return "Neutral"


def classify_swing(snap) -> dict[str, Any]:
    trend = classify_trend(snap)
    momentum = classify_momentum(snap)
    rs = classify_relative_strength(snap)
    volume = classify_volume(snap)
    entry = classify_entry(snap, trend, momentum)
    setup = "Extended" if entry == "Extended" else (
        "Attractive" if entry == "Attractive" else ("Weak" if entry == "Weak" else "Normal")
    )
    return {
        "trend": trend,
        "momentum": momentum,
        "relative_strength": rs,
        "setup": setup,
        "volume": volume,
        "regime": classify_regime(snap, trend, momentum, entry),
        "entry_quality": entry,
        "rsi": getattr(snap, "rsi14", None),
        "pct_b": getattr(snap, "pct_b", None),
        "vs_sma20_pct": _pct(getattr(snap, "price", None), getattr(snap, "sma20", None)),
        "vs_sma50_pct": _pct(getattr(snap, "price", None), getattr(snap, "sma50", None)),
        "adx": getattr(snap, "adx14", None),
        "rs_3m": (getattr(snap, "relative_strength", None) or {}).get("3m"),
    }
