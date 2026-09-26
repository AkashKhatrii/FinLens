"""Index constituent universes (Nifty 50/100/500, S&P 500).

The index source defines membership. This module does not rank by market cap
and does not score stocks. Adding another index is another INDEX_SOURCES entry.

US universe — S&P 500: inclusion/exclusion criteria
---------------------------------------------------
Inclusion is enforced by the S&P Dow Jones Indices committee itself; FinLens
adds no further filter, so every current constituent is screenable:

  INCLUDED (committee rules, all must hold)
  - US-domiciled operating company listed on NYSE, Nasdaq, or Cboe
  - Market capitalisation above the published large-cap threshold
    (raised periodically; $18B+ in the 2024 methodology round)
  - Public float of at least 10% of shares outstanding
  - Positive GAAP earnings in the most recent quarter AND over the trailing
    four quarters combined (the profitability screen)
  - Adequate liquidity: median daily value traded over the prior six months

  EXCLUDED (by the index, so never in the universe)
  - ADRs and other foreign listings — every constituent reports in USD,
    which is what keeps FinLens' cross-currency guards quiet
  - Preferred stock, warrants, rights, OTC listings
  - Business development companies and closed-end structures

Why not the Nasdaq-100 as the second US universe: it admits ADRs (ASML is a
member), whose trading currency differs from their reporting currency, and
FinLens' multiples silently distort on those. The S&P 500's US-only rule
sidesteps the whole class of problem, so it is the right first US universe.
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

from .. import cache

log = logging.getLogger(__name__)

LIST_TTL = 24 * 3600
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def _nse_index_urls(filename: str) -> tuple[str, ...]:
    return (
        f"https://archives.nseindia.com/content/indices/{filename}",
        f"https://nsearchives.nseindia.com/content/indices/{filename}",
    )


# Official index constituent sources. "format" selects the CSV dialect:
# "nse" for NSE's Company Name/Symbol/Series files, "generic" for
# Symbol/Name (or Symbol/Security) files such as the S&P 500 dataset.
INDEX_SOURCES: dict[str, dict[str, object]] = {
    "NIFTY50": {
        "name": "Nifty 50",
        "market": "IN",
        "format": "nse",
        "urls": _nse_index_urls("ind_nifty50list.csv"),
    },
    "NIFTY100": {
        "name": "Nifty 100",
        "market": "IN",
        "format": "nse",
        "urls": _nse_index_urls("ind_nifty100list.csv"),
    },
    "NIFTY500": {
        "name": "Nifty 500",
        "market": "IN",
        "format": "nse",
        "urls": _nse_index_urls("ind_nifty500list.csv"),
    },
    "SP500": {
        "name": "S&P 500",
        "market": "US",
        "format": "generic",
        # S&P 500 constituent list (Symbol, Security, Sector) from the
        # datasets GitHub mirror, with the jsDelivr CDN as fallback host.
        "urls": (
            "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
            "https://cdn.jsdelivr.net/gh/datasets/s-and-p-500-companies@main/data/constituents.csv",
        ),
    },
}


@dataclass(frozen=True)
class Constituent:
    symbol: str
    name: str


@dataclass
class IndexUniverse:
    index_id: str
    name: str
    market: str = "IN"
    constituents: list[Constituent] = field(default_factory=list)
    source_url: str | None = None
    as_of: str | None = None

    def to_dict(self) -> dict:
        return {
            "index": self.index_id,
            "name": self.name,
            "market": self.market,
            "count": len(self.constituents),
            "as_of": self.as_of,
            "source_url": self.source_url,
            "constituents": [
                {"symbol": c.symbol, "name": c.name} for c in self.constituents
            ],
        }


def get_index_constituents(index_id: str) -> IndexUniverse:
    """Return the current constituents for a known index id,
    e.g. NIFTY50, NIFTY100, NIFTY500, SP500."""
    key = (index_id or "").strip().upper()
    spec = INDEX_SOURCES.get(key)
    if spec is None:
        known = ", ".join(sorted(INDEX_SOURCES))
        raise KeyError(f"Unknown index {index_id!r}. Known: {known}.")
    cached = cache.memoize(
        "index_constituents",
        key,
        LIST_TTL,
        lambda: _download(key, spec),
    )
    if cached is None:
        raise RuntimeError(f"Could not load constituents for {key}.")
    return cached


def parse_index_csv(text: str, format: str = "nse") -> list[Constituent]:
    """Parse an index constituent CSV. Duplicates keep the first symbol.

    format="nse": NSE's Company Name/Symbol/Series dialect (default, and what
    the existing tests exercise). format="generic": Symbol/Name files such as
    the S&P 500 dataset.
    """
    blob = (text or "").lstrip("\ufeff")
    rows = list(csv.DictReader(io.StringIO(blob)))
    seen: set[str] = set()
    out: list[Constituent] = []
    for row in rows:
        mapped = {_norm_header(k): (v or "").strip() for k, v in row.items()}
        symbol = (mapped.get("symbol") or mapped.get("ticker") or "").upper()
        name = (mapped.get("company name") or mapped.get("company")
                or mapped.get("name") or mapped.get("security") or "")
        if format == "nse":
            series = (mapped.get("series") or "EQ").upper()
            if series and series not in {"EQ", "BE", ""}:
                continue
        else:
            # S&P-style dotted share classes (BRK.B) become Yahoo's hyphen
            # form (BRK-B) so the screener resolves them directly.
            symbol = symbol.replace(".", "-")
        if not symbol or not name:
            continue
        if symbol in seen:
            continue
        seen.add(symbol)
        out.append(Constituent(symbol=symbol, name=name))
    return out


def _norm_header(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _download(index_id: str, spec: dict[str, object]) -> IndexUniverse | None:
    urls = spec["urls"]
    fmt = str(spec.get("format") or "nse")
    market = str(spec.get("market") or "IN")
    last_error: Exception | None = None
    for url in urls:
        try:
            resp = requests.get(str(url), timeout=20, headers={"User-Agent": UA})
            resp.raise_for_status()
            constituents = parse_index_csv(resp.text, format=fmt)
            if not constituents:
                log.warning("Index CSV at %s parsed to zero constituents.", url)
                continue
            return IndexUniverse(
                index_id=index_id,
                name=str(spec["name"]),
                market=market,
                constituents=constituents,
                source_url=str(url),
                as_of=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            last_error = exc
            log.warning("Could not fetch index constituents from %s: %s", url, exc)
    if last_error:
        log.warning("All constituent sources failed for %s: %s", index_id, last_error)
    return None
