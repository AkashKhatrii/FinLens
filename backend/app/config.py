"""Central configuration. Everything tunable lives here or in .env."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
load_dotenv(PROJECT_ROOT / ".env")

# --- caching -----------------------------------------------------------------
CACHE_DIR = Path(os.getenv("FINLENS_CACHE_DIR", str(PROJECT_ROOT / ".cache")))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
PRICE_TTL = int(os.getenv("FINLENS_PRICE_TTL", "900"))        # 15 min
FUNDAMENTAL_TTL = int(os.getenv("FINLENS_FUND_TTL", "86400"))  # 24 h
NEWS_TTL = int(os.getenv("FINLENS_NEWS_TTL", "3600"))          # 1 h

# --- markets -----------------------------------------------------------------
DEFAULT_MARKET = "IN"
MARKETS = {
    "IN": {
        "name": "India",
        "currency": "INR",
        "symbol": "₹",
        "benchmark": "^NSEI",
        "benchmark_name": "NIFTY 50",
        "suffixes": (".NS", ".BO"),
        # India 10y G-Sec. Used as the risk-free leg of the DCF discount rate.
        "risk_free_rate": float(os.getenv("FINLENS_RISK_FREE_IN", "0.068")),
        "equity_risk_premium": float(os.getenv("FINLENS_ERP_IN", "0.055")),
    },
    # Wired but not the focus yet - the provider layer is market-agnostic.
    "US": {
        "name": "United States",
        "currency": "USD",
        "symbol": "$",
        "benchmark": "^GSPC",
        "benchmark_name": "S&P 500",
        "suffixes": ("",),
        "risk_free_rate": float(os.getenv("FINLENS_RISK_FREE_US", "0.042")),
        "equity_risk_premium": float(os.getenv("FINLENS_ERP_US", "0.045")),
    },
}

# --- AI ----------------------------------------------------------------------
# Default is DeepSeek. Claude is opt-in via FINLENS_PROVIDER=claude so a leftover
# Anthropic key cannot keep billing Opus on every analysis.
AI_ENABLED = os.getenv("FINLENS_AI", "auto").lower() != "off"
ANTHROPIC_EFFORT = os.getenv("FINLENS_EFFORT", "high")

PROVIDERS = {
    "deepseek": {
        "label": "DeepSeek",
        "kind": "openai_compat",
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "model_env": "FINLENS_DEEPSEEK_MODEL",
        # Same id jobscan uses. deepseek-chat/reasoner retired 2026-07-24 and
        # alias here; name the cost-efficient model explicitly.
        "default_model": "deepseek-v4-flash",
        "timeout": 60.0,
    },
    "claude": {
        "label": "Claude",
        "kind": "anthropic",
        "api_key_env": "ANTHROPIC_API_KEY",
        "model_env": "FINLENS_CLAUDE_MODEL",
        "default_model": os.getenv("FINLENS_MODEL", "claude-opus-5"),
    },
}

# Kept for anything still reading the old name.
ANTHROPIC_MODEL = os.getenv("FINLENS_CLAUDE_MODEL", os.getenv("FINLENS_MODEL", "claude-opus-5"))


def provider_key() -> str:
    raw = (os.getenv("FINLENS_PROVIDER") or "deepseek").strip().lower()
    return raw if raw in PROVIDERS else "deepseek"


def provider_model(key: str | None = None) -> str:
    key = key or provider_key()
    spec = PROVIDERS[key]
    return os.getenv(spec["model_env"], spec["default_model"])
