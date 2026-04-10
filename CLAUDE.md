# finch-epm -- Claude Code Context

This is the finch-epm project, a local-first analytics tool that connects to data sources (NetSuite, SQL Server, PostgreSQL), caches data in a local DuckDB database, and renders interactive dashboards from portable `.fdash` files.

## When a user asks to build a dashboard

If the user asks to create, build, or design a dashboard, report, or visualization:

1. Check what data is available by running: `finch-epm catalog --tables --accessible-only -c <connector> -p <profile>`
2. Check the columns on relevant tables: `finch-epm catalog --columns <table> -c <connector> -p <profile>`
3. Generate a `.fdash` file following the specification in `DASHBOARDS.md`
4. The user can open it with: `finch-epm open <file>.fdash`

## Key commands

```
finch-epm setup                          # First-time setup wizard
finch-epm auth -c netsuite -p <name> --env-file <path>  # Import credentials
finch-epm auth -c sqlserver -p <name> --env-file <path>  # Import SQL Server creds
finch-epm auth -c postgres -p <name> --env-file <path>   # Import Postgres creds
finch-epm auth -c snowflake -p <name> --env-file <path>  # Import Snowflake creds
finch-epm auth -c bigquery -p <name> --env-file <path>   # Import BigQuery creds
finch-epm auth -c odbc -p <name> --env-file <path>       # Import ODBC creds
finch-epm catalog --crawl -c <connector> -p <profile>    # Discover schema
finch-epm catalog --tables -c <connector> -p <profile>   # List tables
finch-epm catalog --columns <table> -c <connector> -p <profile>  # List columns
finch-epm sync -c <connector> -p <profile> -t <table>    # Sync data
finch-epm import <file>.csv                               # Import CSV/Excel into cache
finch-epm open <file>.fdash                               # Open dashboard
finch-epm service                                         # Run background sync
finch-epm service --once                                  # Run one sync cycle
```

## Dashboard file format (.fdash)

See `DASHBOARDS.md` for the complete specification. Key points:

- YAML format with `.fdash` extension
- Defines queries (DuckDB SQL), parameters, and charts
- Chart types: bar, line, area, scatter, timeseries, kpi, table, pivot, variance_table, custom
- Multi-series support: `y: [col1, col2]` with `colors: ["#hex1", "#hex2"]`
- Layout control: `width: full` or `width: half`, `height: 480`
- KPI formatting: `format: currency`, `prefix: "$"`
- Dashboards contain no data and no credentials -- they are portable

## Data sources configured in this project

Check `finch-epm catalog --tables` for current state. Common tables after sync:

### NetSuite
Account, Subsidiary, Department, Location, Transaction, TransactionLine, TransactionAccountingLine, Invoice, VendorBill, Check, JournalEntry

### SQL Server / Azure SQL
Tables keep schema.table naming (e.g., dbo.Hospital, CHNG.Payments)

### PostgreSQL
Tables keep schema.table naming (e.g., public.users)

## Project structure

```
src/finch_epm/
    connectors/     -- NetSuite, SQL Server, PostgreSQL, Snowflake, BigQuery, ODBC, File, Fake
    catalog/        -- DuckDB-backed schema store
    cache/          -- DuckDB-backed data cache + sync engine
    dashboard/      -- .fdash parser, resolver, chart renderers
    server/         -- Local web server for dashboard rendering
    cli/            -- Click CLI commands
    profiles/       -- OS keychain credential management
```

## SQL dialect

All dashboard queries run against the local DuckDB cache. Key notes:
- DuckDB SQL dialect (PostgreSQL-compatible with extensions)
- All NetSuite data is stored as VARCHAR after sync (use CAST for numeric operations)
- SQL Server and Postgres data retains original types
- Use standard SQL: GROUP BY, ORDER BY, CASE WHEN, JOINs, subqueries
