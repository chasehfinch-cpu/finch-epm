"""Dashboard specification data models.

These dataclasses represent the parsed content of a .fdash file.
They are plain data -- no logic, no I/O, no rendering.

A dashboard can have either:
    - A flat list of charts (single-page mode, backward compatible)
    - A list of pages, each with its own charts (multi-tab mode)

Queries, parameters, and filters are shared across all pages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FilterSpec:
    """A dashboard-level filter that appears as a dropdown in the UI.

    Filters re-execute all queries with the selected value injected
    into the SQL via parameter substitution.
    """

    name: str
    label: str
    query: str
    parameter: str
    default: Any = None
    multi: bool = False


@dataclass
class ParameterSpec:
    """A dashboard parameter that can be overridden at render time."""

    name: str
    type: str = "string"
    default: Any = None
    label: str | None = None


@dataclass
class QuerySpec:
    """A named SQL query defined in the dashboard.

    Supports two modes:
        - Raw SQL: ``sql`` is set (traditional mode)
        - Semantic: ``entity`` is set with optional ``measures``,
          ``group_by``, ``query_filters``, ``order_by`` (v0.4)

    At least one of ``sql`` or ``entity`` must be non-empty.
    """

    name: str
    sql: str = ""
    source: str | None = None
    entity: str | None = None
    measures: list[str] = field(default_factory=list)
    group_by: list[str] = field(default_factory=list)
    query_filters: dict[str, Any] = field(default_factory=dict)
    order_by: list[str] = field(default_factory=list)


@dataclass
class ChartSpec:
    """A chart definition referencing a named query."""

    type: str
    title: str
    data: str
    config: dict[str, Any] = field(default_factory=dict)
    cross_filter: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ChartSpec:
        chart_type = d.get("type", "")
        title = d.get("title", "")
        data = d.get("data", "")
        cross_filter = d.get("cross_filter")
        config = {k: v for k, v in d.items()
                  if k not in ("type", "title", "data", "cross_filter")}
        return cls(type=chart_type, title=title, data=data,
                   config=config, cross_filter=cross_filter)

    def to_render_spec(self) -> dict[str, Any]:
        spec = {"type": self.type, "data": self.data, **self.config}
        return spec


@dataclass
class PageSpec:
    """A page (tab) within a multi-page dashboard."""

    name: str
    charts: list[ChartSpec] = field(default_factory=list)
    description: str = ""


@dataclass
class DimensionMappingRef:
    """Reference to a dimension mapping file used by this dashboard."""

    file: str


@dataclass
class DashboardSpec:
    """Complete parsed representation of a .fdash file.

    Supports two modes:
        - Single-page: charts are defined directly on the dashboard
        - Multi-page: pages are defined, each with their own charts

    In multi-page mode, the UI renders a tab bar to switch between pages.
    Queries, parameters, and filters are shared across all pages.
    """

    name: str
    description: str = ""
    sources: list[str] = field(default_factory=list)
    queries: list[QuerySpec] = field(default_factory=list)
    parameters: dict[str, ParameterSpec] = field(default_factory=dict)
    filters: list[FilterSpec] = field(default_factory=list)
    charts: list[ChartSpec] = field(default_factory=list)
    pages: list[PageSpec] = field(default_factory=list)
    dimensions: DimensionMappingRef | None = None
    semantic_model: str | None = None
    federation: dict[str, Any] | None = None

    @property
    def is_multi_page(self) -> bool:
        """True if this dashboard uses the pages/tabs format."""
        return len(self.pages) > 0

    def get_all_charts(self) -> list[ChartSpec]:
        """Return all charts across all pages (or the flat chart list)."""
        if self.pages:
            result = []
            for page in self.pages:
                result.extend(page.charts)
            return result
        return self.charts

    def get_query(self, name: str) -> QuerySpec | None:
        for q in self.queries:
            if q.name == name:
                return q
        return None

    def get_query_names(self) -> list[str]:
        return [q.name for q in self.queries]
