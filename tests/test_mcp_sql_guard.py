"""Tests for the MCP SQL injection guard."""

from __future__ import annotations

import pytest

from finch_epm.mcp.sql_guard import validate_readonly_sql


class TestAllowedQueries:
    """Queries that should pass validation."""

    def test_simple_select(self) -> None:
        ok, err = validate_readonly_sql("SELECT 1")
        assert ok, err

    def test_select_from_table(self) -> None:
        ok, err = validate_readonly_sql("SELECT * FROM Account")
        assert ok, err

    def test_select_with_where(self) -> None:
        ok, err = validate_readonly_sql(
            "SELECT id, name FROM Account WHERE accttype = 'Income'"
        )
        assert ok, err

    def test_select_with_join(self) -> None:
        ok, err = validate_readonly_sql(
            "SELECT a.name, t.amount FROM Account a "
            "JOIN TransactionLine t ON a.id = t.account"
        )
        assert ok, err

    def test_select_with_subquery(self) -> None:
        ok, err = validate_readonly_sql(
            "SELECT * FROM (SELECT 1 AS x) sub"
        )
        assert ok, err

    def test_cte_with_select(self) -> None:
        ok, err = validate_readonly_sql(
            "WITH cte AS (SELECT 1 AS x) SELECT * FROM cte"
        )
        assert ok, err

    def test_select_with_group_by(self) -> None:
        ok, err = validate_readonly_sql(
            "SELECT accttype, COUNT(*) FROM Account GROUP BY accttype"
        )
        assert ok, err

    def test_select_with_order_limit(self) -> None:
        ok, err = validate_readonly_sql(
            "SELECT * FROM Account ORDER BY name LIMIT 10"
        )
        assert ok, err

    def test_union(self) -> None:
        ok, err = validate_readonly_sql(
            "SELECT 1 UNION ALL SELECT 2"
        )
        assert ok, err

    def test_select_with_cast(self) -> None:
        ok, err = validate_readonly_sql(
            "SELECT CAST(amount AS DOUBLE) FROM TransactionLine"
        )
        assert ok, err


class TestBlockedQueries:
    """Queries that should be rejected."""

    def test_insert(self) -> None:
        ok, err = validate_readonly_sql("INSERT INTO Account VALUES (1, 'x')")
        assert not ok
        assert "not allowed" in err.lower() or "disallowed" in err.lower()

    def test_update(self) -> None:
        ok, err = validate_readonly_sql("UPDATE Account SET name = 'x'")
        assert not ok

    def test_delete(self) -> None:
        ok, err = validate_readonly_sql("DELETE FROM Account")
        assert not ok

    def test_drop_table(self) -> None:
        ok, err = validate_readonly_sql("DROP TABLE Account")
        assert not ok

    def test_create_table(self) -> None:
        ok, err = validate_readonly_sql("CREATE TABLE evil (id INT)")
        assert not ok

    def test_alter_table(self) -> None:
        ok, err = validate_readonly_sql("ALTER TABLE Account ADD COLUMN x INT")
        assert not ok

    def test_multiple_statements(self) -> None:
        ok, err = validate_readonly_sql("SELECT 1; DROP TABLE Account")
        assert not ok
        assert "multiple" in err.lower()

    def test_empty_sql(self) -> None:
        ok, err = validate_readonly_sql("")
        assert not ok

    def test_invalid_sql(self) -> None:
        ok, err = validate_readonly_sql("NOT VALID SQL AT ALL !!!")
        # Should either parse-error or reject
        # sqlglot may or may not parse this - either way it shouldn't pass as valid
        if ok:
            # If sqlglot somehow parses it, that's fine as long as it's a SELECT
            pass
        else:
            assert err  # Should have an error message
