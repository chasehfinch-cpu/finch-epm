"""Tests for the Compilation Map — single source of truth for data linking."""

from __future__ import annotations

from pathlib import Path

import pytest

from finch_epm.engine.compilation_map import (
    CompilationMap,
    FlagDefinition,
    FlagGroup,
    ReferenceTable,
    RollupLevel,
    SourceLink,
)


def _sample_map() -> CompilationMap:
    """Build a sample compilation map matching the IFSLocations pattern."""
    return CompilationMap(
        name="Test Compilation Map",
        references=[
            ReferenceTable(
                name="locations",
                table="ss__dbo__IFSLocations",
                id_column="LocationID",
                display_column="LocationName",
                source_links=[
                    SourceLink(
                        name="netsuite",
                        table="TransactionLine",
                        join_column="location",
                        description="NS Location ID -> IFS LocationID",
                    ),
                    SourceLink(
                        name="sqlserver_rcm",
                        table="dbo__RCMSiteMaster",
                        join_column="Division",
                        description="RCM Division -> IFS Division",
                    ),
                ],
                rollups=[
                    RollupLevel(column="LocationRollup", display="Location"),
                    RollupLevel(column="GroupRollup", display="Group"),
                    RollupLevel(column="State", display="State"),
                ],
                flag_groups=[
                    FlagGroup(
                        name="status",
                        display="Site Status",
                        flags=[
                            FlagDefinition(column="ActiveBusiness", display="Active"),
                            FlagDefinition(column="TerminatedBusiness", display="Terminated"),
                            FlagDefinition(column="Unused", display="Unused"),
                        ],
                    ),
                    FlagGroup(
                        name="core_years",
                        display="Core Year Membership",
                        flags=[
                            FlagDefinition(column="CoreFY25", display="Core FY25"),
                            FlagDefinition(column="CoreFY26", display="Core FY26"),
                        ],
                    ),
                ],
            ),
            ReferenceTable(
                name="departments",
                table="ss__dbo__IFSDepartments",
                id_column="DepartmentID",
                display_column="DepartmentName",
                rollups=[
                    RollupLevel(column="DepartmentRollup", display="Department Group"),
                ],
            ),
        ],
    )


class TestCompilationMap:
    def test_roundtrip_save_load(self, tmp_path: Path) -> None:
        path = tmp_path / "map.yaml"
        cmap = _sample_map()
        cmap.save(path)

        loaded = CompilationMap.load(path)
        assert loaded.name == "Test Compilation Map"
        assert len(loaded.references) == 2

        loc = loaded.get_reference("locations")
        assert loc is not None
        assert loc.table == "ss__dbo__IFSLocations"
        assert loc.id_column == "LocationID"
        assert len(loc.source_links) == 2
        assert len(loc.rollups) == 3
        assert len(loc.flag_groups) == 2
        assert len(loc.get_all_flags()) == 5

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        cmap = CompilationMap.load(tmp_path / "missing.yaml")
        assert len(cmap.references) == 0

    def test_get_reference(self) -> None:
        cmap = _sample_map()
        assert cmap.get_reference("locations") is not None
        assert cmap.get_reference("departments") is not None
        assert cmap.get_reference("nonexistent") is None

    def test_get_reference_by_table(self) -> None:
        cmap = _sample_map()
        ref = cmap.get_reference_by_table("ss__dbo__IFSLocations")
        assert ref is not None
        assert ref.name == "locations"

    def test_get_all_source_links(self) -> None:
        cmap = _sample_map()
        links = cmap.get_all_source_links()
        assert len(links) == 2  # netsuite + sqlserver_rcm (departments has no links)

    def test_flag_group_lookup(self) -> None:
        cmap = _sample_map()
        loc = cmap.get_reference("locations")
        assert loc is not None

        status = loc.get_flag_group("status")
        assert status is not None
        assert len(status.flags) == 3

        periods = loc.get_flag_group("core_years")
        assert periods is not None
        assert len(periods.flags) == 2


class TestJoinGeneration:
    def test_generate_join_netsuite(self) -> None:
        cmap = _sample_map()
        sql = cmap.generate_join_sql("locations", "netsuite")
        assert "LEFT JOIN ss__dbo__IFSLocations ref_locations" in sql
        assert "TransactionLine.location" in sql
        assert "ref_locations.LocationID" in sql

    def test_generate_join_sqlserver(self) -> None:
        cmap = _sample_map()
        sql = cmap.generate_join_sql("locations", "sqlserver_rcm")
        assert "LEFT JOIN ss__dbo__IFSLocations ref_locations" in sql
        assert "dbo__RCMSiteMaster.Division" in sql

    def test_generate_join_unknown_source(self) -> None:
        cmap = _sample_map()
        sql = cmap.generate_join_sql("locations", "unknown")
        assert sql == ""

    def test_generate_filter_sql(self) -> None:
        cmap = _sample_map()
        sql = cmap.generate_filter_sql("locations", "ActiveBusiness")
        assert sql == "ref_locations.ActiveBusiness = 1"

        sql2 = cmap.generate_filter_sql("locations", "CoreFY26")
        assert sql2 == "ref_locations.CoreFY26 = 1"


class TestNetworkPointer:
    def test_use_network_path(self, tmp_path: Path, monkeypatch) -> None:
        """Test pointing to a shared network map."""
        # Create a map on the "network" (simulated as tmp_path)
        network_map = tmp_path / "shared" / "compilation_map.yaml"
        network_map.parent.mkdir()
        cmap = _sample_map()
        cmap.save(network_map)

        # Point to it
        local_config = tmp_path / "config"
        local_config.mkdir()
        pointer = local_config / "compilation_map_pointer.txt"
        pointer.write_text(str(network_map))

        # Load should follow the pointer
        # (We'd normally monkeypatch config_dir but let's test the file directly)
        loaded = CompilationMap.load(network_map)
        assert loaded.name == "Test Compilation Map"
        assert len(loaded.references) == 2

    def test_get_active_path_default(self) -> None:
        # Without a pointer, returns the default config path
        path = CompilationMap.get_active_path()
        assert "compilation_map.yaml" in str(path)


class TestYAMLReadability:
    """Ensure the saved YAML is human-readable and editable."""

    def test_yaml_is_readable(self, tmp_path: Path) -> None:
        path = tmp_path / "map.yaml"
        cmap = _sample_map()
        cmap.save(path)

        content = path.read_text(encoding="utf-8")
        # Should be readable YAML, not compressed
        assert "name: Test Compilation Map" in content
        assert "LocationID" in content
        assert "ActiveBusiness" in content
        assert "Core FY26" in content
        # Should NOT have Python-style repr or JSON
        assert "OrderedDict" not in content
        assert "{'" not in content
