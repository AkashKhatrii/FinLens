"""CAN SLIM-inspired growth-leader checklist.

This is a ranked overlay on existing analyse() metrics. It does not score
horizons, change Overall, or claim to be IBD CAN SLIM. Market direction (M)
is skipped because FinLens does not maintain an IBD-style market follow-through
read.
"""
from __future__ import annotations

from typing import Any

LETTERS = ("C", "A", "N", "S", "L", "I")

C_Q_PAT_YOY = 18.0
A_PAT_CAGR = 15.0
A_ROE = 17.0
N_WEEK52 = 80.0
S_VOLUME = 1.2
L_RS_3M = 0.0
I_INST = 10.0

_LABELS = {
    "C": "Current quarterly profit YoY",
    "A": "Annual profit CAGR",
    "N": "Position in 52-week range",
    "S": "Volume trend (20d/50d)",
    "L": "3-month relative strength vs benchmark",
    "I": "Institutional holding",
}


def empty_leaders() -> dict[str, Any]:
    return {
        "letters": {
            k: {
                "pass": None,
                "value": None,
                "threshold": _threshold_for(k),
                "label": _LABELS[k],
            }
            for k in LETTERS
        },
        "letters_passed": 0,
        "letters_scored": 0,
        "leader_score": None,
    }


def leaders_from_analysis(result: dict[str, Any] | None) -> dict[str, Any]:
    """Build the six-letter view from an analyse() payload. Missing ≠ fail."""
    result = result or {}
    tech = result.get("technicals") or {}
    own = result.get("ownership") or {}
    rs = tech.get("relative_strength") or {}

    q_pat = _metric_value(result, "q_pat_yoy")
    pat_cagr = _metric_value(result, "pat_cagr")
    roe = _metric_value(result, "roe")
    week52 = _first(tech.get("week52_position"), _metric_value(result, "week52_position"))
    volume = _first(tech.get("volume_ratio"), _metric_value(result, "volume_ratio"))
    rs_3m = _first(rs.get("3m"), _metric_value(result, "rs_3m"))
    inst = _first(own.get("institutions_pct"), _metric_value(result, "institutional_holding"))

    letters = {
        "C": _letter(q_pat, C_Q_PAT_YOY, "C", gte=True),
        "A": _annual(pat_cagr, roe),
        "N": _letter(week52, N_WEEK52, "N", gte=True),
        "S": _letter(volume, S_VOLUME, "S", gte=True),
        "L": _letter(rs_3m, L_RS_3M, "L", gte=False),
        "I": _letter(inst, I_INST, "I", gte=True),
    }
    scored = [v for v in letters.values() if v["pass"] is not None]
    passed = [v for v in scored if v["pass"]]
    return {
        "letters": letters,
        "letters_passed": len(passed),
        "letters_scored": len(scored),
        "leader_score": round(100.0 * len(passed) / len(LETTERS), 1) if scored else None,
    }


def sort_leader_rows(rows: list[dict[str, Any]], descending: bool = True) -> list[dict[str, Any]]:
    """More letters first, then fit. Unscored rows always sort last."""

    def sort_key(row: dict[str, Any]) -> tuple:
        view = row.get("leaders") or {}
        scored = int(view.get("letters_scored") or 0)
        missing = scored == 0
        passed = int(view.get("letters_passed") or 0)
        fit = float(view["leader_score"]) if view.get("leader_score") is not None else 0.0
        if descending:
            passed = -passed
            fit = -fit
        return (missing, passed, fit, row.get("symbol") or "")

    return sorted(rows, key=sort_key)


def _annual(pat_cagr: float | None, roe: float | None) -> dict[str, Any]:
    if pat_cagr is not None:
        return _letter(pat_cagr, A_PAT_CAGR, "A", gte=True)
    if roe is not None:
        letter = _letter(roe, A_ROE, "A", gte=True)
        letter["label"] = "ROE (annual CAGR unavailable)"
        return letter
    return _letter(None, A_PAT_CAGR, "A", gte=True)


def _letter(value: float | None, threshold: float, key: str, *, gte: bool) -> dict[str, Any]:
    passed: bool | None
    if value is None:
        passed = None
    elif gte:
        passed = value >= threshold
    else:
        passed = value > threshold
    return {
        "pass": passed,
        "value": value,
        "threshold": threshold,
        "label": _LABELS[key],
    }


def _threshold_for(key: str) -> float:
    return {
        "C": C_Q_PAT_YOY,
        "A": A_PAT_CAGR,
        "N": N_WEEK52,
        "S": S_VOLUME,
        "L": L_RS_3M,
        "I": I_INST,
    }[key]


def _metric_value(result: dict[str, Any], key: str) -> float | None:
    for pillar in (result.get("pillars") or {}).values():
        if not isinstance(pillar, dict):
            continue
        for metric in pillar.get("metrics") or []:
            if metric.get("key") == key:
                return _as_float(metric.get("value"))
    return None


def _first(*values: Any) -> float | None:
    for value in values:
        parsed = _as_float(value)
        if parsed is not None:
            return parsed
    return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
