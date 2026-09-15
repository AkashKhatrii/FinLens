"""Stage 3B: deterministic canonical metric resolution. No live AI."""
from __future__ import annotations

import unittest

from app.providers.bank_documents import BankDocument
from app.providers.bank_kpi_extractor import extract_bank_metrics_from_pages
from app.providers.bank_metric_canonical import resolve_canonical_metric
from app.providers.bank_metric_definitions import BANK_METRIC_DEFINITIONS
from app.providers.bank_metrics import RawFact
from app.providers.pdf_text import PdfPage


def _doc(ticker: str = "HDFCBANK") -> BankDocument:
    return BankDocument(
        ticker=ticker,
        title=f"{ticker} Investor Presentation Q1 FY27",
        url=f"https://example.bank.in/{ticker.lower()}-q1fy27.pdf",
        document_type="investor_presentation",
        period="Q1 FY27",
        source="official_ir",
    )


def _pages() -> list[PdfPage]:
    return [PdfPage(number=2, text="Key highlights for Q1 FY27 standalone")]


def _fact(key: str, value: float, **kwargs) -> RawFact:
    return RawFact(
        key=key,
        raw_label=kwargs.pop("raw_label", key),
        value=value,
        unit=kwargs.pop("unit", "%"),
        period=kwargs.pop("period", "Q1 FY27"),
        comparison=kwargs.pop("comparison", "point_in_time"),
        measurement=kwargs.pop("measurement", None),
        consolidation=kwargs.pop("consolidation", "standalone"),
        excerpt=kwargs.pop("excerpt", ""),
        page=kwargs.pop("page", 2),
        confidence=kwargs.pop("confidence", 0.9),
        uncertain=kwargs.pop("uncertain", False),
        series=kwargs.pop("series", None),
        **kwargs,
    )


def _cand(metric: str, value: float, evidence: str, **kwargs) -> dict:
    payload = {
        "metric": metric,
        "value": value,
        "unit": kwargs.pop("unit", "percent"),
        "period": kwargs.pop("period", "Q1 FY27"),
        "basis": kwargs.pop("basis", "point_in_time"),
        "scope": kwargs.pop("scope", "standalone"),
        "evidence": evidence,
        "page": kwargs.pop("page", 2),
        "confidence": kwargs.pop("confidence", 0.9),
        "raw_label": kwargs.pop("raw_label", metric),
    }
    payload.update(kwargs)
    return payload


def _run(ticker: str, candidates: list[dict]):
    return extract_bank_metrics_from_pages(
        _pages(),
        _doc(ticker),
        target_period="Q1 FY27",
        ai_complete=lambda system, user: {"candidates": candidates},
    )


def _resolve(key: str, facts: list[RawFact]):
    return resolve_canonical_metric(facts, key, target_period="Q1 FY27")


class TestDefinitionsAreDeclarative(unittest.TestCase):
    def test_every_bank_metric_has_a_definition(self):
        from app.providers.bank_metrics import BANK_METRIC_KEYS

        for key in BANK_METRIC_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, BANK_METRIC_DEFINITIONS)
                definition = BANK_METRIC_DEFINITIONS[key]
                self.assertEqual(definition.key, key)
                self.assertTrue(definition.explanation)


class TestLoanAndDepositCanonical(unittest.TestCase):
    def test_eop_yoy_beats_average_and_qoq_for_loan_growth(self):
        facts = [
            _fact("loan_growth", 13.4, comparison="yoy", measurement="average",
                  raw_label="Gross Advances average YoY",
                  excerpt="Gross Advances; average YoY 13.4%"),
            _fact("loan_growth", 15.4, comparison="yoy", measurement="end_of_period",
                  raw_label="Gross Advances EOP YoY",
                  excerpt="Gross Advances; EOP YoY 15.4%"),
            _fact("loan_growth", 3.4, comparison="qoq", measurement="end_of_period",
                  raw_label="Gross Advances EOP QoQ",
                  excerpt="Gross Advances; EOP QoQ 3.4%"),
        ]
        chosen = _resolve("loan_growth", facts)
        self.assertIsNotNone(chosen.fact)
        self.assertEqual(chosen.fact.value, 15.4)
        self.assertEqual(chosen.fact.comparison, "yoy")
        self.assertEqual(chosen.fact.measurement, "end_of_period")
        self.assertIn("eop", chosen.reason)
        self.assertIn("yoy", chosen.reason)

    def test_average_only_loan_growth_stays_null(self):
        facts = [
            _fact("loan_growth", 13.4, comparison="yoy", measurement="average",
                  raw_label="Gross Advances average YoY",
                  excerpt="Gross Advances; average YoY 13.4%"),
        ]
        chosen = _resolve("loan_growth", facts)
        self.assertIsNone(chosen.fact)

    def test_eop_yoy_beats_average_for_deposit_growth(self):
        facts = [
            _fact("deposit_growth", 13.3, comparison="yoy", measurement="average",
                  raw_label="Deposits average YoY",
                  excerpt="Deposits; average YoY 13.3%"),
            _fact("deposit_growth", 14.7, comparison="yoy", measurement="end_of_period",
                  raw_label="Deposits EOP YoY",
                  excerpt="Deposits; EOP YoY 14.7%"),
        ]
        chosen = _resolve("deposit_growth", facts)
        self.assertEqual(chosen.fact.value, 14.7)
        self.assertEqual(chosen.fact.comparison, "yoy")
        self.assertEqual(chosen.fact.measurement, "end_of_period")

    def test_average_only_deposit_growth_stays_null(self):
        facts = [
            _fact("deposit_growth", 13.3, comparison="yoy", measurement="average",
                  raw_label="Deposits average YoY", excerpt="average YoY 13.3%"),
        ]
        self.assertIsNone(_resolve("deposit_growth", facts).fact)

    def test_nii_yoy_beats_qoq_and_qoq_only_stays_null(self):
        yoy = _fact("nii_growth", 6.7, comparison="yoy",
                    raw_label="NII growth", excerpt="NII grew 6.7% YoY")
        qoq = _fact("nii_growth", 1.4, comparison="qoq",
                    raw_label="NII growth QoQ", excerpt="NII grew 1.4% QoQ")
        chosen = _resolve("nii_growth", [yoy, qoq])
        self.assertEqual(chosen.fact.value, 6.7)
        self.assertEqual(chosen.fact.comparison, "yoy")
        self.assertIsNone(_resolve("nii_growth", [qoq]).fact)


class TestHeadlineVersusSubseries(unittest.TestCase):
    def test_overall_nim_beats_domestic_and_domestic_only_is_null(self):
        cases = (
            ("SBIN", 2.86, "NIM (Whole Bank) 2.86%", 3.00, "NIM (Domestic) 3.00%"),
            ("AXISBANK", 3.46, "NIM - Overall 3.46%", 3.60, "NIM - Domestic 3.60%"),
        )
        for ticker, overall, overall_ev, domestic, domestic_ev in cases:
            with self.subTest(ticker=ticker):
                chosen = _resolve("nim", [
                    _fact("nim", overall, raw_label="NIM", excerpt=overall_ev),
                    _fact("nim", domestic, raw_label="NIM Domestic", excerpt=domestic_ev,
                          series="domestic"),
                ])
                self.assertEqual(chosen.fact.value, overall)
                self.assertIsNone(_resolve("nim", [
                    _fact("nim", domestic, raw_label="NIM Domestic", excerpt=domestic_ev,
                          series="domestic"),
                ]).fact)

    def test_headline_pcr_beats_subseries_and_subseries_only_is_null(self):
        cases = (
            ("HDFCBANK", 74.2, "PCR 74.20%", 66.0, "Specific PCR = 66%", "specific"),
            ("SBIN", 74.2, "PCR 74.20%", 91.82, "PCR (incl. AUCA) 91.82%", "including_writeoffs"),
            ("AXISBANK", 70.0, "PCR healthy at 70%", 161.0,
             "On an aggregated basis, Coverage ratio at 161%", "including_writeoffs"),
        )
        for ticker, headline, headline_ev, sub, sub_ev, series in cases:
            with self.subTest(ticker=ticker, series=series):
                chosen = _resolve("pcr", [
                    _fact("pcr", headline, raw_label="PCR", excerpt=headline_ev),
                    _fact("pcr", sub, raw_label=sub_ev, excerpt=sub_ev, series=series),
                ])
                self.assertEqual(chosen.fact.value, headline)
                self.assertIsNone(_resolve("pcr", [
                    _fact("pcr", sub, raw_label=sub_ev, excerpt=sub_ev, series=series),
                ]).fact)

    def test_net_credit_cost_is_not_canonical_when_headline_exists(self):
        chosen = _resolve("credit_cost", [
            _fact("credit_cost", 0.92, raw_label="Credit Cost (Annualised)",
                  excerpt="Credit Cost (Annualised) 0.92%"),
            _fact("credit_cost", 0.63, raw_label="Net credit cost",
                  excerpt="Net credit cost at 0.63%", series="net_of_recoveries"),
        ])
        self.assertEqual(chosen.fact.value, 0.92)
        self.assertIsNone(_resolve("credit_cost", [
            _fact("credit_cost", 0.63, raw_label="Net credit cost",
                  excerpt="Net credit cost at 0.63%", series="net_of_recoveries"),
        ]).fact)

    def test_annualized_and_quarterly_credit_cost_are_not_collapsed(self):
        chosen = _resolve("credit_cost", [
            _fact("credit_cost", 0.27, raw_label="Credit Cost",
                  excerpt="0.27% Credit Cost"),
            _fact("credit_cost", 0.92, raw_label="Credit Cost (Annualised)",
                  excerpt="Credit Cost (Annualised) 0.92%"),
        ])
        self.assertIsNone(chosen.fact)


class TestCapitalCasaAndCost(unittest.TestCase):
    def test_car_and_cet1_stay_separate(self):
        car = _fact("car", 15.67, raw_label="CRAR", excerpt="Capital Adequacy 15.67%")
        cet1 = _fact("cet1", 12.89, raw_label="CET-1", excerpt="CET-1 12.89%")
        self.assertEqual(_resolve("car", [car, cet1]).fact.value, 15.67)
        self.assertEqual(_resolve("cet1", [car, cet1]).fact.value, 12.89)

    def test_casa_ratio_stays_separate_from_casa_growth(self):
        ratio = _fact("casa", 39.24, raw_label="CASA", excerpt="CASA: 39.24%")
        growth = _fact("casa_trend", 9.3, comparison="yoy", raw_label="CASA Deposits",
                       excerpt="CASA Deposits grew 9.30% YoY")
        self.assertEqual(_resolve("casa", [ratio, growth]).fact.value, 39.24)
        self.assertEqual(_resolve("casa_trend", [ratio, growth]).fact.value, 9.3)
        self.assertNotEqual(_resolve("casa", [ratio, growth]).fact.value, 9.3)

    def test_qab_and_meb_casa_stay_null_when_both_are_headline_candidates(self):
        chosen = _resolve("casa", [
            _fact("casa", 37, measurement="average", raw_label="CASA QAB",
                  excerpt="CASA ratio at 37% QAB"),
            _fact("casa", 38, measurement="end_of_period", raw_label="CASA MEB",
                  excerpt="CASA ratio at 38% MEB"),
        ])
        self.assertIsNone(chosen.fact)

    def test_cost_to_assets_is_not_cost_income(self):
        chosen = _resolve("cost_income", [
            _fact("cost_income", 2.20, raw_label="Cost to assets",
                  excerpt="Cost to assets 2.20%"),
        ])
        self.assertIsNone(chosen.fact)

    def test_core_cost_to_income_may_be_canonical(self):
        chosen = _resolve("cost_income", [
            _fact("cost_income", 39.2, raw_label="Core cost-to-income",
                  excerpt="Core cost-to-income ratio of 39.2%"),
        ])
        self.assertEqual(chosen.fact.value, 39.2)


class TestScopePeriodAndSegments(unittest.TestCase):
    def test_prior_period_cannot_become_current(self):
        chosen = _resolve("gnpa", [
            _fact("gnpa", 1.42, period="Q4 FY26", excerpt="GNPA 1.42% in Q4 FY26"),
            _fact("gnpa", 1.17, period="Q1 FY27", excerpt="GNPA 1.17% in Q1 FY27"),
        ])
        self.assertEqual(chosen.fact.value, 1.17)

    def test_standalone_and_consolidated_are_not_mixed(self):
        chosen = _resolve("roa", [
            _fact("roa", 1.85, consolidation="standalone", excerpt="Standalone RoA 1.85%"),
            _fact("roa", 1.90, consolidation="consolidated", excerpt="Consolidated RoA 1.90%"),
        ])
        self.assertIsNone(chosen.fact)

    def test_bank_level_loan_growth_beats_segment_when_eop_yoy_exists(self):
        chosen = _resolve("loan_growth", [
            _fact("loan_growth", 19.6, comparison="yoy", measurement="end_of_period",
                  raw_label="Total loans", excerpt="Total loans grew by 19.6% y-o-y"),
            _fact("loan_growth", 12.0, comparison="yoy", measurement="end_of_period",
                  raw_label="Retail loans", excerpt="Retail loans grew by 12.0% y-o-y"),
        ])
        self.assertEqual(chosen.fact.value, 19.6)
        self.assertIsNone(_resolve("loan_growth", [
            _fact("loan_growth", 12.0, comparison="yoy", measurement="end_of_period",
                  raw_label="Retail loans", excerpt="Retail loans grew by 12.0% y-o-y"),
        ]).fact)

    def test_does_not_pick_by_magnitude_or_order(self):
        facts = [
            _fact("gnpa", 1.24, raw_label="GNPA", excerpt="GNPA 1.24%", page=1, confidence=0.99),
            _fact("gnpa", 1.17, raw_label="Gross NPA", excerpt="Gross NPA 1.17%", page=9, confidence=0.4),
        ]
        self.assertIsNone(_resolve("gnpa", facts).fact)
        self.assertIsNone(_resolve("gnpa", list(reversed(facts))).fact)


class TestHdfcPipelineCanonical(unittest.TestCase):
    def test_hdfc_canonical_metrics_from_competing_candidates(self):
        metrics = _run("HDFCBANK", [
            _cand("gnpa", 1.17, "GNPA ratio at 1.17%; ex-agri at 0.91%"),
            _cand("gnpa", 0.91, "GNPA ratio at 1.17%; ex-agri at 0.91%", raw_label="GNPA ex-agri"),
            _cand("nim", 3.26, "Net interest margin (NIM) of 3.26%"),
            _cand("roa", 1.85, "RoA of 1.85%"),
            _cand("roe", 13.8, "RoE of 13.8%"),
            _cand("nii_growth", 6.7, "NII grew 6.7% YoY", basis="yoy"),
            _cand("nii_growth", 1.4, "NII grew 1.4% QoQ", basis="qoq"),
            _cand("loan_growth", 13.4, "Gross Advances; average YoY 13.4%",
                  basis="yoy", measurement="average", raw_label="Gross Advances average YoY"),
            _cand("loan_growth", 15.4, "Gross Advances; EOP YoY 15.4%",
                  basis="yoy", measurement="end_of_period", raw_label="Gross Advances EOP YoY"),
            _cand("loan_growth", 3.4, "Gross Advances; EOP QoQ 3.4%",
                  basis="qoq", measurement="end_of_period", raw_label="Gross Advances EOP QoQ"),
            _cand("deposit_growth", 13.3, "Deposits; average YoY 13.3%",
                  basis="yoy", measurement="average", raw_label="Deposits average YoY"),
            _cand("deposit_growth", 14.7, "Deposits; EOP YoY 14.7%",
                  basis="yoy", measurement="end_of_period", raw_label="Deposits EOP YoY"),
            _cand("casa", 32, "CASA ratio ... Jun'26 32%"),
            _cand("car", 19.6, "Capital adequacy ratio at 19.6%"),
            _cand("cet1", 17.4, "CET1 at 17.4%"),
            _cand("cost_income", 39.2, "Core cost-to-income ratio of 39.2%"),
            _cand("pcr", 66, "Specific PCR = 66%", raw_label="Specific PCR"),
        ])
        expected = {
            "gnpa": (1.17, "point_in_time", None),
            "nim": (3.26, "point_in_time", None),
            "roa": (1.85, "point_in_time", None),
            "roe": (13.8, "point_in_time", None),
            "nii_growth": (6.7, "yoy", None),
            "loan_growth": (15.4, "yoy", "end_of_period"),
            "deposit_growth": (14.7, "yoy", "end_of_period"),
            "casa": (32, "point_in_time", None),
            "car": (19.6, "point_in_time", None),
            "cet1": (17.4, "point_in_time", None),
            "cost_income": (39.2, "point_in_time", None),
        }
        for key, (value, basis, measurement) in expected.items():
            with self.subTest(key=key):
                metric = getattr(metrics, key)
                self.assertIsNotNone(metric)
                self.assertEqual(metric.value, value)
                self.assertEqual(metric.unit, "%")
                self.assertEqual(metric.comparison, basis)
                if measurement:
                    self.assertEqual(metric.measurement, measurement)
                self.assertTrue(metric.resolution_reason)
        self.assertNotEqual(metrics.gnpa.value, 0.91)
        self.assertIsNone(metrics.pcr)
        loan_values = sorted(fact.value for fact in metrics.raw_facts if fact.key == "loan_growth")
        self.assertEqual(loan_values, [3.4, 13.4, 15.4])


class TestParameterizedPipeline(unittest.TestCase):
    def test_combined_recoveries_cannot_become_canonical(self):
        cases = (
            ("SBIN", "Recovery + Upgradation 3,574", 3574),
            ("ICICIBANK", "recoveries, upgrades and others 28.45", 28.45),
        )
        for ticker, evidence, value in cases:
            with self.subTest(ticker=ticker):
                metrics = _run(ticker, [
                    _cand("recoveries", value, evidence, unit="₹ bn", raw_label=evidence),
                ])
                self.assertIsNone(metrics.recoveries)

    def test_cost_to_assets_pipeline_is_not_cost_income(self):
        metrics = _run("AXISBANK", [
            _cand("cost_income", 2.20, "Cost to assets 2.20%", raw_label="Cost to assets"),
        ])
        self.assertIsNone(metrics.cost_income)
        self.assertTrue(metrics.raw_facts)


if __name__ == "__main__":
    unittest.main()
