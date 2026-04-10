"""Generic ODBC connector.

Works with any data source that has an ODBC driver: OneStream, SAP,
Oracle, Access, custom applications. Users provide the ODBC connection
string and the connector handles introspection and data fetching.

Uses pyodbc (same as SQL Server connector) but with a user-supplied
connection string instead of building one from known parameters.
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

# Generic type mapping -- covers most ODBC sources
_ODBC_TYPE_MAP: dict[str, ColumnType] = {
    "int": ColumnType.INTEGER,
    "integer": ColumnType.INTEGER,
    "bigint": ColumnType.INTEGER,
    "smallint": ColumnType.INTEGER,
    "tinyint": ColumnType.INTEGER,
    "bit": ColumnType.BOOLEAN,
    "decimal": ColumnType.DECIMAL,
    "numeric": ColumnType.DECIMAL,
    "money": ColumnType.DECIMAL,
    "float": ColumnType.FLOAT,
    "real": ColumnType.FLOAT,
    "double": ColumnType.FLOAT,
    "date": ColumnType.DATE,
    "datetime": ColumnType.DATETIME,
    "datetime2": ColumnType.DATETIME,
    "timestamp": ColumnType.DATETIME,
    "char": ColumnType.STRING,
    "varchar": ColumnType.STRING,
    "nchar": ColumnType.STRING,
    "nvarchar": ColumnType.STRING,
    "text": ColumnType.TEXT,
    "ntext": ColumnType.TEXT,
    "clob": ColumnType.TEXT,
    "number": ColumnType.DECIMAL,
    "varchar2": ColumnType.STRING,
    "nvarchar2": ColumnType.STRING,
}


@register_connector
class OdbcConnector(ConnectorBase):
    """Generic ODBC connector for any ODBC-accessible data source.

    Config fields:
        connection_string: Full ODBC connection string
        driver: ODBC driver name (if not in connection_string)

    Secret fields (in keychain):
        password: Password (appended to connection_string if present)

    Use this for OneStream, SAP, Oracle, or any system with an ODBC driver.
    """

    connector_type: ClassVar[str] = "odbc"
    display_name: ClassVar[str] = "ODBC (Generic)"

    def __init__(
        self,
        profile_name: str = "default",
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(profile_name, config or {})
        self._conn: Any = None

    def connect(self) -> None:
        try:
            import pyodbc
        except ImportError:
            raise ConnectorError(
                "pyodbc is not installed. Install with: pip install pyodbc"
            )

        from finch_epm.profiles.manager import ProfileManager

        if not self.config:
            pm = ProfileManager()
            if not pm.profile_exists("odbc", self.profile_name):
                raise ConnectorAuthError(
                    f"No ODBC profile '{self.profile_name}' found. "
                    "Run: finch-epm auth -c odbc -p <profile> --env-file <path>"
                )
            self.config = pm.get_config("odbc", self.profile_name)

        conn_str = self.config.get("connection_string", "")

        # Append password from keychain if available
        pm = ProfileManager()
        password = pm.get_secret("odbc", self.profile_name, "password")
        if password and "PWD=" not in conn_str.upper():
            conn_str += f";PWD={password}"

        try:
            self._conn = pyodbc.connect(conn_str, timeout=30)
            self._connected = True
        except Exception as e:
            raise ConnectorAuthError(f"ODBC connection failed: {e}") from e

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
                cur = self._conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
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
        """Discover tables using pyodbc.cursor.tables() (ODBC standard)."""
        self._ensure_connected()
        tables: list[TableInfo] = []
        cur = self._conn.cursor()

        # Use ODBC catalog functions (works for any ODBC source)
        for row in cur.tables(tableType="TABLE"):
            schema_name = row.table_schem or ""
            table_name = row.table_name or ""
            full_name = f"{schema_name}.{table_name}" if schema_name else table_name

            # Discover columns
            columns: list[ColumnInfo] = []
            try:
                for col_row in cur.columns(table=table_name, schema=schema_name):
                    col_type = _ODBC_TYPE_MAP.get(
                        (col_row.type_name or "").lower(), ColumnType.UNKNOWN
                    )
                    columns.append(ColumnInfo(
                        name=col_row.column_name,
                        display_name=col_row.column_name,
                        column_type=col_type,
                        is_nullable=(col_row.nullable == 1),
                    ))
            except Exception:
                pass

            tables.append(TableInfo(
                name=full_name,
                display_name=full_name,
                columns=columns,
                metadata={"access_status": "accessible", "category": "table"},
            ))

        cur.close()

        return SchemaInfo(
            tables=tables,
            source_name="odbc",
            profile_name=self.profile_name,
            introspected_at=datetime.now(),
            metadata={
                "total_records": len(tables),
                "accessible": len(tables),
                "restricted": 0,
                "not_found": 0,
            },
        )

    def list_dimensions(self) -> list[DimensionInfo]:
        # ODBC has no standard dimension discovery -- return empty
        return []

    def get_hierarchy(self, dimension_name: str) -> list[HierarchyNode]:
        raise ValueError(f"Hierarchy not supported for generic ODBC connector.")

    def plan_scope(self, scope: ScopeDescription) -> FetchPlan:
        self._ensure_connected()
        estimated_rows = 0
        cur = self._conn.cursor()
        for table_name in scope.tables:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table_name}")
                estimated_rows += cur.fetchone()[0]
            except Exception:
                pass
        cur.close()

        return FetchPlan(
            scope=scope,
            estimated_rows=estimated_rows,
            estimated_api_calls=len(scope.tables),
            native_plan={"method": "odbc"},
        )

    def fetch_facts(self, plan: FetchPlan) -> FactResult:
        self._ensure_connected()
        if not plan.scope.tables:
            return FactResult(column_names=[], column_types=[], rows=[])

        cur = self._conn.cursor()
        all_column_names: list[str] = []
        all_column_types: list[ColumnType] = []
        all_rows: list[list[Any]] = []

        for table_name in plan.scope.tables:
            sql = f"SELECT * FROM {table_name}"
            if plan.scope.limit:
                # Try standard LIMIT; fall back to TOP for SQL Server-like sources
                sql += f" FETCH FIRST {plan.scope.limit} ROWS ONLY"

            try:
                cur.execute(sql)
                if not all_column_names:
                    all_column_names = [desc[0] for desc in cur.description]
                    all_column_types = [ColumnType.STRING] * len(all_column_names)
                for row in cur.fetchall():
                    all_rows.append([str(v) if v is not None else None for v in row])
            except Exception as e:
                logger.warning("Failed to fetch from %s: %s", table_name, e)

        cur.close()

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
