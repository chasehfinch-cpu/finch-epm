"""Chart of accounts hierarchy for P&L reporting.

Defines the standard P&L structure: Revenue -> Expenses -> EBITDA ->
Post-EBITDA -> Net Income. Each section contains account type filters
that match NetSuite's accttype values.

This structure is generic -- it works for any NetSuite instance because
it maps against standard NetSuite account types, not specific account
numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PLSection:
    """A section in the P&L hierarchy."""

    name: str
    display_name: str
    account_types: list[str] = field(default_factory=list)
    children: list[PLSection] = field(default_factory=list)
    is_subtotal: bool = False
    sign_convention: int = 1
    """1 = normal (expense positive), -1 = flip (revenue shows as positive)."""


# Standard P&L structure matching NetSuite account types
STANDARD_PL = PLSection(
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
            sign_convention=1,
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
            sign_convention=1,
        ),
        PLSection(
            name="ebitda",
            display_name="EBITDA",
            is_subtotal=True,
        ),
        PLSection(
            name="depreciation_amortization",
            display_name="Depreciation & Amortization",
            account_types=["DeferExpense"],
            sign_convention=1,
        ),
        PLSection(
            name="other_income_expense",
            display_name="Other Income / Expense",
            account_types=["OthCurrLiab", "LongTermLiab"],
            sign_convention=1,
        ),
    ],
)


def get_pl_structure() -> PLSection:
    """Return the standard P&L section hierarchy."""
    return STANDARD_PL


def get_revenue_account_types() -> list[str]:
    """Return account types that are considered revenue.

    Revenue in NetSuite is negative (credit). The P&L engine flips the
    sign so revenue displays as positive in reports.
    """
    return ["Income", "OthIncome"]


def get_expense_account_types() -> list[str]:
    """Return account types that are considered expenses."""
    return ["Expense", "OthExpense", "COGS", "DeferExpense"]


def get_all_pl_account_types() -> list[str]:
    """Return all account types that appear in a P&L report."""
    return [
        "Income", "OthIncome", "COGS", "Expense", "OthExpense",
        "DeferExpense", "OthCurrLiab", "LongTermLiab",
    ]
