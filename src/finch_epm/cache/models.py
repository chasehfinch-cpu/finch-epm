"""Data structures for the cache layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class StalenessLevel(Enum):
    """How fresh the cached data is."""

    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"


@dataclass(frozen=True)
class QueryRequest:
    """A query to execute against the cache.

    SQL references catalog-resolved names. The dashboard resolver
    translates .fdash SQL before constructing this.
    """

    sql: str
    parameters: dict[str, Any] = field(default_factory=dict)
    source_name: str | None = None


@dataclass
class QueryResult:
    """Result of a cache query.

    The consumer does not know whether this came from local DuckDB
    or was pushed down to a remote source (v0.3 federated mode).
    """

    column_names: list[str]
    column_types: list[str]
    rows: list[list[Any]]
    row_count: int
    staleness: StalenessInfo
    execution_time_ms: float
    served_from: str = "local"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StalenessInfo:
    """Staleness metadata for the render-first pattern."""

    level: StalenessLevel
    last_synced_at: datetime | None = None
    tables_involved: list[str] = field(default_factory=list)
    oldest_table_sync: datetime | None = None


@dataclass(frozen=True)
class SourceTableRef:
    """Reference to a cache table with its source prefix.

    Cache tables are stored as ``{source_prefix}__{sanitized_table_name}``
    to prevent collisions between different data sources.
    """

    source_prefix: str
    raw_table_name: str

    @property
    def cache_name(self) -> str:
        """DuckDB table name: ``prefix__name`` with dots replaced."""
        sanitized = self.raw_table_name.replace(".", "__")
        return f"{self.source_prefix}__{sanitized}"

    @classmethod
    def parse(cls, cache_name: str) -> SourceTableRef:
        """Parse a cache table name back into prefix + raw name.

        Raises:
            ValueError: If the name has no ``__`` separator.
        """
        sep = "__"
        idx = cache_name.find(sep)
        if idx < 0:
            raise ValueError(
                f"Cannot parse cache table name (no source prefix): {cache_name!r}"
            )
        return cls(
            source_prefix=cache_name[:idx],
            raw_table_name=cache_name[idx + len(sep):],
        )


@dataclass(frozen=True)
class SyncWatermark:
    """Per-table watermark tracking for incremental sync."""

    source_name: str
    profile_name: str
    table_name: str
    last_synced_at: datetime
    last_modified_value: str | None = None
    row_count: int = 0


@dataclass
class TableSyncResult:
    """Result of syncing a single table."""

    table_name: str
    rows_synced: int
    mode: str
    elapsed_seconds: float
    success: bool
    error: str | None = None
    truncated: bool = False
    total_available: int | None = None


@dataclass
class SyncReport:
    """Aggregate result of a sync operation."""

    tables_synced: int
    tables_failed: int
    total_rows: int
    elapsed_seconds: float
    per_table: list[TableSyncResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
