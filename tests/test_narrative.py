"""Tests for markdown narrative block templating."""

from __future__ import annotations

import pytest

from finch_epm.dashboard.narrative import render_narrative


class MockQueryResult:
    def __init__(self, column_names, rows):
        self.column_names = column_names
        self.rows = rows


class TestRenderNarrative:
    def test_simple_substitution(self) -> None:
        results = {
            "totals": MockQueryResult(["revenue", "expense"], [[1000000, 750000]])
        }
        template = "Total revenue is {{ totals.revenue }}."
        result = render_narrative(template, results)
        assert result == "Total revenue is 1000000."

    def test_multiple_substitutions(self) -> None:
        results = {
            "totals": MockQueryResult(["revenue", "expense"], [[100, 80]]),
        }
        template = "Revenue: {{ totals.revenue }}, Expense: {{ totals.expense }}"
        result = render_narrative(template, results)
        assert result == "Revenue: 100, Expense: 80"

    def test_missing_query_uses_fallback(self) -> None:
        result = render_narrative("Value: {{ missing.col }}", {})
        assert result == "Value: N/A"

    def test_custom_fallback(self) -> None:
        result = render_narrative(
            "Value: {{ missing.col }}", {}, fallback="--"
        )
        assert result == "Value: --"

    def test_missing_column_uses_fallback(self) -> None:
        results = {
            "q": MockQueryResult(["a"], [[1]])
        }
        result = render_narrative("{{ q.nonexistent }}", results)
        assert result == "N/A"

    def test_empty_rows_uses_fallback(self) -> None:
        results = {
            "q": MockQueryResult(["a"], [])
        }
        result = render_narrative("{{ q.a }}", results)
        assert result == "N/A"

    def test_no_placeholders_passes_through(self) -> None:
        template = "# Report Summary\n\nThis is plain markdown."
        result = render_narrative(template, {})
        assert result == template

    def test_dict_result_format(self) -> None:
        results = {
            "q": {"column_names": ["val"], "rows": [[42]]}
        }
        result = render_narrative("Answer: {{ q.val }}", results)
        assert result == "Answer: 42"

    def test_none_value_uses_fallback(self) -> None:
        results = {
            "q": MockQueryResult(["val"], [[None]])
        }
        result = render_narrative("{{ q.val }}", results)
        assert result == "N/A"


class TestFdashThemeFields:
    """Test that the fdash parser handles new v0.5 theme fields."""

    def test_parse_theme_string(self) -> None:
        from finch_epm.dashboard.fdash import load_fdash_string
        content = """
name: Test
theme: financial
queries:
  - name: q
    sql: SELECT 1
charts:
  - type: kpi
    title: T
    data: q
    value: '1'
"""
        spec = load_fdash_string(content)
        assert spec.theme == "financial"

    def test_parse_theme_dict(self) -> None:
        from finch_epm.dashboard.fdash import load_fdash_string
        content = """
name: Test
theme:
  bg_page: "#ff0000"
  accent: "#00ff00"
queries:
  - name: q
    sql: SELECT 1
charts:
  - type: kpi
    title: T
    data: q
    value: '1'
"""
        spec = load_fdash_string(content)
        assert isinstance(spec.theme, dict)
        assert spec.theme["bg_page"] == "#ff0000"

    def test_parse_brand(self) -> None:
        from finch_epm.dashboard.fdash import load_fdash_string
        content = """
name: Test
brand:
  company_name: Acme Corp
  footer_text: Confidential
queries:
  - name: q
    sql: SELECT 1
charts:
  - type: kpi
    title: T
    data: q
    value: '1'
"""
        spec = load_fdash_string(content)
        assert spec.brand["company_name"] == "Acme Corp"

    def test_parse_custom_css(self) -> None:
        from finch_epm.dashboard.fdash import load_fdash_string
        content = """
name: Test
custom_css: ".my-class { color: red; }"
queries:
  - name: q
    sql: SELECT 1
charts:
  - type: kpi
    title: T
    data: q
    value: '1'
"""
        spec = load_fdash_string(content)
        assert ".my-class" in spec.custom_css

    def test_no_theme_fields_backward_compatible(self) -> None:
        from finch_epm.dashboard.fdash import load_fdash_string
        content = """
name: Legacy Dashboard
queries:
  - name: q
    sql: SELECT 1
charts:
  - type: kpi
    title: T
    data: q
    value: '1'
"""
        spec = load_fdash_string(content)
        assert spec.theme is None
        assert spec.custom_css is None
        assert spec.layout is None
        assert spec.brand is None
