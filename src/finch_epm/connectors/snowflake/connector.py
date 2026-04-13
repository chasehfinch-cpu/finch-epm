"""Snowflake connector via snowflake-connector-python.

Implements ConnectorBase for Snowflake. Uses INFORMATION_SCHEMA for
introspection and standard SQL for queries.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, ClassVar

from finch_epm.connectors.base import ConnectorAuthError, ConnectorBase, ConnectorError
from finch_epm.connectors.registry import register_connector
from finch_epm.connectors.types import (
    ColumnInfo, ColumnType, DimensionInfo, FactResult, FetchPlan,
    HierarchyNode, SchemaInfo, ScopeDescription, TableInfo,
)

logger = logging.getLogger(__name__)

_SF_TYPE_MAP: dict[str, ColumnType] = {
    "NUMBER": ColumnType.DECIMAL,
    "DECIMAL": ColumnType.DECIMAL,
    "NUMERIC": ColumnType.DECIMAL,
    "INT": ColumnType.INTEGER,
    "INTEGER": ColumnType.INTEGER,
    "BIGINT": ColumnType.INTEGER,
    "SMALLINT": ColumnType.INTEGER,
    "TINYINT": ColumnType.INTEGER,
    "FLOAT": ColumnType.FLOAT,
    "FLOAT4": ColumnType.FLOAT,
    "FLOAT8": ColumnType.FLOAT,
    "DOUBLE": ColumnType.FLOAT,
    "REAL": ColumnType.FLOAT,
    "BOOLEAN": ColumnType.BOOLEAN,
    "DATE": ColumnType.DATE,
    "DATETIME": ColumnType.DATETIME,
    "TIMESTAMP": ColumnType.DATETIME,
    "TIMESTAMP_LTZ": ColumnType.DATETIME,
    "TIMESTAMP_NTZ": ColumnType.DATETIME,
    "TIMESTAMP_TZ": ColumnType.DATETIME,
    "TIME": ColumnType.STRING,
    "VARCHAR": ColumnType.STRING,
    "CHAR": ColumnType.STRING,
    "STRING": ColumnType.STRING,
    "TEXT": ColumnType.TEXT,
    "BINARY": ColumnType.UNKNOWN,
    "VARBINARY": ColumnType.UNKNOWN,
    "VARIANT": ColumnType.TEXT,
    "OBJECT": ColumnType.TEXT,
    "ARRAY": ColumnType.TEXT,
}


@register_connector
class SnowflakeConnector(ConnectorBase):
    """Snowflake connector.

    Config fields:
        account: Snowflake account identifier (e.g., xy12345.us-east-1)
        warehouse: Compute warehouse name
        database: Database name
        schema: Schema name (default: PUBLIC)
        username: Login username

    Secret fields (in keychain):
        password: Login password
    """

    connector_type: ClassVar[str] = "snowflake"
    display_name: ClassVar[str] = "Snowflake"
    source_prefix: ClassVar[str] = "sf"

    def __init__(self, profile_name: str = "default", config: dict[str, Any] | None = None) -> None:
        super().__init__(profile_name, config or {})
        self._conn: Any = None

    def connect(self) -> None:
        try:
            import snowflake.connector
        except ImportError:
            raise ConnectorError(
                "snowflake-connector-python is not installed. "
                "Install with: pip install finch-epm[snowflake]"
            )

        from finch_epm.profiles.manager import ProfileManager
        if not self.config:
            pm = ProfileManager()
            if not pm.profile_exists("snowflake", self.profile_name):
                raise ConnectorAuthError(f"No Snowflake profile '{self.profile_name}' found.")
            self.config = pm.get_config("snowflake", self.profile_name)

        pm = ProfileManager()
        password = pm.get_secret("snowflake", self.profile_name, "password")
        if not password:
            raise ConnectorAuthError("Password not found in OS keychain for Snowflake.")

        try:
            self._conn = snowflake.connector.connect(
                account=self.config.get("account", ""),
                user=self.config.get("username", ""),
                password=password,
                warehouse=self.config.get("warehouse", ""),
                database=self.config.get("database", ""),
                schema=self.config.get("schema", "PUBLIC"),
            )
            self._connected = True
        except Exception as e:
            raise ConnectorAuthError(f"Snowflake connection failed: {e}") from e

    def close(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        self._connected = False

    def validate_credentials(self) -> bool:
        if self._conn:
            try:
                cur = self._conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
                return True
            except Exception:
                return False
        try:
            self.connect()
            r = self.validate_credentials()
            self.close()
            return r
        except ConnectorAuthError:
            return False

    def introspect_schema(self) -> SchemaInfo:
        self._ensure_connected()
        tables: list[TableInfo] = []
        cur = self._conn.cursor()

        cur.execute("""
            SELECT table_schema, table_name, table_type, row_count
            FROM information_schema.tables
            WHERE table_schema NOT IN ('INFORMATION_SCHEMA')
            ORDER BY table_schema, table_name
        """)
        table_rows = cur.fetchall()

        cur.execute("""
            SELECT table_schema, table_name, column_name, data_type,
                   is_nullable, ordinal_position
            FROM information_schema.columns
            WHERE table_schema NOT IN ('INFORMATION_SCHEMA')
            ORDER BY table_schema, table_name, ordinal_position
        """)
        col_rows = cur.fetchall()

        columns_by_table: dict[str, list[ColumnInfo]] = {}
        for row in col_rows:
            schema_name, table_name, col_name, data_type, nullable, ordinal = row
            full_name = f"{schema_name}.{table_name}"
            col_type = _SF_TYPE_MAP.get(data_type.upper(), ColumnType.UNKNOWN)
            columns_by_table.setdefault(full_name, []).append(ColumnInfo(
                name=col_name, display_name=col_name, column_type=col_type,
                is_nullable=(nullable == "YES"),
            ))

        for row in table_rows:
            schema_name, table_name, table_type, row_count = row
            full_name = f"{schema_name}.{table_name}"
            display = table_name if schema_name == "PUBLIC" else full_name
            tables.append(TableInfo(
                name=full_name, display_name=display,
                columns=columns_by_table.get(full_name, []),
                row_count_estimate=int(row_count) if row_count else None,
                metadata={"access_status": "accessible", "category": table_type.lower()},
            ))

        cur.close()
        return SchemaInfo(
            tables=tables, source_name="snowflake", profile_name=self.profile_name,
            introspected_at=datetime.now(),
            metadata={"total_records": len(tables), "accessible": len(tables), "restricted": 0, "not_found": 0},
        )

    def list_dimensions(self) -> list[DimensionInfo]:
        return []

    def get_hierarchy(self, dimension_name: str) -> list[HierarchyNode]:
        raise ValueError("Hierarchy not supported for Snowflake connector.")

    def plan_scope(self, scope: ScopeDescription) -> FetchPlan:
        self._ensure_connected()
        cur = self._conn.cursor()
        est = 0
        for t in scope.tables:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {t}")
                est += cur.fetchone()[0]
            except Exception:
                pass
        cur.close()
        return FetchPlan(scope=scope, estimated_rows=est, estimated_api_calls=len(scope.tables), native_plan={"method": "snowflake"})

    def fetch_facts(self, plan: FetchPlan) -> FactResult:
        self._ensure_connected()
        if not plan.scope.tables:
            return FactResult(column_names=[], column_types=[], rows=[])
        cur = self._conn.cursor()
        cols: list[str] = []
        types: list[ColumnType] = []
        rows: list[list[Any]] = []
        for t in plan.scope.tables:
            sql = f"SELECT * FROM {t}"
            if plan.scope.limit:
                sql += f" LIMIT {plan.scope.limit}"
            try:
                cur.execute(sql)
                if not cols:
                    cols = [d[0] for d in cur.description]
                    types = [ColumnType.STRING] * len(cols)
                for row in cur.fetchall():
                    rows.append([str(v) if v is not None else None for v in row])
            except Exception as e:
                logger.warning("Snowflake fetch failed for %s: %s", t, e)
        cur.close()
        return FactResult(column_names=cols, column_types=types, rows=rows, total_rows_available=len(rows), watermark=datetime.now())

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise ConnectorError("Not connected.")
