"""Chart type registry.

Renderers register themselves so the dashboard runtime can look up
the correct renderer for each chart in a ``.fdash`` file.
"""

from __future__ import annotations

from finch_epm.dashboard.renderer.base import ChartRenderer

_CHART_REGISTRY: dict[str, ChartRenderer] = {}


def register_chart(renderer: ChartRenderer) -> ChartRenderer:
    """Register a chart renderer instance by its chart_type."""
    _CHART_REGISTRY[renderer.chart_type] = renderer
    return renderer


def get_chart_renderer(chart_type: str) -> ChartRenderer:
    """Look up a chart renderer by type string.

    Raises:
        KeyError: If no renderer is registered for that type.
    """
    if chart_type not in _CHART_REGISTRY:
        available = sorted(_CHART_REGISTRY.keys())
        raise KeyError(
            f"Unknown chart type: {chart_type!r}. Available: {available}"
        )
    return _CHART_REGISTRY[chart_type]


def list_chart_types() -> list[str]:
    """Return all registered chart type names, sorted."""
    return sorted(_CHART_REGISTRY.keys())
