"""Investor-facing explanation hygiene.

Metric notes must be generated from structured values, not raw extraction
snippets. Malformed table fragments are omitted rather than shown.
"""
from __future__ import annotations

import re

from .common import Metric

_REPEATED_PERCENTS = re.compile(r"(?:\d+(?:\.\d+)?%\s+){2,}\d+(?:\.\d+)?%")
_DUPLICATED_VALUE = re.compile(r"(\d+(?:\.\d+)?)%\s+\1%")
_ELLIPSIS = re.compile(r"\.{3}|…")
_COLUMN_HEADER = re.compile(
    r"\bparticulars\b|"
    r"\b(?:jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)['’.]?\s*\d{2}\b|"
    r"\bnnpa\s*%\s*pcr\b|"
    r"\bpcr\s*\(\s*inc|"
    r"\bslippage\s+ratio\b",
    re.I,
)
_CONCAT_METRICS = re.compile(
    r"\b(?:gnpa|nnpa|pcr|nim|roa|roe|casa|car|cet1|nii|sma)\b"
    r"(?:\s*%?\s+\b(?:gnpa|nnpa|pcr|nim|roa|roe|casa|car|cet1|nii|sma|slippage)\b){1,}",
    re.I,
)
_SOURCE_ARTIFACT = re.compile(
    r"\bsource\s*:|\btable\s+\d+|\bpcr%\s*-|\(excl\s+two\)|\(inc\.?\s*two\)",
    re.I,
)
_MALFORMED_UNIT = re.compile(r"%-\s*\(")
_VAGUE = re.compile(
    r"^(?:growth is cheap|strong momentum|healthy fundamentals|"
    r"good execution|strong franchise)\.?$",
    re.I,
)


def is_clean_investor_text(text: str | None) -> bool:
    """True when `text` is safe to show as an investor-facing explanation."""
    blob = (text or "").strip()
    if not blob:
        return False
    if _ELLIPSIS.search(blob):
        return False
    if _REPEATED_PERCENTS.search(blob):
        return False
    if _DUPLICATED_VALUE.search(blob):
        return False
    if _COLUMN_HEADER.search(blob):
        return False
    if _CONCAT_METRICS.search(blob):
        return False
    if _SOURCE_ARTIFACT.search(blob):
        return False
    if _MALFORMED_UNIT.search(blob):
        return False
    percents = re.findall(r"\d+(?:\.\d+)?%", blob)
    if len(percents) >= 3:
        return False
    return True


def investor_facing_bullet(metric: Metric) -> str | None:
    """One public What's working / What's not line, or None to omit."""
    note = (metric.note or "").strip()
    if note and is_clean_investor_text(note) and not _VAGUE.match(note):
        return note
    if metric.value is None or not metric.display or metric.display == "—":
        return None
    if metric.score is None:
        return None
    if metric.score >= 70 or metric.score <= 40:
        return f"{metric.label} is {metric.display}."
    return None
