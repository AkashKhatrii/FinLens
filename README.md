# FinLens

AI-assisted equity research for Indian listed companies (NSE/BSE). Type a ticker
and get an analyst-style workup: fundamentals from the filings, a DCF when it is
valid, technicals, risk, and separate buy/hold/avoid verdicts for **swing** and
**long-term**. Headline **Overall** is a 40/60 blend of those two — tilted toward
the long view. DeepSeek writes the thesis by default; Claude is optional.

The SPA also has a **Tradebook** (immutable recommendation journal), **Nifty Quant**
screeners, and a Terms glossary. Layout works on a phone and on a desktop.

```bash
./run.sh          # http://127.0.0.1:8000
```

Python 3.12, FastAPI, one Vue page. Copy `backend/.env.example` to `backend/.env`
and add `DEEPSEEK_API_KEY` if you want the written thesis.

---

## What it actually does

The design principle is that **the same evidence should be weighted differently
depending on how long you intend to hold.** A great business can be a bad entry,
and a mediocre business can be a decent swing. Collapsing that into a single
"score out of 10" is the thing most stock apps get wrong.

User-facing horizons are **Swing** (1–3 months) and **Long** (1–3+ years). Long
asks whether the company is worth owning; Swing asks whether the next few months
are a reasonable entry. Short-term setup metrics still exist as a pillar and
feed Swing — they are not a third verdict.

The engine computes nine independent pillars, then scores them twice under two
weightings.

| Pillar | What goes into it |
|---|---|
| Growth | Revenue/PAT YoY and multi-year CAGR, latest-quarter YoY |
| Profitability & Returns | Operating and net margin, margin trend, **ROE, ROCE** |
| Balance Sheet & Cash | D/E, net debt/EBITDA, interest cover, current ratio, **OCF/PAT**, FCF margin |
| Valuation | P/E vs **its own 5-year median**, P/B, EV/EBITDA, PEG, earnings yield vs 10Y G-Sec, DCF |
| Short-Term Setup | RSI, Bollinger %B, price vs 20-DMA, 1-week/1-month return, volume trend |
| Trend & Relative Strength | Price vs 50/200-DMA, ADX, 3M and 1Y relative strength vs NIFTY, 52W position |
| Earnings Momentum | Beat/miss rate and average surprise over the last four quarters |
| Sentiment & Ownership | Street rating and target, promoter holding, institutional holding |
| Risk | Beta, annualised volatility, max drawdown, daily turnover, red flags |

### Horizon weights

| Pillar | Swing (1–3mo) | Long (1–3yr+) |
|---|---|---|
| Short-term setup | 16% | 0% |
| Trend & RS | 26% | 5% |
| Earnings | 16% | 6% |
| Valuation | 12% | 20% |
| Growth | 10% | 20% |
| Profitability | 3% | 22% |
| Balance sheet | 1% | 16% |
| Sentiment | 8% | 2% |
| Risk | 8% | 9% |

Weights live in one declarative dict in `app/engine/scoring.py`. Individual
metrics can be down-weighted per horizon in the same file (`HORIZON_FACTOR`)
so a 1-week RSI does not move Long. Within-pillar overlap (two metrics measuring
the same thing) is handled in `metric_weights.py` and does not change the mix
above.

**Overall** = 40% Swing + 60% Long (`OVERALL_BLEND`). Verdict bands:
Strong Buy ≥ 80, Buy ≥ 66, Hold ≥ 50, Reduce ≥ 35, else Avoid.

Each score also gets a **percentile** against a stored NIFTY-grade universe so
"62" is readable as "around the median of that set", not as a calibrated 0–100.

### Surfaces

- **Analysis** — full report for one ticker, with expandable pillars, DCF
  assumptions, AI thesis on demand, Opportunity (long-term qualitative view),
  and Accumulation (wealth-creation layer; not a third score).
- **Tradebook** — recommendation journal. Adding a name copies the current
  analysis into a JSON snapshot; later price refreshes do not re-run scoring.
  Quantity is a journal field; P&L is quantity-weighted, not a ranking input.
- **Nifty Quant** — Overall / Swing / Long for Nifty 50, Nifty 100, or the 50
  lowest Overall scores from the current Nifty 500. Quant only; no AI.
- **Terms** — in-app glossary for the dotted labels on a report.

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

**Banks are not scored as industrials.** Deposit-taking banks suppress EBITDA /
ROCE / DCF-style metrics and map NIM, GNPA, CAR, loan growth and the rest onto
the existing pillars. NBFCs and brokers stay on the default (industrial) profile
on purpose. Horizon mix and verdict bands do not change.

**Nothing is hidden.** Every pillar expands into its individual metrics with the
raw value, the 0–100 score, and a one-line reading.

---

## The AI layer

DeepSeek (`deepseek-v4-flash`) receives a compact JSON fact pack — all computed
metrics, scores, and notes — and returns a **schema-validated** thesis:
headline, business summary, quality and valuation verdicts, bull/bear cases,
key risks, what to watch, a per-horizon call with *"what would change my mind"*,
a `contrarian_note` arguing where the quantitative score is likely wrong, plus
**Opportunity** (long-term qualitative view) and **Accumulation** (whether to
build a position over years). Neither of those last two is a 0–100 score, and
neither changes Swing/Long.

Thinking mode is disabled: on v4-flash it is on by default and would eat the
token budget, returning empty content. Claude remains available from the header
select (or `FINLENS_PROVIDER=claude`) so a leftover Anthropic key is not billed
by accident.

**It degrades cleanly.** With no API key the app still returns the complete
quantitative analysis and the UI explains what's missing.

```bash
cp backend/.env.example backend/.env   # then add DEEPSEEK_API_KEY
```

---

## Layout

```
backend/app/
  main.py              FastAPI routes + NaN/numpy-safe JSON encoding
  analysis.py          orchestrator; builds the AI fact pack
  access.py            optional HTTP Basic (FINLENS_PASSWORD); /api/health is open
  config.py            markets, cache TTLs, risk-free rate, models
  cache.py             TTL disk cache (the data source is slow and rate-limited)
  providers/
    nse_symbols.py     NSE equity master; fuzzy resolution + "did you mean"
    yf_provider.py     yfinance adapter, symbol resolution, news filtering
    index_constituents.py  Nifty 50 / 100 / 500 membership from NSE CSVs
    bank_*.py          bank KPI fetch/extract → canonical metrics
  engine/
    scoring.py         Swing/Long weights, 40/60 Overall, verdicts, confidence
    metric_weights.py  within-pillar overlap (does not change horizon mix)
    fundamentals.py    growth, profitability, balance sheet
    valuation.py       multiples, own-history P/E band, two-stage DCF
    technicals.py      RSI/MACD/ADX/ATR/Bollinger, relative strength
    qualitative.py     risk + beta, earnings surprises, sentiment
    bank_scoring.py    bank KPIs onto existing pillars
    accumulation.py    qualitative accumulate / watch / do-not layer
    percentile.py      rank vs stored NIFTY-grade universe
  tradebook/           JSON journal under FINLENS_DATA_DIR/tradebook
  screener/            quant rows from analyse(); never calls the AI
  ai/
    schemas.py         Pydantic thesis schema
    prompts.py         frozen (cacheable) analyst system prompt
    analyst.py         DeepSeek / Claude call
  static/index.html    the whole UI
```

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/analyse?q=TCS` | Full quantitative analysis (`ai=true` adds the thesis) |
| `GET /api/search?q=tata` | Typeahead over the NSE equity list |
| `GET /api/resolve?q=tata%20motors` | Name → ticker |
| `GET /api/screener/quant?q=TCS` | One Overall/Swing/Long row; never calls the AI |
| `GET /api/indexes/{NIFTY50\|NIFTY100\|NIFTY500}/constituents` | Current membership |
| `GET /api/tradebook` | Journal list (filters: ticker, swing, AI agreement, active/history) |
| `POST /api/tradebook` | Record a snapshot from an analysis payload |
| `PATCH /api/tradebook/{id}/quantity` | Journal quantity (does not re-score) |
| `POST /api/tradebook/refresh-prices` | Update marks; snapshots stay frozen |
| `GET /api/health` | Status + whether AI credentials resolved (not password-gated) |
| `POST /api/cache/clear` | Drop cached market data |

---

## Deploy (GitHub + Railway)

Local `./run.sh` is unchanged. Hosted FinLens is the same FastAPI app behind HTTPS.

Repo: [AkashKhatrii/FinLens](https://github.com/AkashKhatrii/FinLens). Railway
builds from `main` using the [`Dockerfile`](Dockerfile). A Render blueprint
remains in [`render.yaml`](render.yaml) if you ever want that host instead.

**What you need**

- A Railway service with a volume mounted at `/var/data`. Without a volume,
  Tradebook files vanish on restart.
- Secrets on Railway, never in git: `DEEPSEEK_API_KEY`, `FINLENS_PASSWORD`, and
  optionally `ANTHROPIC_API_KEY`.
- Outbound internet (yfinance, NSE, DeepSeek/Claude). Cloud IPs can make a quote
  fetch flake; Refresh Prices usually recovers.

**Railway variables**

- `FINLENS_DATA_DIR=/var/data`
- `FINLENS_CACHE_DIR=/var/data/cache`
- `FINLENS_PROVIDER=deepseek`
- `DEEPSEEK_API_KEY`
- `FINLENS_PASSWORD` (browser login; username is always `finlens`)
- optional `ANTHROPIC_API_KEY` for Claude

Health check `/api/health`. Leave `FINLENS_PASSWORD` unset on a laptop so local
access stays open.

**Copy a local Tradebook onto the volume**

```bash
./scripts/sync-tradebook.sh
```

That uploads `backend/.data/tradebook/*.json` to `/var/data/tradebook`. Journal
files are gitignored; they are not the scoring engine.

A full Nifty 500 low-score run can exceed a request timeout. Single-ticker
analysis and Tradebook should match local.

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
- **NBFCs and non-bank lenders.** The bank profile is conservative (Yahoo
  industry must look like a deposit-taking bank). Credit-services names still
  get industrial ratios.
- **No sector-relative valuation.** P/E is compared to the company's own history,
  not to its peers.
- **The UI is CDN-loaded Vue + Tailwind Play.** Fine for this app, not a
  production JS bundle.

---

Research and education only — not investment advice.
