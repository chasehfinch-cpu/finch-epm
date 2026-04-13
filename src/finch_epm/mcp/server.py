"""MCP server implementation for finch-epm.

Exposes tools and resources that let any MCP-capable LLM client
(Claude Desktop, Claude Code, Cursor, etc.) interact with the user's
local data catalog, cache, and dashboard system.

Usage:
    finch-epm mcp                  # stdio (for desktop MCP clients)
    finch-epm mcp --transport sse --port 8808  # HTTP (for network clients)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from mcp.server import FastMCP

from finch_epm.cache.local import LocalCacheEngine
from finch_epm.cache.models import QueryRequest
from finch_epm.catalog.catalog import CatalogStore
from finch_epm.mcp.sql_guard import validate_readonly_sql
from finch_epm.paths import cache_db_path, catalog_db_path
from finch_epm.profiles.manager import ProfileManager

logger = logging.getLogger(__name__)


def create_mcp_server(
    catalog: CatalogStore | None = None,
    cache: LocalCacheEngine | None = None,
    profile_manager: ProfileManager | None = None,
) -> FastMCP:
    """Create and configure the finch-epm MCP server.

    Args:
        catalog: Optional pre-built CatalogStore (creates one if None).
        cache: Optional pre-built LocalCacheEngine (creates one if None).
        profile_manager: Optional pre-built ProfileManager (creates one if None).

    Returns:
        Configured FastMCP server ready to run.
    """
    mcp = FastMCP(
        name="finch-epm",
        instructions=(
            "finch-epm is a local-first analytics tool. Use these tools to "
            "explore the user's data catalog, query cached data, and generate "
            "validated .fdash dashboard files. Read the fdash://spec resource "
            "first to understand the dashboard file format."
        ),
    )

    # Shared state -- lazily initialized
    _state: dict[str, Any] = {
        "catalog": catalog,
        "cache": cache,
        "pm": profile_manager,
    }

    def _get_catalog() -> CatalogStore:
        if _state["catalog"] is None:
            _state["catalog"] = CatalogStore(str(catalog_db_path()))
        return _state["catalog"]

    def _get_cache() -> LocalCacheEngine:
        if _state["cache"] is None:
            _state["cache"] = LocalCacheEngine(str(cache_db_path()), read_only=True)
        return _state["cache"]

    def _get_pm() -> ProfileManager:
        if _state["pm"] is None:
            _state["pm"] = ProfileManager()
        return _state["pm"]

    # -----------------------------------------------------------------------
    # Tools
    # -----------------------------------------------------------------------

    @mcp.tool(
        name="list_sources",
        description="List all configured data source profiles with their connector types.",
    )
    def list_sources() -> str:
        pm = _get_pm()
        profiles = pm.list_profiles()
        # Exclude LLM profiles
        data_profiles = [
            {"connector": ct, "profile": pn}
            for ct, pn in profiles if ct != "llm"
        ]
        if not data_profiles:
            return "No data sources configured. Run 'finch-epm setup' first."
        return json.dumps(data_profiles, indent=2)

    @mcp.tool(
        name="list_tables",
        description=(
            "List all tables available in a data profile's catalog. "
            "Returns table names, access status, and row count estimates."
        ),
    )
    def list_tables(connector: str, profile: str, accessible_only: bool = True) -> str:
        catalog = _get_catalog()
        status_filter = "accessible" if accessible_only else None
        tables = catalog.list_tables(connector, profile, access_status=status_filter)
        if not tables:
            return f"No tables found for {connector}/{profile}. Run 'finch-epm catalog --crawl' first."
        return json.dumps(tables, indent=2, default=str)

    @mcp.tool(
        name="describe_table",
        description=(
            "Get the full column list for a table, including column names, "
            "types, and whether they are custom fields."
        ),
    )
    def describe_table(connector: str, profile: str, table: str) -> str:
        catalog = _get_catalog()
        columns = catalog.list_columns(connector, profile, table)
        if not columns:
            return f"Table '{table}' not found in catalog for {connector}/{profile}."
        return json.dumps({"table": table, "columns": columns}, indent=2, default=str)

    @mcp.tool(
        name="preview_rows",
        description="Fetch sample rows from a cached table to see real data values and types.",
    )
    def preview_rows(table: str, limit: int = 5) -> str:
        cache = _get_cache()
        try:
            result = cache.execute_query(QueryRequest(
                sql=f'SELECT * FROM "{table}" LIMIT {min(limit, 50)}',
            ))
            rows = []
            for row in result.rows:
                rows.append(dict(zip(result.column_names, row)))
            return json.dumps({
                "table": table,
                "columns": result.column_names,
                "column_types": result.column_types,
                "rows": rows,
                "row_count": result.row_count,
            }, indent=2, default=str)
        except Exception as e:
            return f"Error previewing '{table}': {e}"

    @mcp.tool(
        name="query_cache",
        description=(
            "Execute a read-only SQL query against the local DuckDB cache. "
            "Only SELECT statements are allowed. Returns structured results. "
            "Use DuckDB SQL dialect (PostgreSQL-compatible)."
        ),
    )
    def query_cache(sql: str) -> str:
        # Validate SQL is read-only
        is_valid, error = validate_readonly_sql(sql)
        if not is_valid:
            return f"Query rejected: {error}"

        cache = _get_cache()
        try:
            result = cache.execute_query(QueryRequest(sql=sql))
            rows = []
            for row in result.rows:
                rows.append(dict(zip(result.column_names, row)))
            return json.dumps({
                "columns": result.column_names,
                "column_types": result.column_types,
                "rows": rows,
                "row_count": result.row_count,
                "execution_time_ms": result.execution_time_ms,
            }, indent=2, default=str)
        except Exception as e:
            return f"Query failed: {e}"

    @mcp.tool(
        name="validate_fdash",
        description=(
            "Validate a .fdash dashboard YAML string. Returns success or "
            "a structured list of errors with descriptions."
        ),
    )
    def validate_fdash_tool(content: str) -> str:
        from finch_epm.dashboard.fdash import FdashError, load_fdash_string, validate_fdash

        try:
            spec = load_fdash_string(content, source="<mcp-validation>")
        except FdashError as e:
            return json.dumps({"valid": False, "errors": [str(e)]})

        errors = validate_fdash(spec)
        if errors:
            return json.dumps({"valid": False, "errors": errors})
        return json.dumps({"valid": True, "name": spec.name, "queries": len(spec.queries),
                           "charts": len(spec.get_all_charts())})

    @mcp.tool(
        name="write_fdash",
        description=(
            "Write a validated .fdash file to disk. Validates before writing. "
            "Returns the file path on success or errors on failure."
        ),
    )
    def write_fdash_tool(path: str, content: str) -> str:
        from finch_epm.dashboard.fdash import FdashError, load_fdash_string, validate_fdash

        try:
            spec = load_fdash_string(content, source="<mcp-write>")
        except FdashError as e:
            return json.dumps({"success": False, "errors": [str(e)]})

        errors = validate_fdash(spec)
        if errors:
            return json.dumps({"success": False, "errors": errors})

        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
        return json.dumps({"success": True, "path": str(out.resolve()), "name": spec.name})

    @mcp.tool(
        name="open_fdash",
        description="Open a .fdash dashboard in the user's browser via the local web server.",
    )
    def open_fdash_tool(path: str) -> str:
        import subprocess
        import sys

        p = Path(path)
        if not p.exists():
            return f"File not found: {path}"
        if p.suffix not in (".fdash", ".yml", ".yaml"):
            return f"Not a dashboard file: {path}"

        # Launch in background
        subprocess.Popen(
            [sys.executable, "-m", "finch_epm.cli.main", "open", str(p)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return f"Opening dashboard: {p.name} (http://localhost:8765)"

    @mcp.tool(
        name="get_dimension_hierarchy",
        description="Get the dimension hierarchy for a dimensional entity (e.g., subsidiary, department).",
    )
    def get_dimension_hierarchy(connector: str, profile: str, dimension: str) -> str:
        catalog = _get_catalog()
        dims = catalog.list_dimensions(connector, profile)
        match = [d for d in dims if d["dimension_name"] == dimension]
        if not match:
            available = [d["dimension_name"] for d in dims]
            return f"Dimension '{dimension}' not found. Available: {available}"
        return json.dumps(match[0], indent=2, default=str)

    @mcp.tool(
        name="list_themes",
        description="List available dashboard theme presets with descriptions.",
    )
    def list_themes() -> str:
        # Stub until M3 -- return the planned themes
        themes = [
            {"name": "modern_light", "description": "Clean light theme (default)"},
            {"name": "modern_dark", "description": "Dark theme with muted accents"},
            {"name": "financial_terminal", "description": "Bloomberg-style dark, amber/cyan accents"},
            {"name": "executive", "description": "WSJ/Economist-inspired, conservative palette"},
            {"name": "wsj", "description": "Charcoal on cream, condensed sans"},
            {"name": "monospace", "description": "Terminal aesthetic, minimal color"},
        ]
        return json.dumps(themes, indent=2)

    # -----------------------------------------------------------------------
    # Resources
    # -----------------------------------------------------------------------

    @mcp.resource(
        "fdash://spec",
        name="Dashboard Specification",
        description="The complete .fdash dashboard file format specification (DASHBOARDS.md).",
        mime_type="text/markdown",
    )
    def resource_spec() -> str:
        candidates = [
            Path(__file__).parent.parent.parent.parent / "DASHBOARDS.md",
            Path.cwd() / "DASHBOARDS.md",
        ]
        for p in candidates:
            if p.exists():
                return p.read_text(encoding="utf-8")
        return "(DASHBOARDS.md not found)"

    @mcp.resource(
        "fdash://catalog/{profile}",
        name="Catalog Summary",
        description="Compact JSON summary of tables and columns for a data profile.",
        mime_type="application/json",
    )
    def resource_catalog(profile: str) -> str:
        catalog = _get_catalog()
        pm = _get_pm()
        # Find the connector type for this profile
        for ct, pn in pm.list_profiles():
            if pn == profile and ct != "llm":
                tables = catalog.list_tables(ct, pn)
                summary = []
                for t in tables:
                    cols = catalog.list_columns(ct, pn, t["table_name"])
                    summary.append({
                        "table": t["table_name"],
                        "access_status": t.get("access_status", "unknown"),
                        "columns": [
                            {"name": c["column_name"], "type": c["column_type"]}
                            for c in cols
                        ],
                    })
                return json.dumps(summary, indent=2, default=str)
        return json.dumps({"error": f"Profile '{profile}' not found"})

    @mcp.resource(
        "fdash://themes",
        name="Available Themes",
        description="List of theme presets available for dashboards.",
        mime_type="application/json",
    )
    def resource_themes() -> str:
        return list_themes()

    @mcp.resource(
        "fdash://examples",
        name="Example Dashboards",
        description="Canonical .fdash examples for reference and few-shot prompting.",
        mime_type="text/yaml",
    )
    def resource_examples() -> str:
        examples_dir = Path(__file__).parent.parent.parent.parent / "examples"
        if not examples_dir.is_dir():
            examples_dir = Path.cwd() / "examples"

        result_parts: list[str] = []
        if examples_dir.is_dir():
            for f in sorted(examples_dir.glob("*.fdash"))[:5]:
                result_parts.append(f"# === {f.name} ===\n")
                result_parts.append(f.read_text(encoding="utf-8"))
                result_parts.append("\n\n")

        if not result_parts:
            result_parts.append("# No example .fdash files found.\n")

        return "".join(result_parts)

    return mcp
