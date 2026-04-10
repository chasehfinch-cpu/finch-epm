"""Tests for the dashboard resolver."""

from __future__ import annotations

from finch_epm.cache.local import LocalCacheEngine
from finch_epm.dashboard.fdash import load_fdash_string
from finch_epm.dashboard.resolver import resolve_parameters, resolve_queries


DASHBOARD_YAML = """
name: Test
sources:
  - fake

queries:
  - name: summary
    sql: SELECT subsidiary_id, SUM(amount) AS total FROM gl_detail GROUP BY subsidiary_id

parameters:
  start:
    type: period
    default: current_quarter_start
  limit:
    type: number
    default: 100

charts:
  - type: table
    title: Summary
    data: summary
"""


class TestResolveParameters:
    def test_defaults(self) -> None:
        spec = load_fdash_string(DASHBOARD_YAML)
        params = resolve_parameters(spec)
        assert "start" in params
        assert params["limit"] == 100

    def test_overrides(self) -> None:
        spec = load_fdash_string(DASHBOARD_YAML)
        params = resolve_parameters(spec, {"limit": 50})
        assert params["limit"] == 50

    def test_period_resolution(self) -> None:
        spec = load_fdash_string(DASHBOARD_YAML)
        params = resolve_parameters(spec)
        # current_quarter_start should resolve to an ISO date string
        assert isinstance(params["start"], str)
        assert len(params["start"]) == 10  # YYYY-MM-DD


class TestResolveQueries:
    def test_execute_against_cache(self, cache_engine: LocalCacheEngine) -> None:
        # Populate cache with test data
        cache_engine.ingest_facts(
            "gl_detail",
            ["subsidiary_id", "amount"],
            ["integer", "decimal"],
            [[1, 100.0], [1, 200.0], [2, 300.0]],
        )

        spec = load_fdash_string(DASHBOARD_YAML)
        results = resolve_queries(spec, cache_engine)

        assert "summary" in results
        result = results["summary"]
        assert result.row_count >= 1
        assert "subsidiary_id" in result.column_names

    def test_empty_cache_returns_empty(self, cache_engine: LocalCacheEngine) -> None:
        spec = load_fdash_string(DASHBOARD_YAML)
        results = resolve_queries(spec, cache_engine)

        # Query should still execute (returns 0 rows or missing staleness)
        assert "summary" in results
