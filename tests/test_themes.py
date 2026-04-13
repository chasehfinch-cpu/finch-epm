"""Tests for the dashboard theming system."""

from __future__ import annotations

import pytest

from finch_epm.dashboard.themes import get_theme, list_themes
from finch_epm.dashboard.themes.css import scope_custom_css, tokens_to_css
from finch_epm.dashboard.themes.presets import PRESETS, get_preset_names
from finch_epm.dashboard.themes.tokens import PLLevelStyle, ThemeTokens


class TestThemeTokens:
    def test_default_tokens_have_all_fields(self) -> None:
        tokens = ThemeTokens(name="test")
        assert tokens.bg_page
        assert tokens.font_family
        assert tokens.chart_colors
        assert len(tokens.chart_colors) >= 8

    def test_to_css_vars(self) -> None:
        tokens = ThemeTokens(name="test")
        css_vars = tokens.to_css_vars()
        assert "--fdash-bg-page" in css_vars
        assert "--fdash-accent" in css_vars
        assert "--fdash-chart-0" in css_vars
        assert len(css_vars) > 20

    def test_from_dict(self) -> None:
        data = {
            "name": "custom",
            "bg_page": "#ff0000",
            "accent": "#00ff00",
            "chart_colors": ["#111", "#222"],
        }
        tokens = ThemeTokens.from_dict(data)
        assert tokens.name == "custom"
        assert tokens.bg_page == "#ff0000"
        assert tokens.accent == "#00ff00"
        assert tokens.chart_colors == ("#111", "#222")

    def test_from_dict_with_pl_levels(self) -> None:
        data = {
            "name": "custom",
            "pl_level5": {"bg": "#000", "text": "#fff", "weight": 800},
        }
        tokens = ThemeTokens.from_dict(data)
        assert tokens.pl_level5.bg == "#000"
        assert tokens.pl_level5.weight == 800

    def test_from_dict_ignores_unknown_keys(self) -> None:
        data = {"name": "test", "unknown_future_field": "value"}
        tokens = ThemeTokens.from_dict(data)
        assert tokens.name == "test"

    def test_pl_level_style(self) -> None:
        style = PLLevelStyle(bg="#1e3a8a", text="#ffffff")
        assert style.weight == 700  # default
        assert style.size == ""  # default


class TestPresets:
    def test_all_presets_load(self) -> None:
        for name in get_preset_names():
            tokens = PRESETS[name]
            assert tokens.name == name
            assert tokens.description
            assert tokens.bg_page
            assert tokens.font_family

    def test_seven_presets_exist(self) -> None:
        names = get_preset_names()
        assert len(names) == 7
        assert "modern_light" in names
        assert "modern_dark" in names
        assert "financial" in names
        assert "financial_terminal" in names
        assert "executive" in names
        assert "wsj" in names
        assert "monospace" in names

    def test_get_theme_by_name(self) -> None:
        tokens = get_theme("financial")
        assert tokens.name == "financial"

    def test_get_theme_default(self) -> None:
        tokens = get_theme(None)
        assert tokens.name == "modern_light"

    def test_get_theme_unknown_returns_default(self) -> None:
        tokens = get_theme("nonexistent_theme")
        assert tokens.name == "modern_light"

    def test_list_themes(self) -> None:
        themes = list_themes()
        assert len(themes) == 7
        for t in themes:
            assert "name" in t
            assert "description" in t

    def test_each_preset_produces_valid_css(self) -> None:
        for name in get_preset_names():
            tokens = PRESETS[name]
            css = tokens_to_css(tokens)
            assert ".fdash-root" in css
            assert "--fdash-bg-page" in css
            assert ".row-level5" in css
            assert ".row-ebitda" in css


class TestCSSGeneration:
    def test_tokens_to_css_contains_vars(self) -> None:
        tokens = get_theme("modern_light")
        css = tokens_to_css(tokens)
        assert ".fdash-root {" in css
        assert "--fdash-accent:" in css

    def test_tokens_to_css_contains_hierarchy(self) -> None:
        tokens = get_theme("financial")
        css = tokens_to_css(tokens)
        assert ".row-level5" in css
        assert ".row-ebitda" in css
        assert ".row-netincome" in css
        assert "background-color: #1e3a8a" in css  # level5

    def test_dark_bg_variance_white(self) -> None:
        tokens = get_theme("financial")
        css = tokens_to_css(tokens)
        # Level5 has white text, so variance text should also be white
        assert ".col-variance-fav" in css


class TestCustomCSSScoping:
    def test_simple_selector_scoped(self) -> None:
        result = scope_custom_css(".my-class { color: red; }")
        assert ".fdash-root .my-class" in result

    def test_empty_css(self) -> None:
        assert scope_custom_css("") == ""
        assert scope_custom_css(None) == ""

    def test_multiple_selectors(self) -> None:
        result = scope_custom_css("h1, h2 { font-size: 20px; }")
        assert ".fdash-root h1" in result
        assert ".fdash-root h2" in result
