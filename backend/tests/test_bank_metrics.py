"""BankMetrics schema: missing metrics stay None and are never inferred."""
from __future__ import annotations

import unittest

from app.providers.bank_metrics import (
    BANK_METRIC_KEYS,
    BankMetric,
    BankMetrics,
    EXTRACTION_OK,
    MetricProvenance,
    RawFact,
)


class TestSchema(unittest.TestCase):
    def test_bank_metrics_has_the_contract_keys(self):
        for key in (
            "gnpa", "nnpa", "pcr", "credit_cost", "slippages",
            "nim", "roa", "roe", "nii_growth",
            "loan_growth", "deposit_growth", "casa", "casa_trend",
            "car", "cet1", "cost_income",
            "restructured_loans", "sma_or_stressed_assets", "writeoffs", "recoveries",
        ):
            self.assertIn(key, BANK_METRIC_KEYS)
            self.assertTrue(hasattr(BankMetrics, key))

    def test_empty_metrics_leave_every_kpi_none(self):
        metrics = BankMetrics(ticker="HDFCBANK", period="Q1 FY27", status=EXTRACTION_OK)
        for key in BANK_METRIC_KEYS:
            self.assertIsNone(getattr(metrics, key))
        self.assertEqual(metrics.raw_facts, [])
        self.assertEqual(metrics.ambiguous, {})

    def test_provenance_is_a_reusable_structure(self):
        provenance = MetricProvenance(
            source_title="Q1FY27 Earnings Presentation",
            source_url="https://www.hdfc.bank.in/example.pdf",
            source_type="official_ir",
            excerpt="GNPA ratio at 1.17%",
            raw_label="GNPA ratio",
            page=2,
        )
        metric = BankMetric(
            key="gnpa",
            label="Gross NPA",
            value=1.17,
            unit="%",
            period="Q1 FY27",
            comparison="point_in_time",
            consolidation="standalone",
            provenance=provenance,
            confidence=0.95,
        )
        self.assertEqual(metric.provenance.page, 2)
        self.assertIsNone(BankMetric(key="slippages", label="Slippages", value=None).provenance)

    def test_raw_fact_is_distinct_from_normalized_metric(self):
        fact = RawFact(
            key="gnpa",
            raw_label="Gross NPA",
            value=1.17,
            unit="%",
            excerpt="Gross NPA at 1.17%",
        )
        metric = BankMetric(key="gnpa", label="Gross NPA", value=fact.value, unit=fact.unit)
        self.assertEqual(fact.raw_label, "Gross NPA")
        self.assertEqual(metric.key, "gnpa")

    def test_measurement_is_optional_on_metric_and_fact(self):
        fact = RawFact(
            key="loan_growth",
            raw_label="Gross Advances EOP YoY",
            value=15.4,
            unit="%",
            comparison="yoy",
            measurement="end_of_period",
            excerpt="EOP YoY 15.4%",
        )
        metric = BankMetric(
            key="loan_growth",
            label="Loan growth",
            value=15.4,
            unit="%",
            comparison="yoy",
            measurement="end_of_period",
        )
        self.assertEqual(fact.measurement, "end_of_period")
        self.assertEqual(metric.measurement, "end_of_period")
        self.assertIsNone(BankMetric(key="nim", label="NIM", value=3.26).measurement)


if __name__ == "__main__":
    unittest.main()
