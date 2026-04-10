"""Incremental sync orchestrator.

Pulls data from connectors into the local DuckDB cache, table by table,
with watermark-based incremental sync and progress reporting.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable

from finch_epm.cache.local import LocalCacheEngine
from finch_epm.cache.models import SyncReport, SyncWatermark, TableSyncResult
from finch_epm.connectors.base import ConnectorBase, ConnectorError
from finch_epm.connectors.types import ScopeDescription

logger = logging.getLogger(__name__)


def _sanitize_cache_table_name(name: str) -> str:
    """Sanitize a source table name for use as a DuckDB table name.

    SQL Server tables like 'dbo.RCMSiteMaster' contain dots which DuckDB
    interprets as schema qualifiers. Replace dots with double underscores.
    """
    return name.replace(".", "__")


class SyncEngine:
    """Orchestrates data sync from a connector into the local DuckDB cache.

    Syncs table by table so partial failures preserve already-synced data.
    Watermarks enable incremental sync where the source supports
    ``lastmodifieddate``.

    Usage::

        with NetSuiteConnector("production") as conn:
            cache = LocalCacheEngine(str(cache_db_path()))
            engine = SyncEngine(conn, cache)
            report = engine.sync_tables(["Account", "Subsidiary"], mode="full")
            print(f"Synced {report.total_rows} rows")
    """

    def __init__(
        self,
        connector: ConnectorBase,
        cache: LocalCacheEngine,
        catalog: Any | None = None,
    ) -> None:
        """Initialize the sync engine.

        Args:
            connector: Must already be connected.
            cache: The cache engine to ingest data into.
            catalog: Optional CatalogStore for ``sync_all_accessible()``.
        """
        self._connector = connector
        self._cache = cache
        self._catalog = catalog

    def sync_tables(
        self,
        table_names: list[str],
        mode: str = "incremental",
        progress_callback: Callable[[str, int], None] | None = None,
    ) -> SyncReport:
        """Sync a list of tables from the connector into the cache.

        Args:
            table_names: Tables to sync.
            mode: ``"incremental"`` uses watermarks to fetch only new data.
                ``"full"`` replaces all cached data for each table.
            progress_callback: Called with ``(table_name, rows_synced)``
                after each table completes.

        Returns:
            SyncReport with aggregate stats and per-table results.
        """
        overall_start = time.monotonic()
        results: list[TableSyncResult] = []
        errors: list[str] = []

        for table_name in table_names:
            result = self._sync_one_table(table_name, mode)
            results.append(result)

            if result.success:
                if progress_callback:
                    progress_callback(table_name, result.rows_synced)
            else:
                error_msg = f"{table_name}: {result.error}"
                errors.append(error_msg)
                logger.warning("Sync failed for %s: %s", table_name, result.error)

        elapsed = time.monotonic() - overall_start

        return SyncReport(
            tables_synced=sum(1 for r in results if r.success),
            tables_failed=sum(1 for r in results if not r.success),
            total_rows=sum(r.rows_synced for r in results),
            elapsed_seconds=elapsed,
            per_table=results,
            errors=errors,
        )

    def sync_all_accessible(
        self,
        mode: str = "incremental",
        progress_callback: Callable[[str, int], None] | None = None,
    ) -> SyncReport:
        """Sync all accessible tables from the catalog.

        Requires the catalog to be set in the constructor.

        Raises:
            RuntimeError: If no catalog was provided.
        """
        if self._catalog is None:
            raise RuntimeError(
                "sync_all_accessible requires a CatalogStore. "
                "Run 'finch-epm catalog --crawl' first, then pass the catalog."
            )

        table_names = self._catalog.get_accessible_table_names(
            self._connector.connector_type,
            self._connector.profile_name,
        )

        if not table_names:
            return SyncReport(
                tables_synced=0,
                tables_failed=0,
                total_rows=0,
                elapsed_seconds=0.0,
                errors=["No accessible tables found in catalog. Run 'finch-epm catalog --crawl' first."],
            )

        return self.sync_tables(table_names, mode, progress_callback)

    def _sync_one_table(self, table_name: str, mode: str) -> TableSyncResult:
        """Sync a single table from the connector into the cache."""
        start = time.monotonic()
        cache_table = _sanitize_cache_table_name(table_name)

        try:
            # Check for existing watermark (incremental mode)
            since: datetime | None = None
            if mode == "incremental":
                wm = self._cache.get_watermark(
                    self._connector.connector_type,
                    self._connector.profile_name,
                    table_name,
                )
                if wm is not None:
                    since = wm.last_synced_at

            # Build scope and plan
            scope = ScopeDescription(
                tables=[table_name],
                since=since,
            )
            plan = self._connector.plan_scope(scope)

            # Fetch data
            result = self._connector.fetch_facts(plan)

            if not result.rows:
                elapsed = time.monotonic() - start
                # Still update watermark even if no new rows
                self._cache.update_watermark(SyncWatermark(
                    source_name=self._connector.connector_type,
                    profile_name=self._connector.profile_name,
                    table_name=table_name,
                    last_synced_at=datetime.now(timezone.utc),
                    row_count=0,
                ))
                return TableSyncResult(
                    table_name=table_name,
                    rows_synced=0,
                    mode=mode,
                    elapsed_seconds=elapsed,
                    success=True,
                )

            # Convert ColumnType enums to strings for cache ingestion
            col_type_strings = [ct.value for ct in result.column_types]

            # Filter out 'links' column if present (NetSuite artifact)
            col_names = list(result.column_names)
            if "links" in col_names:
                links_idx = col_names.index("links")
                col_names.pop(links_idx)
                col_type_strings.pop(links_idx)
                rows = [
                    [v for i, v in enumerate(row) if i != links_idx]
                    for row in result.rows
                ]
            else:
                rows = [list(row) for row in result.rows]

            # Ingest into cache (use sanitized name for DuckDB compatibility)
            ingest_mode = "replace" if mode == "full" else "append"
            rows_ingested = self._cache.ingest_facts(
                cache_table, col_names, col_type_strings, rows, mode=ingest_mode
            )

            # Update watermark
            self._cache.update_watermark(SyncWatermark(
                source_name=self._connector.connector_type,
                profile_name=self._connector.profile_name,
                table_name=table_name,
                last_synced_at=datetime.now(timezone.utc),
                row_count=rows_ingested,
            ))

            # Check for truncation (source had more rows than we fetched)
            truncated = result.truncated
            total_available = result.total_rows_available
            if total_available and rows_ingested < total_available:
                truncated = True

            elapsed = time.monotonic() - start
            return TableSyncResult(
                table_name=table_name,
                rows_synced=rows_ingested,
                mode=mode,
                elapsed_seconds=elapsed,
                success=True,
                truncated=truncated,
                total_available=total_available,
            )

        except (ConnectorError, Exception) as e:
            elapsed = time.monotonic() - start
            return TableSyncResult(
                table_name=table_name,
                rows_synced=0,
                mode=mode,
                elapsed_seconds=elapsed,
                success=False,
                error=str(e)[:500],
            )
