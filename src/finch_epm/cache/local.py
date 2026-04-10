"""Local DuckDB-backed cache engine.

This is the v0.1 implementation of CacheEngine. Stores fact data locally
and tracks sync watermarks for incremental refresh.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import duckdb

from finch_epm.cache.base import CacheEngine
from finch_epm.cache.models import (
    QueryRequest,
    QueryResult,
    StalenessInfo,
    StalenessLevel,
    SyncWatermark,
)

# Mapping from finch-epm ColumnType string names to DuckDB SQL types
_TYPE_MAP: dict[str, str] = {
    "string": "VARCHAR",
    "integer": "BIGINT",
    "float": "DOUBLE",
    "decimal": "DECIMAL(18,2)",
    "boolean": "BOOLEAN",
    "date": "DATE",
    "datetime": "TIMESTAMP",
    "text": "VARCHAR",
    "reference": "VARCHAR",
    "unknown": "VARCHAR",
}


class LocalCacheEngine(CacheEngine):
    """DuckDB-backed local cache engine.

    Args:
        db_path: Path to the DuckDB database file. Use ``":memory:"`` for
            in-memory databases (useful for testing).
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._conn = duckdb.connect(db_path)
        self._ensure_watermark_table()

    def _ensure_watermark_table(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS _finch_watermarks (
                source_name VARCHAR NOT NULL,
                profile_name VARCHAR NOT NULL,
                table_name VARCHAR NOT NULL,
                last_synced_at TIMESTAMP NOT NULL,
                last_modified_value VARCHAR,
                row_count BIGINT DEFAULT 0,
                PRIMARY KEY (source_name, profile_name, table_name)
            )
        """)

    def close(self) -> None:
        """Close the DuckDB connection."""
        self._conn.close()

    def execute_query(self, request: QueryRequest) -> QueryResult:
        start = time.monotonic()
        try:
            if request.parameters:
                result = self._conn.execute(request.sql, list(request.parameters.values()))
            else:
                result = self._conn.execute(request.sql)

            columns = result.description or []
            column_names = [col[0] for col in columns]
            column_types = [col[1] for col in columns]
            rows = [list(row) for row in result.fetchall()]
        except duckdb.CatalogException:
            # Table doesn't exist — return empty result with MISSING staleness
            elapsed = (time.monotonic() - start) * 1000
            return QueryResult(
                column_names=[],
                column_types=[],
                rows=[],
                row_count=0,
                staleness=StalenessInfo(level=StalenessLevel.MISSING),
                execution_time_ms=elapsed,
            )

        elapsed = (time.monotonic() - start) * 1000

        # Extract table names from the query for staleness check (best-effort)
        staleness = StalenessInfo(level=StalenessLevel.FRESH)

        return QueryResult(
            column_names=column_names,
            column_types=column_types,
            rows=rows,
            row_count=len(rows),
            staleness=staleness,
            execution_time_ms=elapsed,
            served_from="local",
        )

    def get_staleness(
        self,
        tables: list[str],
        source_name: str,
        freshness_threshold: timedelta = timedelta(hours=1),
    ) -> StalenessInfo:
        if not tables:
            return StalenessInfo(level=StalenessLevel.MISSING)

        placeholders = ", ".join(["?"] * len(tables))
        result = self._conn.execute(
            f"""
            SELECT table_name, last_synced_at
            FROM _finch_watermarks
            WHERE source_name = ? AND table_name IN ({placeholders})
            """,
            [source_name, *tables],
        ).fetchall()

        if not result:
            return StalenessInfo(
                level=StalenessLevel.MISSING,
                tables_involved=tables,
            )

        synced_tables = {row[0]: row[1] for row in result}
        missing_tables = [t for t in tables if t not in synced_tables]

        if missing_tables:
            return StalenessInfo(
                level=StalenessLevel.MISSING,
                tables_involved=tables,
            )

        sync_times = list(synced_tables.values())
        oldest = min(sync_times)
        newest = max(sync_times)
        # All stored timestamps are naive UTC (stripped on write)
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        level = (
            StalenessLevel.FRESH
            if (now - oldest) <= freshness_threshold
            else StalenessLevel.STALE
        )

        return StalenessInfo(
            level=level,
            last_synced_at=newest,
            tables_involved=tables,
            oldest_table_sync=oldest,
        )

    def get_watermark(
        self, source_name: str, profile_name: str, table_name: str
    ) -> SyncWatermark | None:
        result = self._conn.execute(
            """
            SELECT last_synced_at, last_modified_value, row_count
            FROM _finch_watermarks
            WHERE source_name = ? AND profile_name = ? AND table_name = ?
            """,
            [source_name, profile_name, table_name],
        ).fetchone()

        if result is None:
            return None

        return SyncWatermark(
            source_name=source_name,
            profile_name=profile_name,
            table_name=table_name,
            last_synced_at=result[0],
            last_modified_value=result[1],
            row_count=result[2],
        )

    def update_watermark(self, watermark: SyncWatermark) -> None:
        # Store as naive UTC — strip tzinfo before writing to DuckDB TIMESTAMP
        ts = watermark.last_synced_at
        if ts.tzinfo is not None:
            ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
        self._conn.execute(
            """
            INSERT OR REPLACE INTO _finch_watermarks
                (source_name, profile_name, table_name, last_synced_at,
                 last_modified_value, row_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                watermark.source_name,
                watermark.profile_name,
                watermark.table_name,
                ts,
                watermark.last_modified_value,
                watermark.row_count,
            ],
        )

    def ingest_facts(
        self,
        table_name: str,
        column_names: list[str],
        column_types: list[str],
        rows: list[list[Any]],
        mode: str = "append",
    ) -> int:
        if not rows:
            return 0

        duck_types = [_TYPE_MAP.get(ct, "VARCHAR") for ct in column_types]

        if mode == "replace" and self.has_table(table_name):
            self._conn.execute(f"DROP TABLE IF EXISTS {table_name}")

        if not self.has_table(table_name):
            col_defs = ", ".join(
                f"{name} {dtype}" for name, dtype in zip(column_names, duck_types)
            )
            self._conn.execute(f"CREATE TABLE {table_name} ({col_defs})")

        placeholders = ", ".join(["?"] * len(column_names))
        col_list = ", ".join(column_names)
        insert_sql = f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders})"

        for row in rows:
            self._conn.execute(insert_sql, row)

        return len(rows)

    def has_table(self, table_name: str) -> bool:
        result = self._conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
            [table_name],
        ).fetchone()
        return result is not None and result[0] > 0
