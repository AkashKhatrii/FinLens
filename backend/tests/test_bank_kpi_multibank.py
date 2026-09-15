"""Parameterized multi-bank KPI semantics. Mocked AI only; no live sites."""
from __future__ import annotations

import unittest

from app.providers.bank_documents import BankDocument
from app.providers.bank_kpi import normalize_metric_name, normalize_period_label
from app.providers.bank_kpi_extractor import extract_bank_metrics_from_pages
from app.providers.pdf_text import PdfPage


def _doc(ticker: str) -> BankDocument:
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


# Same assertion, several banks/wordings. Not one test per ticker.
TERMINOLOGY_CASES = (
    ("Gross NPA", "gnpa"),
    ("Gross NPA ratio", "gnpa"),
    ("Gross Non-Performing Assets", "gnpa"),
    ("GNPA", "gnpa"),
    ("Net NPA", "nnpa"),
    ("Net NPA ratio", "nnpa"),
    ("Net Non-Performing Assets", "nnpa"),
    ("NNPA", "nnpa"),
    ("Net Interest Margin", "nim"),
    ("NIM", "nim"),
    ("Return on Assets", "roa"),
    ("Return on average assets", "roa"),
    ("RoA", "roa"),
    ("Return on Equity", "roe"),
    ("Return on average equity", "roe"),
    ("RoE", "roe"),
    ("Capital Adequacy Ratio", "car"),
    ("CRAR", "car"),
    ("CET1", "cet1"),
    ("CET-1", "cet1"),
    ("Common Equity Tier 1", "cet1"),
    ("Cost to Income Ratio", "cost_income"),
    ("cost-to-income", "cost_income"),
)

CURRENT_VS_PRIOR_CASES = (
    (
        "HDFCBANK",
        "gnpa",
        1.17,
        "GNPA 1.17%, compared with 1.24%",
        1.24,
    ),
    (
        "ICICIBANK",
        "nnpa",
        0.35,
        "Net NPA ratio was 0.35% at Jun 30, 2026 (Mar 31, 2026: 0.33%)",
        0.33,
    ),
    (
        "AXISBANK",
        "gnpa",
        1.28,
        "Gross NPA 1.28% as against 1.57% as on 30th June 2025",
        1.57,
    ),
)

CASA_MEASUREMENT_CASES = (
    (
        "AXISBANK",
        "CASA ratio at 37% QAB",
        37,
        "CASA ratio at 38% MEB",
        38,
        "average",
        "end_of_period",
    ),
    (
        "ICICIBANK",
        "Average CASA ratio 38.1%",
        38.1,
        "CASA 39.5% period end share at Jun 30, 2026",
        39.5,
        "average",
        "end_of_period",
    ),
)

PCR_SUBSERIES_CASES = (
    ("HDFCBANK", "Specific PCR = 66%", 66, "specific"),
    ("SBIN", "Provision Coverage Ratio (incl. AUCA) 91.82%", 91.82, "including_writeoffs"),
    ("AXISBANK", "On an aggregated basis, Coverage ratio at 161%", 161, "including_writeoffs"),
)

NIM_HEADLINE_CASES = (
    (
        "SBIN",
        "NIM (Whole Bank) 2.86%",
        2.86,
        "NIM (Domestic) 3.00%",
        3.00,
    ),
    (
        "AXISBANK",
        "NIM - Overall 3.46%",
        3.46,
        "NIM - Domestic 3.60%",
        3.60,
    ),
)


class TestParameterizedTerminology(unittest.TestCase):
    def test_common_labels_map_to_the_same_keys(self):
        for label, key in TERMINOLOGY_CASES:
            with self.subTest(label=label, key=key):
                self.assertEqual(normalize_metric_name(label), key)

    def test_tier_slices_are_not_car_or_cet1(self):
        for label in ("Tier 1", "Tier 2", "AT1", "AT1 CAR", "Tier 2 CAR"):
            with self.subTest(label=label):
                self.assertNotEqual(normalize_metric_name(label), "car")
                self.assertNotEqual(normalize_metric_name(label), "cet1")


class TestParameterizedPeriod(unittest.TestCase):
    def test_bank_period_spellings_normalize_to_q1_fy27(self):
        for raw in ("Q1 FY27", "Q1FY27", "Q1-2027", "Jun'26"):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_period_label(raw), "Q1 FY27")


class TestParameterizedCurrentVsPrior(unittest.TestCase):
    def test_parenthetical_or_compared_prior_is_not_current(self):
        for ticker, key, current, evidence, prior in CURRENT_VS_PRIOR_CASES:
            with self.subTest(ticker=ticker, key=key):
                metrics = _run(ticker, [
                    _cand(key, current, evidence),
                    _cand(key, prior, evidence),
                ])
                metric = getattr(metrics, key)
                self.assertIsNotNone(metric)
                self.assertEqual(metric.value, current)
                self.assertEqual(metric.unit, "%")
                self.assertEqual(metric.comparison, "point_in_time")


class TestParameterizedCasaAndPcr(unittest.TestCase):
    def test_qab_and_meb_casa_are_not_collapsed(self):
        for ticker, avg_ev, avg, eop_ev, eop, avg_m, eop_m in CASA_MEASUREMENT_CASES:
            with self.subTest(ticker=ticker):
                metrics = _run(ticker, [
                    _cand("casa", avg, avg_ev),
                    _cand("casa", eop, eop_ev),
                ])
                self.assertIsNone(metrics.casa)
                values = sorted(fact.value for fact in metrics.raw_facts if fact.key == "casa")
                self.assertEqual(values, sorted([avg, eop]))
                measurements = {fact.measurement for fact in metrics.raw_facts if fact.key == "casa"}
                self.assertEqual(measurements, {avg_m, eop_m})
            with self.subTest(ticker=ticker, mislabeled="casa_trend"):
                metrics = _run(ticker, [
                    _cand("casa_trend", avg, avg_ev),
                    _cand("casa_trend", eop, eop_ev),
                ])
                self.assertIsNone(metrics.casa)
                self.assertIsNone(metrics.casa_trend)
                values = sorted(fact.value for fact in metrics.raw_facts if fact.key == "casa")
                self.assertEqual(values, sorted([avg, eop]))

    def test_casa_deposit_growth_is_not_the_casa_ratio(self):
        cases = (
            ("SBIN", "CASA Deposits grew 9.30% YoY", 9.3),
            ("ICICIBANK", "Average current and savings account deposits grew by 12.1% y-o-y", 12.1),
        )
        for ticker, evidence, value in cases:
            with self.subTest(ticker=ticker):
                metrics = _run(ticker, [
                    _cand("casa", value, evidence, basis="yoy", raw_label="CASA Deposits"),
                ])
                self.assertIsNone(metrics.casa)
                if metrics.casa_trend is not None:
                    self.assertEqual(metrics.casa_trend.value, value)
                    self.assertEqual(metrics.casa_trend.comparison, "yoy")

    def test_pcr_subseries_is_not_headline_pcr(self):
        for ticker, evidence, value, series in PCR_SUBSERIES_CASES:
            with self.subTest(ticker=ticker, series=series):
                metrics = _run(ticker, [
                    _cand("pcr", value, evidence, raw_label=evidence.split("%")[0].strip()),
                ])
                self.assertIsNone(metrics.pcr)
                self.assertEqual(metrics.raw_facts[0].series, series)


class TestParameterizedNimAndCreditCost(unittest.TestCase):
    def test_domestic_nim_is_not_used_as_headline_when_overall_exists(self):
        for ticker, overall_ev, overall, domestic_ev, domestic in NIM_HEADLINE_CASES:
            with self.subTest(ticker=ticker):
                metrics = _run(ticker, [
                    _cand("nim", overall, overall_ev, raw_label="NIM"),
                    _cand("nim", domestic, domestic_ev, raw_label="NIM Domestic"),
                ])
                self.assertIsNotNone(metrics.nim)
                self.assertEqual(metrics.nim.value, overall)
                self.assertNotEqual(metrics.nim.value, domestic)
                series = {fact.series for fact in metrics.raw_facts if fact.key == "nim"}
                self.assertIn("domestic", series)

    def test_net_credit_cost_is_not_headline(self):
        cases = (
            ("AXISBANK", 0.63, "percent", "Net credit cost at 0.63%", "Net credit cost"),
            ("HDFCBANK", 29, "bps", "Credit cost (net of recoveries) 29 bps", "Credit cost net of recoveries"),
        )
        for ticker, value, unit, evidence, raw_label in cases:
            with self.subTest(ticker=ticker):
                metrics = _run(ticker, [
                    _cand("credit_cost", value, evidence, unit=unit, raw_label=raw_label),
                ])
                self.assertIsNone(metrics.credit_cost)
                self.assertEqual(metrics.raw_facts[0].series, "net_of_recoveries")

    def test_recoveries_upgrades_combined_are_rejected(self):
        cases = (
            ("SBIN", "recoveries", 3574, "Recovery + Upgradation 3,574", "₹ bn"),
            ("ICICIBANK", "recoveries", 28.45, "recoveries, upgrades and others 28.45", "₹ bn"),
        )
        for ticker, metric, value, evidence, unit in cases:
            with self.subTest(ticker=ticker):
                metrics = _run(ticker, [
                    _cand(metric, value, evidence, unit=unit, raw_label=evidence),
                ])
                self.assertIsNone(getattr(metrics, metric))


class TestParameterizedHdfcRegression(unittest.TestCase):
    def test_hdfc_headline_values_still_extract(self):
        metrics = _run("HDFCBANK", [
            _cand("gnpa", 1.17, "GNPA ratio at 1.17%; ex-agri at 0.91%"),
            _cand("gnpa", 0.91, "GNPA ratio at 1.17%; ex-agri at 0.91%", raw_label="GNPA ex-agri"),
            _cand("nim", 3.26, "Net interest margin (NIM) of 3.26%"),
            _cand("roa", 1.85, "RoA of 1.85%"),
            _cand("roe", 13.8, "RoE of 13.8%"),
            _cand("nii_growth", 6.7, "NII grew 6.7% YoY", basis="yoy"),
            _cand("casa", 32, "CASA ratio ... Jun'26 32%"),
            _cand("car", 19.6, "Capital adequacy ratio at 19.6%"),
            _cand("cet1", 17.4, "CET1 at 17.4%"),
            _cand("cost_income", 39.2, "Core cost-to-income ratio of 39.2%"),
        ])
        expected = {
            "gnpa": (1.17, "point_in_time"),
            "nim": (3.26, "point_in_time"),
            "roa": (1.85, "point_in_time"),
            "roe": (13.8, "point_in_time"),
            "nii_growth": (6.7, "yoy"),
            "casa": (32, "point_in_time"),
            "car": (19.6, "point_in_time"),
            "cet1": (17.4, "point_in_time"),
            "cost_income": (39.2, "point_in_time"),
        }
        for key, (value, basis) in expected.items():
            with self.subTest(key=key):
                metric = getattr(metrics, key)
                self.assertEqual(metric.value, value)
                self.assertEqual(metric.unit, "%")
                self.assertEqual(metric.comparison, basis)
        self.assertIsNone(metrics.loan_growth)
        self.assertNotEqual(metrics.gnpa.value, 0.91)


class TestParameterizedGrowthAmbiguity(unittest.TestCase):
    def test_total_versus_segment_loan_growth_is_not_guessed(self):
        cases = (
            (
                "ICICIBANK",
                "Total loans grew by 19.6% y-o-y",
                19.6,
                "Retail loans grew by 12.0% y-o-y",
                12.0,
            ),
            (
                "SBIN",
                "Gross Advances 18.63% YoY",
                18.63,
                "Domestic Advances 18.15% YoY",
                18.15,
            ),
        )
        for ticker, total_ev, total, part_ev, part in cases:
            with self.subTest(ticker=ticker):
                metrics = _run(ticker, [
                    _cand("loan_growth", total, total_ev, basis="yoy", raw_label="Total loans"),
                    _cand("loan_growth", part, part_ev, basis="yoy", raw_label="Retail loans"),
                ])
                self.assertIsNone(metrics.loan_growth)
                values = sorted(fact.value for fact in metrics.ambiguous.get("loan_growth", []))
                self.assertEqual(values, sorted([total, part]))


if __name__ == "__main__":
    unittest.main()
