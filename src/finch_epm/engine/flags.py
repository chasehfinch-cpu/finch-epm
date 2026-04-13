"""Binary flag detection, classification, and management.

Reference tables (like IFSLocations) often contain binary flag columns
that indicate status (Active/Terminated), period membership (CoreFY25),
or custom groupings. This module detects these columns, prompts users
to classify them, and stores the configuration for use in dashboard
filters and P&L scoping.

Flag types:
    - status: Active/Terminated/Unused — mutually exclusive states
    - period: CoreFY25, CoreFY26 — which fiscal years a site belongs to
    - custom: User-defined binary groupings

Users can create unlimited flags. Flags are stored in ``flags.yaml``
and are shareable across a team.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from finch_epm.paths import config_dir

logger = logging.getLogger(__name__)


class FlagType:
    STATUS = "status"
    PERIOD = "period"
    CUSTOM = "custom"


@dataclass
class FlagDefinition:
    """A single binary flag column in a reference table."""

    column_name: str
    display_name: str = ""
    flag_type: str = FlagType.CUSTOM
    """One of: status, period, custom"""
    active_value: Any = 1
    """Value that means 'true' (usually 1, but could be 'Y', True, etc.)"""
    description: str = ""
    group: str = ""
    """Group name for related flags (e.g., 'core_years' for CoreFY19-FY26)"""


@dataclass
class FlagSet:
    """Collection of flag definitions for a reference table."""

    table_name: str
    flags: list[FlagDefinition] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_flag(self, column_name: str) -> FlagDefinition | None:
        for f in self.flags:
            if f.column_name == column_name:
                return f
        return None

    def get_by_type(self, flag_type: str) -> list[FlagDefinition]:
        return [f for f in self.flags if f.flag_type == flag_type]

    def get_by_group(self, group: str) -> list[FlagDefinition]:
        return [f for f in self.flags if f.group == group]

    def status_flags(self) -> list[FlagDefinition]:
        return self.get_by_type(FlagType.STATUS)

    def period_flags(self) -> list[FlagDefinition]:
        return self.get_by_type(FlagType.PERIOD)

    def custom_flags(self) -> list[FlagDefinition]:
        return self.get_by_type(FlagType.CUSTOM)


class FlagStore:
    """Persistent storage for flag definitions across all reference tables.

    Stored in ``flags.yaml`` in the user's config directory.
    Shareable — team members can import the same flag definitions.
    """

    def __init__(self, flag_sets: dict[str, FlagSet] | None = None) -> None:
        self.flag_sets: dict[str, FlagSet] = flag_sets or {}

    def get_flag_set(self, table_name: str) -> FlagSet | None:
        return self.flag_sets.get(table_name)

    def set_flag_set(self, flag_set: FlagSet) -> None:
        self.flag_sets[flag_set.table_name] = flag_set

    def all_flags(self) -> list[tuple[str, FlagDefinition]]:
        """Return all (table_name, flag) pairs."""
        result = []
        for tname, fset in self.flag_sets.items():
            for f in fset.flags:
                result.append((tname, f))
        return result

    # -- Persistence --------------------------------------------------------

    def save(self, path: Path | str | None = None) -> Path:
        path = Path(path) if path else _default_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {"version": 1, "tables": {}}
        for tname, fset in self.flag_sets.items():
            data["tables"][tname] = {
                "metadata": fset.metadata,
                "flags": [
                    {
                        "column_name": f.column_name,
                        "display_name": f.display_name,
                        "flag_type": f.flag_type,
                        "active_value": f.active_value,
                        "description": f.description,
                        "group": f.group,
                    }
                    for f in fset.flags
                ],
            }

        path.write_text(
            yaml.dump(data, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, path: Path | str | None = None) -> FlagStore:
        path = Path(path) if path else _default_path()
        if not path.exists():
            return cls()

        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return cls()

        flag_sets: dict[str, FlagSet] = {}
        for tname, tdata in raw.get("tables", {}).items():
            flags = []
            for fd in tdata.get("flags", []):
                flags.append(FlagDefinition(
                    column_name=fd.get("column_name", ""),
                    display_name=fd.get("display_name", ""),
                    flag_type=fd.get("flag_type", FlagType.CUSTOM),
                    active_value=fd.get("active_value", 1),
                    description=fd.get("description", ""),
                    group=fd.get("group", ""),
                ))
            flag_sets[tname] = FlagSet(
                table_name=tname,
                flags=flags,
                metadata=tdata.get("metadata", {}),
            )

        return cls(flag_sets=flag_sets)


# -- Detection and classification -------------------------------------------


def detect_binary_columns(
    table_name: str,
    column_names: list[str],
    sample_rows: list[list[Any]],
) -> list[dict[str, Any]]:
    """Detect columns that are likely binary flags.

    Heuristic: columns where all non-null values are 0/1 (or True/False),
    or columns whose names match common flag patterns.

    Args:
        table_name: Table name for context.
        column_names: All column names.
        sample_rows: Sample data rows.

    Returns:
        List of dicts with column_name, suggested_type, suggested_group.
    """
    candidates: list[dict[str, Any]] = []

    # Name-based patterns
    status_patterns = ["active", "terminated", "inactive", "unused", "enabled", "disabled", "closed"]
    period_patterns = ["fy", "fiscal", "core"]

    for ci, col_name in enumerate(column_names):
        col_lower = col_name.lower()

        # Check values: are they all 0/1?
        values = set()
        for row in sample_rows:
            if ci < len(row) and row[ci] is not None:
                v = row[ci]
                if isinstance(v, bool):
                    values.add(1 if v else 0)
                elif isinstance(v, (int, float)):
                    values.add(int(v))
                elif str(v).strip() in ("0", "1", "True", "False", "Y", "N", "Yes", "No"):
                    values.add(str(v).strip())

        # Must have at least one observed value and all values must be binary
        is_binary = (
            len(values) >= 1
            and (
                values <= {0, 1}
                or values <= {"0", "1"}
                or values <= {"Y", "N"}
                or values <= {"True", "False"}
                or values <= {"Yes", "No"}
            )
        )

        if not is_binary:
            continue

        # Determine suggested type and group
        suggested_type = FlagType.CUSTOM
        suggested_group = ""

        if any(p in col_lower for p in status_patterns):
            suggested_type = FlagType.STATUS
            suggested_group = "status"
        elif any(p in col_lower for p in period_patterns):
            suggested_type = FlagType.PERIOD
            # Extract year if present (e.g., CoreFY25 -> core_years)
            suggested_group = "core_years"

        candidates.append({
            "column_name": col_name,
            "suggested_type": suggested_type,
            "suggested_group": suggested_group,
            "distinct_values": sorted(values),
        })

    return candidates


def classify_flags_interactive(
    table_name: str,
    candidates: list[dict[str, Any]],
    *,
    prompt_fn: Any = None,
) -> FlagSet:
    """Interactively classify detected binary flag columns.

    Args:
        table_name: Reference table name.
        candidates: Output from detect_binary_columns().
        prompt_fn: Override for testing. Receives (question, choices) -> answer.

    Returns:
        FlagSet with classified flags.
    """
    if prompt_fn is None:
        prompt_fn = _click_prompt

    flags: list[FlagDefinition] = []

    for cand in candidates:
        col_name = cand["column_name"]
        suggested = cand["suggested_type"]
        suggested_group = cand["suggested_group"]

        question = (
            f"\n  Column: {table_name}.{col_name}"
            f"\n  Values: {cand['distinct_values']}"
            f"\n  Suggested type: {suggested}"
            f"\n  What kind of flag is this?"
        )
        choices = [
            f"status (active/terminated/unused)",
            f"period (fiscal year membership, e.g., CoreFY25)",
            f"custom grouping (user-defined binary filter)",
            f"not a flag (skip)",
        ]
        answer = prompt_fn(question, choices)

        if "not a flag" in answer or "skip" in answer:
            continue

        if "status" in answer:
            flag_type = FlagType.STATUS
            group = "status"
        elif "period" in answer:
            flag_type = FlagType.PERIOD
            group = suggested_group or "fiscal_years"
        else:
            flag_type = FlagType.CUSTOM
            group = ""

        # Generate display name from column name
        display = col_name.replace("_", " ").replace("FY", " FY")
        if display[0].islower():
            display = display[0].upper() + display[1:]

        flags.append(FlagDefinition(
            column_name=col_name,
            display_name=display,
            flag_type=flag_type,
            active_value=1,
            group=group,
        ))

    return FlagSet(table_name=table_name, flags=flags)


def auto_classify_flags(
    table_name: str,
    candidates: list[dict[str, Any]],
) -> FlagSet:
    """Auto-classify flags without user interaction (for testing/defaults)."""
    flags: list[FlagDefinition] = []
    for cand in candidates:
        col_name = cand["column_name"]
        display = col_name.replace("_", " ")
        if display[0].islower():
            display = display[0].upper() + display[1:]

        flags.append(FlagDefinition(
            column_name=col_name,
            display_name=display,
            flag_type=cand["suggested_type"],
            active_value=1,
            group=cand["suggested_group"],
        ))
    return FlagSet(table_name=table_name, flags=flags)


def _click_prompt(question: str, choices: list[str]) -> str:
    """Default interactive prompt using click."""
    import click
    click.echo(question)
    for i, choice in enumerate(choices, 1):
        click.echo(f"    {i}. {choice}")
    while True:
        raw = click.prompt("  Choice", type=int, default=1)
        if 1 <= raw <= len(choices):
            return choices[raw - 1]
        click.echo(f"  Please enter 1-{len(choices)}")


def _default_path() -> Path:
    return config_dir() / "flags.yaml"
