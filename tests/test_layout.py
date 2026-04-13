"""Tests for dashboard layout parsing."""

from __future__ import annotations

import pytest

from finch_epm.dashboard.layout import LayoutRow, parse_layout


class TestParseLayout:
    def test_simple_row_form(self) -> None:
        raw = [{"row": ["Chart A", "Chart B"]}]
        rows = parse_layout(raw)
        assert len(rows) == 1
        assert len(rows[0].columns) == 2
        assert rows[0].columns[0].chart_ref == "Chart A"
        assert rows[0].columns[1].chart_ref == "Chart B"

    def test_single_item_row_is_full_width(self) -> None:
        raw = [{"row": ["Wide Chart"]}]
        rows = parse_layout(raw)
        assert rows[0].columns[0].width == "full"

    def test_explicit_columns_form(self) -> None:
        raw = [{
            "columns": [
                {"chart": "Revenue", "width": "half"},
                {"chart": "Expense", "width": "half"},
            ]
        }]
        rows = parse_layout(raw)
        assert len(rows) == 1
        assert rows[0].columns[0].chart_ref == "Revenue"
        assert rows[0].columns[0].width == "half"

    def test_multiple_rows(self) -> None:
        raw = [
            {"row": ["KPI 1", "KPI 2", "KPI 3"]},
            {"row": ["Detail Table"], "width": "full"},
        ]
        rows = parse_layout(raw)
        assert len(rows) == 2
        assert len(rows[0].columns) == 3

    def test_empty_layout(self) -> None:
        rows = parse_layout([])
        assert rows == []

    def test_invalid_items_skipped(self) -> None:
        rows = parse_layout(["not a dict", 123, None])
        assert rows == []

    def test_named_row(self) -> None:
        raw = [{"name": "header", "row": ["Title"]}]
        rows = parse_layout(raw)
        assert rows[0].name == "header"
