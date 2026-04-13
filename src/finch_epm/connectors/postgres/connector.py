"""PostgreSQL connector via psycopg2.

Implements the ConnectorBase interface for PostgreSQL. Uses
INFORMATION_SCHEMA for introspection, same pattern as the SQL Server
connector.
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

_PG_TYPE_MAP: dict[str, ColumnType] = {
    "integer": ColumnType.INTEGER,
    "bigint": ColumnType.INTEGER,
    "smallint": ColumnType.INTEGER,
    "serial": ColumnType.INTEGER,
    "bigserial": ColumnType.INTEGER,
    "numeric": ColumnType.DECIMAL,
    "decimal": ColumnType.DECIMAL,
    "money": ColumnType.DECIMAL,
    "real": ColumnType.FLOAT,
    "double precision": ColumnType.FLOAT,
    "boolean": ColumnType.BOOLEAN,
    "date": ColumnType.DATE,
    "timestamp without time zone": ColumnType.DATETIME,
    "timestamp with time zone": ColumnType.DATETIME,
    "character varying": ColumnType.STRING,
    "character": ColumnType.STRING,
    "text": ColumnType.TEXT,
    "uuid": ColumnType.STRING,
    "json": ColumnType.TEXT,
    "jsonb": ColumnType.TEXT,
    "bytea": ColumnType.UNKNOWN,
    "interval": ColumnType.STRING,
    "inet": ColumnType.STRING,
    "cidr": ColumnType.STRING,
    "macaddr": ColumnType.STRING,
    "xml": ColumnType.TEXT,
    "point": ColumnType.UNKNOWN,
    "line": ColumnType.UNKNOWN,
    "array": ColumnType.STRING,
}

_DIMENSION_MAX_ROWS = 10000


@register_connector
class PostgresConnector(ConnectorBase):
    """PostgreSQL connector via psycopg2.

    Uses INFORMATION_SCHEMA for schema introspection and standard SQL
    for queries. Credential storage follows the same OS keychain pattern
    as all other connectors.
    """

    connector_type: ClassVar[str] = "postgres"
    display_name: ClassVar[str] = "PostgreSQL"
    source_prefix: ClassVar[str] = "pg"

    def __init__(
        self,
        profile_name: str = "default",
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(profile_name, config or {})
        self._conn: Any = None

    def connect(self) -> None:
        try:
            import psycopg2
        except ImportError:
            raise ConnectorError(
                "psycopg2 is not installed. Install with: pip install finch-epm[postgres]"
            )

        from finch_epm.connectors.postgres.auth import build_connection_params
        from finch_epm.profiles.manager import ProfileManager

        if not self.config:
            pm = ProfileManager()
            if not pm.profile_exists("postgres", self.profile_name):
                raise ConnectorAuthError(
                    f"No PostgreSQL profile '{self.profile_name}' found. "
                    "Run: finch-epm auth -c postgres -p <profile> --env-file <path>"
                )
            self.config = pm.get_config("postgres", self.profile_name)

        params = build_connection_params("postgres", self.profile_name, self.config)

        try:
            self._conn = psycopg2.connect(**params)
            self._conn.autocommit = True
            self._connected = True
        except Exception as e:
            raise ConnectorAuthError(f"PostgreSQL connection failed: {e}") from e

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
        self._ensure_connected()
        tables: list[TableInfo] = []
        cur = self._conn.cursor()

        # Get all user tables with estimated row counts
        cur.execute("""
            SELECT
                t.table_schema,
                t.table_name,
                t.table_type,
                COALESCE(c.reltuples::bigint, 0) AS row_estimate
            FROM information_schema.tables t
            LEFT JOIN pg_class c ON c.relname = t.table_name
            LEFT JOIN pg_namespace n ON n.oid = c.relnamespace
                AND n.nspname = t.table_schema
            WHERE t.table_schema NOT IN ('pg_catalog', 'information_schema')
                AND t.table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY t.table_schema, t.table_name
        """)
        table_rows = cur.fetchall()

        # Get all columns
        cur.execute("""
            SELECT
                table_schema, table_name, column_name, data_type,
                is_nullable, ordinal_position,
                character_maximum_length, numeric_precision, numeric_scale
            FROM information_schema.columns
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY table_schema, table_name, ordinal_position
        """)
        col_rows = cur.fetchall()

        columns_by_table: dict[str, list[ColumnInfo]] = {}
        for row in col_rows:
            schema_name, table_name, col_name, data_type, nullable, ordinal, *_ = row
            full_name = f"{schema_name}.{table_name}"
            col_type = _PG_TYPE_MAP.get(data_type, ColumnType.UNKNOWN)
            col = ColumnInfo(
                name=col_name,
                display_name=col_name,
                column_type=col_type,
                is_custom=False,
                is_nullable=(nullable == "YES"),
                metadata={"data_type": data_type, "ordinal_position": ordinal},
            )
            columns_by_table.setdefault(full_name, []).append(col)

        for row in table_rows:
            schema_name, table_name, table_type, row_count = row
            full_name = f"{schema_name}.{table_name}"
            display = table_name if schema_name == "public" else full_name
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
                },
            ))

        cur.close()

        return SchemaInfo(
            tables=tables,
            source_name="postgres",
            profile_name=self.profile_name,
            introspected_at=datetime.now(),
            metadata={
                "total_records": len(tables),
                "accessible": len(tables),
                "restricted": 0,
                "not_found": 0,
                "database": self.config.get("database", ""),
            },
        )

    def list_dimensions(self) -> list[DimensionInfo]:
        self._ensure_connected()
        cur = self._conn.cursor()
        dimensions: list[DimensionInfo] = []

        cur.execute("""
            SELECT
                n.nspname AS schema_name,
                c.relname AS table_name,
                c.reltuples::bigint AS row_count
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'r'
                AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                AND c.reltuples <= %s AND c.reltuples >= 0
            ORDER BY c.relname
        """, [_DIMENSION_MAX_ROWS])
        candidates = cur.fetchall()

        for schema_name, table_name, row_count in candidates:
            full_name = f"{schema_name}.{table_name}"
            cur.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
            """, [schema_name, table_name])
            cols = cur.fetchall()

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
                display = table_name if schema_name == "public" else full_name
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
                        "parent_column": "parent_id" if has_parent else None,
                        "source": "heuristic",
                    },
                ))

        cur.close()
        return dimensions

    def get_hierarchy(self, dimension_name: str) -> list[HierarchyNode]:
        self._ensure_connected()
        dims = self.list_dimensions()
        dim = next((d for d in dims if d.name == dimension_name), None)

        if dim is None:
            raise ValueError(f"Unknown dimension: {dimension_name!r}")
        if not dim.supports_hierarchy:
            raise ValueError(f"Dimension '{dimension_name}' does not support hierarchy.")

        parent_col = dim.metadata.get("parent_column", "parent_id")
        cur = self._conn.cursor()
        cur.execute(
            f'SELECT "{dim.id_column}", "{dim.label_column}", "{parent_col}" '
            f'FROM {dimension_name} ORDER BY "{dim.id_column}"'
        )
        rows = cur.fetchall()
        cur.close()

        return self._build_tree(rows)

    def plan_scope(self, scope: ScopeDescription) -> FetchPlan:
        self._ensure_connected()
        cur = self._conn.cursor()
        estimated_rows = 0
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
            native_plan={"method": "sql", "tables": list(scope.tables)},
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
            where_clauses: list[str] = []
            for key, value in plan.scope.filters.items():
                if isinstance(value, list):
                    values_str = ", ".join(f"'{v}'" for v in value)
                    where_clauses.append(f'"{key}" IN ({values_str})')
                else:
                    where_clauses.append(f'"{key}" = \'{value}\'')
            if where_clauses:
                sql += " WHERE " + " AND ".join(where_clauses)
            if plan.scope.limit:
                sql += f" LIMIT {plan.scope.limit}"

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

    @staticmethod
    def _build_tree(rows: list) -> list[HierarchyNode]:
        nodes_by_id: dict[str, dict[str, Any]] = {}
        children_map: dict[str, list[str]] = {}
        for row in rows:
            node_id = str(row[0])
            label = str(row[1]) if row[1] else ""
            parent_id = str(row[2]) if row[2] is not None else None
            nodes_by_id[node_id] = {"id": node_id, "label": label, "parent_id": parent_id}
            if parent_id:
                children_map.setdefault(parent_id, []).append(node_id)

        def _build(nid: str, depth: int = 0) -> HierarchyNode:
            info = nodes_by_id[nid]
            children = [_build(cid, depth + 1) for cid in children_map.get(nid, [])]
            return HierarchyNode(id=info["id"], label=info["label"], parent_id=info["parent_id"], children=children, depth=depth)

        roots = [nid for nid, info in nodes_by_id.items()
                 if info["parent_id"] is None or info["parent_id"] not in nodes_by_id]
        return [_build(rid) for rid in roots]
