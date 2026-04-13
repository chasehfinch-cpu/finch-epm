"""Markdown narrative blocks for dashboards.

A chart of type ``markdown`` renders a prose block. The content can
reference query result values with ``{{ query_name.column }}`` syntax,
pulling from the first row of the named query.
"""

from __future__ import annotations

import re
from typing import Any


def render_narrative(
    template: str,
    query_results: dict[str, Any],
    fallback: str = "N/A",
) -> str:
    """Render a narrative template with query value substitution.

    Args:
        template: Markdown string with ``{{ query_name.column }}`` placeholders.
        query_results: Dict mapping query name to query result objects.
            Each result should have ``column_names`` and ``rows`` attributes,
            or be a dict with those keys.
        fallback: String to substitute when a referenced value is missing.

    Returns:
        Rendered markdown string.
    """
    pattern = re.compile(r"\{\{\s*(\w+)\.(\w+)\s*\}\}")

    def replace(match: re.Match) -> str:
        query_name = match.group(1)
        column_name = match.group(2)

        result = query_results.get(query_name)
        if result is None:
            return fallback

        # Support both objects (QueryResult) and dicts
        if hasattr(result, "column_names"):
            col_names = result.column_names
            rows = result.rows
        elif isinstance(result, dict):
            col_names = result.get("column_names", [])
            rows = result.get("rows", [])
        else:
            return fallback

        if not rows:
            return fallback

        try:
            col_idx = col_names.index(column_name)
            value = rows[0][col_idx]
            if value is None:
                return fallback
            return str(value)
        except (ValueError, IndexError):
            return fallback

    return pattern.sub(replace, template)
