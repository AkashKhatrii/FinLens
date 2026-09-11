"""Price-action engine: indicators, trend structure, and relative strength.

Indicators are hand-rolled in pandas (Wilder smoothing where the classic
definition calls for it) so there is no TA-Lib/C build dependency.

Two pillars come out of here rather than one, because a day-trader and a
position-trader read the same chart differently:
  * `technical_short` - overbought/oversold, volume surges, 20-DMA position
  * `technical_trend`  - 50/200-DMA structure, ADX, multi-month relative strength
The horizon weighting in `scoring.py` leans on them in different proportions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .common import Metric, Pillar, band
from .metric_weights import TECH_SHORT, TECH_TREND


# --- indicator primitives ----------------------------------------------------

def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=max(2, n // 2)).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=max(2, n // 2)).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    # Zero average loss with positive gains is an unbroken run of up-days:
    # RSI is 100 by definition. Warm-up bars stay NaN rather than being filled.
    return out.mask((avg_loss == 0) & (avg_gain > 0), 100.0)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return line, sig, line - sig


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["Close"].shift()
    return pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up = df["High"].diff()
    down = -df["Low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    atr_n = true_range(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / atr_n
    minus_di = 100 * minus_dm.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / atr_n
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def bollinger_pct_b(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.Series:
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=max(2, n // 2)).std()
    upper, lower = mid + k * sd, mid - k * sd
    width = (upper - lower).replace(0, np.nan)
    return (close - lower) / width


def _ret(close: pd.Series, days: int) -> float | None:
    if len(close) <= days:
        return None
    past = close.iloc[-(days + 1)]
    if not past or past <= 0:
        return None
    return (close.iloc[-1] / past - 1) * 100


# --- snapshot ----------------------------------------------------------------

@dataclass
class TechnicalSnapshot:
    price: float | None = None
    sma20: float | None = None
    sma50: float | None = None
    sma200: float | None = None
    rsi14: float | None = None
    macd_hist: float | None = None
    macd_cross: str = ""
    adx14: float | None = None
    atr14: float | None = None
    atr_pct: float | None = None
    pct_b: float | None = None
    volume_ratio: float | None = None
    golden_cross: bool | None = None
    returns: dict[str, float | None] = field(default_factory=dict)
    relative_strength: dict[str, float | None] = field(default_factory=dict)
    support: float | None = None
    resistance: float | None = None
    suggested_stop: float | None = None
    week52_position: float | None = None
    series: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


WINDOWS = {"1w": 5, "1m": 21, "3m": 63, "6m": 126, "1y": 252}


def analyse(history: pd.DataFrame, benchmark: pd.DataFrame) -> tuple[TechnicalSnapshot, Pillar, Pillar]:
    snap = TechnicalSnapshot()
    short = Pillar("technical_short", "Short-Term Setup")
    trend = Pillar("technical_trend", "Trend & Relative Strength")

    if history is None or history.empty or len(history) < 30:
        short.notes.append("Not enough price history for a technical read.")
        trend.notes.append("Not enough price history for a technical read.")
        return snap, short, trend

    df = history.dropna(subset=["Close"]).copy()
    close = df["Close"]
    snap.price = float(close.iloc[-1])

    snap.sma20 = _last(sma(close, 20))
    snap.sma50 = _last(sma(close, 50))
    snap.sma200 = _last(sma(close, 200))
    snap.rsi14 = _last(rsi(close))
    line, sig, hist = macd(close)
    snap.macd_hist = _last(hist)
    snap.adx14 = _last(adx(df))
    snap.atr14 = _last(atr(df))
    snap.atr_pct = (snap.atr14 / snap.price * 100) if (snap.atr14 and snap.price) else None
    snap.pct_b = _last(bollinger_pct_b(close))

    # MACD cross within the last 5 sessions is what traders actually act on.
    if len(hist.dropna()) > 6:
        recent = hist.dropna().iloc[-6:]
        if (recent.iloc[0] < 0) and (recent.iloc[-1] > 0):
            snap.macd_cross = "bullish"
        elif (recent.iloc[0] > 0) and (recent.iloc[-1] < 0):
            snap.macd_cross = "bearish"

    if snap.sma50 and snap.sma200:
        snap.golden_cross = snap.sma50 > snap.sma200

    if "Volume" in df and len(df) > 50:
        v20 = df["Volume"].tail(20).mean()
        v50 = df["Volume"].tail(50).mean()
        snap.volume_ratio = float(v20 / v50) if v50 else None

    snap.returns = {k: _ret(close, d) for k, d in WINDOWS.items()}

    # Relative strength: stock return minus benchmark return over the same window.
    if benchmark is not None and not benchmark.empty:
        bclose = benchmark.dropna(subset=["Close"])["Close"]
        for k, d in WINDOWS.items():
            r, b = _ret(close, d), _ret(bclose, d)
            snap.relative_strength[k] = (r - b) if (r is not None and b is not None) else None

    # Swing levels from the last ~3 months of extremes.
    window = df.tail(63)
    snap.support = float(window["Low"].min())
    snap.resistance = float(window["High"].max())
    if snap.atr14:
        snap.suggested_stop = round(snap.price - 2 * snap.atr14, 2)

    hi, lo = float(df["High"].tail(252).max()), float(df["Low"].tail(252).min())
    if hi > lo:
        snap.week52_position = (snap.price - lo) / (hi - lo) * 100

    snap.series = _chart_series(df)

    _build_short(snap, short)
    _build_trend(snap, trend)
    return snap, short, trend


def _last(s: pd.Series) -> float | None:
    s = s.dropna()
    if s.empty:
        return None
    v = float(s.iloc[-1])
    return None if v != v else v


def _chart_series(df: pd.DataFrame, points: int = 180) -> dict[str, Any]:
    tail = df.tail(points)
    closes = tail["Close"]
    return {
        "dates": [d.strftime("%Y-%m-%d") for d in tail.index],
        "close": [round(float(v), 2) for v in closes],
        "sma50": [None if pd.isna(v) else round(float(v), 2) for v in sma(df["Close"], 50).tail(points)],
        "sma200": [None if pd.isna(v) else round(float(v), 2) for v in sma(df["Close"], 200).tail(points)],
        "volume": [int(v) for v in tail["Volume"].fillna(0)] if "Volume" in tail else [],
    }


def _build_short(s: TechnicalSnapshot, p: Pillar) -> None:
    # RSI is scored as a hill: extremes in both directions are penalised, but
    # oversold is treated as less damaging than overbought for a buy decision.
    p.metrics.append(Metric(
        "rsi14", "RSI (14)", s.rsi14, "",
        band(s.rsi14, [(15, 55), (30, 75), (45, 80), (55, 75), (70, 40), (80, 15), (90, 5)]),
        _rsi_note(s.rsi14), weight=TECH_SHORT["rsi14"],
    ))
    p.metrics.append(Metric(
        "pct_b", "Bollinger %B", s.pct_b, "",
        band(s.pct_b, [(-0.2, 45), (0.2, 70), (0.5, 75), (0.8, 55), (1.1, 25)]),
        "Near the upper band — extended." if (s.pct_b or 0) > 0.9
        else "Near the lower band — stretched to the downside." if (s.pct_b is not None and s.pct_b < 0.1)
        else "Mid-channel.",
        weight=TECH_SHORT["pct_b"],
    ))
    above20 = ((s.price / s.sma20 - 1) * 100) if (s.price and s.sma20) else None
    p.metrics.append(Metric(
        "vs_sma20", "Price vs 20-DMA", above20, "%",
        band(above20, [(-12, 15), (-5, 40), (0, 65), (4, 80), (10, 60), (18, 30)]),
        f"Trading {above20:+.1f}% vs its 20-day average." if above20 is not None else "",
        weight=TECH_SHORT["vs_sma20"],
    ))
    p.metrics.append(Metric(
        "ret_1w", "1-Week Return", s.returns.get("1w"), "%",
        band(s.returns.get("1w"), [(-10, 25), (-3, 45), (0, 60), (4, 75), (12, 55)]),
        "", weight=TECH_SHORT["ret_1w"],
    ))
    p.metrics.append(Metric(
        "volume_ratio", "Volume Trend (20d/50d)", s.volume_ratio, "x",
        band(s.volume_ratio, [(0.5, 35), (0.8, 50), (1.0, 60), (1.4, 78), (2.5, 70)]),
        "Volume expanding — participation confirming the move." if (s.volume_ratio or 0) > 1.2
        else "Volume thinning out." if (s.volume_ratio or 1) < 0.8 else "",
        weight=TECH_SHORT["volume_ratio"],
    ))
    if s.macd_cross == "bullish":
        p.notes.append("MACD crossed above signal within the last week — fresh momentum trigger.")
    elif s.macd_cross == "bearish":
        p.notes.append("MACD crossed below signal within the last week — momentum rolling over.")
    if s.suggested_stop and s.price:
        p.notes.append(
            f"ATR-based stop ≈ ₹{s.suggested_stop:,.0f} "
            f"({(s.price / s.suggested_stop - 1) * 100:.1f}% below spot)."
        )


def _build_trend(s: TechnicalSnapshot, p: Pillar) -> None:
    above200 = ((s.price / s.sma200 - 1) * 100) if (s.price and s.sma200) else None
    p.metrics.append(Metric(
        "vs_sma200", "Price vs 200-DMA", above200, "%",
        band(above200, [(-30, 5), (-12, 25), (0, 55), (10, 78), (30, 88), (60, 75)]),
        ("Above the 200-DMA — long-term trend is up." if (above200 or 0) > 0
         else "Below the 200-DMA — long-term trend is down."),
        weight=TECH_TREND["vs_sma200"],
    ))
    above50 = ((s.price / s.sma50 - 1) * 100) if (s.price and s.sma50) else None
    p.metrics.append(Metric(
        "vs_sma50", "Price vs 50-DMA", above50, "%",
        band(above50, [(-20, 10), (-8, 32), (0, 58), (8, 80), (20, 72)]),
        "", weight=TECH_TREND["vs_sma50"],
    ))
    p.metrics.append(Metric(
        "adx14", "Trend Strength (ADX)", s.adx14, "",
        band(s.adx14, [(10, 35), (20, 55), (25, 70), (40, 85), (60, 70)]),
        ("Strong, well-defined trend." if (s.adx14 or 0) >= 25
         else "Choppy / rangebound — trend-following setups are unreliable here."),
        weight=TECH_TREND["adx14"],
    ))
    rs3 = s.relative_strength.get("3m")
    p.metrics.append(Metric(
        "rs_3m", "3M vs Benchmark", rs3, "%",
        band(rs3, [(-25, 10), (-10, 30), (0, 55), (8, 78), (25, 92)]),
        (f"Outperforming the index by {rs3:.1f}pp over 3 months." if (rs3 or 0) > 0
         else f"Lagging the index by {abs(rs3):.1f}pp over 3 months." if rs3 is not None else ""),
        weight=TECH_TREND["rs_3m"],
    ))
    rs12 = s.relative_strength.get("1y")
    p.metrics.append(Metric(
        "rs_1y", "1Y vs Benchmark", rs12, "%",
        band(rs12, [(-40, 10), (-15, 32), (0, 55), (15, 80), (45, 92)]),
        "", weight=TECH_TREND["rs_1y"],
    ))
    p.metrics.append(Metric(
        "week52_position", "Position in 52W Range", s.week52_position, "%",
        band(s.week52_position, [(0, 20), (25, 42), (50, 62), (75, 80), (95, 68)]),
        (f"{s.week52_position:.0f}% of the way up its 52-week range."
         if s.week52_position is not None else ""),
        weight=TECH_TREND["week52_position"],
    ))
    if s.golden_cross is True:
        p.notes.append("50-DMA is above the 200-DMA (golden-cross structure intact).")
    elif s.golden_cross is False:
        p.notes.append("50-DMA is below the 200-DMA (death-cross structure).")


def _rsi_note(v: float | None) -> str:
    if v is None:
        return ""
    if v >= 75:
        return f"RSI {v:.0f} — overbought; poor risk/reward for a fresh entry."
    if v >= 60:
        return f"RSI {v:.0f} — strong momentum, not yet stretched."
    if v <= 30:
        return f"RSI {v:.0f} — oversold; bounce candidate but catching a falling knife is a real risk."
    return f"RSI {v:.0f} — neutral."
