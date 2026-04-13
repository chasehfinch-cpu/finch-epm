"""Interactive data classifier for new schema items.

When a catalog crawl detects new tables, columns, or unmapped accounts,
this module prompts the user to classify them. Classifications are
persisted in ``classifications.yaml`` and feed into the P&L engine,
the LLM prompt builder, and dashboard warnings.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any, Callable

from finch_epm.catalog.change_detector import (
    NewColumn,
    NewTable,
    SchemaChanges,
    detect_unmapped_accounts,
    flatten_pl_sections,
)
from finch_epm.engine.classification_models import (
    AccountClassification,
    ClassificationStore,
    ColumnClassification,
    DataClass,
    PendingItem,
    TableClassification,
)

logger = logging.getLogger(__name__)

# Interactive prompt function type -- defaults to click.prompt but can be
# replaced in tests with a function that returns canned answers.
PromptFunc = Callable[[str, list[str]], str]


def _default_choices() -> list[tuple[str, DataClass]]:
    """Return the top-level classification choices for interactive prompts."""
    return [
        ("financial (P&L revenue)", DataClass.PL_REVENUE),
        ("financial (P&L expense)", DataClass.PL_EXPENSE),
        ("financial (COGS)", DataClass.PL_COGS),
        ("financial (other P&L)", DataClass.PL_OTHER),
        ("financial (balance sheet)", DataClass.BALANCE_SHEET),
        ("financial (cash flow)", DataClass.CASH_FLOW),
        ("financial (other)", DataClass.FINANCIAL_OTHER),
        ("statistical", DataClass.STATISTICAL),
        ("operational", DataClass.OPERATIONAL),
        ("qualitative", DataClass.QUALITATIVE),
        ("skip (decide later)", DataClass.UNDETERMINED),
    ]


class DataClassifier:
    """Prompts users to classify new schema items and persists results.

    Usage::

        classifier = DataClassifier(store, source_key)
        classifier.classify_tables(changes.new_tables)
        classifier.classify_accounts(unmapped_accounts, pl_structure)
        classifier.store.save()
    """

    def __init__(
        self,
        store: ClassificationStore,
        connector_type: str,
        profile_name: str,
    ) -> None:
        self.store = store
        self.connector_type = connector_type
        self.profile_name = profile_name
        self._source_key = store.source_key(connector_type, profile_name)

    def classify_new_tables(
        self,
        new_tables: list[NewTable],
        *,
        prompt_fn: PromptFunc | None = None,
    ) -> int:
        """Prompt user to classify new tables.

        Args:
            new_tables: Tables detected as new.
            prompt_fn: Override for testing. Receives (question, choices) -> answer.

        Returns:
            Number of tables classified (excluding skipped).
        """
        if not new_tables:
            return 0

        prompt_fn = prompt_fn or _click_prompt
        choices = _default_choices()
        choice_labels = [c[0] for c in choices]
        classified = 0

        for table in new_tables:
            question = (
                f"\n  New table: {table.name}"
                f" ({table.column_count} columns"
                f"{', custom' if table.is_custom else ''})"
                f"\n  What kind of data does this table contain?"
            )
            answer = prompt_fn(question, choice_labels)
            data_class = _resolve_choice(answer, choices)

            if data_class != DataClass.UNDETERMINED:
                classified += 1

            self.store.set_table_class(
                self.connector_type,
                self.profile_name,
                table.name,
                TableClassification(
                    data_class=data_class,
                    classified_at=str(date.today()),
                ),
            )

            # Remove from pending if it was there
            self.store.remove_pending(self._source_key, "table", table.name)

        return classified

    def classify_new_columns(
        self,
        new_columns: list[NewColumn],
        *,
        prompt_fn: PromptFunc | None = None,
    ) -> int:
        """Prompt user to classify new columns.

        Returns:
            Number of columns classified (excluding skipped).
        """
        if not new_columns:
            return 0

        prompt_fn = prompt_fn or _click_prompt
        choices = _default_choices()
        choice_labels = [c[0] for c in choices]
        classified = 0

        for col in new_columns:
            question = (
                f"\n  New column: {col.table_name}.{col.column_name}"
                f" (type: {col.column_type}"
                f"{', custom' if col.is_custom else ''})"
                f"\n  What kind of data does this column contain?"
            )
            answer = prompt_fn(question, choice_labels)
            data_class = _resolve_choice(answer, choices)

            if data_class != DataClass.UNDETERMINED:
                classified += 1

            self.store.set_column_class(
                self.connector_type,
                self.profile_name,
                col.table_name,
                col.column_name,
                ColumnClassification(data_class=data_class),
            )

            self.store.remove_pending(
                self._source_key, "column", f"{col.table_name}.{col.column_name}"
            )

        return classified

    def classify_unmapped_accounts(
        self,
        unmapped_rows: list[dict[str, Any]],
        pl_structure: Any,
        *,
        prompt_fn: PromptFunc | None = None,
    ) -> int:
        """Prompt user to classify accounts that don't map to any P&L section.

        Args:
            unmapped_rows: Account rows from the cache (id, accttype, acctnumber, fullname).
            pl_structure: The root PLSection (for listing available sections).
            prompt_fn: Override for testing.

        Returns:
            Number of accounts classified (excluding skipped).
        """
        if not unmapped_rows:
            return 0

        prompt_fn = prompt_fn or _click_prompt

        # Build section choices from the P&L structure
        flat_sections = flatten_pl_sections(pl_structure)
        section_names = [
            s.name for s in flat_sections
            if not s.is_subtotal and s.name
        ]

        # Build choice list: first the P&L sections, then non-financial options
        choices: list[tuple[str, str]] = []
        for sname in section_names:
            section = next(s for s in flat_sections if s.name == sname)
            choices.append((f"P&L > {section.display_name}", sname))
        choices.append(("balance sheet", "_balance_sheet"))
        choices.append(("cash flow", "_cash_flow"))
        choices.append(("statistical / non-financial", "_statistical"))
        choices.append(("skip (decide later)", "_skip"))

        choice_labels = [c[0] for c in choices]
        classified = 0

        for row in unmapped_rows:
            acct_id = str(row.get("id", ""))
            acct_number = str(row.get("acctnumber", ""))
            acct_type = str(row.get("accttype", ""))
            acct_name = str(row.get("fullname", row.get("name", "")))

            display = acct_name or acct_number or acct_id
            question = (
                f"\n  Unmapped account: {display}"
                f"\n    Number: {acct_number}, Type: {acct_type}"
                f"\n  Where should this account roll up?"
            )
            answer = prompt_fn(question, choice_labels)

            # Resolve the choice
            section_key = ""
            data_class = DataClass.UNDETERMINED
            for label, key in choices:
                if answer == label:
                    section_key = key
                    break

            if section_key == "_skip":
                data_class = DataClass.UNDETERMINED
            elif section_key == "_balance_sheet":
                data_class = DataClass.BALANCE_SHEET
            elif section_key == "_cash_flow":
                data_class = DataClass.CASH_FLOW
            elif section_key == "_statistical":
                data_class = DataClass.STATISTICAL
            else:
                # It's a P&L section
                data_class = DataClass.PL_EXPENSE  # Default for sections
                # Detect revenue vs expense from the section
                section_obj = next(
                    (s for s in flat_sections if s.name == section_key), None
                )
                if section_obj and section_obj.sign_convention == -1:
                    data_class = DataClass.PL_REVENUE

            if data_class != DataClass.UNDETERMINED:
                classified += 1

            self.store.set_account_class(
                self.connector_type,
                self.profile_name,
                acct_id,
                AccountClassification(
                    display_name=display,
                    data_class=data_class,
                    pl_section=section_key if section_key and not section_key.startswith("_") else "",
                    classified_at=str(date.today()),
                ),
            )

            self.store.remove_pending(self._source_key, "account", acct_id)

        return classified

    def add_pending_for_changes(self, changes: SchemaChanges) -> None:
        """Add pending items for any unclassified changes."""
        today = str(date.today())

        for table in changes.new_tables:
            existing = self.store.get_table_class(
                self.connector_type, self.profile_name, table.name
            )
            if existing.data_class == DataClass.UNDETERMINED:
                self.store.add_pending(PendingItem(
                    source=self._source_key,
                    item_type="table",
                    identifier=table.name,
                    display_name=table.display_name,
                    detected_at=today,
                ))

        for col in changes.new_columns:
            existing = self.store.get_column_class(
                self.connector_type, self.profile_name,
                col.table_name, col.column_name,
            )
            if existing.data_class == DataClass.UNDETERMINED:
                self.store.add_pending(PendingItem(
                    source=self._source_key,
                    item_type="column",
                    identifier=f"{col.table_name}.{col.column_name}",
                    display_name=f"{col.table_name}.{col.column_name} ({col.column_type})",
                    detected_at=today,
                ))


def _click_prompt(question: str, choices: list[str]) -> str:
    """Default interactive prompt using click."""
    import click

    click.echo(question)
    for i, choice in enumerate(choices, 1):
        click.echo(f"    {i}. {choice}")
    while True:
        raw = click.prompt("  Choice", type=int, default=len(choices))
        if 1 <= raw <= len(choices):
            return choices[raw - 1]
        click.echo(f"  Please enter a number between 1 and {len(choices)}")


def _resolve_choice(
    answer: str, choices: list[tuple[str, DataClass]]
) -> DataClass:
    """Map a choice label back to a DataClass."""
    for label, dc in choices:
        if answer == label:
            return dc
    return DataClass.UNDETERMINED
