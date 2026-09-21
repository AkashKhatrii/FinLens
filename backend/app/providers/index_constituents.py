"""Index constituent universes (Nifty 50, Nifty 100, Nifty 500).

The index source defines membership. This module does not rank by market cap
and does not score stocks. Adding another NSE index is another INDEX_SOURCES entry.
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
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


# Official NSE index constituent CSVs.
INDEX_SOURCES: dict[str, dict[str, object]] = {
    "NIFTY50": {
        "name": "Nifty 50",
        "urls": _nse_index_urls("ind_nifty50list.csv"),
    },
    "NIFTY100": {
        "name": "Nifty 100",
        "urls": _nse_index_urls("ind_nifty100list.csv"),
    },
    "NIFTY500": {
        "name": "Nifty 500",
        "urls": _nse_index_urls("ind_nifty500list.csv"),
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
    constituents: list[Constituent]
    source_url: str | None = None
    as_of: str | None = None

    def to_dict(self) -> dict:
        return {
            "index": self.index_id,
            "name": self.name,
            "count": len(self.constituents),
            "as_of": self.as_of,
            "source_url": self.source_url,
            "constituents": [
                {"symbol": c.symbol, "name": c.name} for c in self.constituents
            ],
        }


def get_index_constituents(index_id: str) -> IndexUniverse:
    """Return the current constituents for a known index id, e.g. NIFTY50, NIFTY100, NIFTY500."""
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


def parse_index_csv(text: str) -> list[Constituent]:
    """Parse an NSE index constituent CSV. Duplicates keep the first symbol."""
    blob = (text or "").lstrip("\ufeff")
    rows = list(csv.DictReader(io.StringIO(blob)))
    seen: set[str] = set()
    out: list[Constituent] = []
    for row in rows:
        mapped = { _norm_header(k): (v or "").strip() for k, v in row.items() }
        symbol = (mapped.get("symbol") or mapped.get("ticker") or "").upper()
        name = mapped.get("company name") or mapped.get("company") or mapped.get("name") or ""
        series = (mapped.get("series") or "EQ").upper()
        if series and series not in {"EQ", "BE", ""}:
            continue
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
    last_error: Exception | None = None
    for url in urls:
        try:
            resp = requests.get(str(url), timeout=20, headers={"User-Agent": UA})
            resp.raise_for_status()
            constituents = parse_index_csv(resp.text)
            if not constituents:
                log.warning("Index CSV at %s parsed to zero constituents.", url)
                continue
            return IndexUniverse(
                index_id=index_id,
                name=str(spec["name"]),
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
