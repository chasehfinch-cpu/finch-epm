"""SQL injection guard for the MCP query_cache tool.

Uses sqlglot to parse SQL and reject anything that is not a read-only
SELECT or WITH...SELECT statement. This protects the local DuckDB cache
from mutations via MCP tool calls.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp


# Statement types that are allowed (read-only).
_ALLOWED_TYPES = (exp.Select, exp.Union, exp.Intersect, exp.Except)


def validate_readonly_sql(sql: str) -> tuple[bool, str]:
    """Parse SQL and verify it is read-only.

    Args:
        sql: The SQL statement to validate.

    Returns:
        Tuple of (is_valid, error_message). error_message is empty when valid.
    """
    try:
        statements = sqlglot.parse(sql, dialect="duckdb")
    except sqlglot.errors.ParseError as e:
        return False, f"SQL parse error: {e}"

    if not statements:
        return False, "Empty SQL statement."

    if len(statements) > 1:
        return False, "Multiple SQL statements are not allowed. Send one query at a time."

    stmt = statements[0]
    if stmt is None:
        return False, "Could not parse SQL statement."

    # Check the top-level statement type
    if isinstance(stmt, _ALLOWED_TYPES):
        # Also check for subqueries that might contain DML via CTEs
        # (CTEs with SELECT are fine, CTEs with INSERT/UPDATE are not)
        for node in stmt.walk():
            if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Drop,
                                 exp.Create, exp.Alter)):
                return False, (
                    f"Statement contains a disallowed operation: "
                    f"{type(node).__name__}. Only SELECT queries are allowed."
                )
        return True, ""

    # Reject everything else explicitly
    stmt_type = type(stmt).__name__
    return False, (
        f"Statement type '{stmt_type}' is not allowed. "
        "Only SELECT and WITH...SELECT queries are permitted. "
        "INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, ATTACH, COPY, "
        "and EXPORT are blocked."
    )
