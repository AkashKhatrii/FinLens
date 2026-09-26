"""Qualitative Accumulation layer for long-term wealth creation.

Not a horizon, not a 0–100 score, and not driven by Swing technicals.
A fundamental-deterioration gate can downgrade the base Long + Opportunity mapping.
"""
from __future__ import annotations

import re
from typing import Any

STATE_LABELS = {
    "ACCUMULATE": "Accumulate",
    "ACCUMULATE_GRADUALLY": "Accumulate Gradually",
    "WATCH_FOR_ACCUMULATION": "Watch for Accumulation",
    "DO_NOT_ACCUMULATE": "Do Not Accumulate",
}

DETERIORATION_NONE = "none"
DETERIORATION_EMERGING = "emerging_concern"
DETERIORATION_MATERIAL = "material"

_BUYS = {"Buy", "Strong Buy"}
_WEAK = {"Reduce", "Avoid"}
_QUALITY_PILLARS = ("profitability", "health", "growth")
_BANK_REASON_KEYS = (
    "gnpa", "nnpa", "pcr", "credit_cost", "slippages", "nim", "roa", "roe",
    "nii_growth", "loan_growth", "deposit_growth", "casa", "casa_trend",
    "car", "crar", "cet1", "cost_income",
)
_INDUSTRIAL_LABELS = {"roce", "fcf", "ev/ebitda", "cash conversion", "operating margin"}

# One reported period is a warning, not a thesis break.
_SINGLE_PERIOD_KEYS = frozenset({
    "q_rev_yoy", "q_pat_yoy", "rev_yoy", "pat_yoy",
})

# Multi-period industrial evidence already scored by FinLens.
_INDUSTRIAL_TREND_KEYS = frozenset({
    "rev_cagr", "pat_cagr", "margin_trend", "ocf_to_pat",
})

_INDUSTRIAL_ONLY_KEYS = frozenset({
    "roce", "ocf_to_pat", "fcf_margin", "fcf", "net_debt_ebitda", "ev_ebitda",
    "op_margin", "debt_equity", "interest_cover", "interest_cov", "current_ratio",
    "rev_cagr", "pat_cagr", "margin_trend", "net_margin",
})

_BANK_KEYS = frozenset({
    "gnpa", "nnpa", "pcr", "credit_cost", "slippages", "nim", "roa", "roe",
    "nii_growth", "loan_growth", "deposit_growth", "casa", "casa_trend",
    "car", "crar", "cet1", "cost_income", "restructured", "restructured_loans",
    "sma", "sma_or_stressed_assets", "write_offs", "recoveries",
})

_BANK_FAMILIES = {
    "asset_quality": frozenset({
        "gnpa", "nnpa", "pcr", "credit_cost", "slippages",
        "restructured", "restructured_loans", "sma", "sma_or_stressed_assets",
        "write_offs", "recoveries",
    }),
    "profitability": frozenset({
        "nim", "roa", "roe", "cost_income", "nii_growth",
    }),
    "capital": frozenset({"cet1", "car", "crar"}),
    "franchise": frozenset({
        "loan_growth", "deposit_growth", "casa", "casa_trend",
    }),
}

# Language already used in FinLens notes, plus explicit deterioration wording.
_DETERIORATION_NOTE = re.compile(
    r"deteriorat|compress|worsen|weakening|declining|squeezed|squeezing|"
    r"rising credit|rising slippage|increasing leverage|increasing debt|"
    r"not converting into cash|slower than revenue|margins are being squeezed|"
    r"asset quality worsening|credit cost is rising|slippages are worsening",
    re.I,
)
_IMPROVEMENT_NOTE = re.compile(
    r"expanding|compounding faster|converting into real cash|improv|"
    r"recover|strengthen|operating leverage is working",
    re.I,
)

_DOWNGRADE = {
    "ACCUMULATE": {
        DETERIORATION_EMERGING: "ACCUMULATE_GRADUALLY",
        DETERIORATION_MATERIAL: "WATCH_FOR_ACCUMULATION",
    },
    "ACCUMULATE_GRADUALLY": {
        DETERIORATION_EMERGING: "ACCUMULATE_GRADUALLY",
        DETERIORATION_MATERIAL: "WATCH_FOR_ACCUMULATION",
    },
    "WATCH_FOR_ACCUMULATION": {
        DETERIORATION_EMERGING: "WATCH_FOR_ACCUMULATION",
        DETERIORATION_MATERIAL: "WATCH_FOR_ACCUMULATION",
    },
}


def classify_accumulation(
    *,
    long_verdict: str | None,
    pillars: dict[str, Any] | None = None,
    opportunity_category: str | None = None,
    bank_metrics: dict[str, Any] | None = None,
    thesis_breakers: list[str] | None = None,
    long_score: float | None = None,
    valuation: dict[str, Any] | None = None,
    fundamentals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a qualitative Accumulation view. Never reads Swing or technicals."""
    del long_score, valuation, fundamentals  # accepted for call-site compatibility; unused as gates
    pillars = pillars or {}
    is_bank = bool(bank_metrics)
    quality = _quality_average(pillars)
    expensive = _valuation_stretched(pillars)
    deterioration, det_evidence = _deterioration(pillars, bank_metrics, is_bank)
    improved = _demonstrated_improvement(pillars, is_bank)
    state = _base_state(long_verdict, opportunity_category, improved)
    if state == "ACCUMULATE" and expensive:
        state = "ACCUMULATE_GRADUALLY"
    state = _apply_deterioration(state, deterioration)
    reasons = _reasons(
        state, long_verdict, opportunity_category, pillars, bank_metrics,
        expensive, quality, deterioration, det_evidence, improved,
    )
    monitors = _monitors(state, is_bank, thesis_breakers, deterioration, det_evidence)
    return {
        "state": state,
        "label": STATE_LABELS[state],
        "rationale": _rationale(
            state, long_verdict, opportunity_category, expensive, deterioration,
        ),
        "accumulation_reasons": reasons,
        "monitor_conditions": monitors,
        "thesis_risk": _thesis_risk(state, expensive, quality, deterioration),
        "confidence": _confidence(quality, opportunity_category, deterioration),
        "context": _context(state, long_verdict, deterioration),
        "deterioration": deterioration,
        "deterioration_evidence": det_evidence,
    }


def accumulation_from_analysis(
    result: dict[str, Any],
    opportunity_category: str | None = None,
    thesis_breakers: list[str] | None = None,
) -> dict[str, Any]:
    """Classify from an analysis payload without reading price tape or Swing."""
    long_h = ((result.get("horizons") or {}).get("long") or {})
    return classify_accumulation(
        long_verdict=long_h.get("verdict"),
        long_score=long_h.get("score"),
        pillars=result.get("pillars") or {},
        opportunity_category=opportunity_category,
        bank_metrics=result.get("bank_metrics"),
        thesis_breakers=thesis_breakers,
        valuation=result.get("valuation"),
        fundamentals=result.get("fundamentals"),
    )


def _state_from_label(value: str) -> str | None:
    folded = _norm_label(value)
    for key, label in STATE_LABELS.items():
        if _norm_label(key) == folded or _norm_label(label) == folded:
            return key
    return None


def _norm_label(value: str) -> str:
    return re.sub(r"[^a-z]+", "", value.lower())


def _pillar_score(pillars: dict[str, Any], key: str) -> float | None:
    raw = pillars.get(key) or {}
    score = raw.get("score") if isinstance(raw, dict) else None
    try:
        return None if score is None else float(score)
    except (TypeError, ValueError):
        return None


def _quality_average(pillars: dict[str, Any]) -> float | None:
    scores = [_pillar_score(pillars, key) for key in _QUALITY_PILLARS]
    present = [s for s in scores if s is not None]
    if not present:
        return None
    return sum(present) / len(present)


def _valuation_stretched(pillars: dict[str, Any]) -> bool | None:
    score = _pillar_score(pillars, "valuation")
    if score is None:
        return None
    return score < 40


def _base_state(
    long_verdict: str | None,
    opportunity: str | None,
    improved: bool,
) -> str:
    """Long + Opportunity mapping. Quality cutoffs do not decide the state."""
    verdict = long_verdict or "Hold"
    if verdict in _WEAK:
        return "DO_NOT_ACCUMULATE"
    if verdict in _BUYS:
        if opportunity in {"Watch", "Emerging Opportunity"}:
            return "ACCUMULATE_GRADUALLY"
        return "ACCUMULATE"
    if opportunity == "No Opportunity":
        return "DO_NOT_ACCUMULATE"
    if opportunity == "Established Opportunity":
        return "ACCUMULATE_GRADUALLY"
    if opportunity == "Emerging Opportunity":
        if improved:
            return "ACCUMULATE_GRADUALLY"
        return "WATCH_FOR_ACCUMULATION"
    if opportunity == "Watch":
        return "WATCH_FOR_ACCUMULATION"
    return "WATCH_FOR_ACCUMULATION"


def _apply_deterioration(state: str, deterioration: str) -> str:
    if deterioration == DETERIORATION_NONE:
        return state
    return _DOWNGRADE.get(state, {}).get(deterioration, state)


def _metric_verdict(metric: dict[str, Any]) -> str:
    raw = metric.get("verdict")
    if raw in {"good", "ok", "bad", "unknown"}:
        return raw
    try:
        score = float(metric.get("score"))
    except (TypeError, ValueError):
        return "unknown"
    if score >= 70:
        return "good"
    if score >= 45:
        return "ok"
    return "bad"


def _iter_metrics(
    pillars: dict[str, Any],
    bank_metrics: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for pillar in (pillars or {}).values():
        if not isinstance(pillar, dict):
            continue
        for metric in pillar.get("metrics") or []:
            if isinstance(metric, dict):
                out.append(metric)
        for note in pillar.get("notes") or []:
            text = str(note).strip()
            if text:
                out.append({"key": pillar.get("key") or "", "note": text, "score": None})
    for group in ((bank_metrics or {}).get("groups") or []):
        for metric in (group.get("metrics") or []):
            if isinstance(metric, dict):
                out.append(metric)
    return out


def _allowed_key(key: str, is_bank: bool) -> bool:
    if not key or key in _SINGLE_PERIOD_KEYS:
        return False
    if is_bank:
        return key in _BANK_KEYS
    return key not in _BANK_KEYS - {"roe"}


def _deterioration(
    pillars: dict[str, Any],
    bank_metrics: dict[str, Any] | None,
    is_bank: bool,
) -> tuple[str, list[str]]:
    metrics = _iter_metrics(pillars, bank_metrics)
    signals: dict[str, str] = {}
    bad_bank_keys: list[str] = []

    for metric in metrics:
        key = str(metric.get("key") or "").strip()
        note = str(metric.get("note") or "").strip()
        label = str(metric.get("label") or key or "Fundamentals")
        if key in _SINGLE_PERIOD_KEYS:
            continue
        if is_bank and key in _INDUSTRIAL_ONLY_KEYS:
            continue
        if not is_bank and key in (_BANK_KEYS - {"roe"}):
            continue

        sid = key or f"note:{(note or label)[:48]}"
        if note and _DETERIORATION_NOTE.search(note):
            if not key or _allowed_key(key, is_bank) or key in _QUALITY_PILLARS:
                signals.setdefault(sid, f"{label}: {note}")

        if not key:
            continue
        if is_bank:
            if key in _BANK_KEYS and _metric_verdict(metric) == "bad":
                bad_bank_keys.append(key)
        elif key in _INDUSTRIAL_TREND_KEYS and _metric_verdict(metric) == "bad":
            signals.setdefault(key, f"{label} is weak on a multi-period basis.")

    family_count = 0
    if is_bank:
        families = {
            family for family, keys in _BANK_FAMILIES.items()
            if any(k in keys for k in bad_bank_keys)
        }
        family_count = len(families)
        # One weak bank snapshot is not deterioration. Two families is material.
        if family_count >= 2:
            signals["bank_families"] = (
                "Multiple bank fundamental families are weak on the reported evidence "
                f"({', '.join(sorted(families))})."
            )

    evidence = list(signals.values())
    if len(evidence) >= 2 or family_count >= 2:
        return DETERIORATION_MATERIAL, evidence[:6]
    if len(evidence) == 1:
        return DETERIORATION_EMERGING, evidence
    return DETERIORATION_NONE, []


def _demonstrated_improvement(pillars: dict[str, Any], is_bank: bool) -> bool:
    """Actual multi-period improvement, not merely a high quality average."""
    if is_bank:
        keys = _BANK_KEYS
    else:
        keys = _INDUSTRIAL_TREND_KEYS
    hits = 0
    for metric in _iter_metrics(pillars, None):
        key = str(metric.get("key") or "").strip()
        if key in _SINGLE_PERIOD_KEYS or key not in keys:
            continue
        if is_bank and key in _INDUSTRIAL_ONLY_KEYS:
            continue
        note = str(metric.get("note") or "")
        good = _metric_verdict(metric) == "good"
        improving = bool(note and _IMPROVEMENT_NOTE.search(note))
        if good or improving:
            hits += 1
    return hits >= 2


def _rationale(
    state: str,
    long_verdict: str | None,
    opportunity: str | None,
    expensive: bool | None,
    deterioration: str,
) -> str:
    if state == "ACCUMULATE":
        return (
            "Proven business with strong long-term economics and no material deterioration "
            "in the available evidence."
        )
    if state == "ACCUMULATE_GRADUALLY":
        if expensive:
            return (
                "Long-term thesis remains attractive, but current valuation makes gradual "
                "position building more appropriate than a full-size entry."
            )
        if opportunity == "Emerging Opportunity":
            return (
                "Long-term thesis remains attractive. Improvement is visible in the available "
                "evidence, but the business is not yet a full-size Long Buy, so gradual "
                "position building is more appropriate."
            )
        return (
            "Long-term thesis remains attractive, but current valuation or unresolved "
            "fundamentals make gradual position building more appropriate than a full-size entry."
        )
    if state == "WATCH_FOR_ACCUMULATION":
        if deterioration != DETERIORATION_NONE:
            return (
                "The long-term opportunity is interesting, but fundamental deterioration "
                "needs to be monitored before building exposure."
            )
        return (
            "The long-term opportunity is interesting, but important evidence remains "
            "unresolved or fundamental deterioration needs to be monitored before building exposure."
        )
    return (
        f"Current evidence does not support building a long-term position "
        f"({long_verdict or 'weak'} on the Long horizon)."
    )


def _context(state: str, long_verdict: str | None, deterioration: str) -> str:
    if state in {"ACCUMULATE", "ACCUMULATE_GRADUALLY"}:
        if long_verdict == "Hold":
            return (
                "Long Hold does not mean do not buy any shares. "
                "Accumulate Gradually means the long-term thesis is attractive enough for gradual position building, "
                "but not strong enough for a full-size Long Buy today."
            )
        return "The stock is attractive to own today and also suitable for gradually building a position."
    if state == "WATCH_FOR_ACCUMULATION":
        if deterioration != DETERIORATION_NONE:
            return (
                "Interesting company, but fundamentals are deteriorating. "
                "Monitor the business evidence before starting or materially increasing a long-term position."
            )
        return (
            "Interesting future possibility, but not proven yet. "
            "Monitor for evidence before starting or materially increasing a long-term position."
        )
    return "Do not treat a cheap multiple or a weak chart as a reason to start accumulating."


def _reasons(
    state: str,
    long_verdict: str | None,
    opportunity: str | None,
    pillars: dict[str, Any],
    bank_metrics: dict[str, Any] | None,
    expensive: bool | None,
    quality: float | None,
    deterioration: str,
    det_evidence: list[str],
    improved: bool,
) -> list[str]:
    reasons: list[str] = []
    if bank_metrics:
        reasons.extend(_bank_reasons(bank_metrics))
    else:
        reasons.extend(_industrial_reasons(pillars))
    if opportunity:
        reasons.append(f"Opportunity classification is {opportunity}.")
    if long_verdict:
        reasons.append(
            f"Quantitative Long is {long_verdict} on current evidence, "
            "which is not treated as an automatic accumulation instruction."
        )
    if expensive:
        reasons.append(
            "Valuation looks demanding relative to the supplied multiples, "
            "so any accumulation should stay gradual."
        )
    if quality is None:
        reasons.append("Some quality metrics are missing; missing data is treated as unknown, not as weakness.")
    if improved and opportunity == "Emerging Opportunity" and state == "ACCUMULATE_GRADUALLY":
        reasons.append("Improvement is visible across multiple available multi-period metrics.")
    if deterioration == DETERIORATION_MATERIAL:
        reasons.append(
            "Material fundamental deterioration is visible in the available evidence, "
            "so Opportunity classification does not protect the accumulation case."
        )
        reasons.extend(det_evidence[:2])
    elif deterioration == DETERIORATION_EMERGING:
        reasons.append(
            "There is an emerging fundamental concern, so accumulation is more cautious "
            "than the base Long and Opportunity mapping."
        )
        reasons.extend(det_evidence[:1])
    elif state in {"ACCUMULATE", "ACCUMULATE_GRADUALLY"}:
        reasons.append("No material deterioration is evident in the available multi-period evidence.")
    if state == "DO_NOT_ACCUMULATE" and not reasons:
        reasons.append("Long-term fundamentals do not currently support building a position.")
    return reasons[:6]


def _industrial_reasons(pillars: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in _QUALITY_PILLARS:
        pillar = pillars.get(key) or {}
        for metric in pillar.get("metrics") or []:
            label = str(metric.get("label") or "")
            display = metric.get("display")
            if not display:
                continue
            if label.lower() in _INDUSTRIAL_LABELS or label.lower() in {"roe", "roce", "revenue yoy", "debt/equity"}:
                note = (metric.get("note") or "").strip()
                out.append(f"{label} is {display}" + (f" — {note}" if note else "."))
            if len(out) >= 3:
                return out
    return out


def _bank_reasons(bank_metrics: dict[str, Any]) -> list[str]:
    by_key = {
        item.get("key"): item
        for group in (bank_metrics.get("groups") or [])
        for item in (group.get("metrics") or [])
        if item.get("key")
    }
    out: list[str] = []
    for key in _BANK_REASON_KEYS:
        item = by_key.get(key)
        if not item or not item.get("display"):
            continue
        out.append(f"{item.get('label') or key.upper()} is {item['display']} on the reported bank fundamentals.")
        if len(out) >= 4:
            break
    if out:
        out.append("Bank accumulation uses canonical asset-quality, profitability and capital measures, not industrial cash-flow ratios.")
    return out


def _monitors(
    state: str,
    is_bank: bool,
    thesis_breakers: list[str] | None,
    deterioration: str,
    det_evidence: list[str],
) -> list[str]:
    if state == "DO_NOT_ACCUMULATE":
        return ["Reassess only if the long-term business case itself improves on reported evidence."]
    out: list[str] = []
    if deterioration != DETERIORATION_NONE:
        out.append("Monitor whether the fundamental deterioration persists or reverses on reported evidence.")
        out.extend(det_evidence[:1])
    for item in thesis_breakers or []:
        text = str(item).strip()
        if text:
            out.append(text)
    if is_bank:
        out.append("Reassess accumulation if asset quality, credit costs, or capital strength deteriorate materially.")
    else:
        out.append("Reassess accumulation if returns on incremental capital deteriorate materially.")
    out.append("Reassess if the expected long-term growth thesis is not developing.")
    seen: set[str] = set()
    unique = []
    for item in out:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique[:3]


def _thesis_risk(
    state: str,
    expensive: bool | None,
    quality: float | None,
    deterioration: str,
) -> str:
    if state == "DO_NOT_ACCUMULATE" or deterioration == DETERIORATION_MATERIAL:
        return "High"
    if state == "WATCH_FOR_ACCUMULATION" or quality is None or expensive or deterioration == DETERIORATION_EMERGING:
        return "Medium"
    return "Low"


def _confidence(
    quality: float | None,
    opportunity: str | None,
    deterioration: str,
) -> str:
    if deterioration == DETERIORATION_MATERIAL:
        return "Low"
    if quality is None and not opportunity:
        return "Low"
    if opportunity == "Established Opportunity" and deterioration == DETERIORATION_NONE:
        return "High"
    if opportunity in {"Emerging Opportunity", "Watch"} or deterioration == DETERIORATION_EMERGING:
        return "Medium"
    if quality is None:
        return "Low"
    return "Medium"
