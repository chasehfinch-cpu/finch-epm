"""Chart of Accounts engine with unlimited hierarchy levels.

Users define their own P&L structure by mapping each account to a series
of rollup levels (level1 through levelN). The deepest level is the account
itself; each higher level aggregates accounts into categories, subtotals,
and section totals. The top level is always one of: Total Revenue,
Total Expense, or a custom top-level name.

Templates are sharable YAML files. A team member creates a COA template,
shares it, and others import it. finch-epm ships a default template that
works with standard NetSuite account types.

Usage:
    coa = ChartOfAccounts.load("coa.yaml")
    coa = ChartOfAccounts.from_accounts(account_rows)  # auto-generate
    tree = coa.build_pl_tree(gl_data)  # build the P&L hierarchy
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from finch_epm.paths import config_dir

logger = logging.getLogger(__name__)


@dataclass
class AccountMapping:
    """Maps a single account to its position in the P&L hierarchy.

    Levels are numbered from 1 (finest detail) upward. The number of
    levels is unlimited — a simple structure might use 2 levels, a
    complex one might use 6.
    """

    account_id: str
    account_name: str = ""
    levels: dict[str, str] = field(default_factory=dict)
    """Mapping of level name -> value. Example:
    {"level1": "Physician Salaries", "level2": "MD Comp",
     "level3": "Direct Labor", "level4": "Total Expense"}"""
    category: str = "undetermined"
    """One of: revenue, expense, below-the-line, statistical, undetermined"""
    sign_convention: int = 1
    """1 = normal (debit positive), -1 = flip (revenue shows positive)"""
    is_below_the_line: bool = False
    btl_sign: str = ""
    """For below-the-line items: "add" or "subtract" relative to EBITDA"""


@dataclass
class PLRow:
    """A single row in a rendered P&L report."""

    label: str
    depth: int
    amount: float = 0.0
    row_class: str = ""
    """CSS class: row-level5, row-level4, ..., row-account, row-ebitda, etc."""
    is_subtotal: bool = False
    is_account: bool = False
    account_id: str = ""
    children_labels: list[str] = field(default_factory=list)


class ChartOfAccounts:
    """User-defined chart of accounts with unlimited hierarchy levels.

    The COA maps each account to a set of named levels. Level names are
    user-defined (e.g., "level1", "level2", "level3", "level4" or
    "detail", "subcategory", "category", "section").

    Accounts are grouped by their level values to build the P&L tree.
    """

    def __init__(
        self,
        accounts: dict[str, AccountMapping] | None = None,
        level_names: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.accounts: dict[str, AccountMapping] = accounts or {}
        self.level_names: list[str] = level_names or []
        self.metadata: dict[str, Any] = metadata or {}

    # -- Persistence --------------------------------------------------------

    def save(self, path: Path | str | None = None) -> Path:
        """Save the COA to a YAML file."""
        path = Path(path) if path else _default_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {
            "version": 1,
            "level_names": self.level_names,
            "metadata": self.metadata,
            "accounts": {},
        }
        for aid, mapping in sorted(self.accounts.items()):
            entry: dict[str, Any] = {"name": mapping.account_name}
            for lname in self.level_names:
                entry[lname] = mapping.levels.get(lname, "")
            entry["category"] = mapping.category
            if mapping.sign_convention != 1:
                entry["sign_convention"] = mapping.sign_convention
            if mapping.is_below_the_line:
                entry["is_below_the_line"] = True
                entry["btl_sign"] = mapping.btl_sign
            data["accounts"][aid] = entry

        path.write_text(
            yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, path: Path | str | None = None) -> ChartOfAccounts:
        """Load a COA from a YAML file."""
        path = Path(path) if path else _default_path()
        if not path.exists():
            return cls()

        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return cls()

        level_names = raw.get("level_names", [])
        metadata = raw.get("metadata", {})
        accounts: dict[str, AccountMapping] = {}

        for aid, entry in raw.get("accounts", {}).items():
            aid = str(aid)
            levels = {ln: entry.get(ln, "") for ln in level_names}
            accounts[aid] = AccountMapping(
                account_id=aid,
                account_name=entry.get("name", ""),
                levels=levels,
                category=entry.get("category", "undetermined"),
                sign_convention=entry.get("sign_convention", 1),
                is_below_the_line=entry.get("is_below_the_line", False),
                btl_sign=entry.get("btl_sign", ""),
            )

        return cls(accounts=accounts, level_names=level_names, metadata=metadata)

    @classmethod
    def from_json(cls, path: Path | str) -> ChartOfAccounts:
        """Import a COA from a JSON file (e.g., ECP-style chart-of-accounts.json).

        Expects format: {"account_id": {"name": "...", "level1": "...", ...}}
        Auto-detects level names from keys starting with "level".
        """
        path = Path(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Expected a JSON object, got {type(raw).__name__}")

        # Auto-detect level names from the first entry
        level_names: list[str] = []
        for entry in raw.values():
            if isinstance(entry, dict):
                level_names = sorted(
                    [k for k in entry.keys() if k.startswith("level")],
                    key=lambda x: int(x.replace("level", "") or "0"),
                )
                break

        accounts: dict[str, AccountMapping] = {}
        for aid, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            aid = str(aid)
            levels = {ln: entry.get(ln, "") for ln in level_names}
            category = entry.get("category", "undetermined")
            accounts[aid] = AccountMapping(
                account_id=aid,
                account_name=entry.get("name", entry.get("id", "")),
                levels=levels,
                category=category,
                sign_convention=-1 if category == "revenue" else 1,
                is_below_the_line=entry.get("isBelowTheLine", False),
                btl_sign=entry.get("btlSign", ""),
            )

        return cls(
            accounts=accounts,
            level_names=level_names,
            metadata={"imported_from": str(path)},
        )

    @classmethod
    def from_csv(cls, path: Path | str) -> ChartOfAccounts:
        """Import a COA from a CSV file.

        Expected columns: account_id, name, level1, level2, ..., category
        Level columns are auto-detected (any column starting with "level").
        """
        import csv

        path = Path(path)
        with open(path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise ValueError("CSV has no header row")

            level_names = sorted(
                [c for c in reader.fieldnames if c.startswith("level")],
                key=lambda x: int(x.replace("level", "") or "0"),
            )

            accounts: dict[str, AccountMapping] = {}
            for row in reader:
                aid = str(row.get("account_id", row.get("id", ""))).strip()
                if not aid:
                    continue
                levels = {ln: row.get(ln, "").strip() for ln in level_names}
                category = row.get("category", "undetermined").strip()
                accounts[aid] = AccountMapping(
                    account_id=aid,
                    account_name=row.get("name", "").strip(),
                    levels=levels,
                    category=category,
                    sign_convention=-1 if category == "revenue" else 1,
                    is_below_the_line=row.get("is_below_the_line", "").lower() in ("true", "1", "yes"),
                    btl_sign=row.get("btl_sign", ""),
                )

        return cls(
            accounts=accounts,
            level_names=level_names,
            metadata={"imported_from": str(path)},
        )

    # -- Auto-generation ----------------------------------------------------

    @classmethod
    def from_accounts(
        cls,
        account_rows: list[dict[str, Any]],
        level_names: list[str] | None = None,
    ) -> ChartOfAccounts:
        """Auto-generate a COA from cached Account table data.

        Groups accounts by their ``accttype`` field into a sensible
        default hierarchy. Users should customize this after generation.

        Args:
            account_rows: Rows from the Account table. Each row should have
                at least ``id``, ``acctnumber``, ``accttype``, ``fullname``.
            level_names: Custom level names. Defaults to
                ["level1", "level2", "level3", "level4"].
        """
        if level_names is None:
            level_names = ["level1", "level2", "level3", "level4"]

        # Map NetSuite account types to default P&L categories
        type_to_category = {
            "Income": ("revenue", "Net Revenue", "Net Revenue", "Total Revenue"),
            "OthIncome": ("revenue", "Other Income", "Other Income", "Total Revenue"),
            "COGS": ("expense", "Cost of Goods Sold", "Cost of Goods Sold", "Total Expense"),
            "Expense": ("expense", "Operating Expenses", "Operating Expenses", "Total Expense"),
            "OthExpense": ("expense", "Other Expenses", "Other Expenses", "Total Expense"),
            "DeferExpense": ("expense", "Depreciation & Amortization", "Depreciation & Amortization", "Total Expense"),
        }

        # Non-P&L types
        non_pl_types = {
            "Bank", "AcctRec", "AcctPay", "OthCurrAsset", "OthCurrLiab",
            "FixedAsset", "OthAsset", "LongTermLiab", "Equity",
            "Stat", "NonPosting",
        }

        accounts: dict[str, AccountMapping] = {}

        for row in account_rows:
            aid = str(row.get("id", row.get("acctnumber", "")))
            acct_type = str(row.get("accttype", ""))
            acct_name = str(row.get("fullname", row.get("name", "")))
            acct_number = str(row.get("acctnumber", ""))

            if acct_type in type_to_category:
                category, l1_default, l2_default, l3_default = type_to_category[acct_type]
                # Use the account name as level1 (finest grain)
                levels = {}
                if len(level_names) >= 4:
                    levels[level_names[0]] = acct_name or acct_type
                    levels[level_names[1]] = l1_default
                    levels[level_names[2]] = l2_default
                    levels[level_names[3]] = l3_default
                elif len(level_names) >= 2:
                    levels[level_names[0]] = acct_name or acct_type
                    levels[level_names[-1]] = l3_default
                elif len(level_names) == 1:
                    levels[level_names[0]] = l3_default

                accounts[aid] = AccountMapping(
                    account_id=aid,
                    account_name=acct_name,
                    levels=levels,
                    category=category,
                    sign_convention=-1 if category == "revenue" else 1,
                )
            elif acct_type in non_pl_types:
                levels = {ln: "" for ln in level_names}
                if level_names:
                    levels[level_names[0]] = acct_name or acct_type
                accounts[aid] = AccountMapping(
                    account_id=aid,
                    account_name=acct_name,
                    levels=levels,
                    category="statistical" if acct_type == "Stat" else "undetermined",
                )
            else:
                levels = {ln: "" for ln in level_names}
                if level_names:
                    levels[level_names[0]] = acct_name or acct_type
                accounts[aid] = AccountMapping(
                    account_id=aid,
                    account_name=acct_name,
                    levels=levels,
                    category="undetermined",
                )

        return cls(
            accounts=accounts,
            level_names=level_names,
            metadata={"auto_generated": True},
        )

    # -- Query methods ------------------------------------------------------

    def get_account(self, account_id: str) -> AccountMapping | None:
        return self.accounts.get(str(account_id))

    def find_unmapped(self) -> list[AccountMapping]:
        """Return accounts with category 'undetermined'."""
        return [a for a in self.accounts.values() if a.category == "undetermined"]

    def count_by_category(self) -> dict[str, int]:
        """Count accounts by category."""
        counts: dict[str, int] = defaultdict(int)
        for a in self.accounts.values():
            counts[a.category] += 1
        return dict(counts)

    def get_pl_accounts(self) -> list[AccountMapping]:
        """Return only revenue and expense accounts."""
        return [
            a for a in self.accounts.values()
            if a.category in ("revenue", "expense")
        ]

    # -- P&L tree building --------------------------------------------------

    def build_pl_tree(
        self,
        gl_data: dict[str, float],
    ) -> list[PLRow]:
        """Build a P&L report tree from GL data.

        Args:
            gl_data: Mapping of account_id -> amount (from GL aggregation).

        Returns:
            Ordered list of PLRow objects representing the P&L statement.
        """
        if not self.level_names or len(self.level_names) < 2:
            return self._build_simple_pl(gl_data)

        rows: list[PLRow] = []
        top_level = self.level_names[-1]  # e.g., "level4" = Total Revenue / Total Expense

        # Group accounts by top-level category
        revenue_accounts = [
            a for a in self.accounts.values()
            if a.category == "revenue" and str(a.account_id) in gl_data
        ]
        expense_accounts = [
            a for a in self.accounts.values()
            if a.category == "expense" and str(a.account_id) in gl_data
        ]
        btl_accounts = [
            a for a in self.accounts.values()
            if a.is_below_the_line and str(a.account_id) in gl_data
        ]

        # Build revenue section
        rev_total = 0.0
        if revenue_accounts:
            rev_rows, rev_total = self._build_section(
                revenue_accounts, gl_data, "Total Revenue", "row-level5", 0
            )
            rows.extend(rev_rows)

        # Build expense section
        exp_total = 0.0
        if expense_accounts:
            exp_rows, exp_total = self._build_section(
                expense_accounts, gl_data, "Total Expense", "row-level5", 0
            )
            rows.extend(exp_rows)

        # EBITDA
        ebitda = rev_total - exp_total
        rows.append(PLRow(
            label="EBITDA",
            depth=0,
            amount=ebitda,
            row_class="row-ebitda",
            is_subtotal=True,
        ))

        # Below-the-line items
        net = ebitda
        for acct in btl_accounts:
            amount = gl_data.get(str(acct.account_id), 0.0)
            if acct.btl_sign == "subtract":
                net -= abs(amount)
            else:
                net += amount
            rows.append(PLRow(
                label=acct.account_name,
                depth=1,
                amount=amount,
                row_class="row-account",
                is_account=True,
                account_id=acct.account_id,
            ))

        # Net Income
        if btl_accounts:
            rows.append(PLRow(
                label="Net Income",
                depth=0,
                amount=net,
                row_class="row-netincome",
                is_subtotal=True,
            ))

        return rows

    def _build_section(
        self,
        accounts: list[AccountMapping],
        gl_data: dict[str, float],
        section_label: str,
        section_class: str,
        base_depth: int,
    ) -> tuple[list[PLRow], float]:
        """Build a hierarchical section (Revenue or Expense) from levels.

        Groups accounts by their level values from the second-highest level
        down, creating nested subtotals.
        """
        rows: list[PLRow] = []
        total = 0.0

        # Work through levels from highest to lowest
        # e.g., level_names = [level1, level2, level3, level4]
        # We group by level3 (second from top), then level2, then level1
        inner_levels = self.level_names[:-1]  # All except the top level

        if len(inner_levels) >= 1:
            # Group by the second-highest level
            group_level = inner_levels[-1]  # e.g., level3
            groups: dict[str, list[AccountMapping]] = defaultdict(list)
            for acct in accounts:
                group_key = acct.levels.get(group_level, "Other")
                groups[group_key].append(acct)

            row_classes = ["row-level4", "row-level3", "row-level2", "row-level1"]

            for group_name, group_accounts in groups.items():
                group_total = sum(
                    gl_data.get(str(a.account_id), 0.0) * a.sign_convention
                    for a in group_accounts
                )
                total += group_total

                # Group header
                depth = base_depth + 1
                cls_idx = min(depth, len(row_classes)) - 1
                rows.append(PLRow(
                    label=group_name,
                    depth=depth,
                    amount=group_total,
                    row_class=row_classes[cls_idx] if cls_idx >= 0 else "row-level1",
                    is_subtotal=True,
                ))

                # Recurse into sub-levels if there are more
                if len(inner_levels) >= 2:
                    sub_level = inner_levels[-2]  # e.g., level2
                    sub_groups: dict[str, list[AccountMapping]] = defaultdict(list)
                    for acct in group_accounts:
                        sub_key = acct.levels.get(sub_level, acct.account_name)
                        sub_groups[sub_key].append(acct)

                    for sub_name, sub_accounts in sub_groups.items():
                        sub_total = sum(
                            gl_data.get(str(a.account_id), 0.0) * a.sign_convention
                            for a in sub_accounts
                        )
                        if sub_name != group_name:  # Avoid duplicate labels
                            rows.append(PLRow(
                                label=sub_name,
                                depth=depth + 1,
                                amount=sub_total,
                                row_class=row_classes[min(depth, len(row_classes) - 1)],
                                is_subtotal=True,
                            ))

                        # Individual accounts
                        for acct in sub_accounts:
                            amt = gl_data.get(str(acct.account_id), 0.0) * acct.sign_convention
                            rows.append(PLRow(
                                label=acct.account_name,
                                depth=depth + 2,
                                amount=amt,
                                row_class="row-account",
                                is_account=True,
                                account_id=acct.account_id,
                            ))
                else:
                    # No sub-levels — just list accounts
                    for acct in group_accounts:
                        amt = gl_data.get(str(acct.account_id), 0.0) * acct.sign_convention
                        rows.append(PLRow(
                            label=acct.account_name,
                            depth=depth + 1,
                            amount=amt,
                            row_class="row-account",
                            is_account=True,
                            account_id=acct.account_id,
                        ))

        # Section total
        rows.insert(0, PLRow(
            label=section_label,
            depth=base_depth,
            amount=total,
            row_class=section_class,
            is_subtotal=True,
        ))

        return rows, total

    def _build_simple_pl(self, gl_data: dict[str, float]) -> list[PLRow]:
        """Fallback: simple P&L with no hierarchy (just revenue/expense totals)."""
        rows: list[PLRow] = []
        rev = sum(
            gl_data.get(str(a.account_id), 0.0) * a.sign_convention
            for a in self.accounts.values() if a.category == "revenue"
        )
        exp = sum(
            gl_data.get(str(a.account_id), 0.0) * a.sign_convention
            for a in self.accounts.values() if a.category == "expense"
        )
        rows.append(PLRow(label="Total Revenue", depth=0, amount=rev, row_class="row-level5", is_subtotal=True))
        rows.append(PLRow(label="Total Expense", depth=0, amount=exp, row_class="row-level5", is_subtotal=True))
        rows.append(PLRow(label="EBITDA", depth=0, amount=rev - exp, row_class="row-ebitda", is_subtotal=True))
        return rows


def _default_path() -> Path:
    return config_dir() / "coa.yaml"
