"""Built-in theme presets.

Users can select any of these by name in their .fdash file, override
individual tokens, or define a fully custom theme. These presets serve
as starting points — not constraints.
"""

from __future__ import annotations

from finch_epm.dashboard.themes.tokens import PLLevelStyle, ThemeTokens

# -- modern_light (default) ------------------------------------------------

modern_light = ThemeTokens(
    name="modern_light",
    description="Clean light theme with professional typography. Default for all dashboards.",
)

# -- modern_dark -----------------------------------------------------------

modern_dark = ThemeTokens(
    name="modern_dark",
    description="Dark theme with muted accents. Easier on the eyes for extended use.",
    bg_page="#0f172a",
    bg_card="#1e293b",
    bg_surface="#334155",
    border_color="#475569",
    header_bg="linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%)",
    header_text="#e2e8f0",
    text_primary="#e2e8f0",
    text_secondary="#94a3b8",
    text_muted="#64748b",
    text_label="#94a3b8",
    accent="#3b82f6",
    accent_hover="#60a5fa",
    table_header_bg="#0f172a",
    table_header_text="#e2e8f0",
    table_header_border="#334155",
    table_row_even="#1e293b",
    table_row_hover="rgba(59,130,246,0.15)",
    table_border="#334155",
    filter_bg="#1e293b",
    filter_border="2px solid #334155",
    filter_label_color="#94a3b8",
    kpi_bg="#1e293b",
    kpi_border="1px solid #334155",
    kpi_value_color="#93c5fd",
    kpi_label_color="#64748b",
    tab_active_bg="#1e293b",
    tooltip_bg="#f1f5f9",
    tooltip_text="#0f172a",
    card_shadow="0 1px 4px rgba(0,0,0,0.3), 0 0 1px rgba(0,0,0,0.2)",
)

# -- financial -------------------------------------------------------------
# Professional financial reporting theme. High-density, navy hierarchy,
# green/red variance coloring. Inspired by institutional financial software.

financial = ThemeTokens(
    name="financial",
    description="Professional financial reporting. Navy hierarchy, green/red variance, high-density tables.",
    bg_page="#eef1f5",
    header_bg="linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%)",
    chart_colors=(
        "#1e3a8a", "#2563eb", "#059669", "#dc2626",
        "#f59e0b", "#0891b2", "#9333ea", "#3b82f6",
    ),
    font_size_base="10pt",
    table_font_size="9pt",
    pl_level5=PLLevelStyle(bg="#1e3a8a", text="#ffffff", weight=700, size="10.5pt"),
    pl_level4=PLLevelStyle(bg="#2563eb", text="#ffffff", weight=700),
    pl_level3=PLLevelStyle(bg="#3b82f6", text="#ffffff", weight=700),
    pl_level2=PLLevelStyle(bg="#60a5fa", text="#1e3a8a", weight=700),
    pl_level1=PLLevelStyle(bg="#93c5fd", text="#1e3a8a", weight=600),
    pl_ebitda=PLLevelStyle(bg="#059669", text="#ffffff", weight=700, size="10.5pt"),
    pl_net_income=PLLevelStyle(bg="#0891b2", text="#ffffff", weight=700, size="11pt"),
    pl_stats_header=PLLevelStyle(bg="#4b5563", text="#ffffff", weight=700),
)

# -- financial_terminal ----------------------------------------------------

financial_terminal = ThemeTokens(
    name="financial_terminal",
    description="Bloomberg-adjacent dark theme. Amber/cyan accents, monospace-heavy, high density.",
    bg_page="#0a0a0a",
    bg_card="#111111",
    bg_surface="#1a1a1a",
    border_color="#333333",
    header_bg="#0a0a0a",
    header_text="#00ff88",
    text_primary="#e0e0e0",
    text_secondary="#999999",
    text_muted="#666666",
    text_label="#888888",
    accent="#00ccff",
    accent_hover="#00ffff",
    success="#00ff88",
    danger="#ff4444",
    warning="#ffaa00",
    info="#00ccff",
    chart_colors=(
        "#00ccff", "#00ff88", "#ffaa00", "#ff4444",
        "#cc66ff", "#ff6699", "#66ffcc", "#ffcc00",
    ),
    font_family="'Cascadia Code', 'Fira Code', 'Consolas', monospace",
    font_family_mono="'Cascadia Code', 'Fira Code', 'Consolas', monospace",
    font_size_base="9pt",
    table_header_bg="#1a1a1a",
    table_header_text="#00ccff",
    table_header_border="#333333",
    table_row_even="#0f0f0f",
    table_row_hover="rgba(0,204,255,0.1)",
    table_border="#222222",
    filter_bg="#111111",
    filter_border="1px solid #333333",
    filter_label_color="#888888",
    kpi_bg="#111111",
    kpi_border="1px solid #333333",
    kpi_value_color="#00ff88",
    kpi_label_color="#666666",
    tab_active_border="#00ccff",
    tab_active_bg="#1a1a1a",
    tab_active_text="#00ccff",
    tooltip_bg="#1a1a1a",
    tooltip_text="#e0e0e0",
    card_radius="2px",
    card_shadow="none",
    kpi_radius="2px",
    filter_radius="2px",
    pl_level5=PLLevelStyle(bg="#1a1a1a", text="#00ccff", weight=700, size="10pt"),
    pl_level4=PLLevelStyle(bg="#1a1a1a", text="#00ff88", weight=700),
    pl_level3=PLLevelStyle(bg="#1a1a1a", text="#ffaa00", weight=600),
    pl_level2=PLLevelStyle(bg="#111111", text="#cccccc", weight=600),
    pl_level1=PLLevelStyle(bg="#0f0f0f", text="#aaaaaa", weight=500),
    pl_ebitda=PLLevelStyle(bg="#003322", text="#00ff88", weight=700),
    pl_net_income=PLLevelStyle(bg="#002233", text="#00ccff", weight=700),
    pl_stats_header=PLLevelStyle(bg="#1a1a1a", text="#ffaa00", weight=700),
)

# -- executive -------------------------------------------------------------

executive = ThemeTokens(
    name="executive",
    description="Economist/WSJ-inspired. Cream background, serif headers, conservative palette for printed decks.",
    bg_page="#faf8f5",
    bg_card="#ffffff",
    bg_surface="#f5f3f0",
    border_color="#d8d4cf",
    header_bg="#1a1a1a",
    header_text="#ffffff",
    text_primary="#1a1a1a",
    text_secondary="#4a4a4a",
    text_muted="#8a8a8a",
    accent="#1a1a1a",
    accent_hover="#333333",
    success="#2d6a4f",
    danger="#9b2c2c",
    warning="#92400e",
    chart_colors=(
        "#1a1a1a", "#4a4a4a", "#2d6a4f", "#9b2c2c",
        "#92400e", "#1e3a5f", "#6b4c9a", "#8a8a8a",
    ),
    font_family="Georgia, 'Times New Roman', serif",
    font_size_base="10.5pt",
    table_header_bg="#1a1a1a",
    table_header_text="#ffffff",
    table_row_even="#f5f3f0",
    table_row_hover="rgba(26,26,26,0.05)",
    table_border="#d8d4cf",
    kpi_bg="#f5f3f0",
    kpi_border="1px solid #d8d4cf",
    kpi_value_color="#1a1a1a",
    tab_active_border="#1a1a1a",
    tab_active_bg="#f5f3f0",
    tab_active_text="#1a1a1a",
    card_shadow="0 1px 3px rgba(0,0,0,0.04)",
    pl_level5=PLLevelStyle(bg="#1a1a1a", text="#ffffff", weight=700),
    pl_level4=PLLevelStyle(bg="#333333", text="#ffffff", weight=700),
    pl_level3=PLLevelStyle(bg="#4a4a4a", text="#ffffff", weight=700),
    pl_level2=PLLevelStyle(bg="#8a8a8a", text="#ffffff", weight=600),
    pl_level1=PLLevelStyle(bg="#d8d4cf", text="#1a1a1a", weight=600),
    pl_ebitda=PLLevelStyle(bg="#2d6a4f", text="#ffffff", weight=700),
    pl_net_income=PLLevelStyle(bg="#1e3a5f", text="#ffffff", weight=700),
)

# -- wsj ------------------------------------------------------------------

wsj = ThemeTokens(
    name="wsj",
    description="Wall Street Journal aesthetic. Charcoal on cream, condensed sans, red/navy accent.",
    bg_page="#f4f1ec",
    bg_card="#ffffff",
    border_color="#ccc5b9",
    header_bg="#222222",
    header_text="#ffffff",
    text_primary="#222222",
    text_secondary="#555555",
    text_muted="#999999",
    accent="#0a3161",
    success="#2d6a4f",
    danger="#b91c1c",
    chart_colors=(
        "#0a3161", "#b91c1c", "#222222", "#555555",
        "#2d6a4f", "#92400e", "#6b4c9a", "#999999",
    ),
    font_family="'Franklin Gothic', 'Arial Narrow', sans-serif",
    font_size_base="10pt",
    table_header_bg="#222222",
    table_header_text="#ffffff",
    table_row_even="#f4f1ec",
    table_border="#ccc5b9",
    kpi_bg="#f4f1ec",
    kpi_border="1px solid #ccc5b9",
    kpi_value_color="#0a3161",
    tab_active_border="#0a3161",
    tab_active_text="#0a3161",
    card_shadow="none",
    card_radius="0px",
    kpi_radius="0px",
    filter_radius="0px",
)

# -- monospace -------------------------------------------------------------

monospace = ThemeTokens(
    name="monospace",
    description="Everything monospaced. Terminal aesthetic, minimal color. For the data engineer.",
    bg_page="#fafafa",
    bg_card="#ffffff",
    border_color="#e0e0e0",
    header_bg="#333333",
    header_text="#ffffff",
    text_primary="#333333",
    text_secondary="#666666",
    text_muted="#999999",
    accent="#333333",
    chart_colors=(
        "#333333", "#666666", "#999999", "#059669",
        "#dc2626", "#2563eb", "#f59e0b", "#9333ea",
    ),
    font_family="'Cascadia Code', 'Fira Code', 'Consolas', monospace",
    font_family_mono="'Cascadia Code', 'Fira Code', 'Consolas', monospace",
    font_size_base="9.5pt",
    table_header_bg="#333333",
    table_header_text="#ffffff",
    table_row_even="#f5f5f5",
    table_border="#e0e0e0",
    kpi_bg="#f5f5f5",
    kpi_border="1px solid #e0e0e0",
    kpi_value_color="#333333",
    tab_active_border="#333333",
    tab_active_text="#333333",
    card_shadow="none",
    card_radius="0px",
    kpi_radius="0px",
    filter_radius="0px",
)

# -- Registry --------------------------------------------------------------

PRESETS: dict[str, ThemeTokens] = {
    "modern_light": modern_light,
    "modern_dark": modern_dark,
    "financial": financial,
    "financial_terminal": financial_terminal,
    "executive": executive,
    "wsj": wsj,
    "monospace": monospace,
}


def get_preset_names() -> list[str]:
    """Return preset names in display order."""
    return list(PRESETS.keys())
