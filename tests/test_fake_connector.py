"""Tests specific to the FakeConnector's built-in data."""

from __future__ import annotations

from finch_epm.connectors.fake import FakeConnector
from finch_epm.connectors.types import ScopeDescription


class TestDefaultData:
    def test_has_three_tables(self, fake_connector: FakeConnector) -> None:
        schema = fake_connector.introspect_schema()
        names = {t.name for t in schema.tables}
        assert names == {"gl_detail", "subsidiary", "account"}

    def test_gl_detail_has_expected_columns(self, fake_connector: FakeConnector) -> None:
        schema = fake_connector.introspect_schema()
        gl = next(t for t in schema.tables if t.name == "gl_detail")
        col_names = [c.name for c in gl.columns]
        assert "period" in col_names
        assert "amount" in col_names
        assert "subsidiary_id" in col_names

    def test_gl_detail_has_rows(self, fake_connector: FakeConnector) -> None:
        scope = ScopeDescription(tables=["gl_detail"])
        plan = fake_connector.plan_scope(scope)
        result = fake_connector.fetch_facts(plan)
        assert len(result.rows) == 10

    def test_two_dimensions(self, fake_connector: FakeConnector) -> None:
        dims = fake_connector.list_dimensions()
        names = {d.name for d in dims}
        assert names == {"subsidiary", "account"}

    def test_subsidiary_hierarchy(self, fake_connector: FakeConnector) -> None:
        nodes = fake_connector.get_hierarchy("subsidiary")
        assert len(nodes) == 1  # One root: Parent Corp
        root = nodes[0]
        assert root.label == "Parent Corp"
        assert len(root.children) == 2  # US Operations, EU Operations

    def test_account_hierarchy(self, fake_connector: FakeConnector) -> None:
        nodes = fake_connector.get_hierarchy("account")
        assert len(nodes) == 2  # Income, Expense
        labels = {n.label for n in nodes}
        assert labels == {"Income", "Expense"}

    def test_source_name_is_fake(self, fake_connector: FakeConnector) -> None:
        schema = fake_connector.introspect_schema()
        assert schema.source_name == "fake"


class TestCustomData:
    def test_custom_tables(self) -> None:
        from finch_epm.connectors.types import ColumnInfo, ColumnType, TableInfo

        custom_table = TableInfo(
            "custom", "Custom",
            [ColumnInfo("id", "ID", ColumnType.INTEGER)],
        )
        conn = FakeConnector(
            tables={"custom": custom_table},
            dimensions=[],
            hierarchies={},
            fact_data={"custom": [[1], [2], [3]]},
        )
        conn.connect()
        schema = conn.introspect_schema()
        assert len(schema.tables) == 1
        assert schema.tables[0].name == "custom"

        scope = ScopeDescription(tables=["custom"])
        plan = conn.plan_scope(scope)
        result = conn.fetch_facts(plan)
        assert len(result.rows) == 3
        conn.close()
