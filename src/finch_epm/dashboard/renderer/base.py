"""Abstract base class for chart renderers.

Each built-in chart type (table, bar, line, area, kpi, pivot, timeseries,
scatter) is a subclass. v0.3 custom charts (Vega-Lite, user JS) will also
subclass this, so the rendering pipeline never changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from finch_epm.dashboard.renderer.types import RenderContext, RenderOutput


class ChartRenderer(ABC):
    """Abstract interface for rendering a single chart type."""

    chart_type: ClassVar[str]
    """Type identifier used in ``.fdash`` files, e.g. ``"bar"``, ``"table"``."""

    display_name: ClassVar[str]
    """Human-readable name for the chart type."""

    @abstractmethod
    def validate_spec(self, chart_spec: dict) -> list[str]:
        """Validate a chart spec from a .fdash file.

        Returns:
            List of validation error messages. Empty list means valid.
        """
        ...

    @abstractmethod
    def render(self, context: RenderContext) -> RenderOutput:
        """Produce renderable output for the given data and chart spec.

        Args:
            context: Data, spec, parameters, and theme.

        Returns:
            HTML and JS configuration for the frontend.
        """
        ...

    def get_required_columns(self, chart_spec: dict) -> list[str]:
        """Return column names this chart requires from the query result.

        Used for early validation when loading a ``.fdash`` file.
        Default returns empty (no requirements).
        """
        return []
