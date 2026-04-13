"""Tests for semantic query resolution through the dashboard pipeline."""

from __future__ import annotations

import tempfile
from pathlib import Path

from finch_epm.cache.local import LocalCacheEngine
from finch_epm.cache.sync import SyncEngine
from finch_epm.connectors.fake import FakeConnector
from finch_epm.dashboard.fdash import load_fdash_string
from finch_epm.dashboard.resolver import resolve_queries


SEMANTIC_YAML = """
name: Test Model
entities:
  - name: transaction
    display_name: GL Transaction
    physical_table: fake__gl_detail
    measures:
      - name: total_amount
        expression: "SUM(CAST(amount AS DOUBLE))"
      - name: count
        expression: "COUNT(*)"
    columns: [period, subsidiary_id, account_id, account_type, amount]
relationships: []
"""


class TestSemanticResolver:
    def test_fdash_with_semantic_query(
        self, fake_connector: FakeConnector, cache_engine: LocalCacheEngine
    ) -> None:
        """Full round-trip: .fdash with entity query -> resolver -> results."""
        SyncEngine(fake_connector, cache_engine).sync_tables(
            ["gl_detail"], mode="full"
        )

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".semantic.yml", delete=False, encoding="utf-8"
        ) as f:
            f.write(SEMANTIC_YAML)
            semantic_path = f.name

        try:
            dashboard_yaml = f"""
name: Semantic Test
sources: [fake]
semantic_model: {semantic_path}

queries:
  - name: by_type
    entity: transaction
    measures: [transaction.total_amount]
    group_by: [transaction.account_type]

charts:
  - type: table
    title: By Type
    data: by_type
"""
            spec = load_fdash_string(dashboard_yaml)
            results = resolve_queries(spec, cache_engine)

            assert "by_type" in results
            result = results["by_type"]
            assert result.row_count >= 1
            assert "account_type" in result.column_names
            assert "total_amount" in result.column_names
        finally:
            Path(semantic_path).unlink(missing_ok=True)

    def test_mixed_semantic_and_raw_queries(
        self, fake_connector: FakeConnector, cache_engine: LocalCacheEngine
    ) -> None:
        """Dashboard with both semantic and raw SQL queries resolves correctly."""
        SyncEngine(fake_connector, cache_engine).sync_tables(
            ["gl_detail"], mode="full"
        )

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".semantic.yml", delete=False, encoding="utf-8"
        ) as f:
            f.write(SEMANTIC_YAML)
            semantic_path = f.name

        try:
            dashboard_yaml = f"""
name: Mixed Test
sources: [fake]
semantic_model: {semantic_path}

queries:
  - name: semantic_query
    entity: transaction
    measures: [transaction.count]
  - name: raw_query
    sql: SELECT COUNT(*) AS cnt FROM fake__gl_detail

charts:
  - type: table
    title: Semantic
    data: semantic_query
  - type: kpi
    title: Count
    data: raw_query
    value: cnt
"""
            spec = load_fdash_string(dashboard_yaml)
            results = resolve_queries(spec, cache_engine)

            assert "semantic_query" in results
            assert "raw_query" in results
            assert results["semantic_query"].row_count >= 1
            assert results["raw_query"].row_count >= 1
        finally:
            Path(semantic_path).unlink(missing_ok=True)

    def test_backward_compat_raw_sql_only(
        self, cache_engine: LocalCacheEngine
    ) -> None:
        """Existing dashboards without semantic_model still work."""
        cache_engine.ingest_facts(
            "gl_detail",
            ["subsidiary_id", "amount"],
            ["integer", "decimal"],
            [[1, 100.0], [2, 200.0]],
        )

        dashboard_yaml = """
name: Legacy Test
sources: [fake]

queries:
  - name: summary
    sql: SELECT subsidiary_id, SUM(amount) AS total FROM gl_detail GROUP BY subsidiary_id

charts:
  - type: table
    title: Summary
    data: summary
"""
        spec = load_fdash_string(dashboard_yaml)
        assert spec.semantic_model is None

        results = resolve_queries(spec, cache_engine)
        assert "summary" in results
        assert results["summary"].row_count >= 1


class TestFdashEntityParsing:
    def test_entity_query_parsed(self) -> None:
        yaml_str = """
name: Test
queries:
  - name: q1
    entity: transaction
    measures: [transaction.total]
    group_by: [transaction.type]
    filters:
      type: Income
    order_by: [transaction.type]
charts:
  - type: table
    title: T
    data: q1
"""
        spec = load_fdash_string(yaml_str)
        q = spec.queries[0]
        assert q.entity == "transaction"
        assert q.measures == ["transaction.total"]
        assert q.group_by == ["transaction.type"]
        assert q.query_filters == {"type": "Income"}
        assert q.order_by == ["transaction.type"]
        assert q.sql == ""

    def test_mixed_entity_and_sql(self) -> None:
        yaml_str = """
name: Test
queries:
  - name: q1
    entity: transaction
    measures: [transaction.count]
  - name: q2
    sql: SELECT 1
charts:
  - type: table
    title: T
    data: q1
"""
        spec = load_fdash_string(yaml_str)
        assert spec.queries[0].entity == "transaction"
        assert spec.queries[1].sql == "SELECT 1"
