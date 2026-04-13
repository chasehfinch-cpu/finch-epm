"""Dashboard query resolver.

Executes dashboard queries against the cache engine, substituting
parameter values into SQL. Returns results keyed by query name.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from finch_epm.cache.base import CacheEngine
from finch_epm.cache.models import QueryRequest, QueryResult, StalenessInfo, StalenessLevel
from finch_epm.dashboard.models import DashboardSpec, ParameterSpec


def resolve_parameters(
    spec: DashboardSpec,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge parameter defaults with user overrides.

    Resolves parameters from three sources (in priority order):
        1. Explicit ``overrides`` (URL query params, user-provided values)
        2. Filter definitions (``spec.filters`` with ``parameter`` + ``default``)
        3. Parameter definitions (``spec.parameters`` with ``type`` + ``default``)

    Args:
        spec: The dashboard spec containing parameter and filter definitions.
        overrides: User-provided parameter values that override defaults.

    Returns:
        Dict mapping parameter name to resolved value.
    """
    result: dict[str, Any] = {}
    overrides = overrides or {}

    # Start with explicit parameter definitions
    for name, param in spec.parameters.items():
        value = overrides.get(name, param.default)
        result[name] = _resolve_value(value, param)

    # Merge filter parameters (filter.parameter -> filter.default)
    for f in spec.filters:
        param_name = f.parameter
        if param_name in overrides:
            result[param_name] = overrides[param_name]
        elif param_name not in result and f.default is not None:
            result[param_name] = f.default

    # Pass through any remaining overrides not yet captured
    # (e.g., cross-filter values injected by the frontend)
    for name, value in overrides.items():
        if name not in result:
            result[name] = value

    return result


def resolve_queries(
    spec: DashboardSpec,
    cache: CacheEngine,
    parameter_overrides: dict[str, Any] | None = None,
    federation_router: Any | None = None,
) -> dict[str, QueryResult]:
    """Execute all queries in a dashboard spec against the cache.

    Substitutes parameter values into SQL using named parameter syntax
    (`:param_name`), then executes against the cache engine.

    Args:
        spec: The dashboard spec.
        cache: The cache engine to query.
        parameter_overrides: Optional parameter value overrides.
        federation_router: Optional :class:`FederatedQueryRouter` for
            hybrid local/remote execution. When provided, each query
            is routed through the router's decision logic.

    Returns:
        Dict mapping query name to QueryResult.
    """
    params = resolve_parameters(spec, parameter_overrides)
    results: dict[str, QueryResult] = {}

    # Load semantic model if referenced
    semantic_model = None
    if spec.semantic_model:
        from finch_epm.engine.semantic import load_semantic_model

        semantic_model = load_semantic_model(spec.semantic_model)

    for query in spec.queries:
        # Build SQL from semantic model or use raw SQL
        if query.entity and semantic_model:
            from finch_epm.engine.query_builder import SemanticQueryBuilder

            builder = SemanticQueryBuilder(semantic_model)
            sql = builder.build_query(
                entities=[query.entity],
                measures=query.measures,
                group_by=query.group_by,
                filters=query.query_filters,
                order_by=query.order_by,
            )
            sql = _substitute_parameters(sql, params)
        else:
            sql = _substitute_parameters(query.sql, params)

        # Pre-execution validation: check referenced tables exist
        tables = _extract_table_names(sql)
        if tables and hasattr(cache, "validate_tables_exist"):
            found, missing = cache.validate_tables_exist(tables)  # type: ignore[attr-defined]
            if missing:
                results[query.name] = QueryResult(
                    column_names=[],
                    column_types=[],
                    rows=[],
                    row_count=0,
                    staleness=StalenessInfo(
                        level=StalenessLevel.MISSING,
                        tables_involved=tables,
                    ),
                    execution_time_ms=0.0,
                    metadata={"missing_tables": missing},
                )
                continue

        try:
            if federation_router is not None:
                results[query.name] = federation_router.execute(
                    sql, source_hint=query.source
                )
            else:
                request = QueryRequest(
                    sql=sql,
                    source_name=query.source or (spec.sources[0] if spec.sources else None),
                )
                results[query.name] = cache.execute_query(request)
        except Exception as exc:
            # Graceful degradation: return an error result instead of crashing
            # so other charts in the dashboard can still render.
            error_msg = str(exc)
            error_meta: dict[str, Any] = {"error": error_msg, "sql": sql}

            # Detect specific failure modes and provide actionable guidance
            error_lower = error_msg.lower()
            if "does not exist" in error_lower or "not found" in error_lower:
                error_meta["error_type"] = "missing_table"
                error_meta["missing_tables"] = tables
                error_meta["guidance"] = (
                    f"This query references tables that are not in your local cache. "
                    f"You may need to sync: {', '.join(tables)}. "
                    f"Run: finch-epm sync -c <connector> -p <profile> -t <table>"
                )
            elif "permission" in error_lower or "access" in error_lower:
                error_meta["error_type"] = "permission_denied"
                error_meta["guidance"] = (
                    "Your credentials do not have access to the data this query needs. "
                    "Contact your administrator to request access to the required tables."
                )
            elif "column" in error_lower and ("not found" in error_lower or "does not exist" in error_lower):
                error_meta["error_type"] = "missing_column"
                error_meta["guidance"] = (
                    "This query references columns that don't exist in your cached data. "
                    "The data source schema may differ from what the dashboard author has. "
                    "Try re-crawling: finch-epm catalog --crawl -c <connector> -p <profile>"
                )
            else:
                error_meta["error_type"] = "query_error"
                error_meta["guidance"] = (
                    f"Query '{query.name}' failed: {error_msg}"
                )

            results[query.name] = QueryResult(
                column_names=[],
                column_types=[],
                rows=[],
                row_count=0,
                staleness=StalenessInfo(
                    level=StalenessLevel.MISSING,
                    tables_involved=tables,
                ),
                execution_time_ms=0.0,
                metadata=error_meta,
            )

    return results


def _substitute_parameters(sql: str, params: dict[str, Any]) -> str:
    """Replace :param_name placeholders in SQL with actual values.

    Uses simple string replacement with proper quoting for safety.
    DuckDB parameterized queries would be better, but the cache engine's
    execute_query takes raw SQL for now.

    Any :param_name placeholder remaining after substitution (because the
    parameter was not provided or was deleted by a filter set to "All")
    is replaced with NULL. This prevents raw ``:param`` tokens from
    reaching the SQL parser.
    """
    for name, value in params.items():
        placeholder = f":{name}"
        if placeholder in sql:
            if value is None:
                sql = sql.replace(placeholder, "NULL")
            elif isinstance(value, (int, float)):
                sql = sql.replace(placeholder, str(value))
            else:
                # String values -- escape single quotes
                escaped = str(value).replace("'", "''")
                sql = sql.replace(placeholder, f"'{escaped}'")

    # Replace any remaining :param_name placeholders with NULL.
    # This handles filters set to "All" (parameter deleted from overrides).
    sql = re.sub(r":([a-zA-Z_][a-zA-Z0-9_]*)", _null_if_unresolved, sql)
    return sql


def _null_if_unresolved(match: re.Match) -> str:
    """Replace unresolved :param placeholders with NULL.

    Skips DuckDB-internal tokens like ::TYPE casts.
    """
    # Check if this is a DuckDB :: cast (preceded by another colon)
    start = match.start()
    if start > 0 and match.string[start - 1] == ":":
        return match.group(0)  # Leave ::TYPE casts alone
    return "NULL"


def _resolve_value(value: Any, param: ParameterSpec) -> Any:
    """Resolve a parameter value based on its type."""
    if value is None:
        return None

    if param.type == "period":
        return _resolve_period(value)

    return value


def _resolve_period(value: Any) -> str:
    """Resolve symbolic period names to date strings.

    Supported symbols:
        - current_quarter_start
        - current_quarter_end
        - current_year_start
        - current_year_end
        - current_month_start
        - current_month_end
        - today
    """
    if not isinstance(value, str):
        return str(value)

    today = date.today()
    quarter = (today.month - 1) // 3

    resolvers: dict[str, date] = {
        "today": today,
        "current_month_start": today.replace(day=1),
        "current_month_end": _month_end(today),
        "current_quarter_start": today.replace(month=quarter * 3 + 1, day=1),
        "current_quarter_end": _month_end(
            today.replace(month=quarter * 3 + 3, day=1)
        ),
        "current_year_start": today.replace(month=1, day=1),
        "current_year_end": today.replace(month=12, day=31),
    }

    if value in resolvers:
        return resolvers[value].isoformat()

    # Not a symbolic name -- return as-is
    return value


def _month_end(d: date) -> date:
    """Return the last day of the month for the given date."""
    if d.month == 12:
        return d.replace(day=31)
    return d.replace(month=d.month + 1, day=1) - timedelta(days=1)


def _extract_table_names(sql: str) -> list[str]:
    """Best-effort extraction of table names from FROM and JOIN clauses.

    Handles common SQL patterns including subqueries (skips them),
    aliases, and quoted identifiers. Not a full SQL parser — covers
    the patterns used in .fdash queries.

    Returns:
        De-duplicated list of table names referenced in the SQL.
    """
    # Match FROM/JOIN followed by a table name (not a subquery)
    pattern = r"(?:FROM|JOIN)\s+(?:\"([^\"]+)\"|([A-Za-z_][A-Za-z0-9_]*))"
    matches = re.findall(pattern, sql, re.IGNORECASE)
    tables: list[str] = []
    seen: set[str] = set()
    for quoted, unquoted in matches:
        name = quoted or unquoted
        # Skip SQL keywords that might match (e.g., SELECT after a subquery)
        if name.upper() in {"SELECT", "WHERE", "GROUP", "ORDER", "HAVING", "LIMIT",
                            "UNION", "EXCEPT", "INTERSECT", "VALUES", "SET"}:
            continue
        if name not in seen:
            seen.add(name)
            tables.append(name)
    return tables
