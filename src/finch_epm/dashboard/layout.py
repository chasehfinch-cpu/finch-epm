"""Dashboard layout system.

Defines named rows with chart placements using simple fraction-based
widths (full, half, third, quarter). Dashboards without a layout block
use the existing auto-flow behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Named fractions -> CSS grid fraction
FRACTION_MAP = {
    "full": "1fr",
    "half": "1fr 1fr",
    "third": "1fr 1fr 1fr",
    "quarter": "1fr 1fr 1fr 1fr",
}


@dataclass
class LayoutColumn:
    """A column within a layout row, referencing a chart by title or index."""

    chart_ref: str
    width: str = "half"  # full, half, third, quarter


@dataclass
class LayoutRow:
    """A row in the layout grid."""

    columns: list[LayoutColumn] = field(default_factory=list)
    name: str = ""


def parse_layout(raw: list[dict[str, Any]]) -> list[LayoutRow]:
    """Parse a layout definition from raw YAML.

    Format::

        layout:
          - row: [chart_title_1, chart_title_2]
          - row: [chart_title_3]
            width: full

    Or the more explicit form::

        layout:
          - columns:
              - chart: Revenue Chart
                width: half
              - chart: Expense Chart
                width: half
          - columns:
              - chart: Detail Table
                width: full

    Returns:
        List of LayoutRow objects.
    """
    rows: list[LayoutRow] = []

    for item in raw:
        if not isinstance(item, dict):
            continue

        row = LayoutRow(name=item.get("name", ""))

        # Simple form: row: [title1, title2]
        if "row" in item and isinstance(item["row"], list):
            for ref in item["row"]:
                width = item.get("width", "half")
                if len(item["row"]) == 1:
                    width = "full"
                row.columns.append(LayoutColumn(chart_ref=str(ref), width=width))

        # Explicit form: columns: [{chart: ..., width: ...}]
        elif "columns" in item and isinstance(item["columns"], list):
            for col_def in item["columns"]:
                if isinstance(col_def, dict):
                    row.columns.append(LayoutColumn(
                        chart_ref=col_def.get("chart", ""),
                        width=col_def.get("width", "half"),
                    ))
                elif isinstance(col_def, str):
                    row.columns.append(LayoutColumn(chart_ref=col_def, width="half"))

        if row.columns:
            rows.append(row)

    return rows
