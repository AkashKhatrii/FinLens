"""Sector scoring profiles.

Today there are two: `default` (industrial / everything else) and `bank`.
Unknown industries stay on `default`. Classification is conservative so an
NBFC is never treated as a deposit-taking bank.
"""
from __future__ import annotations

from .common import Pillar

PROFILE_BANK = "bank"
PROFILE_DEFAULT = "default"

BANK_SUPPRESS = frozenset({
    "op_margin",
    "net_margin",
    "margin_trend",
    "roce",
    "debt_equity",
    "interest_cover",
    "current_ratio",
    "net_debt_ebitda",
    "ev_ebitda",
    "ocf_to_pat",
    "fcf_margin",
    "dcf_upside",
    "promoter_holding",
})

_BANK_NOTE = (
    "Not scored for banks — this industrial ratio is not meaningful "
    "for a deposit-taking lender."
)


def classify(sector: str | None = "", industry: str | None = "") -> str:
    """Map Yahoo sector/industry to a scoring profile.

    Only industries whose leading token is `bank` or `banks` qualify
    (`Banks - Regional`, `Banks - Diversified`). `Credit Services`,
    `Investment Banking & Brokerage`, blank, and anything unrecognised
    stay on `default`.
    """
    head = (industry or "").strip().lower().split("-", 1)[0].strip()
    if head in {"bank", "banks"}:
        return PROFILE_BANK
    return PROFILE_DEFAULT


def apply_profile(pillar: Pillar, profile: str) -> None:
    """Null scores on inapplicable metrics. Raw values stay for display."""
    if profile != PROFILE_BANK:
        return
    for m in pillar.metrics:
        if m.key not in BANK_SUPPRESS:
            continue
        m.score = None
        m.weight = 0.0
        if m.key == "promoter_holding" and m.note:
            if _BANK_NOTE not in m.note:
                m.note = m.note.rstrip(".") + ". " + _BANK_NOTE
        else:
            m.note = _BANK_NOTE
