"""Dashboard theming system.

Provides design tokens, built-in presets, and CSS generation.
Users can select a built-in theme by name, override individual tokens,
or provide a completely custom theme in their .fdash file.
"""

from __future__ import annotations

from finch_epm.dashboard.themes.presets import PRESETS, get_preset_names
from finch_epm.dashboard.themes.tokens import ThemeTokens


def get_theme(name: str | None = None) -> ThemeTokens:
    """Return a theme by name, falling back to modern_light."""
    if name is None:
        name = "modern_light"
    if name in PRESETS:
        return PRESETS[name]
    # Unknown theme name -- return default
    return PRESETS["modern_light"]


def list_themes() -> list[dict[str, str]]:
    """Return all available theme presets with descriptions."""
    return [
        {"name": name, "description": PRESETS[name].description}
        for name in get_preset_names()
    ]


__all__ = ["ThemeTokens", "get_theme", "list_themes"]
