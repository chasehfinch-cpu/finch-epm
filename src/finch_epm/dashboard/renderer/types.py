"""Data structures for the chart rendering pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RenderContext:
    """Everything a chart renderer needs to produce output."""

    chart_spec: dict[str, Any]
    data: list[dict[str, Any]]
    column_names: list[str]
    column_types: list[str]
    parameters: dict[str, Any] = field(default_factory=dict)
    theme: dict[str, Any] = field(default_factory=dict)


@dataclass
class RenderOutput:
    """Output of a chart render, sent to the frontend by the web server.

    For built-in types, ``chart_config_json`` contains configuration for the
    frontend JS charting library. For v0.3 custom types, this may contain
    a Vega-Lite spec or a user-supplied script reference.
    """

    html_fragment: str
    chart_config_json: dict[str, Any]
    javascript_assets: list[str] = field(default_factory=list)
    css_assets: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
