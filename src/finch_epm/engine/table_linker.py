"""Cross-source table linking system.

Users link tables across data sources by pointing column headers at each
other. For example, a NetSuite Location ID column links to a SQL Server
Division column via a reference table. The system stores these links and
uses them to generate JOINs in dashboard queries.

Usage:
    linker = TableLinker.load()
    linker.add_link(
        source_table="Location",
        source_column="id",
        target_table="dbo__RCMSiteMaster",
        target_column="Division",
        link_name="location_to_rcm",
    )
    linker.save()

    # In a dashboard query:
    join_sql = linker.get_join_sql("Location", "dbo__RCMSiteMaster")
    # -> "LEFT JOIN dbo__RCMSiteMaster ON CAST(Location.id AS VARCHAR) = CAST(dbo__RCMSiteMaster.Division AS VARCHAR)"
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
class TableLink:
    """A link between two table columns across data sources."""

    name: str
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    link_type: str = "left"  # left, inner, right
    description: str = ""
    cast_to: str = "VARCHAR"  # Cast both sides for safe comparison


@dataclass
class DimensionLink:
    """A dimension reference table that enriches fact data.

    Example: Location table enriches TransactionLine.location with
    human-readable names, groups, and rollups.
    """

    name: str
    dimension_table: str
    id_column: str
    label_column: str
    fact_join_column: str
    """Column in fact tables (e.g., TransactionLine.location)"""
    rollup_columns: list[str] = field(default_factory=list)
    """Columns for grouping/rollup (e.g., [name, subsidiary, parent])"""
    flag_columns: list[str] = field(default_factory=list)
    """Binary flag columns for filtering (e.g., [isinactive])"""
    cross_source_links: list[TableLink] = field(default_factory=list)
    """Links to tables in other data sources"""


class TableLinker:
    """Manages cross-source table links and dimension mappings.

    Links are stored in ``table_links.yaml`` in the user's config directory
    and are shareable — export and import as a team.
    """

    def __init__(
        self,
        links: list[TableLink] | None = None,
        dimensions: list[DimensionLink] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.links: list[TableLink] = links or []
        self.dimensions: list[DimensionLink] = dimensions or []
        self.metadata: dict[str, Any] = metadata or {}

    # -- Link management ----------------------------------------------------

    def add_link(
        self,
        source_table: str,
        source_column: str,
        target_table: str,
        target_column: str,
        name: str = "",
        link_type: str = "left",
        description: str = "",
    ) -> TableLink:
        """Add a link between two table columns."""
        if not name:
            name = f"{source_table}.{source_column}_to_{target_table}.{target_column}"

        # Check for duplicates
        for existing in self.links:
            if (existing.source_table == source_table
                    and existing.source_column == source_column
                    and existing.target_table == target_table
                    and existing.target_column == target_column):
                return existing

        link = TableLink(
            name=name,
            source_table=source_table,
            source_column=source_column,
            target_table=target_table,
            target_column=target_column,
            link_type=link_type,
            description=description,
        )
        self.links.append(link)
        return link

    def add_dimension(
        self,
        name: str,
        dimension_table: str,
        id_column: str,
        label_column: str,
        fact_join_column: str,
        rollup_columns: list[str] | None = None,
        flag_columns: list[str] | None = None,
    ) -> DimensionLink:
        """Register a dimension reference table."""
        dim = DimensionLink(
            name=name,
            dimension_table=dimension_table,
            id_column=id_column,
            label_column=label_column,
            fact_join_column=fact_join_column,
            rollup_columns=rollup_columns or [],
            flag_columns=flag_columns or [],
        )
        # Replace existing dimension with same name
        self.dimensions = [d for d in self.dimensions if d.name != name]
        self.dimensions.append(dim)
        return dim

    def get_link(self, source_table: str, target_table: str) -> TableLink | None:
        """Find a link between two tables."""
        for link in self.links:
            if link.source_table == source_table and link.target_table == target_table:
                return link
            if link.source_table == target_table and link.target_table == source_table:
                return link
        return None

    def get_dimension(self, name: str) -> DimensionLink | None:
        """Find a dimension by name."""
        for dim in self.dimensions:
            if dim.name == name:
                return dim
        return None

    def get_join_sql(self, source_table: str, target_table: str) -> str:
        """Generate a JOIN clause for two linked tables."""
        link = self.get_link(source_table, target_table)
        if not link:
            return ""

        join_type = link.link_type.upper()
        cast = link.cast_to
        return (
            f"{join_type} JOIN {link.target_table} "
            f"ON CAST({link.source_table}.{link.source_column} AS {cast}) "
            f"= CAST({link.target_table}.{link.target_column} AS {cast})"
        )

    # -- Auto-detection -----------------------------------------------------

    @staticmethod
    def detect_dimension_tables(
        table_info: list[dict[str, Any]],
        max_rows: int = 5000,
    ) -> list[dict[str, Any]]:
        """Identify tables that are likely dimension/reference tables.

        Heuristic: small row count + has columns named 'id'/'name'/'code'.
        """
        candidates: list[dict[str, Any]] = []
        for t in table_info:
            row_count = t.get("row_count_estimate") or t.get("row_count", 0)
            if row_count and row_count <= max_rows:
                candidates.append({
                    "table_name": t.get("table_name", ""),
                    "row_count": row_count,
                    "display_name": t.get("display_name", ""),
                })
        return sorted(candidates, key=lambda x: x.get("row_count", 0))

    @staticmethod
    def detect_linkable_columns(
        source_columns: list[dict[str, Any]],
        target_columns: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        """Suggest column links by matching names across tables.

        Heuristic: columns with matching names or common patterns
        (id/ID, name/Name, code/Code, location/Location, etc.)
        """
        suggestions: list[dict[str, str]] = []
        source_names = {c.get("column_name", "").lower(): c.get("column_name", "")
                        for c in source_columns}
        target_names = {c.get("column_name", "").lower(): c.get("column_name", "")
                        for c in target_columns}

        # Exact name matches
        for sname_lower, sname in source_names.items():
            if sname_lower in target_names:
                suggestions.append({
                    "source_column": sname,
                    "target_column": target_names[sname_lower],
                    "match_type": "exact_name",
                    "confidence": "high",
                })

        # Common patterns: source.id = target.{source_table_name}_id
        # or source.location = target.locationid
        for sname_lower, sname in source_names.items():
            for tname_lower, tname in target_names.items():
                if sname_lower == tname_lower:
                    continue  # Already caught
                # Check if one contains the other
                if (sname_lower in tname_lower or tname_lower in sname_lower) and len(sname_lower) > 2:
                    suggestions.append({
                        "source_column": sname,
                        "target_column": tname,
                        "match_type": "partial_name",
                        "confidence": "medium",
                    })

        return suggestions

    # -- Persistence --------------------------------------------------------

    def save(self, path: Path | str | None = None) -> Path:
        """Save links to YAML. Shareable with team members."""
        path = Path(path) if path else _default_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {
            "version": 1,
            "metadata": self.metadata,
            "links": [
                {
                    "name": l.name,
                    "source_table": l.source_table,
                    "source_column": l.source_column,
                    "target_table": l.target_table,
                    "target_column": l.target_column,
                    "link_type": l.link_type,
                    "description": l.description,
                }
                for l in self.links
            ],
            "dimensions": [
                {
                    "name": d.name,
                    "dimension_table": d.dimension_table,
                    "id_column": d.id_column,
                    "label_column": d.label_column,
                    "fact_join_column": d.fact_join_column,
                    "rollup_columns": d.rollup_columns,
                    "flag_columns": d.flag_columns,
                    "cross_source_links": [
                        {
                            "name": cl.name,
                            "source_table": cl.source_table,
                            "source_column": cl.source_column,
                            "target_table": cl.target_table,
                            "target_column": cl.target_column,
                        }
                        for cl in d.cross_source_links
                    ],
                }
                for d in self.dimensions
            ],
        }

        path.write_text(
            yaml.dump(data, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, path: Path | str | None = None) -> TableLinker:
        """Load links from YAML."""
        path = Path(path) if path else _default_path()
        if not path.exists():
            return cls()

        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return cls()

        links: list[TableLink] = []
        for ld in raw.get("links", []):
            links.append(TableLink(
                name=ld.get("name", ""),
                source_table=ld.get("source_table", ""),
                source_column=ld.get("source_column", ""),
                target_table=ld.get("target_table", ""),
                target_column=ld.get("target_column", ""),
                link_type=ld.get("link_type", "left"),
                description=ld.get("description", ""),
            ))

        dimensions: list[DimensionLink] = []
        for dd in raw.get("dimensions", []):
            cross_links = [
                TableLink(
                    name=cl.get("name", ""),
                    source_table=cl.get("source_table", ""),
                    source_column=cl.get("source_column", ""),
                    target_table=cl.get("target_table", ""),
                    target_column=cl.get("target_column", ""),
                )
                for cl in dd.get("cross_source_links", [])
            ]
            dimensions.append(DimensionLink(
                name=dd.get("name", ""),
                dimension_table=dd.get("dimension_table", ""),
                id_column=dd.get("id_column", ""),
                label_column=dd.get("label_column", ""),
                fact_join_column=dd.get("fact_join_column", ""),
                rollup_columns=dd.get("rollup_columns", []),
                flag_columns=dd.get("flag_columns", []),
                cross_source_links=cross_links,
            ))

        return cls(
            links=links,
            dimensions=dimensions,
            metadata=raw.get("metadata", {}),
        )


def _default_path() -> Path:
    return config_dir() / "table_links.yaml"
