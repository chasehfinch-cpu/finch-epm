"""Schema change detection between catalog crawls.

Compares the current catalog snapshot with a new introspection result
and produces a structured diff: new tables, removed tables, new columns,
removed columns, and type changes. This feeds into the classification
system so users can be prompted about new items.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from finch_epm.connectors.types import SchemaInfo, TableInfo


@dataclass(frozen=True)
class NewTable:
    """A table that exists in the new schema but not the old."""

    name: str
    display_name: str
    column_count: int
    is_custom: bool = False


@dataclass(frozen=True)
class RemovedTable:
    """A table that existed in the old schema but not the new."""

    name: str


@dataclass(frozen=True)
class NewColumn:
    """A column that exists in a table in the new schema but not the old."""

    table_name: str
    column_name: str
    column_type: str
    is_custom: bool = False


@dataclass(frozen=True)
class RemovedColumn:
    """A column that existed in a table in the old schema but not the new."""

    table_name: str
    column_name: str


@dataclass(frozen=True)
class TypeChange:
    """A column whose type changed between schema versions."""

    table_name: str
    column_name: str
    old_type: str
    new_type: str


@dataclass
class SchemaChanges:
    """Complete diff between two catalog snapshots."""

    new_tables: list[NewTable] = field(default_factory=list)
    removed_tables: list[RemovedTable] = field(default_factory=list)
    new_columns: list[NewColumn] = field(default_factory=list)
    removed_columns: list[RemovedColumn] = field(default_factory=list)
    type_changes: list[TypeChange] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(
            self.new_tables or self.removed_tables
            or self.new_columns or self.removed_columns
            or self.type_changes
        )

    @property
    def total_changes(self) -> int:
        return (
            len(self.new_tables) + len(self.removed_tables)
            + len(self.new_columns) + len(self.removed_columns)
            + len(self.type_changes)
        )

    def summary(self) -> str:
        """One-line summary of changes."""
        parts: list[str] = []
        if self.new_tables:
            parts.append(f"{len(self.new_tables)} new table(s)")
        if self.removed_tables:
            parts.append(f"{len(self.removed_tables)} removed table(s)")
        if self.new_columns:
            parts.append(f"{len(self.new_columns)} new column(s)")
        if self.removed_columns:
            parts.append(f"{len(self.removed_columns)} removed column(s)")
        if self.type_changes:
            parts.append(f"{len(self.type_changes)} type change(s)")
        return ", ".join(parts) if parts else "no changes"


def detect_changes(
    old_tables: list[dict[str, Any]],
    old_columns: dict[str, list[dict[str, Any]]],
    new_schema: SchemaInfo,
) -> SchemaChanges:
    """Compare old catalog state with new introspection results.

    Args:
        old_tables: List of table dicts from ``CatalogStore.list_tables()``.
            Each dict has at minimum ``table_name``.
        old_columns: Mapping of table_name -> list of column dicts from
            ``CatalogStore.list_columns()``. Each dict has at minimum
            ``column_name`` and ``column_type``.
        new_schema: Fresh introspection result from a connector.

    Returns:
        SchemaChanges describing all differences.
    """
    changes = SchemaChanges()

    old_table_names = {t["table_name"] for t in old_tables}
    new_table_map: dict[str, TableInfo] = {t.name: t for t in new_schema.tables}
    new_table_names = set(new_table_map.keys())

    # New tables
    for name in sorted(new_table_names - old_table_names):
        table = new_table_map[name]
        changes.new_tables.append(NewTable(
            name=name,
            display_name=table.display_name,
            column_count=len(table.columns),
            is_custom=table.is_custom,
        ))

    # Removed tables
    for name in sorted(old_table_names - new_table_names):
        changes.removed_tables.append(RemovedTable(name=name))

    # Column-level changes for tables that exist in both
    for table_name in sorted(old_table_names & new_table_names):
        old_cols = old_columns.get(table_name, [])
        new_table = new_table_map[table_name]

        old_col_map = {c["column_name"]: c for c in old_cols}
        new_col_map = {c.name: c for c in new_table.columns}

        old_col_names = set(old_col_map.keys())
        new_col_names = set(new_col_map.keys())

        # New columns
        for col_name in sorted(new_col_names - old_col_names):
            col = new_col_map[col_name]
            changes.new_columns.append(NewColumn(
                table_name=table_name,
                column_name=col_name,
                column_type=col.column_type.value,
                is_custom=col.is_custom,
            ))

        # Removed columns
        for col_name in sorted(old_col_names - new_col_names):
            changes.removed_columns.append(RemovedColumn(
                table_name=table_name,
                column_name=col_name,
            ))

        # Type changes
        for col_name in sorted(old_col_names & new_col_names):
            old_type = old_col_map[col_name].get("column_type", "")
            new_type = new_col_map[col_name].column_type.value
            if old_type and new_type and old_type != new_type:
                changes.type_changes.append(TypeChange(
                    table_name=table_name,
                    column_name=col_name,
                    old_type=old_type,
                    new_type=new_type,
                ))

    return changes


def detect_unmapped_accounts(
    account_rows: list[dict[str, Any]],
    pl_sections: list[Any],
    classified_account_ids: set[str],
) -> list[dict[str, Any]]:
    """Find accounts that don't map to any P&L section.

    Args:
        account_rows: Rows from the cached Account table. Each row should
            have at least ``id``, ``accttype``, ``acctnumber``, ``fullname``.
        pl_sections: Flat list of PLSection objects from the active COA.
        classified_account_ids: Account IDs already classified by the user.

    Returns:
        List of account row dicts that are unmapped.
    """
    # Collect all account types and number prefixes from the COA
    mapped_types: set[str] = set()
    mapped_prefixes: list[str] = []
    mapped_names: list[str] = []

    for section in pl_sections:
        mapped_types.update(section.account_types)
        mapped_prefixes.extend(section.account_numbers)
        mapped_names.extend(section.account_names)

    unmapped: list[dict[str, Any]] = []

    for row in account_rows:
        acct_id = str(row.get("id", ""))
        if acct_id in classified_account_ids:
            continue

        acct_type = str(row.get("accttype", ""))
        acct_number = str(row.get("acctnumber", ""))
        acct_name = str(row.get("fullname", row.get("name", "")))

        # Check if this account matches any section
        matched = False

        if acct_type in mapped_types:
            matched = True

        if not matched and acct_number:
            for prefix in mapped_prefixes:
                if acct_number.startswith(prefix):
                    matched = True
                    break

        if not matched and acct_name:
            for name_pattern in mapped_names:
                if name_pattern.lower() in acct_name.lower():
                    matched = True
                    break

        if not matched:
            unmapped.append(row)

    return unmapped


def flatten_pl_sections(section: Any) -> list[Any]:
    """Recursively flatten a PLSection tree into a list."""
    result = [section]
    for child in getattr(section, "children", []):
        result.extend(flatten_pl_sections(child))
    return result
