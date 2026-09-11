"""Rebuild the score-distribution snapshot used for percentile ranking.

Run occasionally:  .venv/bin/python scripts_build_benchmark.py
"""
import json, logging, warnings
from datetime import date
from pathlib import Path

warnings.filterwarnings("ignore"); logging.basicConfig(level=logging.CRITICAL)
from app.analysis import analyse  # noqa: E402

UNIVERSE = ["RELIANCE","TCS","INFY","HDFCBANK","ICICIBANK","SBIN","BHARTIARTL","ITC","LT","MARUTI",
            "HINDUNILVR","ASIANPAINT","TITAN","SUNPHARMA","NESTLEIND","BAJFINANCE","KOTAKBANK",
            "AXISBANK","ULTRACEMCO","HCLTECH","WIPRO","DMART","TATASTEEL","JSWSTEEL","ONGC","NTPC",
            "COALINDIA","PIDILITIND","BRITANNIA","CIPLA","DRREDDY","EICHERMOT","HEROMOTOCO","TRENT",
            "BEL","POLYCAB","APOLLOHOSP","TVSMOTOR","VBL","CGPOWER"]

out = {"generated": date.today().isoformat(), "universe_size": 0,
       "overall": [], "short": [], "swing": [], "long": []}
for sym in UNIVERSE:
    try:
        r = analyse(sym, use_ai=False)
        if r["overall"]["score"] is None:
            continue
        out["overall"].append(round(r["overall"]["score"], 2))
        for k in ("short", "swing", "long"):
            s = r["horizons"][k]["score"]
            if s is not None:
                out[k].append(round(s, 2))
        print(f"  {sym:12s} {r['overall']['score']:.1f}")
    except Exception as exc:
        print(f"  skip {sym}: {type(exc).__name__}")

for k in ("overall", "short", "swing", "long"):
    out[k].sort()
out["universe_size"] = len(out["overall"])
Path("app/benchmark.json").write_text(json.dumps(out, indent=1))
print(f"\nwrote app/benchmark.json ({out['universe_size']} names)")
