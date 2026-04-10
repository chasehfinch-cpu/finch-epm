"""Dashboard specification data models.

These dataclasses represent the parsed content of a .fdash file.
They are plain data -- no logic, no I/O, no rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ChartSpec:
        """Build a ChartSpec from a raw YAML dict.

        Extracts type, title, and data as top-level fields.
        Everything else goes into config for the renderer.
        """
        chart_type = d.get("type", "")
        title = d.get("title", "")
        data = d.get("data", "")
        config = {k: v for k, v in d.items() if k not in ("type", "title", "data")}
        return cls(type=chart_type, title=title, data=data, config=config)

    def to_render_spec(self) -> dict[str, Any]:
        """Convert to the dict format expected by ChartRenderer.validate_spec()."""
        spec = {"type": self.type, "data": self.data, **self.config}
        return spec


@dataclass
class DashboardSpec:
    """Complete parsed representation of a .fdash file."""

    name: str
    description: str = ""
    sources: list[str] = field(default_factory=list)
    queries: list[QuerySpec] = field(default_factory=list)
    parameters: dict[str, ParameterSpec] = field(default_factory=dict)
    charts: list[ChartSpec] = field(default_factory=list)

    def get_query(self, name: str) -> QuerySpec | None:
        """Look up a query by name."""
        for q in self.queries:
            if q.name == name:
                return q
        return None

    def get_query_names(self) -> list[str]:
        """Return all query names defined in this dashboard."""
        return [q.name for q in self.queries]
