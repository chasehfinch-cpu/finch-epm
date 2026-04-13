"""Tests for the data classification system."""

from __future__ import annotations

from pathlib import Path

import pytest

from finch_epm.catalog.change_detector import NewColumn, NewTable
from finch_epm.engine.chart_of_accounts import PLSection, get_default_pl_structure
from finch_epm.engine.classification_models import (
    AccountClassification,
    ClassificationStore,
    ColumnClassification,
    DataClass,
    PendingItem,
    TableClassification,
)
from finch_epm.engine.classifier import DataClassifier


class TestClassificationStore:
    def test_roundtrip_save_load(self, tmp_path: Path) -> None:
        path = tmp_path / "classifications.yaml"

        store = ClassificationStore()
        store.set_table_class("netsuite", "prod", "Account", TableClassification(
            data_class=DataClass.PL_REVENUE,
            notes="Chart of accounts",
        ))
        store.set_column_class("netsuite", "prod", "Account", "balance", ColumnClassification(
            data_class=DataClass.FINANCIAL_OTHER,
            pl_section="revenue",
        ))
        store.set_account_class("netsuite", "prod", "8350", AccountClassification(
            display_name="PA Labor",
            data_class=DataClass.PL_EXPENSE,
            pl_section="labor",
            classified_at="2026-04-13",
        ))
        store.add_pending(PendingItem(
            source="netsuite/prod",
            item_type="table",
            identifier="NewTable",
            display_name="New Table",
            detected_at="2026-04-13",
        ))
        store.save(path)

        loaded = ClassificationStore.load(path)
        tc = loaded.get_table_class("netsuite", "prod", "Account")
        assert tc.data_class == DataClass.PL_REVENUE
        assert tc.notes == "Chart of accounts"

        cc = loaded.get_column_class("netsuite", "prod", "Account", "balance")
        assert cc.data_class == DataClass.FINANCIAL_OTHER
        assert cc.pl_section == "revenue"

        ac = loaded.get_account_class("netsuite", "prod", "8350")
        assert ac.display_name == "PA Labor"
        assert ac.data_class == DataClass.PL_EXPENSE
        assert ac.pl_section == "labor"

        assert loaded.pending_count() == 1

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        store = ClassificationStore.load(tmp_path / "missing.yaml")
        assert store.pending_count() == 0
        assert store.tables == {}

    def test_pending_dedup(self) -> None:
        store = ClassificationStore()
        item = PendingItem(source="a/b", item_type="table", identifier="T")
        store.add_pending(item)
        store.add_pending(item)  # Duplicate
        assert store.pending_count() == 1

    def test_remove_pending(self) -> None:
        store = ClassificationStore()
        store.add_pending(PendingItem(source="a/b", item_type="table", identifier="T"))
        store.remove_pending("a/b", "table", "T")
        assert store.pending_count() == 0

    def test_unclassified_defaults(self) -> None:
        store = ClassificationStore()
        tc = store.get_table_class("x", "y", "z")
        assert tc.data_class == DataClass.UNDETERMINED

    def test_data_class_is_financial(self) -> None:
        assert DataClass.PL_REVENUE.is_financial
        assert DataClass.BALANCE_SHEET.is_financial
        assert not DataClass.STATISTICAL.is_financial
        assert not DataClass.OPERATIONAL.is_financial
        assert not DataClass.UNDETERMINED.is_financial


class TestDataClassifier:
    def _make_prompt_fn(self, answers: list[str]):
        """Create a mock prompt function that returns canned answers."""
        idx = [0]

        def prompt_fn(question: str, choices: list[str]) -> str:
            if idx[0] < len(answers):
                answer = answers[idx[0]]
                idx[0] += 1
            else:
                answer = choices[-1]  # Default to last (skip)
            # Match the answer to the closest choice
            for c in choices:
                if answer.lower() in c.lower():
                    return c
            return choices[-1]

        return prompt_fn

    def test_classify_new_tables(self) -> None:
        store = ClassificationStore()
        classifier = DataClassifier(store, "test", "default")

        tables = [
            NewTable(name="Revenue", display_name="Revenue Table", column_count=5),
            NewTable(name="StatusLog", display_name="Status Log", column_count=3),
        ]

        prompt_fn = self._make_prompt_fn(["financial (P&L revenue)", "operational"])
        classified = classifier.classify_new_tables(tables, prompt_fn=prompt_fn)

        assert classified == 2
        tc1 = store.get_table_class("test", "default", "Revenue")
        assert tc1.data_class == DataClass.PL_REVENUE

        tc2 = store.get_table_class("test", "default", "StatusLog")
        assert tc2.data_class == DataClass.OPERATIONAL

    def test_classify_new_columns(self) -> None:
        store = ClassificationStore()
        classifier = DataClassifier(store, "test", "default")

        columns = [
            NewColumn(table_name="Account", column_name="new_balance", column_type="float"),
        ]

        prompt_fn = self._make_prompt_fn(["financial (P&L expense)"])
        classified = classifier.classify_new_columns(columns, prompt_fn=prompt_fn)
        assert classified == 1

        cc = store.get_column_class("test", "default", "Account", "new_balance")
        assert cc.data_class == DataClass.PL_EXPENSE

    def test_classify_skip_is_undetermined(self) -> None:
        store = ClassificationStore()
        classifier = DataClassifier(store, "test", "default")

        tables = [NewTable(name="Mystery", display_name="?", column_count=1)]
        prompt_fn = self._make_prompt_fn(["skip"])
        classified = classifier.classify_new_tables(tables, prompt_fn=prompt_fn)

        assert classified == 0  # Skipped items don't count
        tc = store.get_table_class("test", "default", "Mystery")
        assert tc.data_class == DataClass.UNDETERMINED

    def test_classify_unmapped_accounts(self) -> None:
        store = ClassificationStore()
        classifier = DataClassifier(store, "netsuite", "prod")

        pl = get_default_pl_structure()
        unmapped = [
            {"id": "99", "accttype": "Other", "acctnumber": "9999", "fullname": "Mystery Account"},
        ]

        # Choose "revenue" section
        prompt_fn = self._make_prompt_fn(["Revenue"])
        classified = classifier.classify_unmapped_accounts(
            unmapped, pl, prompt_fn=prompt_fn
        )

        assert classified == 1
        ac = store.get_account_class("netsuite", "prod", "99")
        assert ac.pl_section == "revenue"
        assert ac.data_class == DataClass.PL_REVENUE  # Revenue section has sign=-1

    def test_classify_account_skip(self) -> None:
        store = ClassificationStore()
        classifier = DataClassifier(store, "netsuite", "prod")

        pl = get_default_pl_structure()
        unmapped = [
            {"id": "50", "accttype": "X", "acctnumber": "5050", "fullname": "Skip Me"},
        ]

        prompt_fn = self._make_prompt_fn(["skip"])
        classified = classifier.classify_unmapped_accounts(
            unmapped, pl, prompt_fn=prompt_fn
        )
        assert classified == 0

    def test_add_pending_for_changes(self) -> None:
        from finch_epm.catalog.change_detector import SchemaChanges

        store = ClassificationStore()
        classifier = DataClassifier(store, "test", "default")

        changes = SchemaChanges(
            new_tables=[NewTable("T1", "Table 1", 5)],
            new_columns=[NewColumn("T1", "c1", "string")],
        )
        classifier.add_pending_for_changes(changes)

        assert store.pending_count() == 2

    def test_empty_inputs_no_error(self) -> None:
        store = ClassificationStore()
        classifier = DataClassifier(store, "test", "default")
        assert classifier.classify_new_tables([]) == 0
        assert classifier.classify_new_columns([]) == 0
        assert classifier.classify_unmapped_accounts([], get_default_pl_structure()) == 0


class TestCatalogSnapshot:
    def test_get_schema_snapshot(self, catalog_store, fake_connector) -> None:
        schema = fake_connector.introspect_schema()
        catalog_store.save_schema(schema)

        tables, columns = catalog_store.get_schema_snapshot(
            schema.source_name, schema.profile_name
        )
        assert len(tables) > 0
        assert len(columns) > 0
        # Each table should have columns
        for t in tables:
            tname = t["table_name"]
            assert tname in columns
            assert len(columns[tname]) > 0

    def test_empty_snapshot(self, catalog_store) -> None:
        tables, columns = catalog_store.get_schema_snapshot("none", "none")
        assert tables == []
        assert columns == {}
