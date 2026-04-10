""".fdash file parser and validator.

Loads a YAML-based .fdash dashboard file into typed DashboardSpec objects.
Validates structure and chart specs against registered renderers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from finch_epm.dashboard.models import (
    ChartSpec,
    DashboardSpec,
    DimensionMappingRef,
    FilterSpec,
    ParameterSpec,
    QuerySpec,
)


class FdashError(Exception):
    """Raised when a .fdash file cannot be parsed or is invalid."""


def load_fdash(path: str | Path) -> DashboardSpec:
    """Parse a .fdash file and return a DashboardSpec.

    Args:
        path: Path to the .fdash file.

    Returns:
        A fully parsed DashboardSpec.

    Raises:
        FdashError: If the file cannot be read or has invalid structure.
    """
    path = Path(path)

    if not path.exists():
        raise FdashError(f"Dashboard file not found: {path}")

    if path.suffix not in (".fdash", ".yml", ".yaml"):
        raise FdashError(
            f"Unexpected file extension: {path.suffix}. "
            "Dashboard files should use the .fdash extension."
        )

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise FdashError(f"YAML parse error in {path}: {e}") from e

    if not isinstance(raw, dict):
        raise FdashError(f"Dashboard file must be a YAML mapping, got {type(raw).__name__}")

    return _parse_dashboard(raw, str(path))


def load_fdash_string(content: str, source: str = "<string>") -> DashboardSpec:
    """Parse a .fdash YAML string and return a DashboardSpec.

    Useful for testing without writing to disk.
    """
    try:
        raw = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise FdashError(f"YAML parse error: {e}") from e

    if not isinstance(raw, dict):
        raise FdashError(f"Dashboard must be a YAML mapping, got {type(raw).__name__}")

    return _parse_dashboard(raw, source)


def validate_fdash(spec: DashboardSpec) -> list[str]:
    """Validate a DashboardSpec against registered chart renderers.

    Returns:
        List of validation error messages. Empty means valid.
    """
    errors: list[str] = []

    if not spec.name:
        errors.append("Dashboard 'name' is required.")

    if not spec.queries:
        errors.append("Dashboard must define at least one query.")

    if not spec.charts:
        errors.append("Dashboard must define at least one chart.")

    # Check that all chart data references exist as query names
    query_names = set(spec.get_query_names())
    for chart in spec.charts:
        if chart.data not in query_names:
            errors.append(
                f"Chart '{chart.title}' references query '{chart.data}' "
                f"which is not defined. Available: {sorted(query_names)}"
            )

    # Validate each chart spec against its renderer
    try:
        from finch_epm.dashboard.renderer.builtins import _CHART_REGISTRY  # noqa: F401
        from finch_epm.dashboard.renderer.registry import get_chart_renderer

        for chart in spec.charts:
            try:
                renderer = get_chart_renderer(chart.type)
                chart_errors = renderer.validate_spec(chart.to_render_spec())
                errors.extend(chart_errors)
            except KeyError:
                errors.append(
                    f"Unknown chart type '{chart.type}' in chart '{chart.title}'. "
                    f"Available types: table, bar, line, area, kpi, pivot, timeseries, scatter"
                )
    except ImportError:
        pass  # Renderers not available in minimal installs

    return errors


def _parse_dashboard(raw: dict[str, Any], source: str) -> DashboardSpec:
    """Parse a raw YAML dict into a DashboardSpec."""
    name = raw.get("name", "")
    if not name:
        raise FdashError(f"Dashboard 'name' is required in {source}")

    description = raw.get("description", "")
    sources = raw.get("sources", [])
    if isinstance(sources, str):
        sources = [sources]

    # Parse queries
    queries: list[QuerySpec] = []
    for q in raw.get("queries", []):
        if not isinstance(q, dict):
            raise FdashError(f"Each query must be a mapping in {source}")
        if "name" not in q:
            raise FdashError(f"Each query must have a 'name' in {source}")
        if "sql" not in q:
            raise FdashError(f"Query '{q['name']}' must have a 'sql' field in {source}")
        queries.append(QuerySpec(
            name=q["name"],
            sql=q["sql"],
            source=q.get("source"),
        ))

    # Parse parameters
    parameters: dict[str, ParameterSpec] = {}
    for param_name, param_def in raw.get("parameters", {}).items():
        if isinstance(param_def, dict):
            parameters[param_name] = ParameterSpec(
                name=param_name,
                type=param_def.get("type", "string"),
                default=param_def.get("default"),
                label=param_def.get("label"),
            )
        else:
            # Simple value as default
            parameters[param_name] = ParameterSpec(
                name=param_name,
                default=param_def,
            )

    # Parse filters (dashboard-level dropdowns)
    filters: list[FilterSpec] = []
    for f in raw.get("filters", []):
        if isinstance(f, dict):
            filters.append(FilterSpec(
                name=f.get("name", ""),
                label=f.get("label", f.get("name", "")),
                query=f.get("query", ""),
                parameter=f.get("parameter", f.get("name", "")),
                default=f.get("default"),
                multi=f.get("multi", False),
            ))

    # Parse charts
    charts: list[ChartSpec] = []
    for c in raw.get("charts", []):
        if not isinstance(c, dict):
            raise FdashError(f"Each chart must be a mapping in {source}")
        if "type" not in c:
            raise FdashError(f"Each chart must have a 'type' in {source}")
        charts.append(ChartSpec.from_dict(c))

    # Parse dimension mapping reference
    dimensions = None
    dim_raw = raw.get("dimensions")
    if isinstance(dim_raw, dict) and "file" in dim_raw:
        dimensions = DimensionMappingRef(file=dim_raw["file"])
    elif isinstance(dim_raw, str):
        dimensions = DimensionMappingRef(file=dim_raw)

    return DashboardSpec(
        name=name,
        description=description,
        sources=sources,
        queries=queries,
        parameters=parameters,
        filters=filters,
        charts=charts,
        dimensions=dimensions,
    )
