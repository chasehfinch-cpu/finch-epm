"""Data structures shared across all connectors.

All types are frozen dataclasses — connectors produce them, consumers read them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Sequence


class ColumnType(Enum):
    """Column/field data types recognized by finch-epm."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    TEXT = "text"
    REFERENCE = "reference"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ColumnInfo:
    """A single column/field discovered via introspection."""

    name: str
    display_name: str
    column_type: ColumnType
    is_custom: bool = False
    is_nullable: bool = True
    reference_target: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TableInfo:
    """A table/record type discovered via introspection."""

    name: str
    display_name: str
    columns: Sequence[ColumnInfo]
    is_custom: bool = False
    row_count_estimate: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SchemaInfo:
    """Complete schema introspection result from a connector."""

    tables: Sequence[TableInfo]
    source_name: str
    profile_name: str
    introspected_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DimensionInfo:
    """A dimensional entity (e.g., subsidiary, department, location)."""

    name: str
    display_name: str
    table_name: str
    id_column: str
    label_column: str
    supports_hierarchy: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HierarchyNode:
    """A node in a parent-child hierarchy tree."""

    id: str
    label: str
    parent_id: str | None = None
    children: Sequence[HierarchyNode] = field(default_factory=tuple)
    depth: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScopeDescription:
    """Connector-agnostic description of what data to fetch.

    Produced by the sync planner from dashboard queries. Each connector
    translates this into its own native fetch plan via plan_scope().
    """

    tables: Sequence[str]
    columns: Sequence[str] | None = None
    filters: dict[str, Any] = field(default_factory=dict)
    since: datetime | None = None
    limit: int | None = None


@dataclass(frozen=True)
class FetchPlan:
    """Connector-specific execution plan produced by plan_scope().

    The native_plan field is opaque — only the originating connector
    interprets it. The cache/sync layer passes it back unchanged to
    fetch_facts().
    """

    scope: ScopeDescription
    estimated_rows: int | None = None
    estimated_api_calls: int | None = None
    native_plan: dict[str, Any] = field(default_factory=dict)
    warnings: Sequence[str] = field(default_factory=tuple)


@dataclass
class FactResult:
    """Result of a fetch_facts() call.

    Uses plain lists (not DataFrames) so connectors stay dependency-free.
    The cache layer is responsible for ingesting this into DuckDB.
    """

    column_names: Sequence[str]
    column_types: Sequence[ColumnType]
    rows: Sequence[Sequence[Any]]
    total_rows_available: int | None = None
    watermark: datetime | None = None
    truncated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
