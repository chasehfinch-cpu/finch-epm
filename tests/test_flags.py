"""Tests for the binary flag detection and classification system."""

from __future__ import annotations

from pathlib import Path

import pytest

from finch_epm.engine.flags import (
    FlagDefinition,
    FlagSet,
    FlagStore,
    FlagType,
    auto_classify_flags,
    classify_flags_interactive,
    detect_binary_columns,
)


class TestDetectBinaryColumns:
    def test_detects_01_integer_columns(self) -> None:
        cols = ["id", "name", "ActiveBusiness", "TerminatedBusiness"]
        rows = [
            [1, "Site A", 1, 0],
            [2, "Site B", 0, 1],
            [3, "Site C", 1, 0],
        ]
        candidates = detect_binary_columns("test_table", cols, rows)
        names = [c["column_name"] for c in candidates]
        assert "ActiveBusiness" in names
        assert "TerminatedBusiness" in names
        assert "id" not in names  # id has values 1,2,3 — not binary
        assert "name" not in names

    def test_detects_status_type(self) -> None:
        cols = ["id", "Active", "Terminated"]
        rows = [[1, 1, 0], [2, 0, 1]]
        candidates = detect_binary_columns("t", cols, rows)
        active = next(c for c in candidates if c["column_name"] == "Active")
        assert active["suggested_type"] == FlagType.STATUS

    def test_detects_period_type(self) -> None:
        cols = ["id", "CoreFY25", "CoreFY26"]
        rows = [[1, 0, 1], [2, 1, 1]]
        candidates = detect_binary_columns("t", cols, rows)
        fy25 = next(c for c in candidates if c["column_name"] == "CoreFY25")
        assert fy25["suggested_type"] == FlagType.PERIOD

    def test_skips_non_binary(self) -> None:
        cols = ["id", "amount", "status_code"]
        rows = [[1, 1000.50, 3], [2, 2500.00, 5]]
        candidates = detect_binary_columns("t", cols, rows)
        assert len(candidates) == 0

    def test_handles_empty_rows(self) -> None:
        candidates = detect_binary_columns("t", ["a", "b"], [])
        assert candidates == []

    def test_handles_null_values(self) -> None:
        cols = ["id", "flag"]
        rows = [[1, 1], [2, None], [3, 0]]
        candidates = detect_binary_columns("t", cols, rows)
        assert any(c["column_name"] == "flag" for c in candidates)

    def test_real_ifs_locations_pattern(self) -> None:
        """Test with the actual IFSLocations column pattern."""
        cols = [
            "LocationID", "LocationName", "GroupRollup", "State",
            "ActiveBusiness", "TerminatedBusiness", "Unused",
            "CoreFY19", "CoreFY20", "CoreFY21", "CoreFY22",
            "CoreFY23", "CoreFY24", "CoreFY25", "CoreFY26",
        ]
        rows = [
            ["L132", "Ahwatukee", "CSEP", "AZ", 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
            ["L28", "Assumption", "AEP", "IL", 1, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1],
            ["L99", "Closed Site", "OLD", "TX", 0, 1, 0, 1, 1, 0, 0, 0, 0, 0, 0],
        ]
        candidates = detect_binary_columns("IFSLocations", cols, rows)
        names = [c["column_name"] for c in candidates]

        # Should detect all binary columns
        assert "ActiveBusiness" in names
        assert "TerminatedBusiness" in names
        assert "Unused" in names
        assert "CoreFY25" in names
        assert "CoreFY26" in names

        # Should NOT detect non-binary columns
        assert "LocationID" not in names
        assert "LocationName" not in names
        assert "State" not in names

        # Check types
        active = next(c for c in candidates if c["column_name"] == "ActiveBusiness")
        assert active["suggested_type"] == FlagType.STATUS

        core26 = next(c for c in candidates if c["column_name"] == "CoreFY26")
        assert core26["suggested_type"] == FlagType.PERIOD


class TestAutoClassify:
    def test_auto_classifies_all_candidates(self) -> None:
        candidates = [
            {"column_name": "Active", "suggested_type": FlagType.STATUS, "suggested_group": "status", "distinct_values": [0, 1]},
            {"column_name": "CoreFY25", "suggested_type": FlagType.PERIOD, "suggested_group": "core_years", "distinct_values": [0, 1]},
        ]
        flag_set = auto_classify_flags("test_table", candidates)
        assert len(flag_set.flags) == 2
        assert flag_set.flags[0].flag_type == FlagType.STATUS
        assert flag_set.flags[1].flag_type == FlagType.PERIOD


class TestClassifyInteractive:
    def test_interactive_with_mock(self) -> None:
        candidates = [
            {"column_name": "Active", "suggested_type": FlagType.STATUS, "suggested_group": "status", "distinct_values": [0, 1]},
            {"column_name": "CoreFY26", "suggested_type": FlagType.PERIOD, "suggested_group": "core_years", "distinct_values": [0, 1]},
        ]

        answers = iter(["status", "period"])

        def mock_prompt(question, choices):
            answer_keyword = next(answers)
            for c in choices:
                if answer_keyword in c:
                    return c
            return choices[-1]

        flag_set = classify_flags_interactive("test", candidates, prompt_fn=mock_prompt)
        assert len(flag_set.flags) == 2
        assert flag_set.flags[0].flag_type == FlagType.STATUS
        assert flag_set.flags[1].flag_type == FlagType.PERIOD

    def test_skip_option(self) -> None:
        candidates = [
            {"column_name": "SomeCol", "suggested_type": FlagType.CUSTOM, "suggested_group": "", "distinct_values": [0, 1]},
        ]

        def mock_prompt(question, choices):
            return choices[-1]  # "not a flag (skip)"

        flag_set = classify_flags_interactive("test", candidates, prompt_fn=mock_prompt)
        assert len(flag_set.flags) == 0


class TestFlagStore:
    def test_roundtrip_save_load(self, tmp_path: Path) -> None:
        path = tmp_path / "flags.yaml"
        store = FlagStore()
        store.set_flag_set(FlagSet(
            table_name="IFSLocations",
            flags=[
                FlagDefinition("ActiveBusiness", "Active Business", FlagType.STATUS, 1, group="status"),
                FlagDefinition("CoreFY26", "Core FY26", FlagType.PERIOD, 1, group="core_years"),
            ],
        ))
        store.save(path)

        loaded = FlagStore.load(path)
        fset = loaded.get_flag_set("IFSLocations")
        assert fset is not None
        assert len(fset.flags) == 2
        assert fset.status_flags()[0].column_name == "ActiveBusiness"
        assert fset.period_flags()[0].column_name == "CoreFY26"

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        store = FlagStore.load(tmp_path / "missing.yaml")
        assert len(store.flag_sets) == 0

    def test_all_flags(self) -> None:
        store = FlagStore()
        store.set_flag_set(FlagSet("t1", [FlagDefinition("a", flag_type=FlagType.STATUS)]))
        store.set_flag_set(FlagSet("t2", [FlagDefinition("b", flag_type=FlagType.PERIOD)]))
        all_flags = store.all_flags()
        assert len(all_flags) == 2

    def test_flag_set_helpers(self) -> None:
        fset = FlagSet("test", [
            FlagDefinition("Active", flag_type=FlagType.STATUS),
            FlagDefinition("CoreFY25", flag_type=FlagType.PERIOD, group="core"),
            FlagDefinition("CoreFY26", flag_type=FlagType.PERIOD, group="core"),
            FlagDefinition("Custom1", flag_type=FlagType.CUSTOM),
        ])
        assert len(fset.status_flags()) == 1
        assert len(fset.period_flags()) == 2
        assert len(fset.custom_flags()) == 1
        assert len(fset.get_by_group("core")) == 2
