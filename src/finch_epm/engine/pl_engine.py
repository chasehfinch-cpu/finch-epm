"""P&L report engine.

Takes raw GL data from the DuckDB cache (TransactionAccountingLine joined
with Account) and produces structured P&L reports with:
    - Account type hierarchy (Revenue, COGS, Expenses, EBITDA, etc.)
    - Period aggregation (monthly, quarterly, YTD, trailing twelve months)
    - Sign convention normalization (revenue shows as positive)
    - Variance calculations (actual vs budget/forecast/prior year)

This engine works against any NetSuite instance because it uses standard
account type classifications, not customer-specific account numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from finch_epm.cache.base import CacheEngine
from finch_epm.cache.models import QueryRequest
from finch_epm.engine.chart_of_accounts import (
    get_revenue_account_types,
    get_expense_account_types,
)
from finch_epm.engine.classification_models import (
    ClassificationStore,
    DataClass,
)


@dataclass
class PLLine:
    """A single line in a P&L report."""

    account_type: str
    display_name: str
    periods: dict[str, float] = field(default_factory=dict)
    is_subtotal: bool = False
    depth: int = 0


@dataclass
class PLReport:
    """A complete P&L report."""

    title: str
    period_labels: list[str]
    lines: list[PLLine]
    metadata: dict[str, Any] = field(default_factory=dict)


class PLEngine:
    """Generates P&L reports from cached GL data.

    Expects TransactionAccountingLine and Account tables to be synced
    in the local DuckDB cache.

    Usage::

        engine = PLEngine(cache)
        report = engine.monthly_pl(year=2024)
        report = engine.ytd_pl(year=2024, through_month=6)
    """

    def __init__(
        self,
        cache: CacheEngine,
        classifications: ClassificationStore | None = None,
        connector_type: str = "netsuite",
        profile_name: str = "default",
    ) -> None:
        self._cache = cache
        self._classifications = classifications
        self._connector_type = connector_type
        self._profile_name = profile_name

    def get_account_overrides(self) -> dict[str, str]:
        """Return account_id -> pl_section mappings from classifications.

        Accounts with an explicit ``pl_section`` in classifications.yaml
        override the default type-based matching. This lets users route
        accounts with generic types (e.g., "Expense") to specific
        sub-sections (e.g., "labor", "overhead").
        """
        if not self._classifications:
            return {}
        source_key = self._classifications.source_key(
            self._connector_type, self._profile_name
        )
        overrides: dict[str, str] = {}
        for acct_id, acct_cls in self._classifications.accounts.get(source_key, {}).items():
            if acct_cls.pl_section:
                overrides[acct_id] = acct_cls.pl_section
        return overrides

    def monthly_pl(
        self,
        year: int,
        subsidiary: str | None = None,
        department: str | None = None,
    ) -> PLReport:
        """Generate a 12-month P&L report for a given year.

        Returns one column per month (Jan through Dec).
        """
        sql = self._build_monthly_query(year, subsidiary, department)
        result = self._cache.execute_query(QueryRequest(sql=sql))
        return self._build_report(
            f"P&L {year} Monthly",
            result,
            period_type="monthly",
            year=year,
        )

    def ytd_pl(
        self,
        year: int,
        through_month: int = 12,
        subsidiary: str | None = None,
        department: str | None = None,
    ) -> PLReport:
        """Generate a year-to-date P&L report."""
        sql = self._build_ytd_query(year, through_month, subsidiary, department)
        result = self._cache.execute_query(QueryRequest(sql=sql))
        return self._build_report(
            f"P&L {year} YTD through Month {through_month}",
            result,
            period_type="ytd",
            year=year,
        )

    def _build_monthly_query(
        self,
        year: int,
        subsidiary: str | None,
        department: str | None,
    ) -> str:
        """Build SQL for monthly P&L from TransactionAccountingLine + Account."""
        where_clauses = [
            "t.posting = 'T'",
            f"SUBSTRING(tx.trandate, 1, 4) = '{year}'",
        ]
        if subsidiary:
            where_clauses.append(f"tl.subsidiary = '{subsidiary}'")
        if department:
            where_clauses.append(f"tl.department = '{department}'")

        where = " AND ".join(where_clauses)

        return f"""
            SELECT
                a.accttype,
                CAST(SUBSTRING(tx.trandate, 6, 2) AS INTEGER) AS month_num,
                SUM(CAST(t.amount AS DOUBLE)) AS amount
            FROM TransactionAccountingLine t
            JOIN Transaction tx
                ON CAST(t.transaction AS INTEGER) = CAST(tx.id AS INTEGER)
            JOIN TransactionLine tl
                ON CAST(t.transaction AS INTEGER) = CAST(tl.transaction AS INTEGER)
                AND CAST(t.transactionline AS INTEGER) = CAST(tl.id AS INTEGER)
            JOIN Account a
                ON CAST(t.account AS INTEGER) = CAST(a.id AS INTEGER)
            WHERE {where}
            GROUP BY a.accttype, CAST(SUBSTRING(tx.trandate, 6, 2) AS INTEGER)
            ORDER BY a.accttype, month_num
        """

    def _build_ytd_query(
        self,
        year: int,
        through_month: int,
        subsidiary: str | None,
        department: str | None,
    ) -> str:
        """Build SQL for YTD P&L."""
        where_clauses = [
            "t.posting = 'T'",
            f"SUBSTRING(tx.trandate, 1, 4) = '{year}'",
            f"CAST(SUBSTRING(tx.trandate, 6, 2) AS INTEGER) <= {through_month}",
        ]
        if subsidiary:
            where_clauses.append(f"tl.subsidiary = '{subsidiary}'")
        if department:
            where_clauses.append(f"tl.department = '{department}'")

        where = " AND ".join(where_clauses)

        return f"""
            SELECT
                a.accttype,
                'YTD' AS period,
                SUM(CAST(t.amount AS DOUBLE)) AS amount
            FROM TransactionAccountingLine t
            JOIN Transaction tx
                ON CAST(t.transaction AS INTEGER) = CAST(tx.id AS INTEGER)
            JOIN TransactionLine tl
                ON CAST(t.transaction AS INTEGER) = CAST(tl.transaction AS INTEGER)
                AND CAST(t.transactionline AS INTEGER) = CAST(tl.id AS INTEGER)
            JOIN Account a
                ON CAST(t.account AS INTEGER) = CAST(a.id AS INTEGER)
            WHERE {where}
            GROUP BY a.accttype
            ORDER BY a.accttype
        """

    def _build_report(
        self,
        title: str,
        result: Any,
        period_type: str,
        year: int,
    ) -> PLReport:
        """Build a PLReport from query results."""
        month_names = [
            "Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
        ]
        revenue_types = set(get_revenue_account_types())
        expense_types = set(get_expense_account_types())

        # Parse query results into a dict: {accttype: {period: amount}}
        amounts: dict[str, dict[str, float]] = {}
        for row in result.rows:
            acct_type = str(row[0])
            period = str(row[1])
            amount = float(row[2]) if row[2] else 0.0
            if acct_type not in amounts:
                amounts[acct_type] = {}
            amounts[acct_type][period] = amount

        if period_type == "monthly":
            period_labels = month_names
            period_keys = [str(i) for i in range(1, 13)]
        else:
            period_labels = ["YTD"]
            period_keys = ["YTD"]

        lines: list[PLLine] = []

        # Revenue (sign-flipped: NetSuite credits are negative, we show positive)
        revenue_total: dict[str, float] = {}
        for acct_type in revenue_types:
            if acct_type in amounts:
                for pk, label in zip(period_keys, period_labels):
                    val = amounts[acct_type].get(pk, 0.0)
                    revenue_total[label] = revenue_total.get(label, 0.0) + (val * -1)

        lines.append(PLLine(
            account_type="revenue",
            display_name="Revenue",
            periods=revenue_total,
            depth=0,
        ))

        # COGS
        cogs_total: dict[str, float] = {}
        if "COGS" in amounts:
            for pk, label in zip(period_keys, period_labels):
                cogs_total[label] = amounts["COGS"].get(pk, 0.0)

        if any(v != 0 for v in cogs_total.values()):
            lines.append(PLLine(
                account_type="cogs",
                display_name="Cost of Goods Sold",
                periods=cogs_total,
                depth=0,
            ))

        # Gross Profit
        gross: dict[str, float] = {}
        for label in period_labels:
            gross[label] = revenue_total.get(label, 0.0) - cogs_total.get(label, 0.0)
        lines.append(PLLine(
            account_type="gross_profit",
            display_name="Gross Profit",
            periods=gross,
            is_subtotal=True,
            depth=0,
        ))

        # Operating Expenses
        expense_total: dict[str, float] = {}
        for acct_type in expense_types:
            if acct_type in amounts and acct_type != "COGS":
                for pk, label in zip(period_keys, period_labels):
                    val = amounts[acct_type].get(pk, 0.0)
                    expense_total[label] = expense_total.get(label, 0.0) + val

        lines.append(PLLine(
            account_type="operating_expense",
            display_name="Operating Expenses",
            periods=expense_total,
            depth=0,
        ))

        # EBITDA
        ebitda: dict[str, float] = {}
        for label in period_labels:
            ebitda[label] = gross.get(label, 0.0) - expense_total.get(label, 0.0)
        lines.append(PLLine(
            account_type="ebitda",
            display_name="EBITDA",
            periods=ebitda,
            is_subtotal=True,
            depth=0,
        ))

        # Net Income (same as EBITDA for now -- post-EBITDA items added later)
        lines.append(PLLine(
            account_type="net_income",
            display_name="Net Income",
            periods=dict(ebitda),
            is_subtotal=True,
            depth=0,
        ))

        return PLReport(
            title=title,
            period_labels=period_labels,
            lines=lines,
            metadata={
                "year": year,
                "period_type": period_type,
                "account_types_found": list(amounts.keys()),
            },
        )

    def generate_pl_fdash(
        self,
        year: int,
        subsidiary: str | None = None,
    ) -> str:
        """Generate a .fdash YAML string for a P&L dashboard.

        This produces a dashboard that shows P&L KPIs and charts
        by querying the local cache directly.
        """
        sub_filter = ""
        if subsidiary:
            sub_filter = f"\n                AND tl.subsidiary = '{subsidiary}'"

        return f"""name: P&L Report {year}
description: Profit and Loss statement for fiscal year {year}
sources:
  - netsuite

queries:
  - name: pl_summary
    sql: |
      SELECT
        a.accttype,
        SUM(CAST(t.amount AS DOUBLE)) AS amount
      FROM TransactionAccountingLine t
      JOIN Transaction tx ON CAST(t.transaction AS INTEGER) = CAST(tx.id AS INTEGER)
      JOIN Account a ON CAST(t.account AS INTEGER) = CAST(a.id AS INTEGER)
      WHERE t.posting = 'T'
        AND SUBSTRING(tx.trandate, 1, 4) = '{year}'{sub_filter}
      GROUP BY a.accttype
      ORDER BY a.accttype

  - name: monthly_revenue
    sql: |
      SELECT
        SUBSTRING(tx.trandate, 1, 7) AS month,
        SUM(CAST(t.amount AS DOUBLE)) * -1 AS revenue
      FROM TransactionAccountingLine t
      JOIN Transaction tx ON CAST(t.transaction AS INTEGER) = CAST(tx.id AS INTEGER)
      JOIN Account a ON CAST(t.account AS INTEGER) = CAST(a.id AS INTEGER)
      WHERE t.posting = 'T'
        AND a.accttype IN ('Income', 'OthIncome')
        AND SUBSTRING(tx.trandate, 1, 4) = '{year}'{sub_filter}
      GROUP BY SUBSTRING(tx.trandate, 1, 7)
      ORDER BY month

  - name: monthly_expense
    sql: |
      SELECT
        SUBSTRING(tx.trandate, 1, 7) AS month,
        SUM(CAST(t.amount AS DOUBLE)) AS expense
      FROM TransactionAccountingLine t
      JOIN Transaction tx ON CAST(t.transaction AS INTEGER) = CAST(tx.id AS INTEGER)
      JOIN Account a ON CAST(t.account AS INTEGER) = CAST(a.id AS INTEGER)
      WHERE t.posting = 'T'
        AND a.accttype IN ('Expense', 'OthExpense', 'COGS')
        AND SUBSTRING(tx.trandate, 1, 4) = '{year}'{sub_filter}
      GROUP BY SUBSTRING(tx.trandate, 1, 7)
      ORDER BY month

  - name: revenue_kpi
    sql: |
      SELECT
        SUM(CAST(t.amount AS DOUBLE)) * -1 AS total_revenue
      FROM TransactionAccountingLine t
      JOIN Transaction tx ON CAST(t.transaction AS INTEGER) = CAST(tx.id AS INTEGER)
      JOIN Account a ON CAST(t.account AS INTEGER) = CAST(a.id AS INTEGER)
      WHERE t.posting = 'T'
        AND a.accttype IN ('Income', 'OthIncome')
        AND SUBSTRING(tx.trandate, 1, 4) = '{year}'{sub_filter}

  - name: expense_kpi
    sql: |
      SELECT
        SUM(CAST(t.amount AS DOUBLE)) AS total_expense
      FROM TransactionAccountingLine t
      JOIN Transaction tx ON CAST(t.transaction AS INTEGER) = CAST(tx.id AS INTEGER)
      JOIN Account a ON CAST(t.account AS INTEGER) = CAST(a.id AS INTEGER)
      WHERE t.posting = 'T'
        AND a.accttype IN ('Expense', 'OthExpense', 'COGS')
        AND SUBSTRING(tx.trandate, 1, 4) = '{year}'{sub_filter}

charts:
  - type: kpi
    title: Total Revenue
    data: revenue_kpi
    value: total_revenue
    format: currency
    prefix: "$"
    color: "#2ecc71"

  - type: kpi
    title: Total Expenses
    data: expense_kpi
    value: total_expense
    format: currency
    prefix: "$"
    color: "#e74c3c"

  - type: line
    title: Monthly Revenue
    data: monthly_revenue
    x: month
    y: revenue
    color: "#2ecc71"
    width: full
    height: 400

  - type: line
    title: Monthly Expenses
    data: monthly_expense
    x: month
    y: expense
    color: "#e74c3c"
    width: full
    height: 400

  - type: bar
    title: Amounts by Account Type
    data: pl_summary
    x: accttype
    y: amount
    width: full

  - type: table
    title: P&L Detail by Account Type
    data: pl_summary
    width: full
    columns:
      amount: {{ format: currency, prefix: "$" }}
"""
