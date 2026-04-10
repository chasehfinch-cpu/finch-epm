"""Dashboard query resolver.

Executes dashboard queries against the cache engine, substituting
parameter values into SQL. Returns results keyed by query name.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from finch_epm.cache.base import CacheEngine
from finch_epm.cache.models import QueryRequest, QueryResult
from finch_epm.dashboard.models import DashboardSpec, ParameterSpec


def resolve_parameters(
    spec: DashboardSpec,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge parameter defaults with user overrides.

    Resolves special parameter types:
        - period: converts symbolic names (current_quarter_start, etc.) to date strings
        - string: pass through
        - number: pass through

    Args:
        spec: The dashboard spec containing parameter definitions.
        overrides: User-provided parameter values that override defaults.

    Returns:
        Dict mapping parameter name to resolved value.
    """
    result: dict[str, Any] = {}
    overrides = overrides or {}

    for name, param in spec.parameters.items():
        value = overrides.get(name, param.default)
        result[name] = _resolve_value(value, param)

    return result


def resolve_queries(
    spec: DashboardSpec,
    cache: CacheEngine,
    parameter_overrides: dict[str, Any] | None = None,
) -> dict[str, QueryResult]:
    """Execute all queries in a dashboard spec against the cache.

    Substitutes parameter values into SQL using named parameter syntax
    (`:param_name`), then executes against the cache engine.

    Args:
        spec: The dashboard spec.
        cache: The cache engine to query.
        parameter_overrides: Optional parameter value overrides.

    Returns:
        Dict mapping query name to QueryResult.
    """
    params = resolve_parameters(spec, parameter_overrides)
    results: dict[str, QueryResult] = {}

    for query in spec.queries:
        sql = _substitute_parameters(query.sql, params)
        request = QueryRequest(
            sql=sql,
            source_name=query.source or (spec.sources[0] if spec.sources else None),
        )
        results[query.name] = cache.execute_query(request)

    return results


def _substitute_parameters(sql: str, params: dict[str, Any]) -> str:
    """Replace :param_name placeholders in SQL with actual values.

    Uses simple string replacement with proper quoting for safety.
    DuckDB parameterized queries would be better, but the cache engine's
    execute_query takes raw SQL for now.
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
    return sql


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
