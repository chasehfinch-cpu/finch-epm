# finch-epm Dashboard Specification

This document is the complete reference for the `.fdash` dashboard file format. It is designed to be read by both humans and AI assistants. If you paste this document into ChatGPT, Claude, or any other AI and ask it to generate a dashboard, the output should be a valid `.fdash` file.

## File format

A `.fdash` file is YAML with the `.fdash` extension. It defines queries against locally cached data and charts that visualize the results. Dashboards contain no data and no credentials -- they are portable files that render against whichever data the user has synced.

## Top-level structure

```yaml
name: <string, required>
description: <string, optional>
sources:                          # informational -- tells users which connections are needed
  - netsuite/production           # connector_type/profile_name
  - sqlserver/azure_pemmdw        # multiple sources supported
  - postgres                      # profile defaults to connector name if not specified

queries:
  - name: <string>
    sql: |
      <DuckDB SQL>

parameters:
  <name>:
    type: <string>
    default: <value>

charts:
  - type: <chart type>
    title: <string>
    data: <query name>
    <chart-specific fields>
```

## Queries

Each query has a `name` (referenced by charts) and `sql` (DuckDB SQL dialect). SQL runs against the local DuckDB cache, not against the source system.

Column names in the SQL SELECT clause become the column names available to charts. Use aliases to control names:

```yaml
queries:
  - name: revenue_by_site
    sql: |
      SELECT
        subsidiary AS site,
        SUM(amount) AS revenue,
        COUNT(*) AS transaction_count
      FROM TransactionAccountingLine
      WHERE accounttype = 'Income'
      GROUP BY subsidiary
      ORDER BY revenue DESC
```

### Parameter substitution

Use `:param_name` syntax in SQL. Parameters are replaced with their resolved values before execution:

```yaml
queries:
  - name: filtered
    sql: |
      SELECT * FROM Account
      WHERE accttype = :account_type

parameters:
  account_type:
    type: string
    default: "Expense"
```

### Parameter types

| Type | Description | Symbolic defaults |
|------|-------------|-------------------|
| string | Any text value | None |
| number | Numeric value | None |
| period | Date that resolves symbolic names | today, current_month_start, current_month_end, current_quarter_start, current_quarter_end, current_year_start, current_year_end |

## Chart types

Every chart requires `type`, `title`, and `data` (the query name to pull data from). All charts accept these optional fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| height | integer | 360 | Chart height in pixels |
| width | string | "half" | Card width: "full" (100%) or "half" (50%) |

### bar

Bar chart. Supports single or multiple Y series.

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| x | yes | string | Column for X axis categories |
| y | yes | string or list | Column(s) for Y axis values |
| colors | no | list of strings | Hex colors per series (e.g. ["#4a6cf7", "#f74a4a"]) |

Minimal example:
```yaml
- type: bar
  title: Revenue by Site
  data: revenue_by_site
  x: site
  y: revenue
```

Multi-series example:
```yaml
- type: bar
  title: Revenue vs Expense
  data: comparison
  x: site
  y: [revenue, expense]
  colors: ["#2ecc71", "#e74c3c"]
  width: full
  height: 480
```

### line

Line chart. Smooth curves by default.

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| x | yes | string | Column for X axis |
| y | yes | string or list | Column(s) for Y values |
| colors | no | list of strings | Hex colors per series |

```yaml
- type: line
  title: Monthly Trend
  data: monthly
  x: month
  y: [revenue, expense, net_income]
  colors: ["#2ecc71", "#e74c3c", "#3498db"]
  width: full
```

### area

Area chart (filled line). Same fields as line.

```yaml
- type: area
  title: Cumulative Revenue
  data: cumulative
  x: month
  y: revenue
  color: "#2ecc71"
```

### scatter

Scatter plot. Both axes are numeric.

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| x | yes | string | Column for X axis (numeric) |
| y | yes | string | Column for Y axis (numeric) |
| color | no | string | Single hex color |

```yaml
- type: scatter
  title: Volume vs Revenue
  data: sites
  x: transaction_count
  y: revenue
```

### timeseries

Time series chart. X axis is time-based.

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| time | yes | string | Column containing dates/timestamps |
| y | yes | string or list | Column(s) for Y values |
| colors | no | list of strings | Hex colors per series |

```yaml
- type: timeseries
  title: Daily Revenue
  data: daily
  time: trandate
  y: amount
  width: full
```

### kpi

Large single-value display tile.

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| value | yes | string | Column containing the value (first row used) |
| label | no | string | Descriptive text below the number |
| format | no | string | "currency", "percent", or "number" |
| prefix | no | string | Text before the number (e.g. "$") |
| suffix | no | string | Text after the number (e.g. "%") |
| color | no | string | Hex color for the number |

```yaml
- type: kpi
  title: Total Revenue
  data: totals
  value: revenue
  format: currency
  prefix: "$"
  color: "#2ecc71"
```

### table

Data table with scrolling and hover highlighting.

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| columns | no | object | Column formatting: `{column_name: {format: "currency"}}` |

```yaml
- type: table
  title: GL Detail
  data: detail
  width: full
  height: 500
  columns:
    amount: { format: currency, prefix: "$" }
    margin: { format: percent, suffix: "%" }
```

### pivot

Pivot table that groups rows and sums values.

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| rows | yes | list of strings | Columns to group by |
| values | yes | list of strings | Columns to sum |

```yaml
- type: pivot
  title: P&L by Department
  data: gl_data
  rows: [department, accounttype]
  values: [amount]
  width: full
```

## Available tables after sync

After running `finch-epm sync`, tables are available in DuckDB SQL by their original source names.

### NetSuite tables (common)

After `finch-epm sync -c netsuite -p <profile> -t <table>`:

| Table | Description | Key columns |
|-------|-------------|-------------|
| Account | Chart of accounts | id, acctnumber, accttype, fullname, parent |
| Subsidiary | Corporate entities | id, name, parent, country |
| Department | Departments | id, name, fullname |
| Location | Locations/sites | id, name, subsidiary |
| Transaction | All transactions | id, type, trandate, postingperiod, status, memo |
| TransactionLine | Line items | transaction, subsidiary, department, location, amount, memo |
| TransactionAccountingLine | GL posting lines | transaction, transactionline, account, accounttype, amount, debit, posting |
| Invoice | Invoices | id, trandate, entity, total |
| VendorBill | Vendor bills | id, trandate, entity, total |
| JournalEntry | Journal entries | id, trandate, memo |
| Check | Checks | id, trandate, entity, total |

### SQL Server / Postgres tables

Tables keep their `schema.table` names (e.g., `dbo.Hospital`, `CHNG.Payments`).

## Multiple data sources in one dashboard

finch-epm supports connecting to multiple databases simultaneously. Each connection is a named profile (e.g., `sqlserver/azure_pemmdw`, `netsuite/production`, `sqlserver/onprem_warehouse`).

All synced data goes into one local DuckDB cache. You can query tables from different sources in the same dashboard. The key is knowing the cache table names:

- **NetSuite tables**: use the original PascalCase name (e.g., `Account`, `TransactionAccountingLine`)
- **SQL Server / Postgres tables**: dots become double underscores (e.g., `dbo.WaterFallT2` becomes `dbo__WaterFallT2`)

Example multi-source dashboard:

```yaml
name: Combined Financial Overview
description: NetSuite GL data alongside SQL Server revenue cycle data
sources:
  - netsuite/production
  - sqlserver/azure_pemmdw

queries:
  - name: netsuite_revenue
    sql: |
      SELECT a.accttype, SUM(CAST(t.amount AS DOUBLE)) * -1 AS revenue
      FROM TransactionAccountingLine t
      JOIN Account a ON CAST(t.account AS INTEGER) = CAST(a.id AS INTEGER)
      WHERE a.accttype = 'Income' AND t.posting = 'T'
      GROUP BY a.accttype

  - name: rcm_cash
    sql: |
      SELECT PRACTICE, SUM(CAST(PAYMENTS AS DOUBLE)) * -1 AS cash
      FROM dbo__WaterFallT2
      WHERE SUBSTRING(FIRSTDOS, 1, 4) = '2024'
      GROUP BY PRACTICE ORDER BY cash DESC

charts:
  - type: kpi
    title: NetSuite Revenue
    data: netsuite_revenue
    value: revenue
    format: currency
    prefix: "$"

  - type: bar
    title: RCM Cash by Practice
    data: rcm_cash
    x: PRACTICE
    y: cash
```

To set up multiple connections:

```
finch-epm auth -c sqlserver -p azure_pemmdw --env-file /path/to/pemmdw.env
finch-epm auth -c sqlserver -p onprem_warehouse --env-file /path/to/onprem.env
finch-epm auth -c netsuite -p production --env-file /path/to/ns.env --key-file /path/to/key.pem

finch-epm catalog --crawl -c sqlserver -p azure_pemmdw
finch-epm catalog --crawl -c sqlserver -p onprem_warehouse
finch-epm catalog --crawl -c netsuite -p production

finch-epm sync -c sqlserver -p azure_pemmdw -t dbo.WaterFallT2
finch-epm sync -c sqlserver -p onprem_warehouse -t dbo.SomeTable
finch-epm sync -c netsuite -p production -t Account -t TransactionAccountingLine
```

Or use the setup wizard which loops to add multiple connections:

```
finch-epm setup
```

## SQL patterns for common dashboards

### P&L summary

```yaml
queries:
  - name: pl
    sql: |
      SELECT
        a.accttype,
        SUM(CAST(t.amount AS DOUBLE)) AS total
      FROM TransactionAccountingLine t
      JOIN Account a ON CAST(t.account AS INTEGER) = CAST(a.id AS INTEGER)
      WHERE t.posting = 'T'
      GROUP BY a.accttype
      ORDER BY total DESC
```

### Revenue over time

```yaml
queries:
  - name: monthly_revenue
    sql: |
      SELECT
        SUBSTRING(tx.trandate, 1, 7) AS month,
        SUM(CAST(t.amount AS DOUBLE)) AS revenue
      FROM TransactionAccountingLine t
      JOIN Transaction tx ON CAST(t.transaction AS INTEGER) = CAST(tx.id AS INTEGER)
      JOIN Account a ON CAST(t.account AS INTEGER) = CAST(a.id AS INTEGER)
      WHERE a.accttype = 'Income' AND t.posting = 'T'
      GROUP BY SUBSTRING(tx.trandate, 1, 7)
      ORDER BY month
```

### KPI tiles

```yaml
queries:
  - name: kpis
    sql: |
      SELECT
        SUM(CASE WHEN a.accttype = 'Income' THEN CAST(t.amount AS DOUBLE) ELSE 0 END) AS revenue,
        SUM(CASE WHEN a.accttype = 'Expense' THEN CAST(t.amount AS DOUBLE) ELSE 0 END) AS expense
      FROM TransactionAccountingLine t
      JOIN Account a ON CAST(t.account AS INTEGER) = CAST(a.id AS INTEGER)
      WHERE t.posting = 'T'

charts:
  - type: kpi
    title: Total Revenue
    data: kpis
    value: revenue
    format: currency
    prefix: "$"
    color: "#2ecc71"
  - type: kpi
    title: Total Expense
    data: kpis
    value: expense
    format: currency
    prefix: "$"
    color: "#e74c3c"
```

### Account breakdown

```yaml
queries:
  - name: accounts
    sql: |
      SELECT accttype, COUNT(*) AS count
      FROM Account WHERE isinactive = 'F'
      GROUP BY accttype ORDER BY count DESC

charts:
  - type: bar
    title: Active Accounts by Type
    data: accounts
    x: accttype
    y: count
```

## Dashboard-level filters

Filters appear as dropdowns at the top of the dashboard. When the user selects a value, all queries re-execute with the filter value injected as a parameter.

```yaml
filters:
  - name: year
    label: Year
    query: "SELECT DISTINCT SUBSTRING(trandate, 1, 4) AS year FROM Transaction ORDER BY year DESC"
    parameter: selected_year
    default: "2024"

  - name: practice
    label: Practice
    query: "SELECT DISTINCT PRACTICE FROM dbo__WaterFallT2 ORDER BY PRACTICE"
    parameter: selected_practice

queries:
  - name: revenue
    sql: |
      SELECT ...
      WHERE SUBSTRING(trandate, 1, 4) = :selected_year
        AND PRACTICE = :selected_practice
```

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| name | yes | string | Unique filter identifier |
| label | yes | string | Display label in the dropdown |
| query | yes | string | SQL that returns dropdown options (first column = value) |
| parameter | yes | string | Parameter name injected into queries when a value is selected |
| default | no | any | Default selected value |
| multi | no | boolean | Allow multiple selections (default false) |

## Cross-chart filtering

Add `cross_filter` to a chart to make it interactive. Clicking a data point in that chart filters all other charts by the clicked value.

```yaml
charts:
  - type: bar
    title: Revenue by Practice
    data: by_practice
    x: PRACTICE
    y: revenue
    cross_filter: PRACTICE    # clicking a bar filters other charts by PRACTICE

  - type: table
    title: Detail
    data: detail              # this query uses :PRACTICE parameter, auto-filtered
```

When a user clicks a bar (e.g., "STPH"), the dashboard re-executes all queries with `PRACTICE=STPH` as a parameter override. A badge appears showing the active filter, and clicking the badge clears it.

## Dimension mappings

For complex reporting with rollup hierarchies, binary flags, and cross-source joins, define a dimension mapping YAML file:

```yaml
# dimensions.yaml
name: My Company Dimensions
dimensions:
  - name: location
    display_name: Location / Site
    table: dbo__IFSLocations        # cache table name
    id_column: LocationID
    label_column: LocationName
    join_column: location            # column in fact tables
    rollups:
      - name: site
        display_name: Site
        column: LocationName
      - name: group
        display_name: Group
        column: GroupRollup
    flags:
      - name: core_fy25
        display_name: Core FY25
        column: CoreFY25
      - name: active
        display_name: Active Business
        column: ActiveBusiness
```

Reference it in a .fdash file:

```yaml
dimensions:
  file: dimensions.yaml
```

This enables the P&L engine to generate queries with automatic joins, rollup grouping, and flag-based filtering. The dimension mapping is fully customizable per company.

## Rules for AI dashboard generators

1. The file extension must be `.fdash`.
2. `name` is required at the top level.
3. At least one query and one chart are required.
4. SQL must be valid DuckDB dialect. All synced data is stored as VARCHAR, so use CAST for numeric operations (e.g., `CAST(amount AS DOUBLE)`).
5. Column names in chart `x`, `y`, `time`, `value`, `rows`, and `values` fields must exactly match the column names or aliases in the SQL SELECT clause.
6. The `data` field in each chart must exactly match a query `name`.
7. Parameter placeholders in SQL use `:param_name` syntax.
8. Colors must be valid hex strings with `#` prefix (e.g., `"#4a6cf7"`).
9. The `y` field can be a string (single series) or a list of strings (multi-series).
10. When using multi-series, provide `colors` as a list with one color per series.
11. Use `width: full` for charts that need more horizontal space (time series, wide tables).
12. Use `format: currency` with `prefix: "$"` for monetary values in KPI tiles.
13. Tables do not need `x` or `y` fields -- they display all columns from the query.
14. Pivot tables require `rows` (grouping columns) and `values` (aggregation columns).
