"""Tests for chart renderer interface and built-in renderers."""

from __future__ import annotations

import pytest

# Import builtins to trigger registration
import finch_epm.dashboard.renderer.builtins  # noqa: F401
from finch_epm.dashboard.renderer.registry import (
    get_chart_renderer,
    list_chart_types,
)
from finch_epm.dashboard.renderer.types import RenderContext, RenderOutput


EXPECTED_TYPES = ["area", "bar", "kpi", "line", "pivot", "scatter", "table", "timeseries"]

SAMPLE_DATA = [
    {"site": "US", "revenue": 150000, "expense": 85000},
    {"site": "UK", "revenue": 75000, "expense": 40000},
]


class TestRegistry:
    def test_all_builtin_types_registered(self) -> None:
        registered = list_chart_types()
        for chart_type in EXPECTED_TYPES:
            assert chart_type in registered, f"{chart_type} not registered"

    def test_unknown_type_raises(self) -> None:
        with pytest.raises(KeyError):
            get_chart_renderer("__nonexistent__")


class TestRenderers:
    @pytest.mark.parametrize("chart_type", EXPECTED_TYPES)
    def test_render_produces_output(self, chart_type: str) -> None:
        renderer = get_chart_renderer(chart_type)

        # Build a spec that satisfies each renderer's requirements
        spec = {"data": "test_query", "type": chart_type}
        if chart_type in ("bar", "line", "area", "scatter"):
            spec.update({"x": "site", "y": "revenue"})
        elif chart_type == "kpi":
            spec.update({"value": "revenue"})
        elif chart_type == "pivot":
            spec.update({"rows": ["site"], "values": ["revenue"]})
        elif chart_type == "timeseries":
            spec.update({"time": "site", "y": "revenue"})

        context = RenderContext(
            chart_spec=spec,
            data=SAMPLE_DATA,
            column_names=["site", "revenue", "expense"],
            column_types=["string", "decimal", "decimal"],
        )

        output = renderer.render(context)
        assert isinstance(output, RenderOutput)
        assert len(output.html_fragment) > 0
        assert isinstance(output.chart_config_json, dict)

    @pytest.mark.parametrize("chart_type", EXPECTED_TYPES)
    def test_validate_spec_missing_data(self, chart_type: str) -> None:
        renderer = get_chart_renderer(chart_type)
        errors = renderer.validate_spec({"type": chart_type})
        assert any("data" in e for e in errors)

    def test_bar_requires_x_and_y(self) -> None:
        renderer = get_chart_renderer("bar")
        errors = renderer.validate_spec({"data": "q"})
        assert any("x" in e for e in errors)
        assert any("y" in e for e in errors)

    def test_bar_valid_spec(self) -> None:
        renderer = get_chart_renderer("bar")
        errors = renderer.validate_spec({"data": "q", "x": "a", "y": "b"})
        assert errors == []

    def test_get_required_columns(self) -> None:
        renderer = get_chart_renderer("bar")
        cols = renderer.get_required_columns({"x": "site", "y": "revenue"})
        assert "site" in cols
        assert "revenue" in cols

    def test_bar_accepts_y_as_list(self) -> None:
        renderer = get_chart_renderer("bar")
        errors = renderer.validate_spec({"data": "q", "x": "a", "y": ["b", "c"]})
        assert errors == []

    def test_bar_rejects_empty_y_list(self) -> None:
        renderer = get_chart_renderer("bar")
        errors = renderer.validate_spec({"data": "q", "x": "a", "y": []})
        assert len(errors) > 0

    def test_multi_series_required_columns(self) -> None:
        renderer = get_chart_renderer("bar")
        cols = renderer.get_required_columns({"x": "site", "y": ["revenue", "expense"]})
        assert "site" in cols
        assert "revenue" in cols
        assert "expense" in cols

    def test_line_accepts_y_as_list(self) -> None:
        renderer = get_chart_renderer("line")
        errors = renderer.validate_spec({"data": "q", "x": "a", "y": ["b", "c"]})
        assert errors == []

    def test_timeseries_accepts_y_as_list(self) -> None:
        renderer = get_chart_renderer("timeseries")
        errors = renderer.validate_spec({"data": "q", "time": "t", "y": ["a", "b"]})
        assert errors == []
