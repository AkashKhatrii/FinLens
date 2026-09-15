"""Official investor-relations source pages for listed Indian banks.

Declarative registry only: lookups never make HTTP requests. Document
discovery, PDF parsing, and KPI extraction belong in a later provider,
not in this module and not in engine/.
"""
from __future__ import annotations

from dataclasses import dataclass

SOURCE_TYPE_OFFICIAL_IR = "official_ir"


@dataclass(frozen=True)
class BankSource:
    ticker: str
    name: str
    investor_relations_url: str
    financial_results_url: str | None = None
    investor_presentations_url: str | None = None
    source_type: str = SOURCE_TYPE_OFFICIAL_IR


# Canonical .bank.in landings after official domain migration. Optional
# result/presentation URLs are set only when a dedicated archive page was
# verified; otherwise they stay None rather than pointing at a PDF or a
# combined IR hub.
_BANK_SOURCES: tuple[BankSource, ...] = (
    BankSource(
        ticker="HDFCBANK",
        name="HDFC Bank Limited",
        investor_relations_url="https://www.hdfc.bank.in/about-us/investor-relations",
        financial_results_url="https://www.hdfc.bank.in/about-us/investor-relations/financial-results",
        investor_presentations_url=None,
    ),
    BankSource(
        ticker="ICICIBANK",
        name="ICICI Bank Limited",
        investor_relations_url="https://www.icici.bank.in/about-us/invest-relations",
        financial_results_url="https://www.icici.bank.in/about-us/qfr",
        investor_presentations_url="https://www.icici.bank.in/about-us/investor",
    ),
    BankSource(
        ticker="SBIN",
        name="State Bank of India",
        investor_relations_url="https://sbi.bank.in/web/investor-relations/investor-relations",
        financial_results_url="https://sbi.bank.in/web/investor-relations/reports",
        investor_presentations_url="https://sbi.bank.in/web/investor-relations/analyst-presentation",
    ),
    BankSource(
        ticker="AXISBANK",
        name="Axis Bank Limited",
        investor_relations_url="https://www.axis.bank.in/shareholders-corner",
        financial_results_url="https://www.axis.bank.in/shareholders-corner/other-information/quarterly-results",
        investor_presentations_url="https://www.axis.bank.in/shareholders-corner/financial-results-and-other-presentation",
    ),
    BankSource(
        ticker="KOTAKBANK",
        name="Kotak Mahindra Bank Limited",
        investor_relations_url="https://www.kotak.bank.in/en/investor-relations.html",
        financial_results_url="https://www.kotak.bank.in/en/investor-relations/financial-results.html",
        investor_presentations_url=None,
    ),
    BankSource(
        ticker="INDUSINDBK",
        name="IndusInd Bank Limited",
        investor_relations_url="https://www.indusind.bank.in/in/en/investors/investor-landing.html",
        financial_results_url="https://www.indusind.bank.in/in/en/investors/investor-landing/investor-resources.html",
        investor_presentations_url=None,
    ),
    BankSource(
        ticker="BANKBARODA",
        name="Bank of Baroda",
        investor_relations_url="https://bankofbaroda.bank.in/shareholders-corner",
        financial_results_url="https://bankofbaroda.bank.in/shareholders-corner/financial-reports",
        investor_presentations_url="https://bankofbaroda.bank.in/shareholders-corner/presentation-made-to-analyst",
    ),
    BankSource(
        ticker="PNB",
        name="Punjab National Bank",
        investor_relations_url="https://pnb.bank.in/financials-current.html",
        financial_results_url="https://pnb.bank.in/financials-current.html",
        investor_presentations_url=None,
    ),
    BankSource(
        ticker="CANBK",
        name="Canara Bank",
        investor_relations_url="https://www.canarabank.bank.in/investor-relation",
        financial_results_url="https://www.canarabank.bank.in/financial-result",
        investor_presentations_url="https://www.canarabank.bank.in/pages/investor-presentation",
    ),
    BankSource(
        ticker="UNIONBANK",
        name="Union Bank of India",
        investor_relations_url="https://www.unionbankofindia.bank.in/en/common/financial-results",
        financial_results_url="https://www.unionbankofindia.bank.in/en/common/financial-results",
        investor_presentations_url=None,
    ),
    BankSource(
        ticker="IDFCFIRSTB",
        name="IDFC First Bank Limited",
        investor_relations_url="https://www.idfcfirst.bank.in/investors",
        financial_results_url="https://www.idfcfirst.bank.in/investors/financial-report",
        investor_presentations_url=None,
    ),
    BankSource(
        ticker="FEDERALBNK",
        name="The Federal Bank Limited",
        investor_relations_url="https://www.federal.bank.in/financial-result",
        financial_results_url="https://www.federal.bank.in/financial-result",
        investor_presentations_url=None,
    ),
    BankSource(
        ticker="AUBANK",
        name="AU Small Finance Bank Limited",
        investor_relations_url="https://www.au.bank.in/investors",
        financial_results_url="https://www.au.bank.in/investors/quarterly-reports",
        investor_presentations_url=None,
    ),
    BankSource(
        ticker="BANDHANBNK",
        name="Bandhan Bank Limited",
        investor_relations_url="https://www.bandhan.bank.in/investor-relations",
        financial_results_url="https://www.bandhan.bank.in/quarterly-report",
        investor_presentations_url=None,
    ),
    BankSource(
        ticker="BANKINDIA",
        name="Bank of India",
        investor_relations_url="https://bankofindia.bank.in/investor-corner",
        financial_results_url="https://bankofindia.bank.in/financial-result",
        investor_presentations_url="https://bankofindia.bank.in/investor-presentation-sebi",
    ),
)

_BY_TICKER: dict[str, BankSource] = {src.ticker: src for src in _BANK_SOURCES}


def _normalize_ticker(ticker: str | None) -> str:
    if not ticker:
        return ""
    return ticker.strip().upper()


def get_bank_source(ticker: str) -> BankSource | None:
    key = _normalize_ticker(ticker)
    if not key:
        return None
    return _BY_TICKER.get(key)


def is_supported_bank(ticker: str) -> bool:
    return get_bank_source(ticker) is not None


def get_supported_bank_tickers() -> list[str]:
    return [src.ticker for src in _BANK_SOURCES]
