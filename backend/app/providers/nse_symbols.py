"""NSE symbol master, used for resolution, validation and typo recovery.

Backed by NSE's own published equity list (~2,570 live symbols), which is the
authoritative answer to "does this ticker exist". Resolving against it first
means:

  * typos get a "did you mean" instead of a dead 404 - Yahoo's search does no
    fuzzy matching at all and returns nothing for `RELAINCE`;
  * delisted/renamed tickers fail honestly. `TATAMOTORS` stopped existing when
    the company demerged into TMCV and TMPV in Nov 2025, and a hardcoded alias
    map would have gone on pointing at a dead symbol;
  * we stop probing Yahoo just to find out whether a symbol is real.

Falls back to Yahoo search if the list can't be fetched, so a network failure
degrades rather than breaks.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher, get_close_matches

import requests

from .. import cache

log = logging.getLogger(__name__)

NSE_EQUITY_LIST = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
LIST_TTL = 7 * 24 * 3600  # the constituent list changes slowly
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Words that carry no distinguishing signal when matching company names.
NOISE = {"limited", "ltd", "the", "and", "co", "company", "corporation", "corp",
         "india", "indian", "industries", "enterprises", "holdings", "group"}


@dataclass(frozen=True)
class Listing:
    symbol: str
    name: str

    @property
    def name_key(self) -> str:
        return _norm(self.name)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _words(s: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", (s or "").lower()) if w and w not in NOISE]


def _download() -> list[dict[str, str]]:
    try:
        resp = requests.get(NSE_EQUITY_LIST, timeout=20, headers={"User-Agent": UA})
        resp.raise_for_status()
        rows = list(csv.DictReader(io.StringIO(resp.text)))
        out = []
        for r in rows:
            sym = (r.get("SYMBOL") or "").strip()
            name = (r.get("NAME OF COMPANY") or "").strip()
            series = (r.get(" SERIES") or r.get("SERIES") or "").strip()
            # EQ and BE are the tradable equity series; the rest are debt etc.
            if sym and name and series in ("EQ", "BE", ""):
                out.append({"symbol": sym, "name": name})
        return out
    except Exception as exc:
        log.warning("Could not fetch the NSE equity list: %s", exc)
        return []


def listings() -> list[Listing]:
    rows = cache.memoize("nselist", "equity_l", LIST_TTL, _download) or []
    return [Listing(r["symbol"], r["name"]) for r in rows]


def available() -> bool:
    return bool(listings())


def find(query: str, limit: int = 5) -> tuple[Listing | None, list[Listing]]:
    """Resolve a query to a listing, plus near-miss suggestions.

    Returns `(exact_or_confident_match, suggestions)`. A confident match still
    returns suggestions so the UI can offer alternatives for ambiguous names
    like "tata motors", which is now two separate listed companies.
    """
    items = listings()
    if not items:
        return None, []

    raw = (query or "").strip()
    if not raw:
        return None, []

    q_norm = _norm(raw)
    q_words = _words(raw)

    by_symbol = {l.symbol.upper(): l for l in items}

    # 1. Exact ticker.
    if raw.upper() in by_symbol:
        return by_symbol[raw.upper()], []

    # 2. Exact company name.
    for l in items:
        if l.name_key == q_norm:
            return l, []

    # 3. Scored fuzzy pass over both symbol and name.
    #
    # Word *recall* (how much of the query the name accounts for) is not enough
    # on its own: "sun pharma" fully matches both SUNPHARMA and SPARC
    # ("Sun Pharma Advanced Research"). Weighting it against *precision* (how
    # much of the name the query accounts for) breaks that tie correctly -
    # SUNPHARMA scores 1.0, SPARC 0.78.
    scored: list[tuple[float, Listing]] = []
    for l in items:
        sym_l = l.symbol.lower()
        name_words = _words(l.name)
        name_key = l.name_key

        score = 0.0
        if q_words and name_words:
            matched_q = sum(1 for qw in q_words if any(nw.startswith(qw) for nw in name_words))
            matched_n = sum(1 for nw in name_words if any(nw.startswith(qw) for qw in q_words))
            recall = matched_q / len(q_words)
            precision = matched_n / len(name_words)
            if recall == 1.0:
                score = max(score, 0.55 * recall + 0.45 * precision)
            elif recall > 0:
                score = max(score, 0.55 * recall * 0.8 + 0.45 * precision * 0.5)

        if name_key.startswith(q_norm) or q_norm.startswith(name_key):
            score = max(score, 0.90)
        if q_norm and q_norm in name_key:
            score = max(score, 0.78)
        # Typo distance against the ticker and against the full name.
        score = max(score, SequenceMatcher(None, q_norm, sym_l).ratio() * 0.97)
        score = max(score, SequenceMatcher(None, q_norm, name_key).ratio() * 0.88)
        if score >= 0.55:
            scored.append((score, l))

    scored.sort(key=lambda t: (-t[0], len(t[1].name)))
    # Weak matches are worse than no matches: offering "ZOTA" for "XYZNOTREAL"
    # just makes the app look broken.
    ranked = [l for s, l in scored[:limit] if s >= 0.66]

    if not scored:
        # Last resort: difflib against the bare ticker list.
        close = get_close_matches(raw.upper(), list(by_symbol), n=limit, cutoff=0.6)
        return None, [by_symbol[c] for c in close]

    top_score, top = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0

    # Auto-accept only a near-perfect, unambiguous match. A misspelling scores
    # in the 0.80s and deliberately falls through to "did you mean" - silently
    # analysing a *different* company than the one asked for is the worst
    # failure this function can have.
    confident = top_score >= 0.95 and (top_score - runner_up) >= 0.03
    return (top if confident else None), ranked


def search(query: str, limit: int = 8) -> list[Listing]:
    """Prefix-first typeahead over the NSE list. Weaker than `find()` on
    purpose: a dropdown should show TATASTEEL when the user has only typed
    TATA, even though that is not yet a confident resolve.
    """
    items = listings()
    raw = (query or "").strip()
    if not items or not raw or limit <= 0:
        return []

    q_up = raw.upper()
    q_norm = _norm(raw)
    q_words = _words(raw)
    scored: dict[str, tuple[float, Listing]] = {}

    def keep(listing: Listing, score: float) -> None:
        if score <= 0:
            return
        prev = scored.get(listing.symbol)
        if prev is None or score > prev[0]:
            scored[listing.symbol] = (score, listing)

    # Colloquial names (ril, zomato) live on the yfinance provider. Import
    # lazily so this module can load first.
    try:
        from .yf_provider import ALIASES
    except Exception:
        ALIASES = {}
    alias = ALIASES.get(raw.lower())
    if alias:
        by_symbol = {l.symbol.upper(): l for l in items}
        hit = by_symbol.get(alias.upper())
        if hit:
            keep(hit, 99.0)

    for l in items:
        score = 0.0
        if l.symbol == q_up:
            score = 100.0
        elif l.symbol.startswith(q_up):
            # Shorter remainder ranks higher: TCS beats TCSANEN before it exists.
            extra = len(l.symbol) - len(q_up)
            score = max(score, 92.0 - min(extra, 30) * 0.4)

        if q_norm and len(q_norm) >= 2:
            if l.name_key.startswith(q_norm):
                score = max(score, 88.0)
            elif q_norm in l.name_key:
                score = max(score, 76.0)

        if q_words and len(raw) >= 2:
            name_words = _words(l.name)
            if name_words:
                matched_q = sum(1 for qw in q_words if any(nw.startswith(qw) for nw in name_words))
                if matched_q == len(q_words):
                    precision = sum(1 for nw in name_words if any(nw.startswith(qw) for qw in q_words)) / len(name_words)
                    score = max(score, 70.0 + 20.0 * precision)

        if len(q_norm) >= 4:
            sym_ratio = SequenceMatcher(None, q_norm, l.symbol.lower()).ratio()
            name_ratio = SequenceMatcher(None, q_norm, l.name_key).ratio()
            if sym_ratio >= 0.82:
                score = max(score, sym_ratio * 85)
            if name_ratio >= 0.78:
                score = max(score, name_ratio * 75)

        keep(l, score)

    ranked = sorted(scored.values(), key=lambda t: (-t[0], len(t[1].symbol), t[1].symbol))
    floor = 50.0 if len(raw) >= 2 else 80.0
    return [listing for s, listing in ranked if s >= floor][:limit]
