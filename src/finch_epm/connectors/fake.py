"""Fake in-memory connector for testing and interface validation.

Ships with a built-in dataset modeled after a simplified general ledger
so that tests and examples can run without any external data source.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from finch_epm.connectors.base import ConnectorBase
from finch_epm.connectors.registry import register_connector
from finch_epm.connectors.types import (
    ColumnInfo,
    ColumnType,
    DimensionInfo,
    FactResult,
    FetchPlan,
    HierarchyNode,
    SchemaInfo,
    ScopeDescription,
    TableInfo,
)


@register_connector
class FakeConnector(ConnectorBase):
    """In-memory connector for testing and interface validation.

    Default dataset:
        - ``gl_detail``: fact table (period, subsidiary_id, account_id,
          account_type, amount, memo)
        - ``subsidiary``: dimension with parent-child hierarchy
        - ``account``: dimension with parent-child hierarchy
          (types: Income, Expense)

    Pass custom data via constructor kwargs for test flexibility.
    """

    connector_type: ClassVar[str] = "fake"
    display_name: ClassVar[str] = "Fake (In-Memory)"

    def __init__(
        self,
        profile_name: str = "test",
        config: dict[str, Any] | None = None,
        *,
        tables: dict[str, TableInfo] | None = None,
        dimensions: list[DimensionInfo] | None = None,
        hierarchies: dict[str, list[HierarchyNode]] | None = None,
        fact_data: dict[str, list[list[Any]]] | None = None,
    ) -> None:
        super().__init__(profile_name, config or {})
        self._tables = tables if tables is not None else self._default_tables()
        self._dimensions = dimensions if dimensions is not None else self._default_dimensions()
        self._hierarchies = hierarchies if hierarchies is not None else self._default_hierarchies()
        self._fact_data = fact_data if fact_data is not None else self._default_fact_data()

    # --- Lifecycle ---

    def connect(self) -> None:
        self._connected = True

    def close(self) -> None:
        self._connected = False

    def validate_credentials(self) -> bool:
        return True

    # --- Schema discovery ---

    def introspect_schema(self) -> SchemaInfo:
        return SchemaInfo(
            tables=list(self._tables.values()),
            source_name="fake",
            profile_name=self.profile_name,
            introspected_at=datetime.now(),
        )

    def list_dimensions(self) -> list[DimensionInfo]:
        return list(self._dimensions)

    def get_hierarchy(self, dimension_name: str) -> list[HierarchyNode]:
        if dimension_name not in self._hierarchies:
            raise ValueError(
                f"No hierarchy for dimension: {dimension_name!r}. "
                f"Available: {sorted(self._hierarchies.keys())}"
            )
        return self._hierarchies[dimension_name]

    # --- Data fetching ---

    def plan_scope(self, scope: ScopeDescription) -> FetchPlan:
        total_rows = sum(
            len(self._fact_data.get(t, [])) for t in scope.tables
        )
        return FetchPlan(
            scope=scope,
            estimated_rows=total_rows,
            estimated_api_calls=0,
            native_plan={"engine": "in-memory"},
        )

    def fetch_facts(self, plan: FetchPlan) -> FactResult:
        if not plan.scope.tables:
            return FactResult(column_names=[], column_types=[], rows=[])

        first_table_name = plan.scope.tables[0]
        table = self._tables.get(first_table_name)
        if table is None:
            raise ValueError(f"Unknown table: {first_table_name!r}")

        col_names = [c.name for c in table.columns]
        col_types = [c.column_type for c in table.columns]

        all_rows: list[list[Any]] = []
        for table_name in plan.scope.tables:
            rows = self._fact_data.get(table_name, [])
            all_rows.extend(rows)

        if plan.scope.limit is not None:
            truncated = len(all_rows) > plan.scope.limit
            all_rows = all_rows[: plan.scope.limit]
        else:
            truncated = False

        return FactResult(
            column_names=col_names,
            column_types=col_types,
            rows=all_rows,
            total_rows_available=len(all_rows),
            watermark=datetime.now(),
            truncated=truncated,
        )

    # --- Default built-in data ---

    @staticmethod
    def _default_tables() -> dict[str, TableInfo]:
        gl_columns = [
            ColumnInfo("period", "Period", ColumnType.STRING),
            ColumnInfo("subsidiary_id", "Subsidiary", ColumnType.INTEGER),
            ColumnInfo("account_id", "Account", ColumnType.INTEGER),
            ColumnInfo("account_type", "Account Type", ColumnType.STRING),
            ColumnInfo("amount", "Amount", ColumnType.DECIMAL),
            ColumnInfo("memo", "Memo", ColumnType.TEXT, is_nullable=True),
        ]
        sub_columns = [
            ColumnInfo("id", "ID", ColumnType.INTEGER),
            ColumnInfo("name", "Name", ColumnType.STRING),
            ColumnInfo("parent_id", "Parent ID", ColumnType.INTEGER, is_nullable=True),
        ]
        acct_columns = [
            ColumnInfo("id", "ID", ColumnType.INTEGER),
            ColumnInfo("name", "Name", ColumnType.STRING),
            ColumnInfo("account_type", "Type", ColumnType.STRING),
            ColumnInfo("parent_id", "Parent ID", ColumnType.INTEGER, is_nullable=True),
        ]
        return {
            "gl_detail": TableInfo(
                "gl_detail", "GL Detail", gl_columns, row_count_estimate=500
            ),
            "subsidiary": TableInfo(
                "subsidiary", "Subsidiary", sub_columns, row_count_estimate=5
            ),
            "account": TableInfo(
                "account", "Account", acct_columns, row_count_estimate=50
            ),
        }

    @staticmethod
    def _default_dimensions() -> list[DimensionInfo]:
        return [
            DimensionInfo(
                "subsidiary", "Subsidiary", "subsidiary", "id", "name",
                supports_hierarchy=True,
            ),
            DimensionInfo(
                "account", "Account", "account", "id", "name",
                supports_hierarchy=True,
            ),
        ]

    @staticmethod
    def _default_hierarchies() -> dict[str, list[HierarchyNode]]:
        return {
            "subsidiary": [
                HierarchyNode(
                    "1", "Parent Corp", None,
                    children=[
                        HierarchyNode("2", "US Operations", "1", depth=1),
                        HierarchyNode(
                            "3", "EU Operations", "1",
                            children=[
                                HierarchyNode("4", "UK Sub", "3", depth=2),
                                HierarchyNode("5", "DE Sub", "3", depth=2),
                            ],
                            depth=1,
                        ),
                    ],
                    depth=0,
                ),
            ],
            "account": [
                HierarchyNode(
                    "100", "Income", None,
                    children=[
                        HierarchyNode("110", "Revenue", "100", depth=1),
                        HierarchyNode("120", "Other Income", "100", depth=1),
                    ],
                    depth=0,
                ),
                HierarchyNode(
                    "200", "Expense", None,
                    children=[
                        HierarchyNode("210", "COGS", "200", depth=1),
                        HierarchyNode("220", "Operating Expense", "200", depth=1),
                    ],
                    depth=0,
                ),
            ],
        }

    @staticmethod
    def _default_fact_data() -> dict[str, list[list[Any]]]:
        return {
            "gl_detail": [
                ["2024-Q1", 2, 110, "Income", 150000.00, "Q1 revenue"],
                ["2024-Q1", 2, 210, "Expense", 85000.00, "Q1 COGS"],
                ["2024-Q1", 2, 220, "Expense", 30000.00, "Q1 OpEx"],
                ["2024-Q1", 4, 110, "Income", 75000.00, "UK Q1 revenue"],
                ["2024-Q1", 5, 110, "Income", 60000.00, "DE Q1 revenue"],
                ["2024-Q2", 2, 110, "Income", 160000.00, "Q2 revenue"],
                ["2024-Q2", 2, 210, "Expense", 90000.00, "Q2 COGS"],
                ["2024-Q2", 2, 220, "Expense", 32000.00, "Q2 OpEx"],
                ["2024-Q2", 4, 110, "Income", 80000.00, "UK Q2 revenue"],
                ["2024-Q2", 5, 110, "Income", 65000.00, "DE Q2 revenue"],
            ],
            "subsidiary": [
                [1, "Parent Corp", None],
                [2, "US Operations", 1],
                [3, "EU Operations", 1],
                [4, "UK Sub", 3],
                [5, "DE Sub", 3],
            ],
            "account": [
                [100, "Income", "Income", None],
                [110, "Revenue", "Income", 100],
                [120, "Other Income", "Income", 100],
                [200, "Expense", "Expense", None],
                [210, "COGS", "Expense", 200],
                [220, "Operating Expense", "Expense", 200],
            ],
        }
