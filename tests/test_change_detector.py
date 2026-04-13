"""Tests for schema change detection between catalog crawls."""

from __future__ import annotations

from datetime import datetime

import pytest

from finch_epm.catalog.change_detector import (
    NewColumn,
    NewTable,
    RemovedColumn,
    RemovedTable,
    SchemaChanges,
    TypeChange,
    detect_changes,
    detect_unmapped_accounts,
    flatten_pl_sections,
)
from finch_epm.connectors.types import (
    ColumnInfo,
    ColumnType,
    SchemaInfo,
    TableInfo,
)
from finch_epm.engine.chart_of_accounts import PLSection, get_default_pl_structure


def _make_schema(tables: list[TableInfo]) -> SchemaInfo:
    return SchemaInfo(
        tables=tables,
        source_name="test",
        profile_name="default",
        introspected_at=datetime.now(),
    )


def _make_table(name: str, columns: list[tuple[str, ColumnType]] | None = None) -> TableInfo:
    cols = [
        ColumnInfo(name=cname, display_name=cname, column_type=ctype)
        for cname, ctype in (columns or [("id", ColumnType.STRING)])
    ]
    return TableInfo(name=name, display_name=name, columns=cols)


class TestDetectChanges:
    def test_no_changes(self) -> None:
        old_tables = [{"table_name": "Account"}]
        old_columns = {
            "Account": [{"column_name": "id", "column_type": "string"}]
        }
        new_schema = _make_schema([
            _make_table("Account", [("id", ColumnType.STRING)])
        ])
        changes = detect_changes(old_tables, old_columns, new_schema)
        assert not changes.has_changes
        assert changes.total_changes == 0
        assert changes.summary() == "no changes"

    def test_new_table(self) -> None:
        old_tables = [{"table_name": "Account"}]
        old_columns = {"Account": [{"column_name": "id", "column_type": "string"}]}
        new_schema = _make_schema([
            _make_table("Account", [("id", ColumnType.STRING)]),
            _make_table("NewTable", [("col1", ColumnType.STRING), ("col2", ColumnType.INTEGER)]),
        ])
        changes = detect_changes(old_tables, old_columns, new_schema)
        assert changes.has_changes
        assert len(changes.new_tables) == 1
        assert changes.new_tables[0].name == "NewTable"
        assert changes.new_tables[0].column_count == 2

    def test_removed_table(self) -> None:
        old_tables = [
            {"table_name": "Account"},
            {"table_name": "OldTable"},
        ]
        old_columns = {
            "Account": [{"column_name": "id", "column_type": "string"}],
            "OldTable": [{"column_name": "x", "column_type": "string"}],
        }
        new_schema = _make_schema([_make_table("Account")])
        changes = detect_changes(old_tables, old_columns, new_schema)
        assert len(changes.removed_tables) == 1
        assert changes.removed_tables[0].name == "OldTable"

    def test_new_column(self) -> None:
        old_tables = [{"table_name": "Account"}]
        old_columns = {
            "Account": [{"column_name": "id", "column_type": "string"}]
        }
        new_schema = _make_schema([
            _make_table("Account", [
                ("id", ColumnType.STRING),
                ("new_field", ColumnType.FLOAT),
            ])
        ])
        changes = detect_changes(old_tables, old_columns, new_schema)
        assert len(changes.new_columns) == 1
        assert changes.new_columns[0].column_name == "new_field"
        assert changes.new_columns[0].table_name == "Account"

    def test_removed_column(self) -> None:
        old_tables = [{"table_name": "Account"}]
        old_columns = {
            "Account": [
                {"column_name": "id", "column_type": "string"},
                {"column_name": "old_field", "column_type": "string"},
            ]
        }
        new_schema = _make_schema([_make_table("Account")])
        changes = detect_changes(old_tables, old_columns, new_schema)
        assert len(changes.removed_columns) == 1
        assert changes.removed_columns[0].column_name == "old_field"

    def test_type_change(self) -> None:
        old_tables = [{"table_name": "Account"}]
        old_columns = {
            "Account": [{"column_name": "amount", "column_type": "string"}]
        }
        new_schema = _make_schema([
            _make_table("Account", [("amount", ColumnType.FLOAT)])
        ])
        changes = detect_changes(old_tables, old_columns, new_schema)
        assert len(changes.type_changes) == 1
        assert changes.type_changes[0].old_type == "string"
        assert changes.type_changes[0].new_type == "float"

    def test_first_crawl_no_old_data(self) -> None:
        new_schema = _make_schema([_make_table("Account")])
        changes = detect_changes([], {}, new_schema)
        assert len(changes.new_tables) == 1
        assert not changes.removed_tables

    def test_summary_format(self) -> None:
        changes = SchemaChanges(
            new_tables=[NewTable("A", "A", 5)],
            new_columns=[NewColumn("B", "c", "string")],
        )
        summary = changes.summary()
        assert "1 new table(s)" in summary
        assert "1 new column(s)" in summary


class TestDetectUnmappedAccounts:
    def test_mapped_account_not_flagged(self) -> None:
        pl = get_default_pl_structure()
        flat = flatten_pl_sections(pl)
        # Income is in the default structure
        rows = [{"id": "1", "accttype": "Income", "acctnumber": "4000", "fullname": "Revenue"}]
        unmapped = detect_unmapped_accounts(rows, flat, set())
        assert len(unmapped) == 0

    def test_unmapped_account_flagged(self) -> None:
        pl = get_default_pl_structure()
        flat = flatten_pl_sections(pl)
        rows = [
            {"id": "1", "accttype": "Income", "acctnumber": "4000", "fullname": "Revenue"},
            {"id": "2", "accttype": "WeirdType", "acctnumber": "9999", "fullname": "Mystery"},
        ]
        unmapped = detect_unmapped_accounts(rows, flat, set())
        assert len(unmapped) == 1
        assert unmapped[0]["id"] == "2"

    def test_already_classified_skipped(self) -> None:
        pl = get_default_pl_structure()
        flat = flatten_pl_sections(pl)
        rows = [{"id": "99", "accttype": "WeirdType", "acctnumber": "9999", "fullname": "X"}]
        unmapped = detect_unmapped_accounts(rows, flat, {"99"})
        assert len(unmapped) == 0

    def test_account_number_prefix_match(self) -> None:
        # Create a structure with specific account number prefixes
        section = PLSection(
            name="test",
            display_name="Test",
            account_numbers=["8100"],
        )
        rows = [
            {"id": "1", "accttype": "Other", "acctnumber": "8100", "fullname": "Matched"},
            {"id": "2", "accttype": "Other", "acctnumber": "9999", "fullname": "Unmatched"},
        ]
        unmapped = detect_unmapped_accounts(rows, [section], set())
        assert len(unmapped) == 1
        assert unmapped[0]["id"] == "2"

    def test_flatten_pl_sections(self) -> None:
        pl = get_default_pl_structure()
        flat = flatten_pl_sections(pl)
        assert len(flat) > 1  # Root + children
        names = [s.name for s in flat]
        assert "revenue" in names
        assert "net_income" in names
