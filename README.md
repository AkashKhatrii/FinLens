# FinLens

AI-assisted equity research for Indian listed companies (NSE/BSE). Type a ticker,
get a full analyst-style workup: fundamentals from the filings, valuation with a
DCF, technicals, risk, and separate buy/hold/avoid verdicts for **short-term,
swing and long-term** horizons — plus a written thesis from Claude.

```bash
./run.sh          # http://127.0.0.1:8000
```

---

## What it actually does

The design principle is that **the same evidence should be weighted differently
depending on how long you intend to hold.** A great business can be a bad trade,
and a mediocre business can be a good one. Collapsing that into a single
"score out of 10" is the thing most stock apps get wrong.

So the engine computes nine independent pillars, then scores them three times
under three different weightings.

| Pillar | What goes into it |
|---|---|
| Growth | Revenue/PAT YoY and multi-year CAGR, latest-quarter YoY |
| Profitability & Returns | Operating and net margin, margin trend, **ROE, ROCE** |
| Balance Sheet & Cash | D/E, net debt/EBITDA, interest cover, current ratio, **OCF/PAT**, FCF margin |
| Valuation | P/E vs **its own 5-year median**, P/B, EV/EBITDA, PEG, earnings yield vs 10Y G-Sec, DCF |
| Short-Term Setup | RSI, Bollinger %B, price vs 20-DMA, 1-week return, volume trend |
| Trend & Relative Strength | Price vs 50/200-DMA, ADX, 3M and 1Y relative strength vs NIFTY, 52W position |
| Earnings Momentum | Beat/miss rate and average surprise over the last four quarters |
| Sentiment & Ownership | Street rating and target, promoter holding, institutional holding |
| Risk | Beta, annualised volatility, max drawdown, daily turnover, red flags |

### Horizon weights

| Pillar | Short (days–3wk) | Swing (1–3mo) | Long (1–3yr+) |
|---|---|---|---|
| Short-term setup | 40% | 16% | 0% |
| Trend & RS | 20% | 26% | 5% |
| Earnings | 10% | 16% | 6% |
| Valuation | 4% | 12% | 20% |
| Growth | 2% | 10% | 20% |
| Profitability | 1% | 3% | 22% |
| Balance sheet | 1% | 1% | 16% |
| Sentiment | 10% | 8% | 2% |
| Risk | 12% | 8% | 9% |

Weights live in one declarative dict in `app/engine/scoring.py` — tune them there.
The headline **Overall** score is a 20/30/50 blend of the three.

---

## Design decisions worth knowing

**Ratios are computed from raw statements, never read off summary fields.**
yfinance returns `returnOnEquity: None` and a beta of `0.15` for Reliance. Every
number that drives a score is derived from the income statement, balance sheet
and cash flow directly, with `.info` used only as a last-resort fallback.

**Missing data lowers confidence, not the score.** A metric with no inputs scores
`None` and is skipped in the weighted average rather than counted as zero. Each
verdict carries a separate confidence figure built from data coverage and how
much the pillars agree with each other.

**Quarterly comparisons match by date, not position.** yfinance quarterly columns
have gaps — Reliance is missing Sep-2025 — so `columns[4]` is regularly not "four
quarters ago". The engine looks for a column within ~6 weeks of the year-ago date
and reports nothing if it can't find one.

**The DCF refuses to run on negative FCF.** A DCF on a cash-burning company
produces a confident-looking number containing no information. All assumptions
(base FCF, fade, discount rate, beta) are shown in the UI.

**News is filtered for relevance.** Yahoo's feed for NSE tickers is largely
untargeted global wire copy; unfiltered it would pollute both the UI and the
model's fact pack.

**Symbols resolve against NSE's own equity master**, not a hardcoded alias list.
Roughly 2,540 live symbols, refreshed weekly. This gives typo recovery
(`RELAINCE` → "Did you mean RELIANCE?") and, more importantly, makes delisted
and renamed tickers fail honestly: `TATAMOTORS` stopped existing when the
company demerged into **TMCV** and **TMPV** in Nov 2025, and Zomato is now
listed as **ETERNAL**. A misspelling deliberately returns suggestions rather
than auto-correcting — silently analysing a *different* company than the one
asked for is the worst failure this path can have.

**Nothing is hidden.** Every pillar expands into its individual metrics with the
raw value, the 0–100 score, and a one-line reading.

---

## The AI layer

DeepSeek (`deepseek-v4-flash`) receives a compact JSON fact pack — all computed
metrics, scores, and notes — and returns a **schema-validated** thesis:
headline, business summary, quality and valuation verdicts, bull/bear cases,
key risks, what to watch, a per-horizon call with *"what would change my mind"*,
and a `contrarian_note` arguing where the quantitative score is likely wrong
about this specific company.

Thinking mode is disabled (same as jobscan): on v4-flash it is on by default and
would eat the token budget, returning empty content. Claude remains available
with `FINLENS_PROVIDER=claude` so a leftover Anthropic key is not billed by
accident.

**It degrades cleanly.** With no API key the app still returns the complete
quantitative analysis and the UI explains what's missing. Set the key in
`backend/.env`:

```bash
cp backend/.env.example backend/.env   # then add DEEPSEEK_API_KEY
```

---

## Layout

```
backend/app/
  main.py              FastAPI routes + NaN/numpy-safe JSON encoding
  analysis.py          orchestrator; builds the AI fact pack
  config.py            markets, cache TTLs, risk-free rate, model
  cache.py             TTL disk cache (the data source is slow and rate-limited)
  providers/
    base.py            StockBundle contract + tolerant statement-row lookup
    nse_symbols.py     NSE equity master; fuzzy resolution + "did you mean"
    yf_provider.py     yfinance adapter, symbol resolution, news filtering
  engine/
    common.py          Metric/Pillar, piecewise-linear band scoring
    fundamentals.py    growth, profitability, balance sheet
    valuation.py       multiples, own-history P/E band, two-stage DCF
    technicals.py      RSI/MACD/ADX/ATR/Bollinger, relative strength
    qualitative.py     risk + beta, earnings surprises, sentiment
    scoring.py         horizon weights, verdicts, confidence, pros/cons
  ai/
    schemas.py         Pydantic thesis schema
    prompts.py         frozen (cacheable) analyst system prompt
    analyst.py         the Claude call
  static/index.html    the whole UI
```

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/analyse?q=TCS&ai=true` | Full analysis |
| `GET /api/resolve?q=tata%20motors` | Name → ticker |
| `GET /api/health` | Status + whether AI credentials resolved |
| `POST /api/cache/clear` | Drop cached market data |

---

## Deploy (GitHub + Railway)

Local `./run.sh` is unchanged. Hosted FinLens is the same FastAPI app behind HTTPS.

This project deploys on **Railway** (persistent volume + env vars). A Render blueprint remains in [`render.yaml`](render.yaml) if you ever want that host instead.

**What you need**

- A Railway service with a volume mounted at `/var/data`. Without a volume, Tradebook files vanish on restart.
- Secrets on Railway, never in git: `DEEPSEEK_API_KEY`, `FINLENS_PASSWORD`, and optionally `ANTHROPIC_API_KEY`.
- Outbound internet (yfinance, NSE, DeepSeek/Claude). Cloud IPs can make a quote fetch flake; Refresh Prices usually recovers.

**GitHub**

```bash
git remote add origin https://github.com/AkashKhatrii/FinLens.git   # once
git push -u origin main
```

`.env` and `.data/` stay local (gitignored).

**Railway**

1. New project → deploy from `AkashKhatrii/FinLens` (`main`). Railway uses the [`Dockerfile`](Dockerfile).
2. Add a **volume** mounted at `/var/data`.
3. Variables:
   - `FINLENS_DATA_DIR=/var/data`
   - `FINLENS_CACHE_DIR=/var/data/cache`
   - `FINLENS_PROVIDER=deepseek`
   - `DEEPSEEK_API_KEY`
   - `FINLENS_PASSWORD` (browser login; username is always `finlens`)
   - optional `ANTHROPIC_API_KEY` for Claude
4. Health check `/api/health` (this path is not password-gated).
5. Generate a public HTTPS domain in Railway, open it, enter username `finlens` and your password.

**Copy your Mac Tradebook onto the volume**

```bash
./scripts/sync-tradebook.sh
```

That uploads `backend/.data/tradebook/*.json` to `/tradebook` on the volume, which the app sees as `/var/data/tradebook`. It is not committed to git.

Leave `FINLENS_PASSWORD` unset on your laptop so local access stays open.

A full Nifty 500 low-score run can exceed a request timeout. Single-ticker analysis and Tradebook should match local.

---

## Adding other markets

`config.MARKETS` already has a `US` entry and the engines are market-agnostic —
they only consume a `StockBundle`. To add a market properly you need a provider
that supplies that market's filings; write one satisfying the `Provider` protocol
in `providers/base.py` and register it. No engine changes required.

## Known limits

- **Data source.** yfinance is free, unofficial and rate-limited. Promoter pledge,
  shareholding-pattern history, concall transcripts and segment detail are *not*
  available from it — all of which a real analyst would read. Moving to EODHD,
  Kite Connect or the BSE/NSE filings APIs means writing one new provider.
- **Banks and NBFCs.** EBITDA-based metrics (EV/EBITDA, net debt/EBITDA) are
  meaningless for lenders; NIM, GNPA and CAR are not yet computed. The AI layer is
  instructed to flag this, but the quant score doesn't yet adjust for it.
- **No sector-relative valuation.** P/E is compared to the company's own history,
  not to its peers.
- **The UI is CDN-loaded Vue + Tailwind Play.** Fine for local use, not a
  production bundle.

---

Research and education only — not investment advice.
