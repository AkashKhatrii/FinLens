"""Bank IR document discovery: parse/classify only, no live websites."""
from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

from app.providers.bank_documents import (
    BankDiscoveryResult,
    BankDocument,
    classify_document,
    deduplicate_documents,
    discover_bank_documents,
    extract_period,
    parse_bank_document_links,
)
from app.providers.bank_sources import get_bank_source


HDFC_BASE = "https://www.hdfc.bank.in/about-us/investor-relations"

HDFC_HTML = """
<html>
  <body>
    <h1>Investor Relations</h1>
    <a href="/content/IR/Q1FY27-Investor-Presentation.pdf">
      Investor Presentation Q1 FY27
    </a>
    <a href="/content/IR/Q1FY27-Financial-Results.pdf">
      Financial Results Q1 FY27
    </a>
    <a href="/content/IR/Q4FY26-Investor-Presentation.pdf">
      Analyst Presentation Q4 FY26
    </a>
    <a href="/content/IR/Q2FY26-Financial-Results.pdf">
      Quarterly Results Q2 FY26
    </a>
    <a href="/content/IR/Q1FY27-Investor-Presentation.pdf">
      Investor Presentation Q1 FY27
    </a>
    <a href="/content/IR/Integrated-Annual-Report-2025-26.pdf">
      Integrated Annual Report FY 2025-26
    </a>
    <a href="/content/IR/shareholding-pattern.pdf">Shareholding Pattern</a>
    <a href="https://www.moneycontrol.com/hdfcbank">HDFC Bank News</a>
    <a href="https://www.bseindia.com/corporates/anndet_new.aspx?newsid=1">
      BSE filing
    </a>
    <a href="/personal/about-us">About Us</a>
    <a href="https://www.hdfc.bank.in/about-us/investor-relations/financial-results">
      Financial Results archive
    </a>
  </body>
</html>
"""


def _ok_response(url: str, text: str, status: int = 200):
    class _Resp:
        def __init__(self) -> None:
            self.url = url
            self.text = text
            self.status_code = status
            self.headers = {"Content-Type": "text/html"}

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"http {self.status_code}")

    return _Resp()


class TestExtractPeriod(unittest.TestCase):
    def test_quarter_fy_abbreviations(self):
        self.assertEqual(extract_period("Investor Presentation Q1 FY27"), "Q1 FY27")
        self.assertEqual(extract_period("Q2 FY26 results"), "Q2 FY26")
        self.assertEqual(extract_period("Q4 FY26"), "Q4 FY26")
        self.assertEqual(extract_period("Q1FY27-Investor-Presentation.pdf"), "Q1 FY27")
        self.assertEqual(extract_period("Results Q1 FY 2027"), "Q1 FY27")

    def test_quarter_ended_and_month_year(self):
        self.assertEqual(
            extract_period("Financial results for the quarter ended June 30, 2026"),
            "Q1 FY27",
        )
        self.assertEqual(extract_period("June 2026"), "Q1 FY27")
        self.assertEqual(extract_period("General Investor PPT June 30 2026"), "Q1 FY27")
        self.assertEqual(extract_period("March 2026"), "Q4 FY26")

    def test_fiscal_year_range(self):
        self.assertEqual(extract_period("Annual Report FY 2025-26"), "FY 2025-26")

    def test_does_not_invent_period(self):
        self.assertIsNone(extract_period("Investor Presentation"))
        self.assertIsNone(extract_period("Q1 results"))
        self.assertIsNone(extract_period("shareholding-pattern.pdf"))


class TestClassifyDocument(unittest.TestCase):
    def test_presentation_phrases(self):
        self.assertEqual(
            classify_document("Investor Presentation Q1 FY27", "https://bank.example/a.pdf"),
            "investor_presentation",
        )
        self.assertEqual(
            classify_document("Analyst Presentation", "https://bank.example/a.pdf"),
            "investor_presentation",
        )
        self.assertEqual(
            classify_document("Results Presentation Q4 FY26", "https://bank.example/a.pdf"),
            "investor_presentation",
        )

    def test_financial_results_phrases(self):
        self.assertEqual(
            classify_document("Financial Results Q1 FY27", "https://bank.example/a.pdf"),
            "financial_results",
        )
        self.assertEqual(
            classify_document("Quarterly Results", "https://bank.example/q.pdf"),
            "financial_results",
        )

    def test_pdf_alone_is_not_a_presentation(self):
        self.assertEqual(
            classify_document("Shareholding Pattern", "https://bank.example/sp.pdf"),
            "other",
        )
        self.assertEqual(
            classify_document("Code of Conduct", "https://bank.example/policy.pdf"),
            "other",
        )
        self.assertEqual(
            classify_document("Press Release Q1 FY27", "https://bank.example/pr.pdf"),
            "press_release",
        )

    def test_real_world_titles_are_not_confused_with_primary_bank_docs(self):
        self.assertEqual(
            classify_document(
                "AMC Investor Presentation for Quarter Ended June 30 2026",
                "https://bank.example/amc-investor-presentation.pdf",
            ),
            "other",
        )
        self.assertEqual(
            classify_document(
                "General Investor PPT June 30 2026",
                "https://bank.example/general-investor-ppt.pdf",
            ),
            "investor_presentation",
        )
        self.assertEqual(
            classify_document(
                "Debt Investor Presentation June 2026",
                "https://bank.example/debt-investor-presentation.pdf",
            ),
            "other",
        )
        self.assertEqual(
            classify_document(
                "Q1 FY27 Earnings Call",
                "https://bank.example/quarterly-results/q1-fy27-earnings-call.pdf",
            ),
            "earnings_call",
        )
        self.assertEqual(
            classify_document(
                "Q1 FY27 Analyst Presentation",
                "https://bank.example/q1-fy27-analyst-presentation.pdf",
            ),
            "investor_presentation",
        )
        self.assertEqual(
            classify_document(
                "Q1 FY27 Financial Results",
                "https://bank.example/q1-fy27-financial-results.pdf",
            ),
            "financial_results",
        )
        self.assertEqual(
            classify_document(
                "Life Investor Presentation for Quarter Ended June 30 2026",
                "https://bank.example/life-investor-presentation-for-quarter-ended-june-30-2026.pdf",
            ),
            "other",
        )
        self.assertEqual(
            classify_document(
                "Q1 FY27 Investor Presentation",
                "https://bank.example/q1-fy27-investor-presentation.pdf",
            ),
            "investor_presentation",
        )
        self.assertEqual(
            classify_document(
                "Q1 FY27 Earnings Presentation",
                "https://bank.example/q1-fy27-earnings-presentation.pdf",
            ),
            "investor_presentation",
        )
        self.assertEqual(
            classify_document(
                "Unaudited Financial Results for the Quarter Ended 30 June 2026",
                "https://bank.example/unaudited-financial-results.pdf",
            ),
            "financial_results",
        )

    def test_earnings_presentation_is_not_financial_results(self):
        self.assertEqual(
            classify_document(
                "Q4 FY26 Earnings Presentation",
                "https://www.hdfc.bank.in/personal/about-us/investor-relations/financial-results/q4fy26-earnings-presentation.pdf",
            ),
            "investor_presentation",
        )
        self.assertEqual(
            classify_document(
                "q4fy26-earnings-presentation.pdf",
                "https://www.hdfc.bank.in/personal/about-us/investor-relations/financial-results/q4fy26-earnings-presentation.pdf",
            ),
            "investor_presentation",
        )
        self.assertEqual(
            classify_document(
                "Q4 FY26 Financial Results",
                "https://www.hdfc.bank.in/personal/about-us/investor-relations/financial-results/q4fy26-financial-results.pdf",
            ),
            "financial_results",
        )
        self.assertEqual(
            classify_document(
                "Audited Financial Results",
                "https://www.hdfc.bank.in/personal/about-us/investor-relations/financial-results/q4fy26-audited-financial-results.pdf",
            ),
            "financial_results",
        )


class TestParseLinks(unittest.TestCase):
    def test_hdfc_like_page_extracts_presentations_and_results(self):
        docs = parse_bank_document_links(HDFC_HTML, HDFC_BASE, "HDFCBANK")
        types = {(d.document_type, d.period) for d in docs}
        self.assertIn(("investor_presentation", "Q1 FY27"), types)
        self.assertIn(("financial_results", "Q1 FY27"), types)
        self.assertIn(("investor_presentation", "Q4 FY26"), types)
        self.assertIn(("financial_results", "Q2 FY26"), types)

    def test_relative_urls_become_absolute_official_urls(self):
        docs = parse_bank_document_links(HDFC_HTML, HDFC_BASE, "HDFCBANK")
        urls = {d.url for d in docs}
        self.assertIn(
            "https://www.hdfc.bank.in/content/IR/Q1FY27-Investor-Presentation.pdf",
            urls,
        )
        self.assertIn(
            "https://www.hdfc.bank.in/content/IR/Q1FY27-Financial-Results.pdf",
            urls,
        )

    def test_third_party_urls_are_rejected(self):
        docs = parse_bank_document_links(HDFC_HTML, HDFC_BASE, "HDFCBANK")
        joined = " ".join(d.url for d in docs)
        self.assertNotIn("moneycontrol.com", joined)
        self.assertNotIn("bseindia.com", joined)

    def test_nav_and_archive_landings_are_not_documents(self):
        docs = parse_bank_document_links(HDFC_HTML, HDFC_BASE, "HDFCBANK")
        titles = [d.title.lower() for d in docs]
        self.assertFalse(any("about us" in t for t in titles))
        self.assertFalse(any("archive" in t for t in titles))

    def test_irrelevant_pdfs_are_not_classified_as_results_or_presentations(self):
        docs = parse_bank_document_links(HDFC_HTML, HDFC_BASE, "HDFCBANK")
        by_title = {d.title: d for d in docs}
        self.assertEqual(by_title["Shareholding Pattern"].document_type, "other")
        annual = by_title["Integrated Annual Report FY 2025-26"]
        self.assertEqual(annual.document_type, "annual_report")

    def test_malformed_html_does_not_raise(self):
        html = "<html><a href='/Q1FY27-Investor-Presentation.pdf'>Investor Presentation Q1 FY27"
        docs = parse_bank_document_links(html, HDFC_BASE, "HDFCBANK")
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].document_type, "investor_presentation")
        garbage = parse_bank_document_links("<<<not html", HDFC_BASE, "HDFCBANK")
        self.assertEqual(garbage, [])


class TestDedupAndOrder(unittest.TestCase):
    def test_duplicate_urls_are_removed(self):
        docs = parse_bank_document_links(HDFC_HTML, HDFC_BASE, "HDFCBANK")
        unique = deduplicate_documents(docs)
        urls = [d.url for d in unique]
        self.assertEqual(len(urls), len(set(urls)))
        self.assertEqual(
            urls.count(
                "https://www.hdfc.bank.in/content/IR/Q1FY27-Investor-Presentation.pdf"
            ),
            1,
        )

    def test_deterministic_newest_then_type_order(self):
        docs = deduplicate_documents(
            parse_bank_document_links(HDFC_HTML, HDFC_BASE, "HDFCBANK")
        )
        ranked = [
            (d.period, d.document_type)
            for d in docs
            if d.document_type in {"investor_presentation", "financial_results"}
        ]
        self.assertEqual(
            ranked[:4],
            [
                ("Q1 FY27", "investor_presentation"),
                ("Q1 FY27", "financial_results"),
                ("Q4 FY26", "investor_presentation"),
                ("Q2 FY26", "financial_results"),
            ],
        )

    def test_amc_debt_and_earnings_call_do_not_outrank_bank_docs(self):
        html = """
        <html><body>
          <a href="/docs/life-investor-presentation.pdf">
            Life Investor Presentation for Quarter Ended June 30 2026
          </a>
          <a href="/docs/amc-investor-presentation.pdf">
            AMC Investor Presentation for Quarter Ended June 30 2026
          </a>
          <a href="/docs/general-investor-ppt.pdf">
            General Investor PPT June 30 2026
          </a>
          <a href="/docs/debt-investor-presentation.pdf">
            Debt Investor Presentation June 2026
          </a>
          <a href="/docs/quarterly-results/q1-fy27-earnings-call.pdf">
            Q1 FY27 Earnings Call
          </a>
          <a href="/docs/q1-fy27-analyst-presentation.pdf">
            Q1 FY27 Analyst Presentation
          </a>
          <a href="/docs/q1-fy27-financial-results.pdf">
            Q1 FY27 Financial Results
          </a>
        </body></html>
        """
        docs = deduplicate_documents(
            parse_bank_document_links(html, HDFC_BASE, "HDFCBANK")
        )
        by_title = {d.title: d for d in docs}
        self.assertEqual(
            by_title["AMC Investor Presentation for Quarter Ended June 30 2026"].document_type,
            "other",
        )
        self.assertEqual(
            by_title["Life Investor Presentation for Quarter Ended June 30 2026"].document_type,
            "other",
        )
        self.assertEqual(
            by_title["General Investor PPT June 30 2026"].document_type,
            "investor_presentation",
        )
        self.assertEqual(
            by_title["Debt Investor Presentation June 2026"].document_type,
            "other",
        )
        self.assertEqual(by_title["Q1 FY27 Earnings Call"].document_type, "earnings_call")
        self.assertEqual(
            by_title["Q1 FY27 Analyst Presentation"].document_type,
            "investor_presentation",
        )
        self.assertEqual(
            by_title["Q1 FY27 Financial Results"].document_type,
            "financial_results",
        )

        ranked = [(d.title, d.document_type) for d in docs]
        types_in_order = [dtype for _, dtype in ranked]
        self.assertEqual(types_in_order[0], "investor_presentation")
        self.assertEqual(types_in_order[1], "investor_presentation")
        self.assertEqual(types_in_order[2], "financial_results")
        self.assertEqual(types_in_order[3], "earnings_call")
        self.assertTrue(all(t == "other" for t in types_in_order[4:]))
        self.assertLess(
            types_in_order.index("investor_presentation"),
            types_in_order.index("other"),
        )
        primary_titles = [title for title, dtype in ranked if dtype == "investor_presentation"]
        self.assertEqual(
            set(primary_titles),
            {"General Investor PPT June 30 2026", "Q1 FY27 Analyst Presentation"},
        )
        self.assertNotIn("AMC Investor Presentation for Quarter Ended June 30 2026", primary_titles)
        self.assertNotIn("Life Investor Presentation for Quarter Ended June 30 2026", primary_titles)
        self.assertNotIn("Debt Investor Presentation June 2026", primary_titles)


class TestDiscoverBankDocuments(unittest.TestCase):
    def test_unknown_ticker_returns_structured_empty_result(self):
        with patch("app.providers.bank_documents.requests.get") as get:
            result = discover_bank_documents("TCS")
        get.assert_not_called()
        self.assertIsInstance(result, BankDiscoveryResult)
        self.assertEqual(result.documents, [])
        self.assertEqual(result.error, "unsupported_ticker")

    def test_discover_uses_registry_urls_and_classifies_hdfc_page(self):
        source = get_bank_source("HDFCBANK")
        fetched: list[str] = []

        def fake_get(url, **kwargs):
            fetched.append(url)
            return _ok_response(url, HDFC_HTML)

        with patch("app.providers.bank_documents.requests.get", side_effect=fake_get):
            result = discover_bank_documents("hdfcbank")

        self.assertIsNone(result.error)
        self.assertEqual(result.ticker, "HDFCBANK")
        self.assertTrue(fetched)
        self.assertTrue(all(u in {
            source.investor_relations_url,
            source.financial_results_url,
            source.investor_presentations_url,
        } for u in fetched))
        types = {d.document_type for d in result.documents}
        self.assertIn("investor_presentation", types)
        self.assertIn("financial_results", types)
        self.assertTrue(all(d.source == "official_ir" for d in result.documents))
        self.assertTrue(all(d.ticker == "HDFCBANK" for d in result.documents))
        self.assertIsInstance(result.documents[0], BankDocument)

    def test_inaccessible_source_is_reported_without_raising(self):
        def fake_get(url, **kwargs):
            raise TimeoutError("timed out")

        with patch("app.providers.bank_documents.requests.get", side_effect=fake_get):
            result = discover_bank_documents("AUBANK")

        self.assertEqual(result.documents, [])
        self.assertIsNone(result.error)
        self.assertTrue(result.sources)
        self.assertTrue(all(not s.ok for s in result.sources))
        self.assertTrue(all(s.error for s in result.sources))

    def test_bot_protected_html_is_unavailable_not_parsed(self):
        html = """
        <html><title>Just a moment...</title>
        <body>Checking your browser before accessing au.bank.in
        <div class="g-recaptcha"></div></body></html>
        """

        def fake_get(url, **kwargs):
            return _ok_response(url, html, status=403)

        with patch("app.providers.bank_documents.requests.get", side_effect=fake_get):
            result = discover_bank_documents("AUBANK")

        self.assertEqual(result.documents, [])
        self.assertTrue(all(not s.ok for s in result.sources))

    def test_helpers_do_not_touch_the_network(self):
        for fn in (
            parse_bank_document_links,
            classify_document,
            extract_period,
            deduplicate_documents,
        ):
            src = inspect.getsource(fn)
            self.assertNotIn("urlopen", src)
            self.assertNotIn("requests", src)
            self.assertNotIn("http.client", src)
            self.assertNotIn("urllib.request", src)


if __name__ == "__main__":
    unittest.main()
