"""Deterministic validation and normalization of bank KPI candidates.

This layer does not call an AI model and does not score. It only checks that
an extracted candidate is well-formed and maps labels into BankMetrics keys.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .bank_documents import extract_period
from .bank_metrics import (
    BANK_METRIC_KEYS,
    COMPARISON_PIT,
    COMPARISON_QOQ,
    COMPARISON_YOY,
    MEASUREMENT_AVERAGE,
    MEASUREMENT_EOP,
    RawFact,
)
from .pdf_text import PdfPage

_GROWTH_KEYS = {"nii_growth", "loan_growth", "deposit_growth", "casa_trend"}
_AMOUNT_KEYS = {"slippages", "writeoffs", "recoveries"}

_MISSING_RE = re.compile(r"^(n\.?a\.?|na|nil|—|--|-)\b", re.I)
_SUBSIDIARY_RE = re.compile(r"\bsubsidiar|\bgroup companies\b", re.I)
_COMBINED_METRIC_RE = re.compile(
    r"upgrades?\s*(?:&|and|,)\s*recover|"
    r"recover(?:y|ies)?\s*(?:&|and|,)\s*upgrades?|"
    r"recover(?:y|ies)?\s*\+\s*upgrad|"
    r"upgrad(?:e|es|ation)?\s*\+\s*recover|"
    r"write[-\s]?offs?\s*(?:&|and)\s*recover|"
    r"recover(?:ies|y)\s*(?:&|and)\s*write[-\s]?offs?|"
    r"write[-\s]?offs?\s*(?:&|and)\s*upgrades?",
    re.I,
)
_COMPARE_PREFIX_RE = re.compile(
    r"(?:compared\s+with|compared\s+to|versus|\bvs\.?\b|against|from)\s*$",
    re.I,
)
_MON_YY_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|"
    r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|"
    r"Oct|Nov|Dec)[.'’\- ]*(\d{2})(?!\d)",
    re.I,
)

_ALIASES: tuple[tuple[str, str], ...] = (
    ("gnpa", r"gross\s+npa|gross\s+non[- ]performing(?:\s+assets?)?|\bgnpa\b"),
    ("nnpa", r"net\s+npa|net\s+non[- ]performing(?:\s+assets?)?|\bnnpa\b"),
    ("pcr", r"provision\s+coverage(?:\s+ratio)?|\bpcr\b"),
    ("credit_cost", r"credit\s+costs?"),
    ("slippages", r"slippage(?:s|\s+ratio)?"),
    ("nim", r"net\s+interest\s+margin|\bnim\b"),
    ("roa", r"return\s+on\s+(?:average\s+)?assets|\broaa\b|\broa\b"),
    ("roe", r"return\s+on\s+(?:average\s+)?equity|\broae\b|\broe\b"),
    ("nii_growth", r"nii\s+growth|net\s+interest\s+income\s+growth"),
    ("loan_growth", r"(?:advances|loans?|credit)\s+growth"),
    ("deposit_growth", r"deposits?\s+growth"),
    ("casa_trend", r"casa\s+trend"),
    ("casa", r"\bcasa\b(?:\s+ratio)?"),
    ("cet1", r"common\s+equity\s+tier\s*1|\bcet\s*[-–]?\s*1\b"),
    ("car", r"total\s+car|capital\s+adequacy|\bcrar\b|\bcar\b"),
    ("cost_income", r"cost\s*[-/]?\s*to\s*[-/]?\s*income|cost\s*/\s*income"),
    ("restructured_loans", r"restructured(?:\s+loans?)?"),
    ("sma_or_stressed_assets", r"\bsma(?:\s*[- ]?\s*\d)?\b|stressed\s+assets"),
    ("writeoffs", r"write[-\s]?offs?"),
    ("recoveries", r"\brecoveries\b"),
)

_ALIAS_RES = tuple((key, re.compile(pattern, re.I)) for key, pattern in _ALIASES)

_UNIT_ALIASES = {
    "percent": "%",
    "pct": "%",
    "%": "%",
    "percentage": "%",
    "percentage_points": "%",
    "pp": "%",
    "bps": "bps",
    "bp": "bps",
    "basis_points": "bps",
    "basis points": "bps",
    "inr_bn": "₹ bn",
    "rs_bn": "₹ bn",
    "₹ bn": "₹ bn",
    "inr billion": "₹ bn",
}

_BASIS_ALIASES = {
    "yoy": COMPARISON_YOY,
    "year_on_year": COMPARISON_YOY,
    "year-on-year": COMPARISON_YOY,
    "year on year": COMPARISON_YOY,
    "y-o-y": COMPARISON_YOY,
    "qoq": COMPARISON_QOQ,
    "quarter_on_quarter": COMPARISON_QOQ,
    "quarter-on-quarter": COMPARISON_QOQ,
    "quarter on quarter": COMPARISON_QOQ,
    "q-o-q": COMPARISON_QOQ,
    "point_in_time": COMPARISON_PIT,
    "point-in-time": COMPARISON_PIT,
    "point in time": COMPARISON_PIT,
    "pit": COMPARISON_PIT,
    "spot": COMPARISON_PIT,
}

_SCOPE_ALIASES = {
    "standalone": "standalone",
    "solo": "standalone",
    "consolidated": "consolidated",
    "consol": "consolidated",
}

_MEASUREMENT_ALIASES = {
    "average": MEASUREMENT_AVERAGE,
    "avg": MEASUREMENT_AVERAGE,
    "qab": MEASUREMENT_AVERAGE,
    "quarterly_average": MEASUREMENT_AVERAGE,
    "quarterly average": MEASUREMENT_AVERAGE,
    "end_of_period": MEASUREMENT_EOP,
    "end-of-period": MEASUREMENT_EOP,
    "end of period": MEASUREMENT_EOP,
    "eop": MEASUREMENT_EOP,
    "meb": MEASUREMENT_EOP,
    "month_end": MEASUREMENT_EOP,
    "month-end": MEASUREMENT_EOP,
    "month end": MEASUREMENT_EOP,
    "period_end": MEASUREMENT_EOP,
    "period-end": MEASUREMENT_EOP,
    "period end": MEASUREMENT_EOP,
}

_SERIES_ALIASES = {
    "ex_agri": "ex_agri",
    "ex-agri": "ex_agri",
    "excluding_agri": "ex_agri",
    "specific": "specific",
    "net_of_recoveries": "net_of_recoveries",
    "excluding_recoveries": "net_of_recoveries",
    "including_writeoffs": "including_writeoffs",
    "including_auca": "including_writeoffs",
    "incl_auca": "including_writeoffs",
    "aggregated": "including_writeoffs",
    "domestic": "domestic",
}


@dataclass
class ValidatedExtraction:
    facts: list[RawFact] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    malformed: bool = False


def parse_percent(text: str) -> tuple[float, str] | None:
    blob = (text or "").strip()
    if not blob or _MISSING_RE.match(blob):
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", blob)
    if not match:
        return None
    leading = blob[: match.start()]
    if re.search(r"[A-Za-z]", leading):
        return None
    return float(match.group(1)), "%"


def normalize_metric_name(name: str) -> str | None:
    blob = re.sub(r"\s+", " ", (name or "").strip())
    if not blob:
        return None
    if re.search(r"\bat-?1\b", blob, re.I) and not re.search(r"cet", blob, re.I):
        return None
    if re.search(r"\btier\s*2\b", blob, re.I):
        return None
    if re.search(r"\btier\s*1\b", blob, re.I) and not re.search(
        r"cet|common\s+equity", blob, re.I
    ):
        return None
    lowered = blob.lower().replace("-", "_").replace(" ", "_")
    if lowered in BANK_METRIC_KEYS:
        return lowered
    for key, pattern in _ALIAS_RES:
        if pattern.fullmatch(blob) or pattern.search(blob):
            return key
    return None


def normalize_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    blob = re.sub(r"\s+", " ", str(unit).strip().lower())
    return _UNIT_ALIASES.get(blob)


def normalize_basis(basis: str | None) -> str | None:
    if basis is None or str(basis).strip() == "":
        return None
    blob = re.sub(r"\s+", " ", str(basis).strip().lower())
    return _BASIS_ALIASES.get(blob)


def normalize_scope(scope: str | None) -> str | None:
    if scope is None or str(scope).strip() == "":
        return None
    blob = re.sub(r"\s+", " ", str(scope).strip().lower())
    return _SCOPE_ALIASES.get(blob)


def normalize_measurement(measurement: str | None) -> str | None:
    if measurement is None or str(measurement).strip() == "":
        return None
    blob = re.sub(r"\s+", " ", str(measurement).strip().lower())
    return _MEASUREMENT_ALIASES.get(blob)


def normalize_period_label(period: str | None) -> str | None:
    if period is None:
        return None
    blob = str(period).strip()
    if not blob or blob.lower() in {"unknown", "none", "null", "n/a"}:
        return None
    parsed = extract_period(blob)
    if parsed:
        return parsed
    match = re.fullmatch(r"Q\s*([1-4])\s*[-_/]?\s*(?:20)?(\d{2})", blob, re.I)
    if match:
        return f"Q{match.group(1)} FY{match.group(2)}"
    match = _MON_YY_RE.search(blob)
    if match:
        year = 2000 + int(match.group(2))
        return extract_period(f"{match.group(1)} {year}")
    if re.fullmatch(r"Q[1-4] FY\d{2}", blob):
        return blob
    return None


def select_metric_candidate(
    facts: list[RawFact],
    key: str,
    target_period: str | None = None,
) -> RawFact | None:
    eligible = [
        fact for fact in facts
        if fact.key == key
        and not fact.series
        and _period_eligible(fact.period, target_period)
    ]
    if not eligible:
        return None
    if key in _GROWTH_KEYS or key == "casa":
        distinct = {
            (fact.value, fact.unit, fact.comparison, fact.measurement)
            for fact in eligible
        }
        if len(distinct) > 1:
            return None
    scopes = {fact.consolidation for fact in eligible if fact.consolidation}
    if len(scopes) > 1 and len({(fact.value, fact.unit) for fact in eligible}) > 1:
        return None
    unique_values = {(fact.value, fact.unit) for fact in eligible}
    scored = [
        (
            _candidate_score(fact, key, target_period),
            fact.confidence if fact.confidence is not None else -1.0,
            -(fact.page or 10**9),
            fact,
        )
        for fact in eligible
    ]
    scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    if key in _GROWTH_KEYS:
        return scored[0][3]
    if len(unique_values) == 1:
        return scored[0][3]
    if len(scored) >= 2 and scored[0][0] == scored[1][0]:
        top, second = scored[0][3], scored[1][3]
        if (top.value, top.unit) != (second.value, second.unit):
            return None
        if top.consolidation and second.consolidation and top.consolidation != second.consolidation:
            return None
    return scored[0][3]


def validate_ai_candidates(
    payload: object,
    pages: list[PdfPage],
    target_period: str | None = None,
) -> ValidatedExtraction:
    del target_period
    result = ValidatedExtraction()
    if not isinstance(payload, dict) or not isinstance(payload.get("candidates"), list):
        result.malformed = True
        result.rejected.append("AI output was not a JSON object with a candidates list.")
        return result

    page_numbers = {page.number for page in pages}
    for index, raw in enumerate(payload["candidates"]):
        reason = _reject_candidate(raw, page_numbers)
        if reason:
            result.rejected.append(f"candidates[{index}]: {reason}")
            continue
        item = raw
        key = normalize_metric_name(str(item.get("metric", "")))
        unit = normalize_unit(item.get("unit"))
        basis = normalize_basis(item.get("basis"))
        evidence = str(item.get("evidence") or "").strip()
        raw_label = str(item.get("raw_label") or item.get("metric") or "")
        value = float(item["value"])
        key = _remap_metric_key(key, evidence, raw_label, basis)
        if basis is None:
            basis = COMPARISON_YOY if key in _GROWTH_KEYS else COMPARISON_PIT
        result.facts.append(
            RawFact(
                key=key or "",
                raw_label=raw_label,
                value=value,
                unit=unit or "%",
                period=normalize_period_label(item.get("period")),
                comparison=basis,
                measurement=_resolve_measurement(item, evidence, raw_label, value),
                consolidation=normalize_scope(item.get("scope")),
                excerpt=evidence,
                page=_as_page(item.get("page")),
                confidence=_as_confidence(item.get("confidence")),
                uncertain=bool(item.get("uncertain")),
                series=_resolve_series(key or "", item, evidence, raw_label, value),
            )
        )
    return result


def _reject_candidate(raw: object, page_numbers: set[int]) -> str | None:
    if not isinstance(raw, dict):
        return "candidate is not an object"
    key = normalize_metric_name(str(raw.get("metric", "")))
    if key is None:
        return f"invalid metric name {raw.get('metric')!r}"
    value = raw.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "value is not numeric"
    if not math.isfinite(float(value)):
        return "value is not finite"
    unit = normalize_unit(raw.get("unit"))
    if unit is None:
        return f"invalid unit {raw.get('unit')!r}"
    if key not in _AMOUNT_KEYS and unit not in {"%", "bps"}:
        return f"unit {unit!r} is not valid for {key}"
    if raw.get("basis") not in (None, ""):
        if normalize_basis(raw.get("basis")) is None:
            return f"invalid basis {raw.get('basis')!r}"
    if raw.get("scope") not in (None, ""):
        if normalize_scope(raw.get("scope")) is None:
            return f"invalid scope {raw.get('scope')!r}"
    if raw.get("measurement") not in (None, ""):
        if normalize_measurement(raw.get("measurement")) is None:
            return f"invalid measurement {raw.get('measurement')!r}"
    evidence = str(raw.get("evidence") or "").strip()
    raw_label = str(raw.get("raw_label") or "")
    if not evidence:
        return "evidence is missing"
    if _SUBSIDIARY_RE.search(evidence):
        return "candidate refers to a subsidiary rather than the bank"
    if key in {"recoveries", "writeoffs"} and _COMBINED_METRIC_RE.search(
        evidence + " " + raw_label
    ):
        return "combined figure is not the requested metric"
    if not _value_in_evidence(float(value), evidence):
        return "evidence does not contain the reported value"
    if _is_comparison_only_value(float(value), evidence):
        return "value is a prior-period or compared-with figure, not the current metric"
    page = raw.get("page")
    if page is not None and page != "":
        parsed_page = _as_page(page)
        if parsed_page is None:
            return f"invalid page {page!r}"
        if page_numbers and parsed_page not in page_numbers:
            return f"page {parsed_page} is not in the supplied document pages"
    if "confidence" in raw and raw.get("confidence") is not None:
        confidence = _as_confidence(raw.get("confidence"))
        if confidence is None:
            return f"confidence {raw.get('confidence')!r} is not in 0..1"
    if raw.get("period") not in (None, ""):
        if normalize_period_label(raw.get("period")) is None and str(raw.get("period")).strip().lower() not in {
            "unknown", "none", "null", "n/a",
        }:
            return f"unparseable period {raw.get('period')!r}"
    return None


def _as_page(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and value.is_integer() and value > 0:
        return int(value)
    return None


def _as_confidence(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if 0.0 <= number <= 1.0:
        return number
    return None


def _value_in_evidence(value: float, evidence: str) -> bool:
    blob = (evidence or "").replace(",", "")
    return _value_token_re(value).search(blob) is not None


def _value_token_re(value: float) -> re.Pattern[str]:
    if abs(value - round(value)) < 1e-9:
        return re.compile(rf"(?<![\d.]){int(round(value))}(?:\.0+)?(?!\d)")
    rendered = format(value, ".10f").rstrip("0").rstrip(".")
    return re.compile(rf"(?<![\d.]){re.escape(rendered)}0*(?!\d)")


def _is_comparison_only_value(value: float, evidence: str) -> bool:
    blob = (evidence or "").replace(",", "")
    matches = list(_value_token_re(value).finditer(blob))
    if not matches:
        return False
    if all(_COMPARE_PREFIX_RE.search(blob[: match.start()]) for match in matches):
        return True
    return all(_inside_unclosed_paren(blob, match.start()) for match in matches)


def _inside_unclosed_paren(blob: str, index: int) -> bool:
    before = blob[:index]
    return before.count("(") > before.count(")")


def _remap_metric_key(
    key: str | None,
    evidence: str,
    raw_label: str,
    basis: str | None,
) -> str | None:
    haystack = f"{raw_label} {evidence}"
    looks_like_growth = basis in {COMPARISON_YOY, COMPARISON_QOQ} or bool(
        re.search(r"\bgrew\b|\bgrowth\b", haystack, re.I)
    )
    if key == "casa":
        return "casa_trend" if looks_like_growth else key
    if key == "casa_trend":
        return "casa_trend" if looks_like_growth else "casa"
    return key


def _resolve_measurement(
    item: dict,
    evidence: str,
    raw_label: str,
    value: float,
) -> str | None:
    explicit = normalize_measurement(item.get("measurement"))
    if explicit:
        return explicit
    prefix = _prefix_before_value(value, f"{raw_label} {evidence}")
    suffix = _suffix_after_value(value, f"{raw_label} {evidence}")
    haystack = f"{raw_label} {prefix}"
    if re.search(r"\bqab\b|quarterly\s+average|\baverage\b|\bavg\b", haystack, re.I):
        return MEASUREMENT_AVERAGE
    if re.search(r"\bqab\b|quarterly\s+average", suffix, re.I):
        return MEASUREMENT_AVERAGE
    if re.search(r"\beop\b|end[-\s]?of[-\s]?period|period[-\s]?end|\bmeb\b|month[-\s]?end", haystack, re.I):
        return MEASUREMENT_EOP
    if re.search(r"\beop\b|end[-\s]?of[-\s]?period|period[-\s]?end|\bmeb\b|month[-\s]?end", suffix, re.I):
        return MEASUREMENT_EOP
    return None


def _resolve_series(
    key: str,
    item: dict,
    evidence: str,
    raw_label: str,
    value: float,
) -> str | None:
    explicit = item.get("series")
    if explicit not in (None, ""):
        blob = re.sub(r"\s+", " ", str(explicit).strip().lower())
        mapped = _SERIES_ALIASES.get(blob)
        if mapped:
            return mapped
    prefix = _prefix_before_value(value, f"{raw_label} {evidence}")
    haystack = f"{raw_label} {prefix}"
    if key in {"gnpa", "nnpa"} and re.search(r"ex[-\s]?agri|excluding\s+agri", haystack, re.I):
        return "ex_agri"
    if key == "pcr" and re.search(r"\bspecific\b", haystack, re.I):
        return "specific"
    if key == "pcr" and re.search(
        r"incl(?:uding|\.)?\s*auca|"
        r"technical\s+write|"
        r"aggregat(?:ed|e)\s+(?:basis|coverage)|"
        r"including\s+(?:technical\s+)?write",
        haystack,
        re.I,
    ):
        return "including_writeoffs"
    if key == "nim" and re.search(r"\bdomestic\b", haystack, re.I):
        near = haystack[-24:]
        if re.search(r"whole\s+bank|\boverall\b", haystack, re.I):
            if re.search(r"\bdomestic\b", near, re.I):
                return "domestic"
            return None
        return "domestic"
    if key == "credit_cost" and re.search(
        r"\bnet\s+credit\s+cost\b|"
        r"net\s+of\s+recover|"
        r"exclud(?:e|ing)\s+recover|"
        r"ex[-\s]?recover",
        haystack,
        re.I,
    ):
        return "net_of_recoveries"
    return None


def _prefix_before_value(value: float, text: str) -> str:
    blob = (text or "").replace(",", "")
    match = _value_token_re(value).search(blob)
    if not match:
        return blob
    return blob[max(0, match.start() - 48) : match.start()]


def _suffix_after_value(value: float, text: str) -> str:
    blob = (text or "").replace(",", "")
    match = _value_token_re(value).search(blob)
    if not match:
        return ""
    return blob[match.end() : match.end() + 32]


def _period_eligible(period: str | None, target_period: str | None) -> bool:
    if not target_period:
        return True
    return period is None or period == target_period


def _candidate_score(fact: RawFact, key: str, target_period: str | None) -> int:
    score = 0
    if target_period and fact.period == target_period:
        score += 20
    elif fact.period is None:
        score += 5
    else:
        score -= 15
    if key in _GROWTH_KEYS:
        if fact.comparison == COMPARISON_YOY:
            score += 15
        elif fact.comparison == COMPARISON_QOQ:
            score += 5
    else:
        if fact.comparison in {COMPARISON_YOY, COMPARISON_QOQ}:
            score -= 15
        else:
            score += 10
    return score
