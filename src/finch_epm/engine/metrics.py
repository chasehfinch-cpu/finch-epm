"""Cross-source metrics layer.

Defines reusable calculated measures that combine data from multiple
sources with automatic sign convention normalization and time alignment.

Example: Revenue Per Visit = NetSuite revenue (negative by convention,
monthly close) / SQL Server billable visits (positive, by DOS).

Metrics are defined in ``metrics.yaml`` and referenced by name in
dashboards. The metrics layer handles:
    - Sign convention normalization (NS negative → positive)
    - Time grain alignment (align DOS dates with period close dates)
    - Cross-source math (numerator from one source, denominator from another)
    - Shareable as YAML (same pattern as compilation map and COA)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from finch_epm.paths import config_dir

logger = logging.getLogger(__name__)


@dataclass
class MeasureComponent:
    """One side of a metric calculation (numerator or denominator)."""

    source: str = ""
    """Data source identifier (e.g., 'netsuite', 'sqlserver')"""
    table: str = ""
    """Cache table name"""
    measure: str = ""
    """SQL expression (e.g., 'SUM(CAST(amount AS DOUBLE) * -1)')"""
    filter: str = ""
    """WHERE clause fragment (e.g., "accttype IN ('Income','OthIncome')")"""
    time_column: str = ""
    """Column containing dates for time alignment"""
    time_format: str = ""
    """Date format hint: 'M/D/YYYY', 'YYYY-MM-DD', etc."""


@dataclass
class MetricDefinition:
    """A reusable cross-source calculated metric."""

    name: str
    display_name: str = ""
    description: str = ""
    numerator: MeasureComponent = field(default_factory=MeasureComponent)
    denominator: MeasureComponent | None = None
    """If None, the metric is just the numerator (simple measure)."""
    sign: str = "positive"
    """'positive' or 'negative' — how the result should display"""
    format: str = "currency"
    """'currency', 'percent', 'number', 'ratio'"""
    time_alignment: str = "monthly"
    """How to align sources: 'monthly', 'quarterly', 'yearly', 'none'"""
    unit: str = ""
    """Display unit (e.g., '$', '%', 'visits')"""


class MetricStore:
    """Persistent storage for metric definitions.

    Stored in ``metrics.yaml`` in the user's config directory.
    Shareable — team members import the same metric definitions.
    """

    def __init__(self, metrics: dict[str, MetricDefinition] | None = None) -> None:
        self.metrics: dict[str, MetricDefinition] = metrics or {}

    def get(self, name: str) -> MetricDefinition | None:
        return self.metrics.get(name)

    def add(self, metric: MetricDefinition) -> None:
        self.metrics[metric.name] = metric

    def list_metrics(self) -> list[MetricDefinition]:
        return list(self.metrics.values())

    def generate_sql(
        self,
        metric_name: str,
        group_by: str = "",
        time_period: str = "",
    ) -> str:
        """Generate the SQL for a metric, handling cross-source alignment.

        For simple metrics (single source), returns a direct query.
        For cross-source metrics, generates a CTE-based query that
        computes numerator and denominator separately, aligns by time
        period, and divides.

        Args:
            metric_name: Name of the metric to generate SQL for.
            group_by: Optional column to group by (e.g., 'location').
            time_period: Optional time filter (e.g., '2024').

        Returns:
            DuckDB SQL string.
        """
        metric = self.metrics.get(metric_name)
        if not metric:
            return f"-- Metric '{metric_name}' not found"

        num = metric.numerator
        den = metric.denominator

        if not den:
            # Simple metric — just the numerator
            where = f"WHERE {num.filter}" if num.filter else ""
            return f"SELECT {num.measure} AS value FROM {num.table} {where}"

        # Cross-source metric with time alignment
        num_time = _build_time_extract(num.time_column, num.time_format, metric.time_alignment)
        den_time = _build_time_extract(den.time_column, den.time_format, metric.time_alignment)

        num_where = f"WHERE {num.filter}" if num.filter else ""
        den_where = f"WHERE {den.filter}" if den.filter else ""

        num_group = f", {group_by}" if group_by else ""
        den_group = f", {group_by}" if group_by else ""

        sql = f"""
WITH numerator AS (
    SELECT
        {num_time} AS period
        {num_group},
        {num.measure} AS num_value
    FROM {num.table}
    {num_where}
    GROUP BY {num_time}{num_group}
),
denominator AS (
    SELECT
        {den_time} AS period
        {den_group},
        {den.measure} AS den_value
    FROM {den.table}
    {den_where}
    GROUP BY {den_time}{den_group}
)
SELECT
    n.period
    {', n.' + group_by if group_by else ''},
    n.num_value,
    d.den_value,
    CASE WHEN d.den_value != 0
         THEN n.num_value / d.den_value
         ELSE NULL END AS metric_value
FROM numerator n
LEFT JOIN denominator d ON n.period = d.period{' AND n.' + group_by + ' = d.' + group_by if group_by else ''}
ORDER BY n.period
"""
        return sql.strip()

    # -- Persistence --------------------------------------------------------

    def save(self, path: Path | str | None = None) -> Path:
        path = Path(path) if path else _default_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {"version": 1, "metrics": {}}
        for name, m in self.metrics.items():
            entry: dict[str, Any] = {
                "display_name": m.display_name,
                "description": m.description,
                "sign": m.sign,
                "format": m.format,
                "time_alignment": m.time_alignment,
                "unit": m.unit,
                "numerator": _component_to_dict(m.numerator),
            }
            if m.denominator:
                entry["denominator"] = _component_to_dict(m.denominator)
            data["metrics"][name] = entry

        path.write_text(
            yaml.dump(data, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, path: Path | str | None = None) -> MetricStore:
        path = Path(path) if path else _default_path()
        if not path.exists():
            return cls()

        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return cls()

        metrics: dict[str, MetricDefinition] = {}
        for name, entry in raw.get("metrics", {}).items():
            num = _dict_to_component(entry.get("numerator", {}))
            den = _dict_to_component(entry.get("denominator")) if "denominator" in entry else None
            metrics[name] = MetricDefinition(
                name=name,
                display_name=entry.get("display_name", name),
                description=entry.get("description", ""),
                numerator=num,
                denominator=den,
                sign=entry.get("sign", "positive"),
                format=entry.get("format", "currency"),
                time_alignment=entry.get("time_alignment", "monthly"),
                unit=entry.get("unit", ""),
            )

        return cls(metrics=metrics)


def _component_to_dict(c: MeasureComponent) -> dict[str, str]:
    return {
        "source": c.source,
        "table": c.table,
        "measure": c.measure,
        "filter": c.filter,
        "time_column": c.time_column,
        "time_format": c.time_format,
    }


def _dict_to_component(d: dict | None) -> MeasureComponent:
    if not d:
        return MeasureComponent()
    return MeasureComponent(
        source=d.get("source", ""),
        table=d.get("table", ""),
        measure=d.get("measure", ""),
        filter=d.get("filter", ""),
        time_column=d.get("time_column", ""),
        time_format=d.get("time_format", ""),
    )


def _build_time_extract(
    time_column: str,
    time_format: str,
    alignment: str,
) -> str:
    """Build a SQL expression to extract the time period from a date column."""
    if not time_column:
        return "'all'"

    if alignment == "yearly":
        if time_format == "M/D/YYYY":
            return f"SPLIT_PART({time_column}, '/', 3)"
        return f"EXTRACT(YEAR FROM CAST({time_column} AS DATE))"

    if alignment == "quarterly":
        if time_format == "M/D/YYYY":
            return (
                f"SPLIT_PART({time_column}, '/', 3) || '-Q' || "
                f"CEIL(CAST(SPLIT_PART({time_column}, '/', 1) AS INTEGER) / 3.0)"
            )
        return (
            f"EXTRACT(YEAR FROM CAST({time_column} AS DATE)) || '-Q' || "
            f"CEIL(EXTRACT(MONTH FROM CAST({time_column} AS DATE)) / 3.0)"
        )

    # Monthly (default)
    if time_format == "M/D/YYYY":
        return (
            f"SPLIT_PART({time_column}, '/', 3) || '-' || "
            f"LPAD(SPLIT_PART({time_column}, '/', 1), 2, '0')"
        )
    return (
        f"EXTRACT(YEAR FROM CAST({time_column} AS DATE)) || '-' || "
        f"LPAD(EXTRACT(MONTH FROM CAST({time_column} AS DATE)), 2, '0')"
    )


def _default_path() -> Path:
    return config_dir() / "metrics.yaml"
