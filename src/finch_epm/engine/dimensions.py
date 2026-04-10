"""Dimension mapping layer.

Defines how reference/dimension tables connect to fact tables, enabling:
    - Multi-level filtering (site -> group -> total)
    - Rollup hierarchies (location rollup, group rollup, department rollup)
    - Binary flag filters (CoreFY25, ActiveBusiness, etc.)
    - Cross-source joins (SQL Server dimensions + NetSuite facts)

Users define their dimension mappings in a YAML file. The mapping tells
finch-epm how to JOIN dimension tables to fact tables and which columns
are available for filtering, grouping, and rollup.

This is the glue between data sources. Every company defines their own
mappings -- the structure is generic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class RollupLevel:
    """A level in a rollup hierarchy (e.g., Site -> Group -> Total)."""

    name: str
    display_name: str
    column: str


@dataclass
class FlagFilter:
    """A binary flag column that can be used for filtering.

    Example: CoreFY25 = 1 means the entity is in the FY25 core set.
    """

    name: str
    display_name: str
    column: str
    active_value: Any = 1


@dataclass
class DimensionMapping:
    """Defines how a reference table connects to fact data.

    This is the central configuration object that users customize.
    It describes:
        - Which table holds the dimension data
        - How it joins to fact tables
        - What rollup levels exist
        - What flag filters are available
        - What display columns to show
    """

    name: str
    display_name: str
    table: str
    """Cache table name (e.g., dbo__IFSLocations)."""

    id_column: str
    """Primary key column in the dimension table."""

    label_column: str
    """Display name column."""

    join_column: str
    """Column in fact tables that references this dimension's id_column.
    For example, if TransactionLine has a 'location' column that matches
    IFSLocations.LocationID, then join_column = 'location'."""

    rollups: list[RollupLevel] = field(default_factory=list)
    """Rollup hierarchy levels, from most detailed to most aggregated."""

    flags: list[FlagFilter] = field(default_factory=list)
    """Binary flag columns available for filtering."""

    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DimensionMappingSet:
    """A complete set of dimension mappings for a dashboard or report.

    Users define one of these per reporting context. A .fdash file
    can reference it to enable dynamic filtering.
    """

    name: str
    description: str = ""
    dimensions: list[DimensionMapping] = field(default_factory=list)

    def get_dimension(self, name: str) -> DimensionMapping | None:
        for d in self.dimensions:
            if d.name == name:
                return d
        return None

    def get_all_flags(self) -> list[tuple[str, str, FlagFilter]]:
        """Return all flags across all dimensions as (dim_name, dim_table, flag) tuples."""
        result = []
        for d in self.dimensions:
            for f in d.flags:
                result.append((d.name, d.table, f))
        return result

    def get_filter_sql(
        self,
        dimension_name: str,
        fact_table_alias: str,
        filters: dict[str, Any],
    ) -> str:
        """Generate SQL WHERE clauses for the given filters.

        Args:
            dimension_name: Which dimension to filter on.
            fact_table_alias: Alias of the fact table in the query.
            filters: Dict of filter values, e.g.:
                {"rollup": "Group A", "CoreFY25": 1, "ActiveBusiness": 1}

        Returns:
            SQL WHERE clause fragment (without the WHERE keyword).
        """
        dim = self.get_dimension(dimension_name)
        if dim is None:
            return ""

        clauses = []
        dim_alias = f"_dim_{dim.name}"

        for key, value in filters.items():
            # Check if it is a rollup filter
            for rollup in dim.rollups:
                if rollup.name == key or rollup.column == key:
                    clauses.append(f"{dim_alias}.{rollup.column} = '{value}'")
                    break
            else:
                # Check if it is a flag filter
                for flag in dim.flags:
                    if flag.name == key or flag.column == key:
                        clauses.append(f"{dim_alias}.{flag.column} = {value}")
                        break
                else:
                    # Direct column filter
                    clauses.append(f"{dim_alias}.{key} = '{value}'")

        return " AND ".join(clauses)

    def get_join_sql(
        self,
        dimension_name: str,
        fact_table: str,
        fact_alias: str = "f",
    ) -> str:
        """Generate a LEFT JOIN clause for a dimension table.

        Returns SQL like:
            LEFT JOIN dbo__IFSLocations _dim_location
                ON f.location = _dim_location.LocationID
        """
        dim = self.get_dimension(dimension_name)
        if dim is None:
            return ""

        dim_alias = f"_dim_{dim.name}"
        return (
            f"LEFT JOIN \"{dim.table}\" {dim_alias} "
            f"ON {fact_alias}.{dim.join_column} = {dim_alias}.{dim.id_column}"
        )


def load_dimension_mappings(path: str | Path) -> DimensionMappingSet:
    """Load dimension mappings from a YAML file.

    Format::

        name: My Company Dimensions
        description: Reference table mappings for company reporting
        dimensions:
          - name: location
            display_name: Location / Site
            table: dbo__IFSLocations
            id_column: LocationID
            label_column: LocationName
            join_column: location
            rollups:
              - name: site
                display_name: Site
                column: LocationName
              - name: location_rollup
                display_name: Location Rollup
                column: LocationRollup
              - name: group_rollup
                display_name: Group
                column: GroupRollup
            flags:
              - name: core_fy25
                display_name: Core FY25
                column: CoreFY25
              - name: active
                display_name: Active Business
                column: ActiveBusiness
    """
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return _parse_mapping_set(raw)


def save_dimension_mappings(mappings: DimensionMappingSet, path: str | Path) -> None:
    """Save dimension mappings to a YAML file."""
    path = Path(path)
    raw = _serialize_mapping_set(mappings)
    path.write_text(
        yaml.dump(raw, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def _parse_mapping_set(raw: dict[str, Any]) -> DimensionMappingSet:
    dimensions = []
    for d in raw.get("dimensions", []):
        rollups = [
            RollupLevel(
                name=r.get("name", ""),
                display_name=r.get("display_name", r.get("name", "")),
                column=r.get("column", ""),
            )
            for r in d.get("rollups", [])
        ]
        flags = [
            FlagFilter(
                name=f.get("name", ""),
                display_name=f.get("display_name", f.get("name", "")),
                column=f.get("column", ""),
                active_value=f.get("active_value", 1),
            )
            for f in d.get("flags", [])
        ]
        dimensions.append(DimensionMapping(
            name=d.get("name", ""),
            display_name=d.get("display_name", d.get("name", "")),
            table=d.get("table", ""),
            id_column=d.get("id_column", "id"),
            label_column=d.get("label_column", "name"),
            join_column=d.get("join_column", ""),
            rollups=rollups,
            flags=flags,
        ))

    return DimensionMappingSet(
        name=raw.get("name", ""),
        description=raw.get("description", ""),
        dimensions=dimensions,
    )


def _serialize_mapping_set(ms: DimensionMappingSet) -> dict[str, Any]:
    dims = []
    for d in ms.dimensions:
        dim_dict: dict[str, Any] = {
            "name": d.name,
            "display_name": d.display_name,
            "table": d.table,
            "id_column": d.id_column,
            "label_column": d.label_column,
            "join_column": d.join_column,
        }
        if d.rollups:
            dim_dict["rollups"] = [
                {"name": r.name, "display_name": r.display_name, "column": r.column}
                for r in d.rollups
            ]
        if d.flags:
            dim_dict["flags"] = [
                {"name": f.name, "display_name": f.display_name,
                 "column": f.column, "active_value": f.active_value}
                for f in d.flags
            ]
        dims.append(dim_dict)

    return {
        "name": ms.name,
        "description": ms.description,
        "dimensions": dims,
    }
