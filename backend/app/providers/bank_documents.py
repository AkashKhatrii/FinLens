"""Discover official quarterly documents from registered bank IR pages.

HTML discovery only: this module fetches landing pages from the bank source
registry, classifies links, and returns candidate documents. It does not
download PDFs, extract text, or parse KPIs.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urljoin, urlparse

import requests
from lxml import html as lxml_html

from .bank_sources import SOURCE_TYPE_OFFICIAL_IR, BankSource, get_bank_source

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

DOC_INVESTOR_PRESENTATION = "investor_presentation"
DOC_FINANCIAL_RESULTS = "financial_results"
DOC_EARNINGS_CALL = "earnings_call"
DOC_ANNUAL_REPORT = "annual_report"
DOC_PRESS_RELEASE = "press_release"
DOC_OTHER = "other"

_DOCUMENT_SUFFIXES = (".pdf", ".ppt", ".pptx", ".xls", ".xlsx", ".zip")

_PRESENTATION_RE = re.compile(
    r"investor\s+(presentation|ppt|pptx)|analyst\s+(presentation|ppt)|"
    r"results\s+presentation|earnings\s+presentation|quarterly\s+presentation|"
    r"presentation\s+made\s+to\s+analyst|general\s+investor|"
    r"investor-presentation|analyst-presentation|results-presentation",
    re.I,
)
_RESULTS_RE = re.compile(
    r"financial\s+results?|quarterly\s+results?|unaudited\s+(financial\s+)?results|"
    r"audited\s+results|financial\s+statements|financial-results?|"
    r"quarterly-results?|\bqfr\b|\bresults\b",
    re.I,
)
_EARNINGS_CALL_RE = re.compile(
    r"earnings\s+call|conference\s+call|earnings-call|conference-call|"
    r"\bconcall\b|call\s+(audio|recording|transcript)|earnings\s+transcript|"
    r"analyst\s+call|\btranscript\b",
    re.I,
)
_ANNUAL_REPORT_RE = re.compile(
    r"annual\s+report|annual-report|integrated\s+annual",
    re.I,
)
_PRESS_RELEASE_RE = re.compile(
    r"press\s+release|press-release|media\s+release",
    re.I,
)
# AMC/debt/ESG/subsidiary decks are not the bank's primary quarterly presentation.
# "life" alone is not excluded; only clearly subsidiary/business-unit combinations.
_EXCLUDED_RE = re.compile(
    r"\bamc\b|asset\s+management|"
    r"debt\s+investor|debt\s+presentation|debt-investor|"
    r"bond\s+investor|fixed\s+income|"
    r"\besg\b|\bsustainability\b|"
    r"\bbasel\b|pillar\s*[- ]?3|"
    r"\bremuneration\b|subsidiar|"
    r"(?:^|[\s/])life\s+(investor|insurance)\b|lifeinsurance|"
    r"general\s+insurance|housing\s+finance|home\s+finance|"
    r"mutual\s+fund",
    re.I,
)

_QUARTER_FY_RE = re.compile(r"Q\s*([1-4])\s*[-_/]?\s*FY\s*(\d{2,4})", re.I)
_QUARTER_ENDED_RE = re.compile(
    r"quarter\s+ended\s+([A-Za-z]+)\s+\d{1,2},?\s+(\d{4})",
    re.I,
)
_MONTH_YEAR_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|"
    r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|"
    r"Oct|Nov|Dec)\.?\s+(?:\d{1,2},?\s+)?(\d{4})\b",
    re.I,
)
_FY_RANGE_RE = re.compile(r"FY\s*(\d{4})\s*[-–/]\s*(\d{2,4})", re.I)

_MONTHS = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

_TYPE_RANK = {
    DOC_INVESTOR_PRESENTATION: 0,
    DOC_FINANCIAL_RESULTS: 1,
    DOC_ANNUAL_REPORT: 2,
    DOC_PRESS_RELEASE: 3,
    DOC_EARNINGS_CALL: 4,
    DOC_OTHER: 5,
}

_BOT_MARKERS = (
    "just a moment",
    "checking your browser",
    "g-recaptcha",
    "cf-challenge",
    "perfdrive",
    "radware",
    "botmanager",
    "verify you are a human",
    "attention required",
    "enable javascript and cookies to continue",
)


@dataclass(frozen=True)
class BankDocument:
    ticker: str
    title: str
    url: str
    document_type: str
    period: str | None = None
    source: str = SOURCE_TYPE_OFFICIAL_IR


@dataclass(frozen=True)
class SourceFetch:
    url: str
    ok: bool
    status_code: int | None = None
    error: str | None = None


@dataclass
class BankDiscoveryResult:
    ticker: str
    documents: list[BankDocument] = field(default_factory=list)
    sources: list[SourceFetch] = field(default_factory=list)
    error: str | None = None


def extract_period(text: str) -> str | None:
    blob = text or ""
    m = _QUARTER_FY_RE.search(blob)
    if m:
        return f"Q{m.group(1)} FY{_fy_yy(m.group(2))}"

    m = _QUARTER_ENDED_RE.search(blob)
    if m:
        parsed = _from_month_year(m.group(1), int(m.group(2)))
        if parsed:
            return parsed

    m = _MONTH_YEAR_RE.search(blob)
    if m:
        parsed = _from_month_year(m.group(1), int(m.group(2)))
        if parsed:
            return parsed

    m = _FY_RANGE_RE.search(blob)
    if m:
        start = m.group(1)
        end = m.group(2)
        if len(end) == 4:
            end = end[-2:]
        return f"FY {start}-{end}"
    return None


def classify_document(title: str, url: str) -> str:
    blob = _signal_text(title, url)
    if _EARNINGS_CALL_RE.search(blob):
        return DOC_EARNINGS_CALL
    if _ANNUAL_REPORT_RE.search(blob):
        return DOC_ANNUAL_REPORT
    if _PRESS_RELEASE_RE.search(blob):
        return DOC_PRESS_RELEASE
    if _EXCLUDED_RE.search(blob):
        return DOC_OTHER
    if _PRESENTATION_RE.search(blob):
        return DOC_INVESTOR_PRESENTATION
    if _RESULTS_RE.search(blob):
        return DOC_FINANCIAL_RESULTS
    return DOC_OTHER


def _signal_text(title: str, url: str) -> str:
    return re.sub(r"[-_]+", " ", f"{title} {url}")


def parse_bank_document_links(
    html: str,
    base_url: str,
    ticker: str,
) -> list[BankDocument]:
    if not (html or "").strip():
        return []
    try:
        tree = lxml_html.fromstring(html)
    except Exception:
        return []

    source = get_bank_source(ticker)
    allowed = _allowed_hosts(source, base_url)
    skip = _landing_urls(source, base_url)
    key = (source.ticker if source else (ticker or "").strip().upper())

    docs: list[BankDocument] = []
    for node in tree.xpath("//a[@href]"):
        href = (node.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        url = urljoin(base_url, href).split("#", 1)[0]
        if not _is_official_url(url, allowed):
            continue
        if _canonical_url(url) in skip:
            continue
        title = _visible_title(node, url)
        if not _is_candidate(title, url):
            continue
        docs.append(
            BankDocument(
                ticker=key,
                title=title,
                url=url,
                document_type=classify_document(title, url),
                period=extract_period(f"{title} {url}"),
                source=SOURCE_TYPE_OFFICIAL_IR,
            )
        )
    return docs


def deduplicate_documents(docs: list[BankDocument]) -> list[BankDocument]:
    seen: set[str] = set()
    unique: list[BankDocument] = []
    for doc in docs:
        if doc.url in seen:
            continue
        seen.add(doc.url)
        unique.append(doc)
    unique.sort(key=_document_sort_key)
    return unique


def discover_bank_documents(
    ticker: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> BankDiscoveryResult:
    source = get_bank_source(ticker)
    if source is None:
        return BankDiscoveryResult(
            ticker=(ticker or "").strip().upper(),
            error="unsupported_ticker",
        )

    documents: list[BankDocument] = []
    fetches: list[SourceFetch] = []
    for url in _source_urls(source):
        fetch, page = _fetch_html(url, timeout)
        fetches.append(fetch)
        if not fetch.ok or not page:
            continue
        documents.extend(parse_bank_document_links(page, url, source.ticker))

    return BankDiscoveryResult(
        ticker=source.ticker,
        documents=deduplicate_documents(documents),
        sources=fetches,
    )


def _source_urls(source: BankSource) -> list[str]:
    urls: list[str] = []
    for url in (
        source.investor_relations_url,
        source.financial_results_url,
        source.investor_presentations_url,
    ):
        if url and url not in urls:
            urls.append(url)
    return urls


def _fetch_html(url: str, timeout: int) -> tuple[SourceFetch, str]:
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": UA},
            allow_redirects=True,
        )
        text = resp.text or ""
        status = resp.status_code
        if status >= 400 or _is_bot_protected(text, status):
            return (
                SourceFetch(
                    url=url,
                    ok=False,
                    status_code=status,
                    error="unavailable",
                ),
                "",
            )
        return SourceFetch(url=url, ok=True, status_code=status), text
    except Exception as exc:
        log.warning("Could not fetch bank IR page %s: %s", url, exc)
        return SourceFetch(url=url, ok=False, error="unavailable"), ""


def _is_bot_protected(text: str, status: int) -> bool:
    if status in {401, 403, 429, 503}:
        return True
    blob = (text or "").lower()
    return any(marker in blob for marker in _BOT_MARKERS)


def _allowed_hosts(source: BankSource | None, base_url: str) -> set[str]:
    hosts: set[str] = set()
    urls = [base_url]
    if source:
        urls.extend(_source_urls(source))
    for url in urls:
        host = urlparse(url).netloc.lower()
        if not host:
            continue
        hosts.add(host)
        if host.startswith("www."):
            hosts.add(host[4:])
        else:
            hosts.add(f"www.{host}")
    return hosts


def _landing_urls(source: BankSource | None, base_url: str) -> set[str]:
    urls = {_canonical_url(base_url)}
    if source:
        for url in _source_urls(source):
            urls.add(_canonical_url(url))
    return urls


def _is_official_url(url: str, allowed_hosts: set[str]) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    return parsed.netloc.lower() in allowed_hosts


def _canonical_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"


def _visible_title(node: object, url: str) -> str:
    raw = node.text_content() if hasattr(node, "text_content") else ""
    title = " ".join((raw or "").split())
    if title:
        return title
    name = unquote(urlparse(url).path.rsplit("/", 1)[-1])
    return name or url


def _is_candidate(title: str, url: str) -> bool:
    blob = _signal_text(title, url)
    if (
        _PRESENTATION_RE.search(blob)
        or _RESULTS_RE.search(blob)
        or _EARNINGS_CALL_RE.search(blob)
        or _ANNUAL_REPORT_RE.search(blob)
        or _PRESS_RELEASE_RE.search(blob)
    ):
        return True
    path = urlparse(url).path.lower()
    return path.endswith(_DOCUMENT_SUFFIXES)


def _fy_yy(raw: str) -> str:
    year = int(raw)
    if year >= 100:
        year = year % 100
    return f"{year:02d}"


def _from_month_year(month_name: str, year: int) -> str | None:
    month = _MONTHS.get(month_name.lower())
    if not month:
        return None
    if month >= 4:
        fy_end = year + 1
        quarter = 1 if month <= 6 else 2 if month <= 9 else 3
    else:
        fy_end = year
        quarter = 4
    return f"Q{quarter} FY{_fy_yy(str(fy_end))}"


def _period_sort_parts(period: str | None) -> tuple[int, int]:
    if not period:
        return (0, -1)
    m = _QUARTER_FY_RE.fullmatch(period.strip())
    if m:
        return (2000 + int(_fy_yy(m.group(2))), int(m.group(1)))
    m = _FY_RANGE_RE.search(period)
    if m:
        end = m.group(2)
        fy_end = int(end) if len(end) == 4 else 2000 + int(end)
        return (fy_end, 0)
    return (0, -1)


def _document_sort_key(doc: BankDocument) -> tuple:
    fy, quarter = _period_sort_parts(doc.period)
    return (
        -fy,
        -quarter,
        _TYPE_RANK.get(doc.document_type, 9),
        doc.url,
        doc.title,
    )
