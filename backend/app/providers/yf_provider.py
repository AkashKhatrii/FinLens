"""yfinance-backed provider.

Free and good enough to build against, with two caveats we design around:

1. `.info` is unreliable for NSE tickers - `returnOnEquity`, `freeCashflow`
   and `beta` come back null or stale. Every ratio that matters is therefore
   computed from raw statements in `app/engine/`, and `.info` is only a
   last-resort fallback.
2. It is rate-limited and slow, so every call goes through the disk cache.
"""
from __future__ import annotations

import logging
import warnings
from typing import Any

import pandas as pd
import yfinance as yf

from .. import cache
from ..config import FUNDAMENTAL_TTL, MARKETS, NEWS_TTL, PRICE_TTL
from . import nse_symbols
from .base import AnalystView, Ownership, Quote, Statements, StockBundle

warnings.filterwarnings("ignore", category=FutureWarning)
log = logging.getLogger(__name__)

# Common ways people refer to large caps that don't match the NSE symbol.
ALIASES = {
    "reliance": "RELIANCE", "ril": "RELIANCE",
    "tcs": "TCS", "tata consultancy": "TCS",
    "infy": "INFY", "infosys": "INFY",
    "hdfc": "HDFCBANK", "hdfc bank": "HDFCBANK",
    "icici": "ICICIBANK", "icici bank": "ICICIBANK",
    "sbi": "SBIN", "state bank": "SBIN",
    "airtel": "BHARTIARTL", "bharti": "BHARTIARTL",
    "itc": "ITC", "lt": "LT", "l&t": "LT", "larsen": "LT",
    "maruti": "MARUTI", "hul": "HINDUNILVR", "hindustan unilever": "HINDUNILVR",
    "wipro": "WIPRO", "axis": "AXISBANK", "kotak": "KOTAKBANK",
    "bajaj finance": "BAJFINANCE", "asian paints": "ASIANPAINT",
    "titan": "TITAN", "sun pharma": "SUNPHARMA", "zomato": "ETERNAL",
    "adani enterprises": "ADANIENT", "adani ports": "ADANIPORTS",
    "tata motors": "TMCV", "tata steel": "TATASTEEL", "jsw steel": "JSWSTEEL",
    "ongc": "ONGC", "ntpc": "NTPC", "powergrid": "POWERGRID", "coal india": "COALINDIA",
    "dmart": "DMART", "avenue supermarts": "DMART", "nestle": "NESTLEIND",
    "hcl": "HCLTECH", "tech mahindra": "TECHM", "ultratech": "ULTRACEMCO",
}


class YFinanceProvider:
    def __init__(self, market: str = "IN") -> None:
        self.market = market
        self.cfg = MARKETS[market]

    # --- symbol resolution ---------------------------------------------------
    def resolve(self, query: str) -> str | None:
        symbol, _ = self.resolve_with_suggestions(query)
        return symbol

    def resolve_with_suggestions(self, query: str) -> tuple[str | None, list[dict[str, str]]]:
        """Resolve a query, and return near-misses when it can't be resolved."""
        raw = (query or "").strip()
        if not raw:
            return None, []

        # Already a fully-qualified ticker.
        if any(raw.upper().endswith(sfx) for sfx in self.cfg["suffixes"] if sfx):
            return raw.upper(), []

        # Aliases first: they encode renames and colloquial names that no
        # amount of string similarity can recover. NSE lists Zomato as
        # "Eternal Limited", so fuzzy matching "zomato" finds nothing.
        alias = ALIASES.get(raw.lower())
        if alias:
            if self.market == "IN" and nse_symbols.available():
                exact, _ = nse_symbols.find(alias)
                if exact:
                    return f"{exact.symbol}.NS", []
            for suffix in self.cfg["suffixes"]:
                if self._is_valid(f"{alias}{suffix}"):
                    return f"{alias}{suffix}", []

        # The NSE master list is authoritative for India and handles typos.
        if self.market == "IN" and nse_symbols.available():
            match, near = nse_symbols.find(raw)
            suggestions = [{"symbol": l.symbol, "name": l.name} for l in near]
            if match:
                return f"{match.symbol}.NS", suggestions
            if suggestions:
                return None, suggestions

        base = raw.upper().replace(" ", "")
        for suffix in self.cfg["suffixes"]:
            candidate = f"{base}{suffix}"
            if self._is_valid(candidate):
                return candidate, []

        # Fall back to Yahoo's search for free-text company names.
        return self._search(raw), []

    def _is_valid(self, symbol: str) -> bool:
        def check() -> dict[str, Any]:
            try:
                fi = yf.Ticker(symbol).fast_info
                price = fi.get("lastPrice") or fi.get("last_price")
                return {"ok": bool(price)}
            except Exception:
                return {"ok": False}

        return bool(cache.memoize("valid", symbol, FUNDAMENTAL_TTL, check)["ok"])

    def _search(self, query: str) -> str | None:
        def run() -> list[dict[str, Any]]:
            try:
                return list(yf.Search(query).quotes or [])
            except Exception as exc:
                log.warning("search failed for %r: %s", query, exc)
                return []

        quotes = cache.memoize("search", f"{self.market}:{query.lower()}", FUNDAMENTAL_TTL, run)
        # Try each configured suffix in order so the primary exchange wins.
        # Without this, 'infosys ltd' resolved to INFY.BO purely because the
        # Bombay listing happened to come back first.
        for suffix in self.cfg["suffixes"]:
            for q in quotes:
                sym = str(q.get("symbol", ""))
                if q.get("quoteType") not in (None, "EQUITY"):
                    continue
                if (suffix and sym.endswith(suffix)) or not suffix:
                    return sym
        return quotes[0].get("symbol") if quotes else None

    # --- fetch ---------------------------------------------------------------
    def fetch(self, symbol: str) -> StockBundle:
        gaps: list[str] = []
        ticker = yf.Ticker(symbol)

        info = cache.memoize(
            "info", symbol, FUNDAMENTAL_TTL, lambda: self._safe(lambda: ticker.info, {}, gaps, "info")
        ) or {}

        statements = cache.memoize(
            "stmts", symbol, FUNDAMENTAL_TTL, lambda: self._fetch_statements(ticker, gaps)
        )
        history = cache.memoize(
            "hist", symbol, PRICE_TTL,
            lambda: self._safe(lambda: ticker.history(period="3y", auto_adjust=True), pd.DataFrame(), gaps, "price history"),
        )
        benchmark = cache.memoize(
            "hist", self.cfg["benchmark"], PRICE_TTL,
            lambda: self._safe(
                lambda: yf.Ticker(self.cfg["benchmark"]).history(period="3y", auto_adjust=True),
                pd.DataFrame(), gaps, "benchmark history",
            ),
        )
        earnings = cache.memoize(
            "earn", symbol, FUNDAMENTAL_TTL,
            lambda: self._safe(lambda: ticker.earnings_dates, pd.DataFrame(), gaps, "earnings history"),
        )
        quote = self._build_quote(symbol, info, history)
        news = cache.memoize(
            "news", symbol, NEWS_TTL, lambda: self._fetch_news(ticker, symbol, quote.name)
        )
        if not news:
            gaps.append("company-specific news")
        ownership = cache.memoize(
            "own", symbol, FUNDAMENTAL_TTL, lambda: self._fetch_ownership(ticker, info)
        )

        return StockBundle(
            market=self.market,
            quote=quote,
            statements=statements,
            history=history if history is not None else pd.DataFrame(),
            benchmark_history=benchmark if benchmark is not None else pd.DataFrame(),
            ownership=ownership,
            analysts=self._build_analysts(info),
            earnings_history=earnings if earnings is not None else pd.DataFrame(),
            news=news or [],
            info=info,
            gaps=gaps,
        )

    # --- pieces --------------------------------------------------------------
    @staticmethod
    def _safe(fn, default, gaps: list[str], label: str):
        try:
            result = fn()
            if result is None or (hasattr(result, "empty") and result.empty):
                gaps.append(label)
                return default
            return result
        except Exception as exc:
            log.warning("%s unavailable: %s", label, exc)
            gaps.append(label)
            return default

    def _fetch_statements(self, ticker: yf.Ticker, gaps: list[str]) -> Statements:
        s = Statements(
            income_annual=self._safe(lambda: ticker.income_stmt, pd.DataFrame(), gaps, "annual income statement"),
            income_quarterly=self._safe(lambda: ticker.quarterly_income_stmt, pd.DataFrame(), gaps, "quarterly income statement"),
            balance_annual=self._safe(lambda: ticker.balance_sheet, pd.DataFrame(), gaps, "annual balance sheet"),
            balance_quarterly=self._safe(lambda: ticker.quarterly_balance_sheet, pd.DataFrame(), gaps, "quarterly balance sheet"),
            cashflow_annual=self._safe(lambda: ticker.cashflow, pd.DataFrame(), gaps, "annual cash flow"),
            cashflow_quarterly=self._safe(lambda: ticker.quarterly_cashflow, pd.DataFrame(), gaps, "quarterly cash flow"),
        )
        return s

    def _fetch_news(self, ticker: yf.Ticker, symbol: str, company_name: str) -> list[dict[str, Any]]:
        """Yahoo's news feed for NSE tickers is largely untargeted - querying
        TCS.NS returns global wire copy about unrelated companies. Unfiltered,
        that noise reaches both the UI and the model's fact pack, so only keep
        items that actually name the company or its ticker."""
        try:
            raw = ticker.news or []
        except Exception:
            return []

        base = symbol.split(".")[0].lower()
        stop = {"limited", "ltd", "the", "and", "company", "corporation", "industries",
                "india", "bank", "services", "enterprises", "motors", "steel"}
        tokens = {t for t in company_name.lower().replace(",", " ").split() if t not in stop and len(t) > 3}
        tokens.add(base)

        out = []
        for item in raw[:20]:
            content = item.get("content", item) or {}
            provider = content.get("provider") or {}
            title = content.get("title") or item.get("title", "")
            summary = (content.get("summary") or "")[:400]
            if not title:
                continue
            haystack = f"{title} {summary}".lower()
            if not any(tok in haystack for tok in tokens):
                continue
            out.append({
                "title": title,
                "summary": summary,
                "publisher": provider.get("displayName") or item.get("publisher", ""),
                "published": content.get("pubDate") or "",
                "url": (content.get("canonicalUrl") or {}).get("url", ""),
            })
        return out[:10]

    def _fetch_ownership(self, ticker: yf.Ticker, info: dict[str, Any]) -> Ownership:
        own = Ownership()
        # In India yfinance's "insiders" bucket maps to promoter holding.
        insiders = info.get("heldPercentInsiders")
        institutions = info.get("heldPercentInstitutions")
        own.promoter_or_insider_pct = float(insiders) * 100 if insiders is not None else None
        own.institutions_pct = float(institutions) * 100 if institutions is not None else None

        try:
            holders = ticker.institutional_holders
            if holders is not None and not holders.empty:
                own.top_holders = [
                    {"name": str(r.get("Holder", "")), "pct": float(r.get("pctHeld") or 0) * 100}
                    for _, r in holders.head(6).iterrows()
                ]
        except Exception:
            pass
        return own

    def _build_quote(self, symbol: str, info: dict[str, Any], history: pd.DataFrame) -> Quote:
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        prev = info.get("previousClose") or info.get("regularMarketPreviousClose")

        # `.info` prices can be stale outside market hours; history is the truth.
        # Yahoo often appends today's session with a NaN close before the auction
        # prints — using iloc[-1] then serialises to null and the UI shows "—".
        if history is not None and not history.empty and "Close" in history:
            closes = history["Close"].dropna()
            if not closes.empty:
                price = float(closes.iloc[-1])
                if len(closes) > 1:
                    prev = float(closes.iloc[-2])

        change = ((price / prev - 1) * 100) if (price and prev) else None
        return Quote(
            symbol=symbol,
            name=info.get("longName") or info.get("shortName") or symbol,
            exchange=info.get("exchange", ""),
            currency=info.get("currency", self.cfg["currency"]),
            price=price,
            previous_close=prev,
            day_change_pct=change,
            market_cap=info.get("marketCap"),
            sector=info.get("sector", ""),
            industry=info.get("industry", ""),
            business_summary=(info.get("longBusinessSummary") or "")[:2000],
            website=info.get("website", ""),
            week52_high=info.get("fiftyTwoWeekHigh"),
            week52_low=info.get("fiftyTwoWeekLow"),
            avg_volume=info.get("averageVolume"),
            shares_outstanding=info.get("sharesOutstanding"),
            float_shares=info.get("floatShares"),
        )

    def last_prices(self, symbols: list[str]) -> dict[str, float | None]:
        """Latest close for many tickers. No statements, news, or scoring."""
        out: dict[str, float | None] = {sym: None for sym in symbols}
        yahoo_for: dict[str, str] = {}
        for sym in symbols:
            yahoo_for[self._yahoo_symbol(sym)] = sym
        if not yahoo_for:
            return out
        try:
            df = yf.download(
                list(yahoo_for.keys()),
                period="5d",
                interval="1d",
                auto_adjust=True,
                progress=False,
                threads=True,
                group_by="ticker",
            )
        except Exception as exc:
            log.warning("last_prices download failed: %s", exc)
            return out
        single = len(yahoo_for) == 1
        for ysym, orig in yahoo_for.items():
            out[orig] = _last_close(df, ysym, single)
        return out

    def _yahoo_symbol(self, symbol: str) -> str:
        raw = (symbol or "").strip().upper()
        suffixes = tuple(sfx.upper() for sfx in self.cfg["suffixes"] if sfx)
        if any(raw.endswith(sfx) for sfx in suffixes):
            return raw
        suffix = next((s for s in self.cfg["suffixes"] if s), "")
        return f"{raw}{suffix}"

    @staticmethod
    def _build_analysts(info: dict[str, Any]) -> AnalystView:
        return AnalystView(
            target_mean=info.get("targetMeanPrice"),
            target_high=info.get("targetHighPrice"),
            target_low=info.get("targetLowPrice"),
            recommendation=(info.get("recommendationKey") or "").replace("_", " "),
            analyst_count=info.get("numberOfAnalystOpinions"),
        )


def _last_close(df: pd.DataFrame, yahoo_symbol: str, single: bool) -> float | None:
    if df is None or getattr(df, "empty", True):
        return None
    try:
        series = None
        if single and "Close" in df.columns and not isinstance(df.columns, pd.MultiIndex):
            series = df["Close"]
        elif isinstance(df.columns, pd.MultiIndex):
            level0 = set(df.columns.get_level_values(0))
            if yahoo_symbol in level0:
                block = df[yahoo_symbol]
                series = block["Close"] if "Close" in block.columns else None
            elif "Close" in level0:
                series = df["Close"][yahoo_symbol]
        if series is None:
            return None
        closes = series.dropna()
        if closes.empty:
            return None
        value = float(closes.iloc[-1])
        if value != value:
            return None
        return value
    except Exception:
        return None
