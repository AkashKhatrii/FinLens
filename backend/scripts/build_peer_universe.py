"""Build the peer-universe map used for peer selection.

Fetches industry/sector/marketCap for every S&P 500 and Nifty 500 constituent
via yfinance and writes backend/app/data/peer_universe.json.

This is a build-time data artifact, NOT per-request work: analysing a stock
then selects peers with a pure dict lookup. Re-run monthly (or when the map
goes stale) to refresh industries and market caps.

Usage:
    python backend/scripts/build_peer_universe.py [--workers 12]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yfinance as yf  # noqa: E402

from app.providers.index_constituents import get_index_constituents  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "peer_universe.json"

SOURCES = (
    ("SP500", "US", lambda s: s),            # already Yahoo-ready
    ("NIFTY500", "IN", lambda s: s + ".NS"),  # NSE bare symbols -> Yahoo
)


def _fetch_one(symbol: str, name: str) -> dict | None:
    try:
        info = yf.Ticker(symbol).info or {}
    except Exception:
        return None
    industry = (info.get("industry") or "").strip()
    sector = (info.get("sector") or "").strip()
    mcap = info.get("marketCap")
    if not industry and not sector:
        return None
    return {
        "symbol": symbol,
        "name": name,
        "industry": industry,
        "sector": sector,
        "market_cap": int(mcap) if mcap else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    result: dict[str, object] = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "sources": {},
        "US": [],
        "IN": [],
    }
    for index_id, market, to_yahoo in SOURCES:
        universe = get_index_constituents(index_id)
        result["sources"][index_id] = {
            "name": universe.name,
            "count": len(universe.constituents),
        }
        jobs = [(to_yahoo(c.symbol), c.name) for c in universe.constituents]
        rows: list[dict] = []
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(_fetch_one, sym, name): sym for sym, name in jobs}
            for i, fut in enumerate(as_completed(futs), 1):
                row = fut.result()
                if row:
                    rows.append(row)
                if i % 100 == 0:
                    print(f"  {index_id}: {i}/{len(jobs)} ...", flush=True)
        result[market] = sorted(rows, key=lambda r: r["symbol"])
        print(f"{index_id}: {len(rows)}/{len(jobs)} with industry data "
              f"({time.time() - t0:.0f}s)", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
