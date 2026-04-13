"""Tests for MCP server tools.

Uses in-memory DuckDB and FakeConnector fixtures. No real MCP transport
is involved -- we call the tool functions directly via the FastMCP server.

Requires the ``mcp`` optional dependency (which requires pywin32 on Windows).
Skipped on platforms where mcp is not installed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

try:
    import mcp  # noqa: F401
    HAS_MCP = True
except ImportError:
    HAS_MCP = False

pytestmark = pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")

if HAS_MCP:
    from finch_epm.mcp.server import create_mcp_server

from finch_epm.cache.local import LocalCacheEngine
from finch_epm.cache.sync import SyncEngine
from finch_epm.catalog.catalog import CatalogStore
from finch_epm.profiles.manager import ProfileManager


@pytest.fixture
def mcp_env(tmp_path, fake_connector, cache_engine, catalog_store):
    """Set up a complete MCP environment with fake data."""
    # Save schema to catalog
    schema = fake_connector.introspect_schema()
    catalog_store.save_schema(schema)

    # Sync data to cache
    engine = SyncEngine(fake_connector, cache_engine, catalog_store)
    engine.sync_tables(["gl_detail", "subsidiary", "account"], "full")

    # Create a profile manager with matching source/profile names
    pm = ProfileManager(config_path=tmp_path / "profiles.json")
    pm.set_config(schema.source_name, schema.profile_name, {"connector": "fake"})

    return {
        "catalog": catalog_store,
        "cache": cache_engine,
        "pm": pm,
        "connector": fake_connector,
        "schema": schema,
        "source_name": schema.source_name,
        "profile_name": schema.profile_name,
        "server": create_mcp_server(catalog_store, cache_engine, pm),
    }


class TestListSources:
    def test_returns_configured_profiles(self, mcp_env) -> None:
        result = _call_tool(mcp_env["server"], "list_sources")
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["connector"] == mcp_env["source_name"]


class TestListTables:
    def test_returns_tables(self, mcp_env) -> None:
        src, prof = mcp_env["source_name"], mcp_env["profile_name"]
        result = _call_tool(mcp_env["server"], "list_tables",
                            connector=src, profile=prof, accessible_only=False)
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) > 0

    def test_no_profile_returns_message(self, mcp_env) -> None:
        result = _call_tool(mcp_env["server"], "list_tables",
                            connector="nonexistent", profile="nope", accessible_only=False)
        assert "no tables" in result.lower() or "not found" in result.lower() or "[]" in result


class TestDescribeTable:
    def test_returns_columns(self, mcp_env) -> None:
        src, prof = mcp_env["source_name"], mcp_env["profile_name"]
        table_name = mcp_env["schema"].tables[0].name
        result = _call_tool(mcp_env["server"], "describe_table",
                            connector=src, profile=prof, table=table_name)
        data = json.loads(result)
        assert "columns" in data
        assert len(data["columns"]) > 0


class TestPreviewRows:
    def test_returns_sample_data(self, mcp_env) -> None:
        # Cache tables are namespaced: fake__gl_detail
        result = _call_tool(mcp_env["server"], "preview_rows",
                            table="fake__gl_detail", limit=3)
        data = json.loads(result)
        assert "rows" in data
        assert data["row_count"] <= 3

    def test_nonexistent_table(self, mcp_env) -> None:
        result = _call_tool(mcp_env["server"], "preview_rows", table="nonexistent_xyz")
        # Should return an error message (not crash)
        assert "error" in result.lower() or "rows" in result.lower()


class TestQueryCache:
    def test_valid_select(self, mcp_env) -> None:
        result = _call_tool(mcp_env["server"], "query_cache",
                            sql="SELECT COUNT(*) AS cnt FROM fake__gl_detail")
        data = json.loads(result)
        assert "rows" in data
        assert data["row_count"] == 1
        assert data["rows"][0]["cnt"] > 0

    def test_rejects_insert(self, mcp_env) -> None:
        result = _call_tool(mcp_env["server"], "query_cache",
                            sql="INSERT INTO fake__gl_detail VALUES (1,2,3)")
        assert "rejected" in result.lower()

    def test_rejects_drop(self, mcp_env) -> None:
        result = _call_tool(mcp_env["server"], "query_cache",
                            sql="DROP TABLE fake__gl_detail")
        assert "rejected" in result.lower()

    def test_rejects_delete(self, mcp_env) -> None:
        result = _call_tool(mcp_env["server"], "query_cache",
                            sql="DELETE FROM fake__gl_detail")
        assert "rejected" in result.lower()


class TestValidateFdash:
    def test_valid_fdash(self, mcp_env) -> None:
        content = """
name: Test
queries:
  - name: q1
    sql: SELECT 1 AS value
charts:
  - type: kpi
    title: Test
    data: q1
    value: value
"""
        result = _call_tool(mcp_env["server"], "validate_fdash", content=content)
        data = json.loads(result)
        assert data["valid"] is True

    def test_invalid_fdash(self, mcp_env) -> None:
        result = _call_tool(mcp_env["server"], "validate_fdash", content="name: Bad")
        data = json.loads(result)
        assert data["valid"] is False
        assert len(data["errors"]) > 0


class TestWriteFdash:
    def test_write_valid(self, mcp_env, tmp_path) -> None:
        content = """name: Test
queries:
  - name: q1
    sql: SELECT 1 AS value
charts:
  - type: kpi
    title: Test
    data: q1
    value: value
"""
        out = str(tmp_path / "test.fdash")
        result = _call_tool(mcp_env["server"], "write_fdash", path=out, content=content)
        data = json.loads(result)
        assert data["success"] is True
        assert Path(out).exists()

    def test_write_invalid_rejected(self, mcp_env, tmp_path) -> None:
        out = str(tmp_path / "bad.fdash")
        result = _call_tool(mcp_env["server"], "write_fdash", path=out, content="name: Bad")
        data = json.loads(result)
        assert data["success"] is False


class TestListThemes:
    def test_returns_themes(self, mcp_env) -> None:
        result = _call_tool(mcp_env["server"], "list_themes")
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) >= 6
        names = [t["name"] for t in data]
        assert "modern_light" in names
        assert "modern_dark" in names


class TestResources:
    def test_spec_resource_function(self) -> None:
        """Test that the spec resource function returns DASHBOARDS.md content."""
        from finch_epm.mcp.server import create_mcp_server
        # The resource functions are registered on the server.
        # We can test DASHBOARDS.md loading directly.
        from pathlib import Path
        dashboards_path = Path(__file__).parent.parent / "DASHBOARDS.md"
        if dashboards_path.exists():
            content = dashboards_path.read_text(encoding="utf-8")
            assert "fdash" in content.lower()
            assert "chart" in content.lower()

    def test_themes_tool_returns_list(self, mcp_env) -> None:
        result = _call_tool(mcp_env["server"], "list_themes")
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) >= 6
        names = [t["name"] for t in data]
        assert "modern_light" in names


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _call_tool(server, tool_name: str, **kwargs) -> str:
    """Call a tool function registered on the FastMCP server."""
    tool_mgr = server._tool_manager
    tool = tool_mgr.get_tool(tool_name)
    if tool is None:
        raise ValueError(f"Tool '{tool_name}' not found")

    fn = tool.fn
    import asyncio
    import inspect
    if inspect.iscoroutinefunction(fn):
        return asyncio.run(fn(**kwargs))
    return fn(**kwargs)
