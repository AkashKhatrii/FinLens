"""Forward-return report for timestamped AI stances.

Reads the stance log (one row per AI horizon call, written every time a
thesis is generated; lives at $FINLENS_DATA_DIR/ai_stance_log.jsonl,
default backend/.data/) and joins each stance against later prices to
answer: did AI Buy/Hold/Reduce/Avoid stances actually predict returns?

Usage:
    cd backend && ../.venv/bin/python scripts_ai_stance_report.py [--log PATH]

Needs network (yfinance). Rows whose forward window has not elapsed yet are
skipped. Returns are price returns; excess is vs the market price index
(^NSEI for IN, ^GSPC for US) — not total return, so long-horizon excess is
an upper bound where dividends matter.
"""
from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import yfinance as yf
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.ai import stance_log  # noqa: E402

OFFSETS = {"6M": 126, "1Y": 252, "2Y": 504}  # trading days
BENCH = {"IN": "^NSEI", "US": "^GSPC"}


def yahoo_symbol(ticker: str, market: str) -> str:
    t = (ticker or "").strip().upper()
    if (market or "IN").upper() == "IN" and not t.endswith(".NS") and not t.endswith(".BO"):
        return f"{t}.NS"
    return t


def closes(ysym: str, start: date) -> list[tuple[date, float]]:
    df = yf.download(
        ysym,
        start=start.isoformat(),
        end=(date.today() + timedelta(days=1)).isoformat(),
        auto_adjust=True,
        progress=False,
    )
    if df is None or df.empty:
        return []
    if isinstance(df.columns, pd.MultiIndex):
        # newer yfinance nests as ("Close", <ticker>)
        try:
            series = df[("Close", ysym)]
        except KeyError:
            close_cols = [c for c in df.columns if c[0] == "Close"]
            if not close_cols:
                return []
            series = df[close_cols[0]]
    else:
        if "Close" not in df.columns:
            return []
        series = df["Close"]
    out = []
    for ts, px in series.items():
        try:
            out.append((ts.date(), float(px)))
        except (TypeError, ValueError):
            continue
    return sorted(out, key=lambda x: x[0])


def fwd_returns(series: list[tuple[date, float]], start: date) -> dict[str, float]:
    """Trading-day-offset forward returns from the first bar on/after start."""
    dates = [d for d, _ in series]
    idx = next((i for i, d in enumerate(dates) if d >= start), None)
    if idx is None:
        return {}
    base = series[idx][1]
    if not base:
        return {}
    out = {}
    for label, n in OFFSETS.items():
        j = idx + n
        if j < len(series) and series[j][1]:
            out[label] = series[j][1] / base - 1
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=None, help="Path to ai_stance_log.jsonl")
    args = ap.parse_args()

    rows = stance_log.read_all(args.log)
    print(f"stance rows: {len(rows)}")
    if not rows:
        return

    # One download per unique symbol + benchmarks.
    symbols = {(r["ticker"], r["market"]) for r in rows if r.get("ticker")}
    min_date = min(date.fromisoformat(r["date"]) for r in rows if r.get("date"))
    px: dict[str, list] = {}
    for ticker, market in sorted(symbols):
        ysym = yahoo_symbol(ticker, market)
        try:
            px[ysym] = closes(ysym, min_date)
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not kill the report
            print(f"  !! download failed for {ysym}: {exc}")
            px[ysym] = []
    bench_px: dict[str, list] = {}
    for m, b in BENCH.items():
        try:
            bench_px[m] = closes(b, min_date)
        except Exception as exc:  # noqa: BLE001
            print(f"  !! download failed for {b}: {exc}")
            bench_px[m] = []

    # (horizon, group_kind, group_label, offset) -> lists of raw/excess returns
    raw: dict[tuple, list[float]] = defaultdict(list)
    exc: dict[tuple, list[float]] = defaultdict(list)
    skipped = 0
    for r in rows:
        try:
            sdate = date.fromisoformat(r["date"])
        except (TypeError, ValueError):
            skipped += 1
            continue
        ysym = yahoo_symbol(r["ticker"], r["market"])
        s = fwd_returns(px.get(ysym, []), sdate)
        b = fwd_returns(bench_px.get(r["market"], []), sdate)
        hz = r.get("horizon") or "?"
        for label in OFFSETS:
            if label not in s:
                continue
            er = s[label] - b.get(label, 0.0) if label in b else None
            for kind, gval in (("ai_stance", r.get("ai_stance")), ("quant_verdict", r.get("quant_verdict"))):
                key = (hz, kind, gval or "None", label)
                raw[key].append(s[label])
                if er is not None:
                    exc[key].append(er)
        if not s:
            skipped += 1

    print(f"rows with no usable forward window yet: {skipped}\n")
    for kind in ("ai_stance", "quant_verdict"):
        for hz in ("long", "swing"):
            print(f"=== {hz.upper()} by {kind} ===")
            print(f"{'group':<12} {'win':<4} {'n':>4}  {'raw_med':>8} {'raw_mean':>8}  {'exc_med':>8} {'exc_mean':>8}  {'hit%':>5}")
            groups = sorted({k[2] for k in raw if k[0] == hz and k[1] == kind})
            for g in groups:
                for label in OFFSETS:
                    key = (hz, kind, g, label)
                    rs = raw.get(key, [])
                    es = exc.get(key, [])
                    if not rs:
                        continue
                    hit = sum(1 for x in es if x > 0) / len(es) * 100 if es else float("nan")
                    print(
                        f"{str(g):<12} {label:<4} {len(rs):>4}  "
                        f"{statistics.median(rs) * 100:>7.1f}% {statistics.fmean(rs) * 100:>7.1f}%  "
                        f"{(statistics.median(es) * 100 if es else float('nan')):>7.1f}% "
                        f"{(statistics.fmean(es) * 100 if es else float('nan')):>7.1f}%  "
                        f"{hit:>4.0f}%"
                    )
            print()


if __name__ == "__main__":
    main()
