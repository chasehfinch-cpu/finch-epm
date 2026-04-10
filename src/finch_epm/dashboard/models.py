"""Dashboard specification data models.

These dataclasses represent the parsed content of a .fdash file.
They are plain data -- no logic, no I/O, no rendering.
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
    """SQL query that returns the dropdown options. First column = value,
    second column (optional) = display label."""
    parameter: str
    """Parameter name in queries where this filter's value is injected."""
    default: Any = None
    multi: bool = False
    """Whether multiple selections are allowed."""


@dataclass
class ParameterSpec:
    """A dashboard parameter that can be overridden at render time."""

    name: str
    type: str = "string"
    default: Any = None
    label: str | None = None


@dataclass
class QuerySpec:
    """A named SQL query defined in the dashboard."""

    name: str
    sql: str
    source: str | None = None


@dataclass
class ChartSpec:
    """A chart definition referencing a named query."""

    type: str
    title: str
    data: str
    config: dict[str, Any] = field(default_factory=dict)
    cross_filter: str | None = None
    """Column name that, when clicked, filters other charts.
    Example: cross_filter: 'site' means clicking a bar sends
    site=<value> as a filter to all other queries."""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ChartSpec:
        """Build a ChartSpec from a raw YAML dict."""
        chart_type = d.get("type", "")
        title = d.get("title", "")
        data = d.get("data", "")
        cross_filter = d.get("cross_filter")
        config = {k: v for k, v in d.items()
                  if k not in ("type", "title", "data", "cross_filter")}
        return cls(type=chart_type, title=title, data=data,
                   config=config, cross_filter=cross_filter)

    def to_render_spec(self) -> dict[str, Any]:
        """Convert to the dict format expected by ChartRenderer.validate_spec()."""
        spec = {"type": self.type, "data": self.data, **self.config}
        return spec


@dataclass
class DimensionMappingRef:
    """Reference to a dimension mapping file used by this dashboard."""

    file: str
    """Path to the dimension mapping YAML file, relative to the .fdash file."""


@dataclass
class DashboardSpec:
    """Complete parsed representation of a .fdash file."""

    name: str
    description: str = ""
    sources: list[str] = field(default_factory=list)
    queries: list[QuerySpec] = field(default_factory=list)
    parameters: dict[str, ParameterSpec] = field(default_factory=dict)
    filters: list[FilterSpec] = field(default_factory=list)
    charts: list[ChartSpec] = field(default_factory=list)
    dimensions: DimensionMappingRef | None = None

    def get_query(self, name: str) -> QuerySpec | None:
        """Look up a query by name."""
        for q in self.queries:
            if q.name == name:
                return q
        return None

    def get_query_names(self) -> list[str]:
        """Return all query names defined in this dashboard."""
        return [q.name for q in self.queries]
