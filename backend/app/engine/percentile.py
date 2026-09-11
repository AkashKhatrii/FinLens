"""Percentile ranking against a reference universe.

The raw 0-100 score is not calibrated and cannot be. Averaging nine pillars
pulls every result toward the middle, and the two pillars a buyer cares most
about - quality and valuation - are structurally anti-correlated (Nestle India
scores 88.7 on profitability and 13.6 on valuation). Across 40 NIFTY-grade
names the observed spread was min 51.8 / median 61.8 / max 71.4, sd 5.0. No
company can reach 80, so an absolute "80 = Strong Buy" threshold is unreadable.

A percentile against a fixed universe *is* readable: "63" means nothing on its
own, "top 15% of the NIFTY universe" means something. Rebuild the snapshot with
`scripts_build_benchmark.py`.
"""
from __future__ import annotations

import json
import logging
from bisect import bisect_left
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_PATH = Path(__file__).resolve().parent.parent / "benchmark.json"
_cache: dict[str, Any] | None = None


def _data() -> dict[str, Any]:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_PATH.read_text())
        except Exception as exc:
            log.warning("No benchmark snapshot available: %s", exc)
            _cache = {}
    return _cache


def rank(score: float | None, key: str = "overall") -> dict[str, Any] | None:
    """Percentile of `score` within the reference distribution for `key`."""
    if score is None:
        return None
    dist = _data().get(key) or []
    if len(dist) < 10:
        return None

    # Fraction of the universe this score beats.
    pct = bisect_left(dist, score) / len(dist) * 100
    return {
        "percentile": round(pct, 1),
        "universe_size": len(dist),
        "universe_median": round(dist[len(dist) // 2], 1),
        "generated": _data().get("generated"),
        "label": _label(pct),
    }


def _label(pct: float) -> str:
    if pct >= 90:
        return "Top 10% of the reference universe"
    if pct >= 75:
        return "Top quartile"
    if pct >= 55:
        return "Above the universe median"
    if pct >= 45:
        return "Around the universe median"
    if pct >= 25:
        return "Below median"
    return "Bottom quartile"
