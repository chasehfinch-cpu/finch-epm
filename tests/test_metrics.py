"""Tests for the metrics layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from finch_epm.engine.metrics import (
    MeasureComponent,
    MetricDefinition,
    MetricStore,
)


class TestMetricStore:
    def test_roundtrip_save_load(self, tmp_path: Path) -> None:
        path = tmp_path / "metrics.yaml"
        store = MetricStore()
        store.add(MetricDefinition(
            name="revenue_per_visit",
            display_name="Revenue Per Visit",
            numerator=MeasureComponent(
                source="netsuite",
                table="TransactionAccountingLine",
                measure="SUM(CAST(amount AS DOUBLE) * -1)",
                filter="accttype IN ('Income','OthIncome')",
                time_column="tx.trandate",
                time_format="M/D/YYYY",
            ),
            denominator=MeasureComponent(
                source="sqlserver",
                table="dbo__BillingDataRCM",
                measure="COUNT(*)",
                filter="Billable_NonBillable = 'Billable'",
                time_column="DOS",
                time_format="YYYY-MM-DD",
            ),
            format="currency",
            time_alignment="monthly",
        ))
        store.save(path)

        loaded = MetricStore.load(path)
        m = loaded.get("revenue_per_visit")
        assert m is not None
        assert m.display_name == "Revenue Per Visit"
        assert m.numerator.source == "netsuite"
        assert m.denominator is not None
        assert m.denominator.source == "sqlserver"

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        store = MetricStore.load(tmp_path / "missing.yaml")
        assert len(store.metrics) == 0

    def test_simple_metric_no_denominator(self) -> None:
        store = MetricStore()
        store.add(MetricDefinition(
            name="total_revenue",
            numerator=MeasureComponent(
                table="TAL",
                measure="SUM(amount * -1)",
                filter="accttype = 'Income'",
            ),
        ))
        sql = store.generate_sql("total_revenue")
        assert "SUM(amount * -1)" in sql
        assert "TAL" in sql

    def test_cross_source_metric_sql(self) -> None:
        store = MetricStore()
        store.add(MetricDefinition(
            name="rev_per_visit",
            numerator=MeasureComponent(
                table="TAL", measure="SUM(amount * -1)",
                time_column="trandate", time_format="M/D/YYYY",
            ),
            denominator=MeasureComponent(
                table="Billing", measure="COUNT(*)",
                time_column="DOS", time_format="YYYY-MM-DD",
            ),
            time_alignment="monthly",
        ))
        sql = store.generate_sql("rev_per_visit")
        assert "numerator" in sql
        assert "denominator" in sql
        assert "num_value / d.den_value" in sql
        assert "period" in sql

    def test_unknown_metric(self) -> None:
        store = MetricStore()
        sql = store.generate_sql("nonexistent")
        assert "not found" in sql

    def test_list_metrics(self) -> None:
        store = MetricStore()
        store.add(MetricDefinition(name="a"))
        store.add(MetricDefinition(name="b"))
        assert len(store.list_metrics()) == 2
