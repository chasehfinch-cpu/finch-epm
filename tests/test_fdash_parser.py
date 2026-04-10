"""Tests for the .fdash parser."""

from __future__ import annotations

import pytest
from pathlib import Path

from finch_epm.dashboard.fdash import load_fdash, load_fdash_string, validate_fdash, FdashError
from finch_epm.dashboard.models import DashboardSpec, ChartSpec


MINIMAL_FDASH = """
name: Test Dashboard
description: A test
sources:
  - fake

queries:
  - name: q1
    sql: SELECT * FROM test

charts:
  - type: table
    title: Test Table
    data: q1
"""

FULL_FDASH = """
name: Full Dashboard
description: All features
sources:
  - netsuite

queries:
  - name: revenue
    sql: |
      SELECT site, SUM(amount) AS total
      FROM gl_detail
      WHERE period BETWEEN :start AND :end
      GROUP BY site

parameters:
  start:
    type: period
    default: current_quarter_start
  end:
    type: period
    default: current_quarter_end

charts:
  - type: bar
    title: Revenue by Site
    data: revenue
    x: site
    y: total
  - type: table
    title: Detail
    data: revenue
  - type: kpi
    title: Total Revenue
    data: revenue
    value: total
"""


class TestLoadFdashString:
    def test_minimal(self) -> None:
        spec = load_fdash_string(MINIMAL_FDASH)
        assert spec.name == "Test Dashboard"
        assert len(spec.queries) == 1
        assert len(spec.charts) == 1
        assert spec.charts[0].type == "table"

    def test_full(self) -> None:
        spec = load_fdash_string(FULL_FDASH)
        assert spec.name == "Full Dashboard"
        assert len(spec.queries) == 1
        assert len(spec.parameters) == 2
        assert len(spec.charts) == 3
        assert spec.parameters["start"].type == "period"

    def test_chart_spec_from_dict(self) -> None:
        spec = load_fdash_string(FULL_FDASH)
        bar = spec.charts[0]
        assert bar.type == "bar"
        assert bar.config["x"] == "site"
        assert bar.config["y"] == "total"

    def test_query_lookup(self) -> None:
        spec = load_fdash_string(FULL_FDASH)
        q = spec.get_query("revenue")
        assert q is not None
        assert "SELECT" in q.sql

    def test_missing_query_returns_none(self) -> None:
        spec = load_fdash_string(MINIMAL_FDASH)
        assert spec.get_query("nonexistent") is None


class TestLoadFdashFile:
    def test_load_example(self) -> None:
        example = Path(__file__).parent.parent / "examples" / "site_pl.fdash"
        if example.exists():
            spec = load_fdash(example)
            assert spec.name == "Site P&L"
            assert len(spec.queries) >= 1
            assert len(spec.charts) >= 1


class TestValidation:
    def test_valid_minimal(self) -> None:
        spec = load_fdash_string(MINIMAL_FDASH)
        errors = validate_fdash(spec)
        assert errors == []

    def test_missing_query_reference(self) -> None:
        bad = """
name: Bad
queries:
  - name: q1
    sql: SELECT 1
charts:
  - type: table
    title: Test
    data: nonexistent
"""
        spec = load_fdash_string(bad)
        errors = validate_fdash(spec)
        assert any("nonexistent" in e for e in errors)

    def test_no_queries(self) -> None:
        bad = """
name: Bad
charts:
  - type: table
    title: Test
    data: q1
"""
        spec = load_fdash_string(bad)
        errors = validate_fdash(spec)
        assert any("query" in e.lower() for e in errors)

    def test_no_charts(self) -> None:
        bad = """
name: Bad
queries:
  - name: q1
    sql: SELECT 1
"""
        spec = load_fdash_string(bad)
        errors = validate_fdash(spec)
        assert any("chart" in e.lower() for e in errors)


class TestMultiSeries:
    def test_y_as_list(self) -> None:
        spec = load_fdash_string("""
name: Multi
queries:
  - name: q1
    sql: SELECT x, a, b FROM t
charts:
  - type: bar
    title: Multi Bar
    data: q1
    x: x
    y: [a, b]
    colors: ["#ff0000", "#00ff00"]
""")
        chart = spec.charts[0]
        assert chart.config["y"] == ["a", "b"]
        assert chart.config["colors"] == ["#ff0000", "#00ff00"]

    def test_y_as_string(self) -> None:
        spec = load_fdash_string(MINIMAL_FDASH)
        # table chart has no y field, so test with bar
        bar_spec = load_fdash_string(FULL_FDASH)
        bar = bar_spec.charts[0]
        assert bar.config["y"] == "total"

    def test_height_and_width(self) -> None:
        spec = load_fdash_string("""
name: Sized
queries:
  - name: q1
    sql: SELECT 1
charts:
  - type: bar
    title: Big Chart
    data: q1
    x: a
    y: b
    height: 500
    width: full
""")
        chart = spec.charts[0]
        assert chart.config["height"] == 500
        assert chart.config["width"] == "full"

    def test_kpi_format(self) -> None:
        spec = load_fdash_string("""
name: KPI
queries:
  - name: q1
    sql: SELECT 100 AS val
charts:
  - type: kpi
    title: Revenue
    data: q1
    value: val
    format: currency
    prefix: "$"
    color: "#2ecc71"
""")
        chart = spec.charts[0]
        assert chart.config["format"] == "currency"
        assert chart.config["prefix"] == "$"
        assert chart.config["color"] == "#2ecc71"

    def test_multi_series_validation_passes(self) -> None:
        spec = load_fdash_string("""
name: Valid Multi
queries:
  - name: q1
    sql: SELECT x, a, b FROM t
charts:
  - type: bar
    title: Multi
    data: q1
    x: x
    y: [a, b]
""")
        errors = validate_fdash(spec)
        assert errors == []


class TestErrors:
    def test_missing_name(self) -> None:
        with pytest.raises(FdashError, match="name"):
            load_fdash_string("queries: []")

    def test_invalid_yaml(self) -> None:
        with pytest.raises(FdashError):
            load_fdash_string("{{invalid")

    def test_not_a_mapping(self) -> None:
        with pytest.raises(FdashError, match="mapping"):
            load_fdash_string("- just a list")

    def test_query_missing_sql(self) -> None:
        with pytest.raises(FdashError, match="sql"):
            load_fdash_string("""
name: Bad
queries:
  - name: q1
charts: []
""")
