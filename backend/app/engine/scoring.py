"""Turns pillar scores into per-horizon verdicts.

The core idea: the *same* evidence gets weighted differently depending on how
long you intend to hold. A stock can be a great business at a bad chart
(good long-term, poor swing) or a strong setup in a mediocre company
(better swing, still a poor long). Collapsing that into one number is exactly
the mistake this tries to avoid.

User-facing horizons are Swing and Long. Long asks whether the company is
worth owning; Swing asks whether the next few months are a reasonable entry.
Short-term setup metrics still exist as a pillar and feed Swing.

Weights are declarative and live here so they are easy to argue with and tune.
Within-pillar metric overlap is handled separately in metric_weights.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import pstdev
from typing import Any

from .common import Metric, Pillar
from .explanations import investor_facing_bullet, is_clean_investor_text
from .swing_regime import classify_swing

# Each horizon's weights must cover the same pillar set; missing pillars are
# renormalised away at scoring time.
HORIZONS: dict[str, dict[str, Any]] = {
    "swing": {
        "label": "Swing",
        "window": "1 to 3 months",
        "thesis": "Ride an established trend into a catalyst — usually the next results print.",
        "weights": {
            "technical_trend": 0.26, "technical_short": 0.16, "earnings": 0.16,
            "valuation": 0.12, "growth": 0.10, "sentiment": 0.08, "risk": 0.08,
            "profitability": 0.03, "health": 0.01,
        },
    },
    "long": {
        "label": "Long Term",
        "window": "1 to 3+ years",
        "thesis": "Own the business. Returns come from compounding and the price you pay.",
        "weights": {
            "profitability": 0.22, "growth": 0.20, "valuation": 0.20, "health": 0.16,
            "risk": 0.09, "earnings": 0.06, "technical_trend": 0.05,
            "sentiment": 0.02, "technical_short": 0.00,
        },
    },
}

# Within-pillar applicability. Default is 1.0 — the metric votes at the
# de-overlap weight in metric_weights.py. Only contaminated factors are
# listed. 0 means the metric is shown on the report but does not move this
# horizon. Pillar mix above is unchanged.
HORIZON_FACTOR: dict[str, dict[str, float]] = {
    "swing": {
        "rev_cagr": 0.55, "pat_cagr": 0.55,
        "dcf_upside": 0.45, "promoter_holding": 0.45,
        "pe": 0.45, "pe_vs_history": 0.45, "pb": 0.4, "ev_ebitda": 0.4,
        "peg": 0.35, "earnings_yield_spread": 0.35, "dividend_yield": 0.35,
    },
    "long": {
        "rsi14": 0.0, "pct_b": 0.0, "vs_sma20": 0.0, "ret_1w": 0.0,
        "ret_1m": 0.0,
        "volume_ratio": 0.0,
        "rs_3m": 0.2, "vs_sma50": 0.25,
        "q_rev_yoy": 0.25, "q_pat_yoy": 0.25,
        "avg_surprise": 0.4,
        "analyst_rating": 0.4, "analyst_upside": 0.4,
    },
}


def factor_scale(horizon: str, key: str) -> float:
    """How much a metric may influence this horizon. 1.0 is full, 0 is none."""
    return float(HORIZON_FACTOR.get(horizon, {}).get(key, 1.0))


def _horizon_pillar_score(pillar: Pillar, horizon: str) -> float | None:
    scored = []
    for m in pillar.metrics:
        if m.score is None:
            continue
        scale = factor_scale(horizon, m.key)
        if scale <= 0:
            continue
        scored.append((m.score, m.weight * scale))
    if not scored:
        return None
    total_w = sum(w for _, w in scored)
    if total_w == 0:
        return None
    return sum(score * w for score, w in scored) / total_w


def _horizon_pillar_coverage(pillar: Pillar, horizon: str) -> float:
    total = have = 0.0
    for m in pillar.metrics:
        scale = factor_scale(horizon, m.key)
        if scale <= 0:
            continue
        w = m.weight * scale
        total += w
        if m.score is not None:
            have += w
    return have / total if total else 0.0


# Blend used for the single headline number, tilted toward the long view.
OVERALL_BLEND = {"swing": 0.40, "long": 0.60}

VERDICT_BANDS = [
    (80, "Strong Buy", "strong-buy"),
    (66, "Buy", "buy"),
    (50, "Hold", "hold"),
    (35, "Reduce", "reduce"),
    (0, "Avoid", "avoid"),
]


@dataclass
class HorizonVerdict:
    key: str
    label: str
    window: str
    thesis: str
    score: float | None
    verdict: str
    verdict_class: str
    confidence: float
    confidence_label: str
    drivers: list[dict[str, Any]] = field(default_factory=list)
    detractors: list[dict[str, Any]] = field(default_factory=list)
    plan: dict[str, Any] = field(default_factory=dict)
    regime: str | None = None
    entry_quality: str | None = None
    swing_factors: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def verdict_for(score: float | None) -> tuple[str, str]:
    if score is None:
        return "Insufficient Data", "unknown"
    for threshold, label, cls in VERDICT_BANDS:
        if score >= threshold:
            return label, cls
    return "Avoid", "avoid"


def _confidence(pillars: dict[str, Pillar], weights: dict[str, float],
                horizon: str) -> tuple[float, str]:
    """Confidence = how much of the weighted evidence we actually have,
    discounted when the pillars disagree sharply with each other."""
    total_w = sum(w for k, w in weights.items() if w > 0)
    have_w, scores = 0.0, []
    for key, w in weights.items():
        if w <= 0:
            continue
        p = pillars.get(key)
        if p is None:
            continue
        hs = _horizon_pillar_score(p, horizon)
        if hs is None:
            continue
        have_w += w * _horizon_pillar_coverage(p, horizon)
        scores.append(hs)

    coverage = (have_w / total_w) if total_w else 0.0
    agreement = 1.0
    if len(scores) >= 3:
        # pstdev of ~30 across pillars means the signals are pulling apart.
        agreement = max(0.0, 1 - (pstdev(scores) / 35))

    conf = 0.65 * coverage + 0.35 * agreement
    conf = max(0.0, min(1.0, conf))
    label = "High" if conf >= 0.72 else "Medium" if conf >= 0.48 else "Low"
    return round(conf * 100, 1), label


def _evidence(pillars: dict[str, Pillar], weights: dict[str, float],
              horizon: str) -> tuple[list, list]:
    """Best and worst individual metrics, weighted by how much this horizon
    cares about the pillar they came from."""
    items = []
    for key, w in weights.items():
        if w <= 0.02:
            continue
        p = pillars.get(key)
        if not p:
            continue
        for m in p.metrics:
            if m.score is None:
                continue
            scale = factor_scale(horizon, m.key)
            if scale <= 0:
                continue
            items.append((m, p, w * scale))


    drivers, detractors = [], []
    for m, p, w in sorted(items, key=lambda t: (-(t[0].score * t[2]))):
        if m.score >= 68 and len(drivers) < 6:
            drivers.append(_ev(m, p))
    for m, p, w in sorted(items, key=lambda t: (t[0].score * t[2])):
        if m.score <= 42 and len(detractors) < 6:
            detractors.append(_ev(m, p))
    return drivers, detractors


def _ev(m: Metric, p: Pillar) -> dict[str, Any]:
    return {
        "metric": m.label,
        "pillar": p.label,
        "value": m.display,
        "score": round(m.score, 1) if m.score is not None else None,
        "note": m.note or f"{m.label} at {m.display}.",
    }


def _plan(horizon: str, tech, val, price: float | None) -> dict[str, Any]:
    """Actionable levels. Only emitted where the inputs genuinely support one."""
    if not price:
        return {}

    if horizon == "swing":
        # Whichever is lower: the ATR stop or the 50-DMA. Losing both is the exit.
        candidates = [x for x in (tech.suggested_stop, tech.sma50) if x]
        stop = min(candidates) if candidates else None
        target = tech.resistance * 1.05 if tech.resistance else None
        return _levels(price, stop, target,
                       "Hold while the 50-DMA holds; trail the technical stop after the next results print. "
                       "These are technical reference levels, not a fundamental price target.")
    fair = val.dcf_value
    return _levels(price, None, fair,
                   "Accumulate in tranches on weakness rather than in one lot; review annually against the thesis.")


def _levels(price: float, stop: float | None, target: float | None, guidance: str) -> dict[str, Any]:
    out: dict[str, Any] = {"guidance": guidance, "reference_price": round(price, 2)}
    if stop:
        out["stop_loss"] = round(stop, 2)
        out["risk_pct"] = round((stop / price - 1) * 100, 2)
    if target:
        out["target"] = round(target, 2)
        out["reward_pct"] = round((target / price - 1) * 100, 2)
    if stop and target and price > stop:
        rr = (target - price) / (price - stop)
        out["risk_reward"] = round(rr, 2)
    return out


def score_all(pillars: dict[str, Pillar], tech, val, price: float | None) -> dict[str, Any]:
    verdicts: dict[str, HorizonVerdict] = {}

    for key, spec in HORIZONS.items():
        weights: dict[str, float] = spec["weights"]
        num, den = 0.0, 0.0
        for pillar_key, w in weights.items():
            if w <= 0:
                continue
            p = pillars.get(pillar_key)
            if p is None:
                continue
            hs = _horizon_pillar_score(p, key)
            if hs is None:
                continue
            num += hs * w
            den += w
        score = (num / den) if den else None

        label, cls = verdict_for(score)
        conf, conf_label = _confidence(pillars, weights, key)
        drivers, detractors = _evidence(pillars, weights, key)

        ctx = classify_swing(tech) if key == "swing" else None
        verdicts[key] = HorizonVerdict(
            key=key, label=spec["label"], window=spec["window"], thesis=spec["thesis"],
            score=round(score, 1) if score is not None else None,
            verdict=label, verdict_class=cls,
            confidence=conf, confidence_label=conf_label,
            drivers=drivers, detractors=detractors,
            plan=_plan(key, tech, val, price),
            regime=None if ctx is None else ctx["regime"],
            entry_quality=None if ctx is None else ctx["entry_quality"],
            swing_factors=None if ctx is None else {
                "trend": ctx["trend"],
                "momentum": ctx["momentum"],
                "relative_strength": ctx["relative_strength"],
                "setup": ctx["setup"],
                "volume": ctx["volume"],
            },
        )

    blended_num = sum(OVERALL_BLEND[k] * v.score for k, v in verdicts.items() if v.score is not None)
    blended_den = sum(OVERALL_BLEND[k] for k, v in verdicts.items() if v.score is not None)
    overall = (blended_num / blended_den) if blended_den else None
    o_label, o_cls = verdict_for(overall)

    return {
        "overall": {
            "score": round(overall, 1) if overall is not None else None,
            "verdict": o_label,
            "verdict_class": o_cls,
            "blend": OVERALL_BLEND,
        },
        "horizons": {k: v.to_dict() for k, v in verdicts.items()},
    }


def build_pros_cons(pillars: dict[str, Pillar], red_flags: list[dict[str, str]]) -> dict[str, list[str]]:
    """Company-level pros and cons, horizon-independent."""
    pros, cons = [], []
    seen: set[str] = set()

    ranked = []
    for p in pillars.values():
        for m in p.metrics:
            if m.score is not None:
                ranked.append((m, p))

    for m, p in sorted(ranked, key=lambda t: -t[0].score):
        if m.score >= 70 and len(pros) < 7:
            text = investor_facing_bullet(m)
            if text and text not in seen:
                pros.append(text)
                seen.add(text)

    for m, p in sorted(ranked, key=lambda t: t[0].score):
        if m.score <= 40 and len(cons) < 7:
            text = investor_facing_bullet(m)
            if text and text not in seen:
                cons.append(text)
                seen.add(text)

    for flag in red_flags:
        if flag["severity"] in ("high", "medium") and flag["text"] not in seen:
            cons.insert(0, flag["text"])
            seen.add(flag["text"])

    for p in pillars.values():
        for note in p.notes:
            if not is_clean_investor_text(note):
                continue
            low = note.lower()
            if any(w in low for w in ("risk", "unreliable", "not available", "unavailable", "squeez", "rolling over", "thin")):
                if note not in seen and len(cons) < 10:
                    cons.append(note)
                    seen.add(note)
            elif any(w in low for w in ("intact", "working", "outperform", "confirming", "trigger", "operating leverage")):
                if note not in seen and len(pros) < 10:
                    pros.append(note)
                    seen.add(note)

    return {"pros": pros[:8], "cons": cons[:8]}
