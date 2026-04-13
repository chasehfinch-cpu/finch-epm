"""Tests for the SemanticQueryBuilder."""

from __future__ import annotations

import pytest

from finch_epm.cache.local import LocalCacheEngine
from finch_epm.cache.models import QueryRequest
from finch_epm.cache.sync import SyncEngine
from finch_epm.connectors.fake import FakeConnector
from finch_epm.engine.query_builder import SemanticQueryBuilder
from finch_epm.engine.semantic import load_semantic_model_string

SAMPLE_YAML = """
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
    calculated_fields:
      - name: fiscal_year
        expression: "SUBSTRING(period, 1, 4)"
    columns: [period, subsidiary_id, account_id, account_type, amount]

  - name: subsidiary
    display_name: Subsidiary
    physical_table: fake__subsidiary
    columns: [id, name, parent_id]

relationships:
  - name: transaction_to_subsidiary
    from_entity: transaction
    from_column: subsidiary_id
    to_entity: subsidiary
    to_column: id
    join_type: LEFT
"""


class TestSemanticQueryBuilder:
    def setup_method(self) -> None:
        self.model = load_semantic_model_string(SAMPLE_YAML)
        self.builder = SemanticQueryBuilder(self.model)

    def test_simple_single_entity(self) -> None:
        sql = self.builder.build_query(
            entities=["transaction"],
            measures=["transaction.total_amount"],
        )
        assert "SUM(CAST(amount AS DOUBLE))" in sql
        assert "FROM fake__gl_detail" in sql

    def test_group_by(self) -> None:
        sql = self.builder.build_query(
            entities=["transaction"],
            measures=["transaction.total_amount"],
            group_by=["transaction.account_type"],
        )
        assert "GROUP BY" in sql
        assert "transaction.account_type" in sql

    def test_cross_entity_join(self) -> None:
        sql = self.builder.build_query(
            entities=["transaction"],
            measures=["transaction.total_amount"],
            group_by=["subsidiary.name"],
        )
        assert "LEFT JOIN fake__subsidiary" in sql
        assert "ON transaction.subsidiary_id = subsidiary.id" in sql

    def test_filter_application(self) -> None:
        sql = self.builder.build_query(
            entities=["transaction"],
            measures=["transaction.count"],
            filters={"transaction.account_type": "Income"},
        )
        assert "WHERE" in sql
        assert "account_type" in sql
        assert "'Income'" in sql

    def test_calculated_field_in_group_by(self) -> None:
        sql = self.builder.build_query(
            entities=["transaction"],
            measures=["transaction.total_amount"],
            group_by=["transaction.fiscal_year"],
        )
        assert "SUBSTRING(period, 1, 4)" in sql
        assert "GROUP BY" in sql

    def test_order_by_and_limit(self) -> None:
        sql = self.builder.build_query(
            entities=["transaction"],
            measures=["transaction.total_amount"],
            group_by=["transaction.account_type"],
            order_by=["transaction.account_type"],
            limit=10,
        )
        assert "ORDER BY" in sql
        assert "LIMIT 10" in sql

    def test_unknown_entity_raises(self) -> None:
        with pytest.raises(ValueError, match="not found"):
            self.builder.build_query(
                entities=["nonexistent"],
                measures=["nonexistent.foo"],
            )

    def test_unknown_measure_raises(self) -> None:
        with pytest.raises(ValueError, match="not found"):
            self.builder.build_query(
                entities=["transaction"],
                measures=["transaction.nonexistent_measure"],
            )


class TestQueryBuilderIntegration:
    def test_execute_against_cache(
        self, fake_connector: FakeConnector, cache_engine: LocalCacheEngine
    ) -> None:
        """Build SQL from semantic model and execute against real cache."""
        SyncEngine(fake_connector, cache_engine).sync_tables(
            ["gl_detail", "subsidiary"], mode="full"
        )

        model = load_semantic_model_string(SAMPLE_YAML)
        builder = SemanticQueryBuilder(model)

        sql = builder.build_query(
            entities=["transaction"],
            measures=["transaction.total_amount", "transaction.count"],
            group_by=["transaction.account_type"],
        )

        result = cache_engine.execute_query(QueryRequest(sql=sql))
        assert result.row_count >= 1
        assert "account_type" in result.column_names
        assert "total_amount" in result.column_names

    def test_cross_entity_join_executes(
        self, fake_connector: FakeConnector, cache_engine: LocalCacheEngine
    ) -> None:
        """Cross-entity JOIN produces valid SQL that executes."""
        SyncEngine(fake_connector, cache_engine).sync_tables(
            ["gl_detail", "subsidiary"], mode="full"
        )

        model = load_semantic_model_string(SAMPLE_YAML)
        builder = SemanticQueryBuilder(model)

        sql = builder.build_query(
            entities=["transaction"],
            measures=["transaction.total_amount"],
            group_by=["subsidiary.name"],
        )

        result = cache_engine.execute_query(QueryRequest(sql=sql))
        assert result.row_count >= 1
        assert "name" in result.column_names
