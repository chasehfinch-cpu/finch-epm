"""Compilation Map — the single source of truth for cross-source data linking.

Every dashboard, every P&L, every filter in finch-epm runs through the
compilation map. It defines:

    1. The master reference table (e.g., IFSLocations) that all data
       sources link through
    2. How each data source connects to that reference (join columns)
    3. Rollup hierarchies (how locations group into sites, groups, states)
    4. Binary flags (Active/Terminated, CoreFY25/FY26, custom groupings)

There is ONE compilation map per finch-epm install. It lives in a visible,
editable location. IT can pre-load it on a network share. Finance can edit
it when sites change. Every user sees the same mapping.

The map is a YAML file that can be:
    - Created interactively via ``finch-epm map setup``
    - Imported from a team share via ``finch-epm map import``
    - Pointed to a network path via ``finch-epm map use <path>``
    - Viewed at any time via ``finch-epm map show``
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
class SourceLink:
    """How one data source connects to the master reference table."""

    name: str
    """Descriptive name (e.g., 'netsuite', 'sqlserver_rcm')"""
    table: str
    """Cache table name (e.g., 'TransactionLine', 'dbo__RCMSiteMaster')"""
    join_column: str
    """Column in this source that matches the reference ID"""
    join_type: str = "left"
    """JOIN type: left, inner"""
    transform: str = ""
    """Optional transform to apply before matching (e.g., 'strip_prefix:L')"""
    description: str = ""


@dataclass
class RollupLevel:
    """A column in the reference table used for hierarchical grouping."""

    column: str
    display: str = ""


@dataclass
class FlagDefinition:
    """A binary flag column in the reference table."""

    column: str
    display: str = ""
    active_value: Any = 1


@dataclass
class FlagGroup:
    """A group of related flags (e.g., status flags, period flags)."""

    name: str
    display: str = ""
    flags: list[FlagDefinition] = field(default_factory=list)


@dataclass
class ReferenceTable:
    """A master reference/dimension table that links data sources."""

    name: str
    """Descriptive name (e.g., 'locations', 'departments')"""
    table: str
    """Cache table name (e.g., 'ss__dbo__IFSLocations')"""
    id_column: str
    """Primary identifier column"""
    display_column: str
    """Column shown to users in filters and labels"""
    source_links: list[SourceLink] = field(default_factory=list)
    rollups: list[RollupLevel] = field(default_factory=list)
    flag_groups: list[FlagGroup] = field(default_factory=list)

    def get_all_flags(self) -> list[FlagDefinition]:
        """Return all flags across all groups."""
        result = []
        for group in self.flag_groups:
            result.extend(group.flags)
        return result

    def get_flag_group(self, name: str) -> FlagGroup | None:
        for g in self.flag_groups:
            if g.name == name:
                return g
        return None


@dataclass
class CompilationMap:
    """The single source of truth for cross-source data linking.

    One per finch-epm install. Every query, dashboard, and filter
    flows through this map.
    """

    name: str = "Data Compilation Map"
    description: str = ""
    references: list[ReferenceTable] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_reference(self, name: str) -> ReferenceTable | None:
        for ref in self.references:
            if ref.name == name:
                return ref
        return None

    def get_reference_by_table(self, table: str) -> ReferenceTable | None:
        for ref in self.references:
            if ref.table == table:
                return ref
        return None

    def get_all_source_links(self) -> list[tuple[str, SourceLink]]:
        """Return all (reference_name, source_link) pairs."""
        result = []
        for ref in self.references:
            for link in ref.source_links:
                result.append((ref.name, link))
        return result

    def generate_join_sql(
        self,
        reference_name: str,
        source_name: str,
    ) -> str:
        """Generate SQL JOIN clause for a source through the reference table.

        Example:
            generate_join_sql('locations', 'netsuite')
            -> 'LEFT JOIN ss__dbo__IFSLocations ref_locations
                ON CAST(TransactionLine.location AS VARCHAR) =
                   CAST(ref_locations.LocationID AS VARCHAR)'
        """
        ref = self.get_reference(reference_name)
        if not ref:
            return ""

        link = None
        for sl in ref.source_links:
            if sl.name == source_name:
                link = sl
                break
        if not link:
            return ""

        alias = f"ref_{reference_name}"
        join_type = link.join_type.upper()

        return (
            f"{join_type} JOIN {ref.table} {alias} "
            f"ON CAST({link.table}.{link.join_column} AS VARCHAR) = "
            f"CAST({alias}.{ref.id_column} AS VARCHAR)"
        )

    def generate_filter_sql(
        self,
        reference_name: str,
        flag_column: str,
        value: Any = 1,
    ) -> str:
        """Generate SQL WHERE clause for a flag filter.

        Example:
            generate_filter_sql('locations', 'ActiveBusiness')
            -> 'ref_locations.ActiveBusiness = 1'
        """
        alias = f"ref_{reference_name}"
        return f"{alias}.{flag_column} = {value}"

    # -- Persistence --------------------------------------------------------

    def save(self, path: Path | str | None = None) -> Path:
        """Save the compilation map to YAML."""
        path = Path(path) if path else _default_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "metadata": self.metadata,
            "references": [],
        }

        for ref in self.references:
            ref_data: dict[str, Any] = {
                "name": ref.name,
                "table": ref.table,
                "id_column": ref.id_column,
                "display_column": ref.display_column,
            }

            if ref.source_links:
                ref_data["source_links"] = [
                    {
                        "name": sl.name,
                        "table": sl.table,
                        "join_column": sl.join_column,
                        "join_type": sl.join_type,
                        "transform": sl.transform,
                        "description": sl.description,
                    }
                    for sl in ref.source_links
                ]

            if ref.rollups:
                ref_data["rollups"] = [
                    {"column": r.column, "display": r.display}
                    for r in ref.rollups
                ]

            if ref.flag_groups:
                ref_data["flag_groups"] = [
                    {
                        "name": fg.name,
                        "display": fg.display,
                        "flags": [
                            {
                                "column": f.column,
                                "display": f.display,
                                "active_value": f.active_value,
                            }
                            for f in fg.flags
                        ],
                    }
                    for fg in ref.flag_groups
                ]

            data["references"].append(ref_data)

        path.write_text(
            yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, path: Path | str | None = None) -> CompilationMap:
        """Load a compilation map from YAML."""
        path = Path(path) if path else _default_path()

        # Also check for a pointer file that redirects to a network path
        pointer = _pointer_path()
        if pointer.exists():
            redirect = pointer.read_text(encoding="utf-8").strip()
            if redirect and Path(redirect).exists():
                path = Path(redirect)

        if not path.exists():
            return cls()

        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return cls()

        references: list[ReferenceTable] = []
        for ref_data in raw.get("references", []):
            source_links = [
                SourceLink(
                    name=sl.get("name", ""),
                    table=sl.get("table", ""),
                    join_column=sl.get("join_column", ""),
                    join_type=sl.get("join_type", "left"),
                    transform=sl.get("transform", ""),
                    description=sl.get("description", ""),
                )
                for sl in ref_data.get("source_links", [])
            ]

            rollups = [
                RollupLevel(column=r.get("column", ""), display=r.get("display", ""))
                for r in ref_data.get("rollups", [])
            ]

            flag_groups = [
                FlagGroup(
                    name=fg.get("name", ""),
                    display=fg.get("display", ""),
                    flags=[
                        FlagDefinition(
                            column=f.get("column", ""),
                            display=f.get("display", ""),
                            active_value=f.get("active_value", 1),
                        )
                        for f in fg.get("flags", [])
                    ],
                )
                for fg in ref_data.get("flag_groups", [])
            ]

            references.append(ReferenceTable(
                name=ref_data.get("name", ""),
                table=ref_data.get("table", ""),
                id_column=ref_data.get("id_column", ""),
                display_column=ref_data.get("display_column", ""),
                source_links=source_links,
                rollups=rollups,
                flag_groups=flag_groups,
            ))

        return cls(
            name=raw.get("name", "Data Compilation Map"),
            description=raw.get("description", ""),
            references=references,
            metadata=raw.get("metadata", {}),
        )

    @classmethod
    def use_network_path(cls, network_path: str) -> None:
        """Point this install at a shared compilation map on the network.

        Creates a pointer file that redirects load() to the network path.
        Every user who runs this command will share the same map.
        """
        pointer = _pointer_path()
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text(network_path, encoding="utf-8")

    @classmethod
    def get_active_path(cls) -> Path:
        """Return the path to the active compilation map."""
        pointer = _pointer_path()
        if pointer.exists():
            redirect = pointer.read_text(encoding="utf-8").strip()
            if redirect and Path(redirect).exists():
                return Path(redirect)
        return _default_path()


def _default_path() -> Path:
    return config_dir() / "compilation_map.yaml"


def _pointer_path() -> Path:
    return config_dir() / "compilation_map_pointer.txt"
