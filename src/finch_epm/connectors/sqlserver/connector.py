"""SQL Server connector via pyodbc.

Implements the ConnectorBase interface for SQL Server and Azure SQL.
Uses INFORMATION_SCHEMA for introspection and standard T-SQL for queries.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, ClassVar

from finch_epm.connectors.base import ConnectorAuthError, ConnectorBase, ConnectorError
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

logger = logging.getLogger(__name__)

# Mapping from SQL Server data types to ColumnType
_SQL_TYPE_MAP: dict[str, ColumnType] = {
    "int": ColumnType.INTEGER,
    "bigint": ColumnType.INTEGER,
    "smallint": ColumnType.INTEGER,
    "tinyint": ColumnType.INTEGER,
    "bit": ColumnType.BOOLEAN,
    "decimal": ColumnType.DECIMAL,
    "numeric": ColumnType.DECIMAL,
    "money": ColumnType.DECIMAL,
    "smallmoney": ColumnType.DECIMAL,
    "float": ColumnType.FLOAT,
    "real": ColumnType.FLOAT,
    "date": ColumnType.DATE,
    "datetime": ColumnType.DATETIME,
    "datetime2": ColumnType.DATETIME,
    "smalldatetime": ColumnType.DATETIME,
    "datetimeoffset": ColumnType.DATETIME,
    "time": ColumnType.STRING,
    "char": ColumnType.STRING,
    "varchar": ColumnType.STRING,
    "nchar": ColumnType.STRING,
    "nvarchar": ColumnType.STRING,
    "text": ColumnType.TEXT,
    "ntext": ColumnType.TEXT,
    "binary": ColumnType.UNKNOWN,
    "varbinary": ColumnType.UNKNOWN,
    "image": ColumnType.UNKNOWN,
    "uniqueidentifier": ColumnType.STRING,
    "xml": ColumnType.TEXT,
}

# Row count threshold for dimension heuristic
_DIMENSION_MAX_ROWS = 10000


@register_connector
class SqlServerConnector(ConnectorBase):
    """SQL Server / Azure SQL connector via pyodbc.

    Uses INFORMATION_SCHEMA for schema introspection and T-SQL for queries.
    Credentials stored in OS keychain; connection config in profiles.json.
    """

    connector_type: ClassVar[str] = "sqlserver"
    display_name: ClassVar[str] = "SQL Server"

    def __init__(
        self,
        profile_name: str = "default",
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(profile_name, config or {})
        self._conn: Any = None  # pyodbc.Connection

    def connect(self) -> None:
        """Connect using stored credentials from the OS keychain."""
        try:
            import pyodbc
        except ImportError:
            raise ConnectorError(
                "pyodbc is not installed. Install with: pip install finch-epm[sqlserver]"
            )

        from finch_epm.connectors.sqlserver.auth import build_connection_string
        from finch_epm.profiles.manager import ProfileManager

        if not self.config:
            pm = ProfileManager()
            if not pm.profile_exists("sqlserver", self.profile_name):
                raise ConnectorAuthError(
                    f"No SQL Server profile '{self.profile_name}' found. "
                    "Run: finch-epm auth -c sqlserver -p <profile> --env-file <path>"
                )
            self.config = pm.get_config("sqlserver", self.profile_name)

        conn_str = build_connection_string("sqlserver", self.profile_name, self.config)

        try:
            self._conn = pyodbc.connect(conn_str, timeout=30)
            self._connected = True
        except pyodbc.Error as e:
            raise ConnectorAuthError(f"SQL Server connection failed: {e}") from e

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        self._connected = False

    def validate_credentials(self) -> bool:
        if self._conn is not None:
            try:
                cursor = self._conn.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
                return True
            except Exception:
                return False
        try:
            self.connect()
            result = self.validate_credentials()
            self.close()
            return result
        except ConnectorAuthError:
            return False

    def introspect_schema(self) -> SchemaInfo:
        """Discover all tables and columns via INFORMATION_SCHEMA."""
        self._ensure_connected()

        tables: list[TableInfo] = []
        cursor = self._conn.cursor()

        # Get all user tables with row counts
        cursor.execute("""
            SELECT
                t.TABLE_SCHEMA,
                t.TABLE_NAME,
                t.TABLE_TYPE,
                p.rows AS row_count
            FROM INFORMATION_SCHEMA.TABLES t
            LEFT JOIN sys.tables st
                ON st.name = t.TABLE_NAME
                AND SCHEMA_NAME(st.schema_id) = t.TABLE_SCHEMA
            LEFT JOIN sys.partitions p
                ON p.object_id = st.object_id AND p.index_id IN (0, 1)
            WHERE t.TABLE_TYPE IN ('BASE TABLE', 'VIEW')
            ORDER BY t.TABLE_SCHEMA, t.TABLE_NAME
        """)
        table_rows = cursor.fetchall()

        # Get all columns
        cursor.execute("""
            SELECT
                TABLE_SCHEMA,
                TABLE_NAME,
                COLUMN_NAME,
                DATA_TYPE,
                IS_NULLABLE,
                ORDINAL_POSITION,
                CHARACTER_MAXIMUM_LENGTH,
                NUMERIC_PRECISION,
                NUMERIC_SCALE
            FROM INFORMATION_SCHEMA.COLUMNS
            ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
        """)
        col_rows = cursor.fetchall()

        # Build column lookup: (schema.table) -> list of ColumnInfo
        columns_by_table: dict[str, list[ColumnInfo]] = {}
        for row in col_rows:
            schema_name, table_name, col_name, data_type, nullable, ordinal, char_len, num_prec, num_scale = row
            full_name = f"{schema_name}.{table_name}"
            col_type = _SQL_TYPE_MAP.get(data_type.lower(), ColumnType.UNKNOWN)

            col = ColumnInfo(
                name=col_name,
                display_name=col_name,
                column_type=col_type,
                is_custom=False,
                is_nullable=(nullable == "YES"),
                metadata={
                    "data_type": data_type,
                    "ordinal_position": ordinal,
                },
            )
            columns_by_table.setdefault(full_name, []).append(col)

        # Build tables
        for row in table_rows:
            schema_name, table_name, table_type, row_count = row
            full_name = f"{schema_name}.{table_name}"
            display = f"{schema_name}.{table_name}" if schema_name != "dbo" else table_name
            columns = columns_by_table.get(full_name, [])

            tables.append(TableInfo(
                name=full_name,
                display_name=display,
                columns=columns,
                is_custom=False,
                row_count_estimate=int(row_count) if row_count else None,
                metadata={
                    "access_status": "accessible",
                    "category": "view" if table_type == "VIEW" else "table",
                    "schema": schema_name,
                    "table_type": table_type,
                },
            ))

        cursor.close()

        return SchemaInfo(
            tables=tables,
            source_name="sqlserver",
            profile_name=self.profile_name,
            introspected_at=datetime.now(),
            metadata={
                "total_records": len(tables),
                "accessible": len(tables),
                "restricted": 0,
                "not_found": 0,
                "database": self.config.get("database", ""),
                "server": self.config.get("server", ""),
            },
        )

    def list_dimensions(self) -> list[DimensionInfo]:
        """Identify dimension-like tables using heuristics.

        A table is treated as a dimension if:
        - It has fewer than _DIMENSION_MAX_ROWS rows
        - It has an 'id' or identity column
        - It has a 'name' or descriptive string column
        """
        self._ensure_connected()
        cursor = self._conn.cursor()

        dimensions: list[DimensionInfo] = []

        cursor.execute("""
            SELECT
                SCHEMA_NAME(t.schema_id) AS schema_name,
                t.name AS table_name,
                p.rows AS row_count
            FROM sys.tables t
            JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0, 1)
            WHERE p.rows <= ?
            ORDER BY t.name
        """, [_DIMENSION_MAX_ROWS])

        candidates = cursor.fetchall()

        for schema_name, table_name, row_count in candidates:
            full_name = f"{schema_name}.{table_name}"

            # Check for id and name-like columns
            cursor.execute("""
                SELECT COLUMN_NAME, DATA_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
                ORDER BY ORDINAL_POSITION
            """, [schema_name, table_name])
            cols = cursor.fetchall()

            id_col = None
            label_col = None
            has_parent = False

            for col_name, data_type in cols:
                lower = col_name.lower()
                if lower in ("id", table_name.lower() + "id", table_name.lower() + "_id"):
                    id_col = col_name
                if lower in ("name", "description", "title", "label",
                             table_name.lower() + "name", table_name.lower() + "_name"):
                    label_col = col_name
                if lower in ("parentid", "parent_id", "parent"):
                    has_parent = True

            if id_col and label_col:
                display = table_name if schema_name == "dbo" else full_name
                dimensions.append(DimensionInfo(
                    name=full_name,
                    display_name=display,
                    table_name=full_name,
                    id_column=id_col,
                    label_column=label_col,
                    supports_hierarchy=has_parent,
                    metadata={
                        "access_status": "accessible",
                        "row_count": int(row_count),
                        "parent_column": "parentid" if has_parent else None,
                        "source": "heuristic",
                    },
                ))

        cursor.close()
        return dimensions

    def get_hierarchy(self, dimension_name: str) -> list[HierarchyNode]:
        """Fetch parent-child hierarchy from a dimension table."""
        self._ensure_connected()

        # Find the dimension info
        dims = self.list_dimensions()
        dim = None
        for d in dims:
            if d.name == dimension_name:
                dim = d
                break

        if dim is None:
            raise ValueError(f"Unknown dimension: {dimension_name!r}")

        if not dim.supports_hierarchy:
            raise ValueError(f"Dimension '{dimension_name}' does not support hierarchy.")

        parent_col = dim.metadata.get("parent_column", "parentid")
        cursor = self._conn.cursor()
        cursor.execute(
            f"SELECT [{dim.id_column}], [{dim.label_column}], [{parent_col}] "
            f"FROM [{dimension_name}] ORDER BY [{dim.id_column}]"
        )
        rows = cursor.fetchall()
        cursor.close()

        return self._build_tree(rows)

    def plan_scope(self, scope: ScopeDescription) -> FetchPlan:
        self._ensure_connected()
        cursor = self._conn.cursor()

        estimated_rows = 0
        estimated_calls = 0
        for table_name in scope.tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM [{table_name}]")
                count = cursor.fetchone()[0]
                estimated_rows += count
                estimated_calls += 1
            except Exception:
                estimated_calls += 1

        cursor.close()

        return FetchPlan(
            scope=scope,
            estimated_rows=estimated_rows,
            estimated_api_calls=estimated_calls,
            native_plan={"method": "tsql", "tables": list(scope.tables)},
        )

    def fetch_facts(self, plan: FetchPlan) -> FactResult:
        self._ensure_connected()

        if not plan.scope.tables:
            return FactResult(column_names=[], column_types=[], rows=[])

        cursor = self._conn.cursor()
        all_column_names: list[str] = []
        all_column_types: list[ColumnType] = []
        all_rows: list[list[Any]] = []

        for table_name in plan.scope.tables:
            sql = f"SELECT * FROM [{table_name}]"

            where_clauses: list[str] = []
            for key, value in plan.scope.filters.items():
                if isinstance(value, list):
                    values_str = ", ".join(f"'{v}'" for v in value)
                    where_clauses.append(f"[{key}] IN ({values_str})")
                else:
                    where_clauses.append(f"[{key}] = '{value}'")

            if where_clauses:
                sql += " WHERE " + " AND ".join(where_clauses)

            if plan.scope.limit:
                sql = sql.replace("SELECT *", f"SELECT TOP {plan.scope.limit} *")

            try:
                cursor.execute(sql)
                if not all_column_names:
                    all_column_names = [desc[0] for desc in cursor.description]
                    all_column_types = [ColumnType.STRING] * len(all_column_names)

                for row in cursor.fetchall():
                    all_rows.append(list(row))
            except Exception as e:
                logger.warning("Failed to fetch from %s: %s", table_name, e)

        cursor.close()

        return FactResult(
            column_names=all_column_names,
            column_types=all_column_types,
            rows=all_rows,
            total_rows_available=len(all_rows),
            watermark=datetime.now(),
        )

    def _ensure_connected(self) -> None:
        if not self._connected or self._conn is None:
            raise ConnectorError("Not connected. Call connect() first.")

    @staticmethod
    def _build_tree(rows: list) -> list[HierarchyNode]:
        """Build hierarchy tree from pyodbc rows (id, label, parent_id)."""
        nodes_by_id: dict[str, dict[str, Any]] = {}
        children_map: dict[str, list[str]] = {}

        for row in rows:
            node_id = str(row[0])
            label = str(row[1]) if row[1] else ""
            parent_id = str(row[2]) if row[2] is not None else None

            nodes_by_id[node_id] = {
                "id": node_id,
                "label": label,
                "parent_id": parent_id,
            }
            if parent_id:
                children_map.setdefault(parent_id, []).append(node_id)

        def _build_node(node_id: str, depth: int = 0) -> HierarchyNode:
            info = nodes_by_id[node_id]
            child_ids = children_map.get(node_id, [])
            children = [_build_node(cid, depth + 1) for cid in child_ids]
            return HierarchyNode(
                id=info["id"],
                label=info["label"],
                parent_id=info["parent_id"],
                children=children,
                depth=depth,
            )

        roots = [
            nid for nid, info in nodes_by_id.items()
            if info["parent_id"] is None or info["parent_id"] not in nodes_by_id
        ]

        return [_build_node(rid) for rid in roots]
