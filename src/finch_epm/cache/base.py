"""Abstract base class for the cache engine.

The dashboard runtime calls execute_query() and gets back a QueryResult.
It never knows or cares whether results came from local DuckDB or were
pushed down to a remote source (v0.3 federated mode).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any

from finch_epm.cache.models import (
    QueryRequest,
    QueryResult,
    StalenessInfo,
    SyncWatermark,
)


class CacheEngine(ABC):
    """Abstract query interface for the cache layer."""

    @abstractmethod
    def execute_query(self, request: QueryRequest) -> QueryResult:
        """Execute a query and return results with staleness metadata.

        Args:
            request: The query to execute.

        Returns:
            Data rows plus staleness information for the render-first pattern.
        """
        ...

    @abstractmethod
    def get_staleness(
        self,
        tables: list[str],
        source_name: str,
        freshness_threshold: timedelta = timedelta(hours=1),
    ) -> StalenessInfo:
        """Check how stale the local data is for the given tables.

        Args:
            tables: Table names to check.
            source_name: Which source these tables belong to.
            freshness_threshold: Data newer than this is FRESH.

        Returns:
            Staleness level and timestamps.
        """
        ...

    @abstractmethod
    def get_watermark(
        self, source_name: str, profile_name: str, table_name: str
    ) -> SyncWatermark | None:
        """Get the sync watermark for a specific table.

        Returns:
            The watermark, or None if the table has never been synced.
        """
        ...

    @abstractmethod
    def update_watermark(self, watermark: SyncWatermark) -> None:
        """Update/insert the sync watermark after a successful sync."""
        ...

    @abstractmethod
    def ingest_facts(
        self,
        table_name: str,
        column_names: list[str],
        column_types: list[str],
        rows: list[list[Any]],
        mode: str = "append",
    ) -> int:
        """Write fact data into the local cache.

        Args:
            table_name: Target table in the cache DB.
            column_names: Column names matching the row data.
            column_types: DuckDB-compatible type strings for each column.
            rows: Row data to insert.
            mode: ``"append"`` adds rows; ``"replace"`` drops and recreates.

        Returns:
            Number of rows ingested.
        """
        ...

    @abstractmethod
    def has_table(self, table_name: str) -> bool:
        """Check if a table exists in the local cache."""
        ...
