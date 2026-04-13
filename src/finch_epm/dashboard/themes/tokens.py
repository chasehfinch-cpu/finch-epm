"""Design tokens for dashboard theming.

A ThemeTokens instance defines every visual property the renderer uses.
Built-in presets provide complete token sets; users can override
individual tokens in their .fdash file's ``theme:`` block.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PLLevelStyle:
    """Styling for one level of P&L hierarchy."""

    bg: str
    text: str
    weight: int = 700
    size: str = ""


@dataclass(frozen=True)
class ThemeTokens:
    """Complete set of design tokens for a dashboard theme.

    Users can create custom themes by defining these tokens in YAML
    or by overriding individual values from a built-in preset.
    """

    name: str
    description: str = ""

    # -- Page & card --
    bg_page: str = "#eef1f5"
    bg_card: str = "#ffffff"
    bg_surface: str = "#f9fafb"
    border_color: str = "#e4e7ec"
    card_radius: str = "6px"
    card_shadow: str = "0 1px 4px rgba(0,0,0,0.06), 0 0 1px rgba(0,0,0,0.08)"

    # -- Header --
    header_bg: str = "linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%)"
    header_text: str = "#ffffff"

    # -- Text --
    text_primary: str = "#1a1a2e"
    text_secondary: str = "#374151"
    text_muted: str = "#6b7280"
    text_label: str = "#4b5563"

    # -- Accent & status --
    accent: str = "#2563eb"
    accent_hover: str = "#1e40af"
    success: str = "#059669"
    danger: str = "#dc2626"
    warning: str = "#f59e0b"
    info: str = "#0891b2"

    # -- Chart palette --
    chart_colors: tuple[str, ...] = (
        "#1e3a8a", "#2563eb", "#3b82f6", "#059669",
        "#f59e0b", "#dc2626", "#0891b2", "#9333ea",
    )

    # -- Typography --
    font_family: str = "'Segoe UI', Tahoma, Geneva, Verdana, sans-serif"
    font_family_mono: str = "'Cascadia Code', 'Fira Code', 'Consolas', monospace"
    font_size_base: str = "10pt"
    font_size_sm: str = "9pt"
    font_size_xs: str = "11px"
    font_size_lg: str = "13px"
    font_size_xl: str = "17px"
    font_size_2xl: str = "22px"
    font_size_3xl: str = "40px"

    # -- Spacing --
    spacing_xs: str = "4px"
    spacing_sm: str = "8px"
    spacing_md: str = "14px"
    spacing_lg: str = "20px"
    spacing_xl: str = "32px"

    # -- Table --
    table_header_bg: str = "#1e3a8a"
    table_header_text: str = "#ffffff"
    table_header_border: str = "#1e40af"
    table_row_even: str = "#f9fafb"
    table_row_hover: str = "rgba(59,130,246,0.1)"
    table_border: str = "#e5e7eb"
    table_font_size: str = "10pt"

    # -- P&L hierarchy levels --
    pl_level5: PLLevelStyle = PLLevelStyle(bg="#1e3a8a", text="#ffffff", weight=700, size="10.5pt")
    pl_level4: PLLevelStyle = PLLevelStyle(bg="#2563eb", text="#ffffff", weight=700)
    pl_level3: PLLevelStyle = PLLevelStyle(bg="#3b82f6", text="#ffffff", weight=700)
    pl_level2: PLLevelStyle = PLLevelStyle(bg="#60a5fa", text="#1e3a8a", weight=700)
    pl_level1: PLLevelStyle = PLLevelStyle(bg="#93c5fd", text="#1e3a8a", weight=600)
    pl_ebitda: PLLevelStyle = PLLevelStyle(bg="#059669", text="#ffffff", weight=700, size="10.5pt")
    pl_net_income: PLLevelStyle = PLLevelStyle(bg="#0891b2", text="#ffffff", weight=700, size="11pt")
    pl_stats_header: PLLevelStyle = PLLevelStyle(bg="#4b5563", text="#ffffff", weight=700)

    # -- Filter toolbar --
    filter_bg: str = "#ffffff"
    filter_border: str = "2px solid #dbeafe"
    filter_radius: str = "8px"
    filter_input_height: str = "32px"
    filter_label_size: str = "10px"
    filter_label_color: str = "#6b7280"

    # -- KPI / stat cards --
    kpi_bg: str = "#f8fafc"
    kpi_border: str = "1px solid #e2e8f0"
    kpi_radius: str = "10px"
    kpi_label_size: str = "11px"
    kpi_label_color: str = "#94a3b8"
    kpi_value_size: str = "22px"
    kpi_value_color: str = "#1e3a8a"

    # -- Tab bar --
    tab_active_border: str = "#2563eb"
    tab_active_bg: str = "#eff6ff"
    tab_active_text: str = "#2563eb"
    tab_hover_bg: str = "#f3f4f6"

    # -- Tooltip --
    tooltip_bg: str = "#1f2937"
    tooltip_text: str = "#f9fafb"
    tooltip_radius: str = "6px"

    # -- Print --
    print_preserve_colors: bool = True

    def to_css_vars(self) -> dict[str, str]:
        """Convert tokens to a flat dict of CSS custom property names and values."""
        css: dict[str, str] = {
            "--fdash-bg-page": self.bg_page,
            "--fdash-bg-card": self.bg_card,
            "--fdash-bg-surface": self.bg_surface,
            "--fdash-border": self.border_color,
            "--fdash-card-radius": self.card_radius,
            "--fdash-card-shadow": self.card_shadow,
            "--fdash-header-bg": self.header_bg,
            "--fdash-header-text": self.header_text,
            "--fdash-text-primary": self.text_primary,
            "--fdash-text-secondary": self.text_secondary,
            "--fdash-text-muted": self.text_muted,
            "--fdash-accent": self.accent,
            "--fdash-accent-hover": self.accent_hover,
            "--fdash-success": self.success,
            "--fdash-danger": self.danger,
            "--fdash-warning": self.warning,
            "--fdash-info": self.info,
            "--fdash-font-family": self.font_family,
            "--fdash-font-family-mono": self.font_family_mono,
            "--fdash-font-size-base": self.font_size_base,
            "--fdash-table-header-bg": self.table_header_bg,
            "--fdash-table-header-text": self.table_header_text,
            "--fdash-table-row-even": self.table_row_even,
            "--fdash-table-row-hover": self.table_row_hover,
            "--fdash-table-border": self.table_border,
            "--fdash-filter-bg": self.filter_bg,
            "--fdash-filter-border": self.filter_border,
            "--fdash-kpi-bg": self.kpi_bg,
            "--fdash-kpi-value-color": self.kpi_value_color,
            "--fdash-kpi-label-color": self.kpi_label_color,
            "--fdash-tab-active-border": self.tab_active_border,
            "--fdash-tab-active-bg": self.tab_active_bg,
            "--fdash-tooltip-bg": self.tooltip_bg,
            "--fdash-tooltip-text": self.tooltip_text,
        }
        # Chart palette as indexed vars
        for i, color in enumerate(self.chart_colors):
            css[f"--fdash-chart-{i}"] = color
        return css

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ThemeTokens:
        """Create ThemeTokens from a raw dict (e.g., from YAML).

        Supports nested PL level overrides and flat token overrides.
        Unknown keys are silently ignored so user themes don't break
        on version upgrades.
        """
        kwargs: dict[str, Any] = {}
        pl_fields = {"pl_level5", "pl_level4", "pl_level3", "pl_level2",
                      "pl_level1", "pl_ebitda", "pl_net_income", "pl_stats_header"}

        for key, value in data.items():
            if key in pl_fields and isinstance(value, dict):
                kwargs[key] = PLLevelStyle(**value)
            elif key == "chart_colors" and isinstance(value, list):
                kwargs[key] = tuple(value)
            elif key in cls.__dataclass_fields__:
                kwargs[key] = value

        # Ensure name is present
        if "name" not in kwargs:
            kwargs["name"] = "custom"

        return cls(**kwargs)
