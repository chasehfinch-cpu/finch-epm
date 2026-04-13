"""Data classification models for schema change tracking.

Every table, column, and account in the catalog can be classified into
a data category. Classifications persist between sessions and feed into
the P&L engine (account routing), the LLM prompt builder (context), and
dashboard warnings (unclassified item alerts).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from finch_epm.paths import config_dir


class DataClass(Enum):
    """Top-level data classification for tables, columns, and accounts."""

    # Financial sub-classes
    PL_REVENUE = "pl_revenue"
    PL_EXPENSE = "pl_expense"
    PL_COGS = "pl_cogs"
    PL_OTHER = "pl_other"
    BALANCE_SHEET = "balance_sheet"
    CASH_FLOW = "cash_flow"
    FINANCIAL_OTHER = "financial_other"

    # Non-financial classes
    STATISTICAL = "statistical"
    OPERATIONAL = "operational"
    QUALITATIVE = "qualitative"
    UNDETERMINED = "undetermined"

    @property
    def is_financial(self) -> bool:
        return self in (
            DataClass.PL_REVENUE, DataClass.PL_EXPENSE, DataClass.PL_COGS,
            DataClass.PL_OTHER, DataClass.BALANCE_SHEET, DataClass.CASH_FLOW,
            DataClass.FINANCIAL_OTHER,
        )

    @property
    def display_name(self) -> str:
        _NAMES = {
            "pl_revenue": "Financial > P&L Revenue",
            "pl_expense": "Financial > P&L Expense",
            "pl_cogs": "Financial > Cost of Goods Sold",
            "pl_other": "Financial > Other P&L",
            "balance_sheet": "Financial > Balance Sheet",
            "cash_flow": "Financial > Cash Flow",
            "financial_other": "Financial > Other",
            "statistical": "Statistical",
            "operational": "Operational",
            "qualitative": "Qualitative",
            "undetermined": "Undetermined",
        }
        return _NAMES.get(self.value, self.value)


# Top-level groupings for interactive prompts
DATA_CLASS_GROUPS = {
    "financial": [
        DataClass.PL_REVENUE, DataClass.PL_EXPENSE, DataClass.PL_COGS,
        DataClass.PL_OTHER, DataClass.BALANCE_SHEET, DataClass.CASH_FLOW,
        DataClass.FINANCIAL_OTHER,
    ],
    "statistical": [DataClass.STATISTICAL],
    "operational": [DataClass.OPERATIONAL],
    "qualitative": [DataClass.QUALITATIVE],
    "undetermined": [DataClass.UNDETERMINED],
}


@dataclass
class TableClassification:
    """Classification metadata for a table."""

    data_class: DataClass = DataClass.UNDETERMINED
    notes: str = ""
    classified_at: str = ""


@dataclass
class ColumnClassification:
    """Classification metadata for a column."""

    data_class: DataClass = DataClass.UNDETERMINED
    pl_section: str = ""
    notes: str = ""


@dataclass
class AccountClassification:
    """Classification for a specific GL account (by account number or ID)."""

    display_name: str = ""
    data_class: DataClass = DataClass.UNDETERMINED
    pl_section: str = ""
    classified_at: str = ""
    notes: str = ""


@dataclass
class PendingItem:
    """An item detected during crawl/sync that needs user classification."""

    source: str  # "connector_type/profile_name"
    item_type: str  # "table", "column", "account"
    identifier: str  # table name, "table.column", or account number
    display_name: str = ""
    detected_at: str = ""
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class ClassificationStore:
    """Persistent storage for all data classifications.

    Reads and writes ``classifications.yaml`` in the user's config directory.
    """

    tables: dict[str, dict[str, TableClassification]] = field(default_factory=dict)
    """source_key -> table_name -> classification"""

    columns: dict[str, dict[str, dict[str, ColumnClassification]]] = field(
        default_factory=dict
    )
    """source_key -> table_name -> column_name -> classification"""

    accounts: dict[str, dict[str, AccountClassification]] = field(default_factory=dict)
    """source_key -> account_id -> classification"""

    pending: list[PendingItem] = field(default_factory=list)
    """Items awaiting user classification."""

    def source_key(self, connector_type: str, profile_name: str) -> str:
        return f"{connector_type}/{profile_name}"

    # -- Table classification ---

    def get_table_class(
        self, connector_type: str, profile_name: str, table_name: str
    ) -> TableClassification:
        key = self.source_key(connector_type, profile_name)
        return self.tables.get(key, {}).get(table_name, TableClassification())

    def set_table_class(
        self,
        connector_type: str,
        profile_name: str,
        table_name: str,
        classification: TableClassification,
    ) -> None:
        key = self.source_key(connector_type, profile_name)
        if key not in self.tables:
            self.tables[key] = {}
        self.tables[key][table_name] = classification

    # -- Column classification ---

    def get_column_class(
        self, connector_type: str, profile_name: str, table_name: str, column_name: str
    ) -> ColumnClassification:
        key = self.source_key(connector_type, profile_name)
        return self.columns.get(key, {}).get(table_name, {}).get(
            column_name, ColumnClassification()
        )

    def set_column_class(
        self,
        connector_type: str,
        profile_name: str,
        table_name: str,
        column_name: str,
        classification: ColumnClassification,
    ) -> None:
        key = self.source_key(connector_type, profile_name)
        if key not in self.columns:
            self.columns[key] = {}
        if table_name not in self.columns[key]:
            self.columns[key][table_name] = {}
        self.columns[key][table_name][column_name] = classification

    # -- Account classification ---

    def get_account_class(
        self, connector_type: str, profile_name: str, account_id: str
    ) -> AccountClassification:
        key = self.source_key(connector_type, profile_name)
        return self.accounts.get(key, {}).get(account_id, AccountClassification())

    def set_account_class(
        self,
        connector_type: str,
        profile_name: str,
        account_id: str,
        classification: AccountClassification,
    ) -> None:
        key = self.source_key(connector_type, profile_name)
        if key not in self.accounts:
            self.accounts[key] = {}
        self.accounts[key][account_id] = classification

    # -- Pending items ---

    def add_pending(self, item: PendingItem) -> None:
        # Avoid duplicates
        for existing in self.pending:
            if (existing.source == item.source
                    and existing.item_type == item.item_type
                    and existing.identifier == item.identifier):
                return
        self.pending.append(item)

    def remove_pending(self, source: str, item_type: str, identifier: str) -> None:
        self.pending = [
            p for p in self.pending
            if not (p.source == source and p.item_type == item_type
                    and p.identifier == identifier)
        ]

    def pending_count(self) -> int:
        return len(self.pending)

    # -- Persistence ---

    def save(self, path: Path | None = None) -> None:
        path = path or _default_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {"version": 1}

        # Tables
        if self.tables:
            data["tables"] = {}
            for src_key, tables in self.tables.items():
                data["tables"][src_key] = {
                    tname: _table_to_dict(tc) for tname, tc in tables.items()
                }

        # Columns
        if self.columns:
            data["columns"] = {}
            for src_key, tables in self.columns.items():
                data["columns"][src_key] = {}
                for tname, cols in tables.items():
                    data["columns"][src_key][tname] = {
                        cname: _column_to_dict(cc) for cname, cc in cols.items()
                    }

        # Accounts
        if self.accounts:
            data["accounts"] = {}
            for src_key, accts in self.accounts.items():
                data["accounts"][src_key] = {
                    aid: _account_to_dict(ac) for aid, ac in accts.items()
                }

        # Pending
        if self.pending:
            data["pending"] = [
                {
                    "source": p.source,
                    "item_type": p.item_type,
                    "identifier": p.identifier,
                    "display_name": p.display_name,
                    "detected_at": p.detected_at,
                }
                for p in self.pending
            ]

        path.write_text(
            yaml.dump(data, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path | None = None) -> ClassificationStore:
        path = path or _default_path()
        if not path.exists():
            return cls()

        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return cls()

        store = cls()

        # Tables
        for src_key, tables in raw.get("tables", {}).items():
            store.tables[src_key] = {}
            for tname, tdata in tables.items():
                store.tables[src_key][tname] = TableClassification(
                    data_class=DataClass(tdata.get("data_class", "undetermined")),
                    notes=tdata.get("notes", ""),
                    classified_at=tdata.get("classified_at", ""),
                )

        # Columns
        for src_key, tables in raw.get("columns", {}).items():
            store.columns[src_key] = {}
            for tname, cols in tables.items():
                store.columns[src_key][tname] = {}
                for cname, cdata in cols.items():
                    store.columns[src_key][tname][cname] = ColumnClassification(
                        data_class=DataClass(cdata.get("data_class", "undetermined")),
                        pl_section=cdata.get("pl_section", ""),
                        notes=cdata.get("notes", ""),
                    )

        # Accounts
        for src_key, accts in raw.get("accounts", {}).items():
            store.accounts[src_key] = {}
            for aid, adata in accts.items():
                store.accounts[src_key][str(aid)] = AccountClassification(
                    display_name=adata.get("display_name", ""),
                    data_class=DataClass(adata.get("data_class", "undetermined")),
                    pl_section=adata.get("pl_section", ""),
                    classified_at=adata.get("classified_at", ""),
                    notes=adata.get("notes", ""),
                )

        # Pending
        for pdata in raw.get("pending", []):
            store.pending.append(PendingItem(
                source=pdata.get("source", ""),
                item_type=pdata.get("item_type", ""),
                identifier=str(pdata.get("identifier", "")),
                display_name=pdata.get("display_name", ""),
                detected_at=pdata.get("detected_at", ""),
            ))

        return store


def _default_path() -> Path:
    return config_dir() / "classifications.yaml"


def _table_to_dict(tc: TableClassification) -> dict[str, Any]:
    d: dict[str, Any] = {"data_class": tc.data_class.value}
    if tc.notes:
        d["notes"] = tc.notes
    if tc.classified_at:
        d["classified_at"] = tc.classified_at
    return d


def _column_to_dict(cc: ColumnClassification) -> dict[str, Any]:
    d: dict[str, Any] = {"data_class": cc.data_class.value}
    if cc.pl_section:
        d["pl_section"] = cc.pl_section
    if cc.notes:
        d["notes"] = cc.notes
    return d


def _account_to_dict(ac: AccountClassification) -> dict[str, Any]:
    d: dict[str, Any] = {"data_class": ac.data_class.value}
    if ac.display_name:
        d["display_name"] = ac.display_name
    if ac.pl_section:
        d["pl_section"] = ac.pl_section
    if ac.classified_at:
        d["classified_at"] = ac.classified_at
    if ac.notes:
        d["notes"] = ac.notes
    return d
