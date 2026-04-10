"""Chart of accounts hierarchy for P&L reporting.

The P&L structure is user-configurable. Users define their own hierarchy
in a YAML file that maps NetSuite account types (or specific account
number ranges) to P&L sections. A default structure ships with finch-epm
that works for most companies.

This design ensures the P&L engine is not locked to any single company's
accounting structure. Different businesses can define different section
hierarchies, subtotal lines, and account groupings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class PLSection:
    """A section in the P&L hierarchy.

    Sections can match accounts by:
        - account_types: NetSuite account type names (Income, Expense, etc.)
        - account_numbers: specific account number prefixes (e.g., "8100" for labor)
        - account_names: substring matches on account names

    These filters are additive -- an account matches if it matches any filter.
    """

    name: str
    display_name: str
    account_types: list[str] = field(default_factory=list)
    account_numbers: list[str] = field(default_factory=list)
    account_names: list[str] = field(default_factory=list)
    children: list[PLSection] = field(default_factory=list)
    is_subtotal: bool = False
    sign_convention: int = 1
    """1 = normal (debit positive), -1 = flip sign (shows revenue as positive)."""


# Default P&L structure that works for any NetSuite instance.
# Maps against standard NetSuite account types, not specific account numbers.
DEFAULT_PL = PLSection(
    name="net_income",
    display_name="Net Income",
    is_subtotal=True,
    children=[
        PLSection(
            name="revenue",
            display_name="Revenue",
            account_types=["Income", "OthIncome"],
            sign_convention=-1,
        ),
        PLSection(
            name="cogs",
            display_name="Cost of Goods Sold",
            account_types=["COGS"],
        ),
        PLSection(
            name="gross_profit",
            display_name="Gross Profit",
            is_subtotal=True,
        ),
        PLSection(
            name="operating_expense",
            display_name="Operating Expenses",
            account_types=["Expense", "OthExpense"],
        ),
        PLSection(
            name="ebitda",
            display_name="EBITDA",
            is_subtotal=True,
        ),
        PLSection(
            name="depreciation",
            display_name="Depreciation and Amortization",
            account_types=["DeferExpense"],
        ),
        PLSection(
            name="other",
            display_name="Other Income / Expense",
            account_types=["OthCurrLiab", "LongTermLiab"],
        ),
    ],
)


def get_default_pl_structure() -> PLSection:
    """Return the default P&L structure that works for any NetSuite instance."""
    return DEFAULT_PL


def load_pl_structure(path: str | Path) -> PLSection:
    """Load a custom P&L structure from a YAML file.

    The YAML format mirrors the PLSection dataclass::

        name: net_income
        display_name: Net Income
        is_subtotal: true
        children:
          - name: revenue
            display_name: Revenue
            account_types: [Income, OthIncome]
            sign_convention: -1
          - name: direct_expense
            display_name: Direct Expenses
            account_types: [Expense]
            account_numbers: ["6000", "6100", "6200"]
          - name: gross_margin
            display_name: Gross Margin
            is_subtotal: true
          - name: overhead
            display_name: Overhead
            account_types: [Expense]
            account_numbers: ["7000", "7100", "7200"]
          - name: labor
            display_name: Labor
            account_types: [Expense]
            account_numbers: ["8100", "8200"]
            children:
              - name: physician_labor
                display_name: Physician Labor
                account_numbers: ["8100"]
              - name: app_labor
                display_name: APP Labor
                account_numbers: ["8200"]
          - name: ebitda
            display_name: EBITDA
            is_subtotal: true

    Args:
        path: Path to the YAML file.

    Returns:
        The root PLSection parsed from the file.
    """
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return _parse_section(raw)


def save_pl_structure(structure: PLSection, path: str | Path) -> None:
    """Save a P&L structure to a YAML file."""
    path = Path(path)
    raw = _serialize_section(structure)
    path.write_text(yaml.dump(raw, default_flow_style=False, sort_keys=False), encoding="utf-8")


def _parse_section(raw: dict[str, Any]) -> PLSection:
    """Recursively parse a PLSection from a raw YAML dict."""
    children = [_parse_section(c) for c in raw.get("children", [])]
    return PLSection(
        name=raw.get("name", ""),
        display_name=raw.get("display_name", raw.get("name", "")),
        account_types=raw.get("account_types", []),
        account_numbers=raw.get("account_numbers", []),
        account_names=raw.get("account_names", []),
        children=children,
        is_subtotal=raw.get("is_subtotal", False),
        sign_convention=raw.get("sign_convention", 1),
    )


def _serialize_section(section: PLSection) -> dict[str, Any]:
    """Recursively serialize a PLSection to a dict for YAML output."""
    d: dict[str, Any] = {
        "name": section.name,
        "display_name": section.display_name,
    }
    if section.account_types:
        d["account_types"] = section.account_types
    if section.account_numbers:
        d["account_numbers"] = section.account_numbers
    if section.account_names:
        d["account_names"] = section.account_names
    if section.is_subtotal:
        d["is_subtotal"] = True
    if section.sign_convention != 1:
        d["sign_convention"] = section.sign_convention
    if section.children:
        d["children"] = [_serialize_section(c) for c in section.children]
    return d


def get_revenue_account_types() -> list[str]:
    """Account types considered revenue in the default structure."""
    return ["Income", "OthIncome"]


def get_expense_account_types() -> list[str]:
    """Account types considered expenses in the default structure."""
    return ["Expense", "OthExpense", "COGS", "DeferExpense"]
