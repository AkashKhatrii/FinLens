"""Hybrid bank KPI pipeline: mocked AI, deterministic validation. No live AI."""
from __future__ import annotations

import unittest

from app.providers.bank_documents import BankDocument
from app.providers.bank_kpi import (
    normalize_metric_name,
    parse_percent,
    select_metric_candidate,
    validate_ai_candidates,
)
from app.providers.bank_kpi_extractor import (
    extract_bank_metrics_from_pages,
    extract_bank_metrics_from_text,
    select_candidate_pages,
)
from app.providers.bank_metrics import (
    EXTRACTION_FAILED,
    EXTRACTION_OK,
    EXTRACTION_PARTIAL,
    RawFact,
)
from app.providers.pdf_text import PdfPage


DOC = BankDocument(
    ticker="HDFCBANK",
    title="Q1FY27 Earnings Presentation",
    url="https://www.hdfc.bank.in/content/IR/q1fy27-earnings-presentation.pdf",
    document_type="investor_presentation",
    period="Q1 FY27",
    source="official_ir",
)

MESSY_KPI_PAGE = """
HDFC Bank Presentation Q1 FY2027
Key performance metrics for Q1 FY27
Deposits; average YoY 13.3% ; EOP YoY 14.7%
Gross Advances; average YoY 13.4% ; EOP YoY 15.4%
Asset quality continues to remain stable; GNPA ratio at 1.17%; ex-agri at 0.91%
PAT for the quarter; RoA of 1.85%; RoE of 13.8%; Standalone EPS
Key financial parameters for Q1 FY27
Net interest margin (NIM) of 3.26%
Core cost-to-income ratio of 39.2%
Gross NPA at 1.17%, ex-agri 0.91%
Return on assets of 1.85%
Capital adequacy ratio at 19.6%
of which CET1 at 17.4%
Standalone Indian GAAP figures
CASA ratio 38% 38% 35% 34% 34% 32%
Particulars Sep'23 Mar'24 Mar'25 Dec'25 Mar'26 Jun'26
"""

COVER_PAGE = "Board of directors and safe harbour statement"


def _candidate(**kwargs):
    payload = {
        "metric": "gnpa",
        "value": 1.17,
        "unit": "percent",
        "period": "Q1 FY27",
        "basis": "point_in_time",
        "scope": "standalone",
        "evidence": "GNPA ratio at 1.17%",
        "page": 2,
        "confidence": 0.95,
        "raw_label": "GNPA ratio",
    }
    payload.update(kwargs)
    return payload


def _pages():
    return [
        PdfPage(number=1, text=COVER_PAGE),
        PdfPage(number=2, text=MESSY_KPI_PAGE),
    ]


class TestNormalizationHelpers(unittest.TestCase):
    def test_percent_is_percentage_points_not_a_fraction(self):
        self.assertEqual(parse_percent("1.42%"), (1.42, "%"))
        self.assertEqual(parse_percent("1.42 %"), (1.42, "%"))
        self.assertIsNone(parse_percent("n.a."))
        self.assertIsNone(parse_percent("—"))
        self.assertIsNone(parse_percent("abc%"))

    def test_extraction_prompt_is_not_the_research_prompt(self):
        from app.ai.bank_kpi_extraction import BANK_KPI_SYSTEM_PROMPT
        from app.ai.prompts import SYSTEM_PROMPT

        self.assertNotEqual(BANK_KPI_SYSTEM_PROMPT, SYSTEM_PROMPT)
        self.assertNotIn("senior equity research analyst", BANK_KPI_SYSTEM_PROMPT.lower())
        self.assertIn("do not infer", BANK_KPI_SYSTEM_PROMPT.lower())

    def test_metric_name_normalization(self):
        self.assertEqual(normalize_metric_name("Gross NPA"), "gnpa")
        self.assertEqual(normalize_metric_name("GNPA"), "gnpa")
        self.assertEqual(normalize_metric_name("Net NPA"), "nnpa")
        self.assertEqual(normalize_metric_name("Net Interest Margin"), "nim")
        self.assertEqual(normalize_metric_name("Advances growth"), "loan_growth")
        self.assertEqual(normalize_metric_name("CRAR"), "car")
        self.assertIsNone(normalize_metric_name("Random footnote"))
        self.assertIsNone(normalize_metric_name("NPA"))


class TestValidateAiCandidates(unittest.TestCase):
    def test_valid_candidate_keeps_percent_points_and_provenance(self):
        result = validate_ai_candidates(
            {"candidates": [_candidate()]},
            pages=_pages(),
            target_period="Q1 FY27",
        )
        self.assertEqual(len(result.facts), 1)
        fact = result.facts[0]
        self.assertEqual(fact.key, "gnpa")
        self.assertEqual(fact.value, 1.17)
        self.assertEqual(fact.unit, "%")
        self.assertEqual(fact.period, "Q1 FY27")
        self.assertEqual(fact.comparison, "point_in_time")
        self.assertEqual(fact.consolidation, "standalone")
        self.assertEqual(fact.page, 2)
        self.assertEqual(fact.excerpt, "GNPA ratio at 1.17%")
        self.assertEqual(fact.confidence, 0.95)
        self.assertFalse(result.rejected)

    def test_invalid_metric_name_is_rejected(self):
        result = validate_ai_candidates(
            {"candidates": [_candidate(metric="magic_ratio", evidence="magic_ratio 1.17%")]},
            pages=_pages(),
            target_period="Q1 FY27",
        )
        self.assertEqual(result.facts, [])
        self.assertTrue(any("metric" in row.lower() for row in result.rejected))

    def test_non_numeric_value_is_rejected(self):
        result = validate_ai_candidates(
            {"candidates": [_candidate(value="about 1.17")]},
            pages=_pages(),
            target_period="Q1 FY27",
        )
        self.assertEqual(result.facts, [])

    def test_confidence_out_of_range_is_rejected(self):
        result = validate_ai_candidates(
            {"candidates": [_candidate(confidence=1.5)]},
            pages=_pages(),
            target_period="Q1 FY27",
        )
        self.assertEqual(result.facts, [])

    def test_missing_evidence_is_rejected(self):
        result = validate_ai_candidates(
            {"candidates": [_candidate(evidence="")]},
            pages=_pages(),
            target_period="Q1 FY27",
        )
        self.assertEqual(result.facts, [])

    def test_invented_page_is_rejected(self):
        result = validate_ai_candidates(
            {"candidates": [_candidate(page=99)]},
            pages=_pages(),
            target_period="Q1 FY27",
        )
        self.assertEqual(result.facts, [])

    def test_unknown_period_is_allowed(self):
        result = validate_ai_candidates(
            {"candidates": [_candidate(period=None)]},
            pages=_pages(),
            target_period="Q1 FY27",
        )
        self.assertEqual(len(result.facts), 1)
        self.assertIsNone(result.facts[0].period)

    def test_abbreviated_month_year_maps_to_finlens_period(self):
        from app.providers.bank_kpi import normalize_period_label

        self.assertEqual(normalize_period_label("Jun'26"), "Q1 FY27")
        self.assertEqual(normalize_period_label("Mar'26"), "Q4 FY26")

    def test_combined_upgrades_and_recoveries_are_rejected(self):
        result = validate_ai_candidates(
            {"candidates": [_candidate(
                metric="recoveries",
                value=40,
                unit="₹ bn",
                evidence="Slippages Upgrades & Recoveries Write offs 40",
                raw_label="Upgrades & Recoveries",
            )]},
            pages=_pages(),
            target_period="Q1 FY27",
        )
        self.assertEqual(result.facts, [])
        self.assertTrue(any("combined" in row.lower() for row in result.rejected))

    def test_malformed_payload_has_no_facts(self):
        result = validate_ai_candidates(
            {"gnpa": 1.36},
            pages=_pages(),
            target_period="Q1 FY27",
        )
        self.assertEqual(result.facts, [])
        self.assertTrue(result.malformed)

    def test_yoy_growth_is_not_a_stock_ratio(self):
        result = validate_ai_candidates(
            {"candidates": [
                _candidate(
                    metric="nii_growth",
                    value=10,
                    evidence="NII grew 10% YoY",
                    basis="yoy",
                    raw_label="NII growth",
                )
            ]},
            pages=_pages(),
            target_period="Q1 FY27",
        )
        self.assertEqual(result.facts[0].key, "nii_growth")
        self.assertEqual(result.facts[0].comparison, "yoy")
        self.assertEqual(result.facts[0].value, 10)


class TestCandidateSelection(unittest.TestCase):
    def test_current_period_beats_prior_period(self):
        facts = [
            RawFact(key="gnpa", raw_label="Gross NPA", value=1.42, unit="%",
                    period="Q4 FY26", comparison="point_in_time",
                    excerpt="Gross NPA 1.42% in Q4 FY26"),
            RawFact(key="gnpa", raw_label="Gross NPA", value=1.17, unit="%",
                    period="Q1 FY27", comparison="point_in_time",
                    excerpt="Gross NPA 1.17% in Q1 FY27"),
        ]
        chosen = select_metric_candidate(facts, "gnpa", target_period="Q1 FY27")
        self.assertEqual(chosen.value, 1.17)

    def test_point_in_time_beats_yoy_for_stock_ratios(self):
        facts = [
            RawFact(key="gnpa", raw_label="GNPA", value=0.12, unit="%",
                    period="Q1 FY27", comparison="yoy", excerpt="GNPA 0.12% YoY"),
            RawFact(key="gnpa", raw_label="Gross NPA", value=1.17, unit="%",
                    period="Q1 FY27", comparison="point_in_time",
                    excerpt="Gross NPA 1.17%"),
        ]
        chosen = select_metric_candidate(facts, "gnpa", target_period="Q1 FY27")
        self.assertEqual(chosen.value, 1.17)
        self.assertEqual(chosen.comparison, "point_in_time")

    def test_equal_candidates_are_ambiguous(self):
        facts = [
            RawFact(key="gnpa", raw_label="GNPA", value=1.17, unit="%",
                    period="Q1 FY27", comparison="point_in_time", excerpt="GNPA 1.17%"),
            RawFact(key="gnpa", raw_label="Gross NPA", value=1.24, unit="%",
                    period="Q1 FY27", comparison="point_in_time", excerpt="Gross NPA 1.24%"),
        ]
        self.assertIsNone(select_metric_candidate(facts, "gnpa", target_period="Q1 FY27"))

    def test_duplicate_identical_values_are_not_ambiguous(self):
        facts = [
            RawFact(key="roe", raw_label="RoE", value=13.8, unit="%",
                    period="Q1 FY27", comparison="point_in_time",
                    excerpt="RoE of 13.8%", page=2, confidence=0.95),
            RawFact(key="roe", raw_label="Return on equity", value=13.8, unit="%",
                    period="Q1 FY27", comparison="point_in_time",
                    excerpt="Return on equity of 13.8%", page=3, confidence=0.90),
        ]
        chosen = select_metric_candidate(facts, "roe", target_period="Q1 FY27")
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.value, 13.8)

    def test_standalone_and_consolidated_same_rank_are_ambiguous(self):
        facts = [
            RawFact(key="roa", raw_label="RoA", value=1.85, unit="%",
                    period="Q1 FY27", comparison="point_in_time",
                    consolidation="standalone", excerpt="RoA of 1.85%"),
            RawFact(key="roa", raw_label="RoA", value=1.90, unit="%",
                    period="Q1 FY27", comparison="point_in_time",
                    consolidation="consolidated", excerpt="RoA of 1.90%"),
        ]
        self.assertIsNone(select_metric_candidate(facts, "roa", target_period="Q1 FY27"))


class TestPipelineWithMockedAi(unittest.TestCase):
    def test_messy_fixture_through_mocked_ai(self):
        def fake_ai(system, user):
            self.assertIn("do not infer", system.lower())
            self.assertIn("--- Page 2 ---", user)
            self.assertNotIn(COVER_PAGE, user)
            return {"candidates": [
                _candidate(),
                _candidate(metric="nim", value=3.26, evidence="Net interest margin (NIM) of 3.26%",
                           raw_label="NIM"),
                _candidate(metric="roa", value=1.85, evidence="RoA of 1.85%", raw_label="RoA"),
                _candidate(metric="roe", value=13.8, evidence="RoE of 13.8%", raw_label="RoE"),
                _candidate(metric="car", value=19.6, evidence="Capital adequacy ratio at 19.6%",
                           raw_label="Capital adequacy ratio"),
                _candidate(metric="cet1", value=17.4, evidence="CET1 at 17.4%", raw_label="CET1"),
                _candidate(metric="cost_income", value=39.2,
                           evidence="Core cost-to-income ratio of 39.2%",
                           raw_label="cost-to-income"),
                _candidate(metric="loan_growth", value=15.4, basis="yoy",
                           evidence="Gross Advances; EOP YoY 15.4%",
                           raw_label="Gross Advances EOP YoY"),
                _candidate(metric="deposit_growth", value=14.7, basis="yoy",
                           evidence="Deposits; EOP YoY 14.7%",
                           raw_label="Deposits EOP YoY"),
                _candidate(metric="casa", value=32, evidence="CASA ratio ... Jun'26 32%",
                           raw_label="CASA ratio"),
            ]}

        pages = _pages()
        self.assertEqual([page.number for page in select_candidate_pages(pages)], [2])
        metrics = extract_bank_metrics_from_pages(
            pages, DOC, target_period="Q1 FY27", ai_complete=fake_ai,
        )
        self.assertEqual(metrics.status, EXTRACTION_OK)
        self.assertIsNone(metrics.error)
        self.assertEqual(metrics.gnpa.value, 1.17)
        self.assertEqual(metrics.gnpa.unit, "%")
        self.assertEqual(metrics.gnpa.period, "Q1 FY27")
        self.assertEqual(metrics.gnpa.comparison, "point_in_time")
        self.assertEqual(metrics.gnpa.consolidation, "standalone")
        self.assertEqual(metrics.gnpa.provenance.page, 2)
        self.assertIn("1.17", metrics.gnpa.provenance.excerpt)
        self.assertEqual(metrics.gnpa.provenance.source_url, DOC.url)
        self.assertEqual(metrics.nim.value, 3.26)
        self.assertEqual(metrics.loan_growth.comparison, "yoy")
        self.assertEqual(metrics.casa.value, 32)
        self.assertIsNone(metrics.slippages)
        self.assertIsNone(metrics.nnpa)

    def test_missing_metrics_stay_none(self):
        metrics = extract_bank_metrics_from_text(
            "No bank ratios here.",
            DOC,
            target_period="Q1 FY27",
            ai_complete=lambda system, user: {"candidates": []},
        )
        self.assertEqual(metrics.status, EXTRACTION_OK)
        self.assertIsNone(metrics.gnpa)
        self.assertIsNone(metrics.slippages)

    def test_ai_failure_does_not_invent_values(self):
        metrics = extract_bank_metrics_from_pages(
            _pages(),
            DOC,
            target_period="Q1 FY27",
            ai_complete=lambda system, user: {"error": "The AI provider timed out."},
        )
        self.assertEqual(metrics.status, EXTRACTION_FAILED)
        self.assertIn("timed out", metrics.error.lower())
        self.assertIsNone(metrics.gnpa)
        self.assertEqual(metrics.candidate_page_numbers, [2])

    def test_malformed_ai_output_does_not_become_metrics(self):
        metrics = extract_bank_metrics_from_pages(
            _pages(),
            DOC,
            target_period="Q1 FY27",
            ai_complete=lambda system, user: {"gnpa": 1.36},
        )
        self.assertEqual(metrics.status, EXTRACTION_FAILED)
        self.assertIsNone(metrics.gnpa)

    def test_previous_period_is_not_selected_as_current_gnpa(self):
        def fake_ai(system, user):
            return {"candidates": [
                _candidate(value=1.42, period="Q4 FY26",
                           evidence="Gross NPA declined to 1.17% from 1.42%"),
                _candidate(value=1.17, period="Q1 FY27",
                           evidence="Gross NPA declined to 1.17% from 1.42%"),
            ]}

        metrics = extract_bank_metrics_from_pages(
            _pages(), DOC, target_period="Q1 FY27", ai_complete=fake_ai,
        )
        self.assertEqual(metrics.gnpa.value, 1.17)
        self.assertEqual(metrics.gnpa.period, "Q1 FY27")

    def test_ambiguous_duplicates_leave_metric_empty(self):
        def fake_ai(system, user):
            return {"candidates": [
                _candidate(value=1.17, evidence="GNPA ratio at 1.17%"),
                _candidate(value=1.24, evidence="Gross NPA 1.24%", raw_label="Gross NPA"),
            ]}

        metrics = extract_bank_metrics_from_pages(
            _pages(), DOC, target_period="Q1 FY27", ai_complete=fake_ai,
        )
        self.assertIsNone(metrics.gnpa)
        self.assertIn("gnpa", metrics.ambiguous)
        self.assertEqual(metrics.status, EXTRACTION_PARTIAL)

    def test_uncertain_flag_does_not_populate_the_metric(self):
        def fake_ai(system, user):
            return {"candidates": [_candidate(uncertain=True)]}

        metrics = extract_bank_metrics_from_pages(
            _pages(), DOC, target_period="Q1 FY27", ai_complete=fake_ai,
        )
        self.assertIsNone(metrics.gnpa)
        self.assertIn("gnpa", metrics.ambiguous)

    def test_subsidiary_candidate_is_not_used_for_the_bank(self):
        def fake_ai(system, user):
            return {"candidates": [
                _candidate(
                    metric="car",
                    value=21.3,
                    evidence="Subsidiaries update: Capital adequacy ratio at 21.3%",
                    raw_label="Capital adequacy ratio",
                )
            ]}

        metrics = extract_bank_metrics_from_pages(
            _pages(), DOC, target_period="Q1 FY27", ai_complete=fake_ai,
        )
        self.assertIsNone(metrics.car)


class TestSemanticHardening(unittest.TestCase):
    def test_loan_growth_preserves_candidates_and_selects_eop_yoy(self):
        def fake_ai(system, user):
            self.assertIn("measurement", system.lower() + user.lower())
            return {"candidates": [
                _candidate(
                    metric="loan_growth", value=13.4, basis="yoy",
                    measurement="average",
                    evidence="Gross Advances; average YoY 13.4%",
                    raw_label="Gross Advances average YoY",
                ),
                _candidate(
                    metric="loan_growth", value=15.4, basis="yoy",
                    measurement="end_of_period",
                    evidence="Gross Advances; EOP YoY 15.4%",
                    raw_label="Gross Advances EOP YoY",
                ),
                _candidate(
                    metric="loan_growth", value=3.4, basis="qoq",
                    measurement="end_of_period",
                    evidence="Gross Advances; EOP QoQ 3.4%",
                    raw_label="Gross Advances EOP QoQ",
                ),
            ]}

        metrics = extract_bank_metrics_from_pages(
            _pages(), DOC, target_period="Q1 FY27", ai_complete=fake_ai,
        )
        self.assertEqual(metrics.loan_growth.value, 15.4)
        self.assertEqual(metrics.loan_growth.comparison, "yoy")
        self.assertEqual(metrics.loan_growth.measurement, "end_of_period")
        self.assertEqual(metrics.loan_growth.resolution_reason, "preferred_yoy_eop_bank_level_headline")
        self.assertEqual(len(metrics.raw_facts), 3)
        measurements = {fact.measurement for fact in metrics.raw_facts}
        self.assertEqual(measurements, {"average", "end_of_period"})
        bases = {fact.comparison for fact in metrics.raw_facts}
        self.assertEqual(bases, {"yoy", "qoq"})
        values = sorted(fact.value for fact in metrics.raw_facts)
        self.assertEqual(values, [3.4, 13.4, 15.4])

    def test_deposit_growth_selects_eop_yoy_and_keeps_average_candidate(self):
        def fake_ai(system, user):
            return {"candidates": [
                _candidate(
                    metric="deposit_growth", value=13.3, basis="yoy",
                    measurement="average",
                    evidence="Deposits; average YoY 13.3%",
                    raw_label="Deposits average YoY",
                ),
                _candidate(
                    metric="deposit_growth", value=14.7, basis="yoy",
                    measurement="end_of_period",
                    evidence="Deposits; EOP YoY 14.7%",
                    raw_label="Deposits EOP YoY",
                ),
            ]}

        metrics = extract_bank_metrics_from_pages(
            _pages(), DOC, target_period="Q1 FY27", ai_complete=fake_ai,
        )
        self.assertEqual(metrics.deposit_growth.value, 14.7)
        self.assertEqual(metrics.deposit_growth.comparison, "yoy")
        self.assertEqual(metrics.deposit_growth.measurement, "end_of_period")
        self.assertEqual(
            sorted(fact.value for fact in metrics.raw_facts),
            [13.3, 14.7],
        )

    def test_loan_growth_yoy_is_canonical_and_qoq_stays_a_candidate(self):
        def fake_ai(system, user):
            return {"candidates": [
                _candidate(
                    metric="loan_growth", value=15.4, basis="yoy",
                    measurement="end_of_period",
                    evidence="Gross Advances EOP YoY 15.4%",
                    raw_label="EOP YoY",
                ),
                _candidate(
                    metric="loan_growth", value=3.4, basis="qoq",
                    measurement="end_of_period",
                    evidence="Gross Advances EOP QoQ 3.4%",
                    raw_label="EOP QoQ",
                ),
            ]}

        metrics = extract_bank_metrics_from_pages(
            _pages(), DOC, target_period="Q1 FY27", ai_complete=fake_ai,
        )
        self.assertEqual(metrics.loan_growth.value, 15.4)
        self.assertEqual(metrics.loan_growth.comparison, "yoy")
        self.assertEqual(metrics.loan_growth.measurement, "end_of_period")
        self.assertEqual(
            sorted(fact.value for fact in metrics.raw_facts if fact.key == "loan_growth"),
            [3.4, 15.4],
        )

    def test_gnpa_ex_agri_is_not_the_headline_gnpa(self):
        def fake_ai(system, user):
            return {"candidates": [
                _candidate(
                    value=1.17,
                    evidence="GNPA ratio at 1.17%; ex-agri at 0.91%",
                    raw_label="GNPA ratio",
                ),
                _candidate(
                    value=0.91,
                    evidence="GNPA ratio at 1.17%; ex-agri at 0.91%",
                    raw_label="GNPA ex-agri",
                ),
            ]}

        metrics = extract_bank_metrics_from_pages(
            _pages(), DOC, target_period="Q1 FY27", ai_complete=fake_ai,
        )
        self.assertEqual(metrics.gnpa.value, 1.17)
        self.assertNotEqual(metrics.gnpa.value, 0.91)
        series = {fact.series for fact in metrics.raw_facts}
        self.assertIn("ex_agri", series)

    def test_specific_pcr_is_not_headline_pcr(self):
        def fake_ai(system, user):
            return {"candidates": [
                _candidate(
                    metric="pcr",
                    value=66,
                    evidence="Specific PCR = 66%",
                    raw_label="Specific PCR",
                ),
            ]}

        metrics = extract_bank_metrics_from_pages(
            _pages(), DOC, target_period="Q1 FY27", ai_complete=fake_ai,
        )
        self.assertIsNone(metrics.pcr)
        self.assertEqual(metrics.raw_facts[0].value, 66)
        self.assertEqual(metrics.raw_facts[0].series, "specific")

    def test_compared_with_prior_is_not_current_gnpa(self):
        def fake_ai(system, user):
            return {"candidates": [
                _candidate(
                    value=1.17,
                    evidence="GNPA 1.17%, compared with 1.24%",
                    raw_label="GNPA",
                ),
                _candidate(
                    value=1.24,
                    evidence="GNPA 1.17%, compared with 1.24%",
                    raw_label="GNPA",
                ),
            ]}

        metrics = extract_bank_metrics_from_pages(
            _pages(), DOC, target_period="Q1 FY27", ai_complete=fake_ai,
        )
        self.assertEqual(metrics.gnpa.value, 1.17)
        self.assertEqual(metrics.gnpa.comparison, "point_in_time")

    def test_nii_growth_is_not_confused_with_nii_stock(self):
        def fake_ai(system, user):
            return {"candidates": [
                _candidate(
                    metric="nii_growth",
                    value=6.7,
                    basis="yoy",
                    evidence="NII grew 6.7% YoY",
                    raw_label="NII growth",
                ),
            ]}

        metrics = extract_bank_metrics_from_pages(
            _pages(), DOC, target_period="Q1 FY27", ai_complete=fake_ai,
        )
        self.assertEqual(metrics.nii_growth.value, 6.7)
        self.assertEqual(metrics.nii_growth.comparison, "yoy")
        self.assertIsNone(metrics.nim)

    def test_writeoffs_and_recoveries_combined_are_not_recoveries(self):
        result = validate_ai_candidates(
            {"candidates": [_candidate(
                metric="recoveries",
                value=63,
                unit="₹ bn",
                evidence="Write-offs and recoveries 63",
                raw_label="Write-offs and recoveries",
            )]},
            pages=_pages(),
            target_period="Q1 FY27",
        )
        self.assertEqual(result.facts, [])

    def test_credit_cost_net_of_recoveries_is_not_headline(self):
        def fake_ai(system, user):
            return {"candidates": [
                _candidate(
                    metric="credit_cost",
                    value=29,
                    unit="bps",
                    evidence="Credit cost (net of recoveries) 29 bps",
                    raw_label="Credit cost net of recoveries",
                ),
            ]}

        metrics = extract_bank_metrics_from_pages(
            _pages(), DOC, target_period="Q1 FY27", ai_complete=fake_ai,
        )
        self.assertIsNone(metrics.credit_cost)
        self.assertEqual(metrics.raw_facts[0].series, "net_of_recoveries")

    def test_standalone_and_consolidated_are_preserved_not_overwritten(self):
        def fake_ai(system, user):
            return {"candidates": [
                _candidate(
                    metric="roa", value=1.85, scope="standalone",
                    evidence="Standalone RoA of 1.85%", raw_label="RoA",
                ),
                _candidate(
                    metric="roa", value=1.90, scope="consolidated",
                    evidence="Consolidated RoA of 1.90%", raw_label="RoA",
                ),
            ]}

        metrics = extract_bank_metrics_from_pages(
            _pages(), DOC, target_period="Q1 FY27", ai_complete=fake_ai,
        )
        self.assertIsNone(metrics.roa)
        scopes = {fact.consolidation for fact in metrics.ambiguous["roa"]}
        self.assertEqual(scopes, {"standalone", "consolidated"})

    def test_single_eop_growth_keeps_measurement(self):
        def fake_ai(system, user):
            return {"candidates": [
                _candidate(
                    metric="loan_growth", value=15.4, basis="yoy",
                    measurement="end_of_period",
                    evidence="Gross Advances; EOP YoY 15.4%",
                    raw_label="Gross Advances EOP YoY",
                ),
            ]}

        metrics = extract_bank_metrics_from_pages(
            _pages(), DOC, target_period="Q1 FY27", ai_complete=fake_ai,
        )
        self.assertEqual(metrics.loan_growth.value, 15.4)
        self.assertEqual(metrics.loan_growth.comparison, "yoy")
        self.assertEqual(metrics.loan_growth.measurement, "end_of_period")


if __name__ == "__main__":
    unittest.main()
