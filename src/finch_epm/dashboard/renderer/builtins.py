"""Built-in chart renderers for v0.1.

Each renderer validates chart specs from .fdash files. Actual rendering
happens client-side in the JavaScript frontend (dashboard.html).

Supported optional fields on all chart types:
    height: int (pixels, default 360)
    width: "full" or "half" (default "half")
    colors: list of hex color strings (for multi-series)
"""

from __future__ import annotations

import json
from typing import ClassVar

from finch_epm.dashboard.renderer.base import ChartRenderer
from finch_epm.dashboard.renderer.registry import register_chart
from finch_epm.dashboard.renderer.types import RenderContext, RenderOutput


def _normalize_y(chart_spec: dict) -> list[str]:
    """Extract y field(s) as a list, handling both string and list input."""
    y = chart_spec.get("y")
    if y is None:
        return []
    if isinstance(y, list):
        return y
    return [y]


class _BuiltinRenderer(ChartRenderer):
    """Base for built-in chart renderers with shared validation logic."""

    def validate_spec(self, chart_spec: dict) -> list[str]:
        errors: list[str] = []
        if "data" not in chart_spec:
            errors.append(f"{self.chart_type}: 'data' field is required")
        return errors

    def render(self, context: RenderContext) -> RenderOutput:
        config = {
            "type": self.chart_type,
            "spec": context.chart_spec,
            "data": context.data,
            "columns": context.column_names,
            "columnTypes": context.column_types,
        }
        html = (
            f'<div class="finch-chart" data-type="{self.chart_type}" '
            f"data-config='{json.dumps(config)}'></div>"
        )
        return RenderOutput(html_fragment=html, chart_config_json=config)


class TableRenderer(_BuiltinRenderer):
    chart_type: ClassVar[str] = "table"
    display_name: ClassVar[str] = "Table"


class BarRenderer(_BuiltinRenderer):
    chart_type: ClassVar[str] = "bar"
    display_name: ClassVar[str] = "Bar Chart"

    def validate_spec(self, chart_spec: dict) -> list[str]:
        errors = super().validate_spec(chart_spec)
        if "x" not in chart_spec:
            errors.append("bar: 'x' field is required")
        if "y" not in chart_spec:
            errors.append("bar: 'y' field is required")
        else:
            y = chart_spec["y"]
            if isinstance(y, list) and len(y) == 0:
                errors.append("bar: 'y' list must not be empty")
        return errors

    def get_required_columns(self, chart_spec: dict) -> list[str]:
        cols = []
        if "x" in chart_spec:
            cols.append(chart_spec["x"])
        cols.extend(_normalize_y(chart_spec))
        return cols


class LineRenderer(_BuiltinRenderer):
    chart_type: ClassVar[str] = "line"
    display_name: ClassVar[str] = "Line Chart"

    def validate_spec(self, chart_spec: dict) -> list[str]:
        errors = super().validate_spec(chart_spec)
        if "x" not in chart_spec:
            errors.append("line: 'x' field is required")
        if "y" not in chart_spec:
            errors.append("line: 'y' field is required")
        return errors

    def get_required_columns(self, chart_spec: dict) -> list[str]:
        cols = []
        if "x" in chart_spec:
            cols.append(chart_spec["x"])
        cols.extend(_normalize_y(chart_spec))
        return cols


class AreaRenderer(_BuiltinRenderer):
    chart_type: ClassVar[str] = "area"
    display_name: ClassVar[str] = "Area Chart"

    def validate_spec(self, chart_spec: dict) -> list[str]:
        errors = super().validate_spec(chart_spec)
        if "x" not in chart_spec:
            errors.append("area: 'x' field is required")
        if "y" not in chart_spec:
            errors.append("area: 'y' field is required")
        return errors

    def get_required_columns(self, chart_spec: dict) -> list[str]:
        cols = []
        if "x" in chart_spec:
            cols.append(chart_spec["x"])
        cols.extend(_normalize_y(chart_spec))
        return cols


class KpiRenderer(_BuiltinRenderer):
    """KPI tile renderer.

    Optional fields:
        format: "currency", "percent", or "number"
        prefix: string prepended to the value (e.g. "$")
        suffix: string appended to the value (e.g. "%")
        color: hex color for the value text
        label: descriptive text below the value
    """

    chart_type: ClassVar[str] = "kpi"
    display_name: ClassVar[str] = "KPI Tile"

    def validate_spec(self, chart_spec: dict) -> list[str]:
        errors = super().validate_spec(chart_spec)
        if "value" not in chart_spec:
            errors.append("kpi: 'value' field is required")
        return errors

    def get_required_columns(self, chart_spec: dict) -> list[str]:
        cols = []
        if "value" in chart_spec:
            cols.append(chart_spec["value"])
        return cols


class PivotRenderer(_BuiltinRenderer):
    chart_type: ClassVar[str] = "pivot"
    display_name: ClassVar[str] = "Pivot Table"

    def validate_spec(self, chart_spec: dict) -> list[str]:
        errors = super().validate_spec(chart_spec)
        if "rows" not in chart_spec:
            errors.append("pivot: 'rows' field is required")
        if "values" not in chart_spec:
            errors.append("pivot: 'values' field is required")
        return errors


class TimeseriesRenderer(_BuiltinRenderer):
    chart_type: ClassVar[str] = "timeseries"
    display_name: ClassVar[str] = "Time Series"

    def validate_spec(self, chart_spec: dict) -> list[str]:
        errors = super().validate_spec(chart_spec)
        if "time" not in chart_spec:
            errors.append("timeseries: 'time' field is required")
        if "y" not in chart_spec:
            errors.append("timeseries: 'y' field is required")
        return errors

    def get_required_columns(self, chart_spec: dict) -> list[str]:
        cols = []
        if "time" in chart_spec:
            cols.append(chart_spec["time"])
        cols.extend(_normalize_y(chart_spec))
        return cols


class ScatterRenderer(_BuiltinRenderer):
    chart_type: ClassVar[str] = "scatter"
    display_name: ClassVar[str] = "Scatter Plot"

    def validate_spec(self, chart_spec: dict) -> list[str]:
        errors = super().validate_spec(chart_spec)
        if "x" not in chart_spec:
            errors.append("scatter: 'x' field is required")
        if "y" not in chart_spec:
            errors.append("scatter: 'y' field is required")
        return errors

    def get_required_columns(self, chart_spec: dict) -> list[str]:
        cols = []
        if "x" in chart_spec:
            cols.append(chart_spec["x"])
        cols.extend(_normalize_y(chart_spec))
        return cols


# Register all built-in renderers
register_chart(TableRenderer())
register_chart(BarRenderer())
register_chart(LineRenderer())
register_chart(AreaRenderer())
register_chart(KpiRenderer())
register_chart(PivotRenderer())
register_chart(TimeseriesRenderer())
register_chart(ScatterRenderer())
