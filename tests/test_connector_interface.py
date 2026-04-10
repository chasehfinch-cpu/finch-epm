"""Contract tests for the ConnectorBase interface.

These tests validate that any ConnectorBase implementation satisfies the
full contract. Parametrize with additional connectors as they are built.
"""

from __future__ import annotations

import pytest

from finch_epm.connectors.base import ConnectorBase
from finch_epm.connectors.fake import FakeConnector
from finch_epm.connectors.types import (
    DimensionInfo,
    FactResult,
    FetchPlan,
    HierarchyNode,
    SchemaInfo,
    ScopeDescription,
)


def _make_connectors() -> list[ConnectorBase]:
    """Instantiate all connectors that can be tested without external deps."""
    return [FakeConnector()]


@pytest.fixture(params=_make_connectors(), ids=lambda c: c.connector_type)
def connector(request: pytest.FixtureRequest) -> ConnectorBase:
    conn = request.param
    conn.connect()
    yield conn
    conn.close()


class TestConnectorLifecycle:
    def test_connect_sets_connected(self) -> None:
        conn = FakeConnector()
        assert not conn.is_connected
        conn.connect()
        assert conn.is_connected
        conn.close()
        assert not conn.is_connected

    def test_context_manager(self) -> None:
        with FakeConnector() as conn:
            assert conn.is_connected
        assert not conn.is_connected

    def test_has_class_vars(self, connector: ConnectorBase) -> None:
        assert isinstance(connector.connector_type, str)
        assert len(connector.connector_type) > 0
        assert isinstance(connector.display_name, str)
        assert len(connector.display_name) > 0

    def test_profile_name(self, connector: ConnectorBase) -> None:
        assert isinstance(connector.profile_name, str)

    def test_validate_credentials(self, connector: ConnectorBase) -> None:
        result = connector.validate_credentials()
        assert isinstance(result, bool)


class TestIntrospectSchema:
    def test_returns_schema_info(self, connector: ConnectorBase) -> None:
        schema = connector.introspect_schema()
        assert isinstance(schema, SchemaInfo)
        assert len(schema.tables) > 0
        assert isinstance(schema.source_name, str)
        assert isinstance(schema.profile_name, str)
        assert schema.introspected_at is not None

    def test_tables_have_columns(self, connector: ConnectorBase) -> None:
        schema = connector.introspect_schema()
        for table in schema.tables:
            assert len(table.columns) > 0
            assert isinstance(table.name, str)
            assert isinstance(table.display_name, str)

    def test_column_types_are_valid(self, connector: ConnectorBase) -> None:
        from finch_epm.connectors.types import ColumnType
        schema = connector.introspect_schema()
        for table in schema.tables:
            for col in table.columns:
                assert isinstance(col.column_type, ColumnType)


class TestDimensions:
    def test_list_dimensions_returns_list(self, connector: ConnectorBase) -> None:
        dims = connector.list_dimensions()
        assert isinstance(dims, list)
        for dim in dims:
            assert isinstance(dim, DimensionInfo)
            assert isinstance(dim.name, str)
            assert isinstance(dim.table_name, str)

    def test_hierarchy_for_supported_dimensions(self, connector: ConnectorBase) -> None:
        dims = connector.list_dimensions()
        hierarchical = [d for d in dims if d.supports_hierarchy]
        for dim in hierarchical:
            nodes = connector.get_hierarchy(dim.name)
            assert isinstance(nodes, list)
            assert len(nodes) > 0
            for node in nodes:
                assert isinstance(node, HierarchyNode)
                assert isinstance(node.id, str)
                assert isinstance(node.label, str)

    def test_hierarchy_raises_for_invalid_dimension(self, connector: ConnectorBase) -> None:
        with pytest.raises(ValueError):
            connector.get_hierarchy("__nonexistent_dimension__")


class TestDataFetching:
    def test_plan_scope_returns_fetch_plan(self, connector: ConnectorBase) -> None:
        schema = connector.introspect_schema()
        table_name = schema.tables[0].name
        scope = ScopeDescription(tables=[table_name])
        plan = connector.plan_scope(scope)
        assert isinstance(plan, FetchPlan)
        assert plan.scope is scope

    def test_fetch_facts_returns_result(self, connector: ConnectorBase) -> None:
        schema = connector.introspect_schema()
        table_name = schema.tables[0].name
        scope = ScopeDescription(tables=[table_name])
        plan = connector.plan_scope(scope)
        result = connector.fetch_facts(plan)
        assert isinstance(result, FactResult)
        assert len(result.column_names) > 0
        assert len(result.column_types) == len(result.column_names)

    def test_fetch_with_limit(self, connector: ConnectorBase) -> None:
        schema = connector.introspect_schema()
        table_name = schema.tables[0].name
        scope = ScopeDescription(tables=[table_name], limit=2)
        plan = connector.plan_scope(scope)
        result = connector.fetch_facts(plan)
        assert len(result.rows) <= 2

    def test_fetch_empty_tables(self, connector: ConnectorBase) -> None:
        scope = ScopeDescription(tables=[])
        plan = connector.plan_scope(scope)
        result = connector.fetch_facts(plan)
        assert len(result.rows) == 0
