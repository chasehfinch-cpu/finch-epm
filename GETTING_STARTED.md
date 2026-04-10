# Getting Started with finch-epm

This guide walks you through installing finch-epm, connecting your data sources, and opening your first dashboard.

## Step 1: Install

```
pip install finch-epm
```

Requires Python 3.10 or later. Works on Windows, macOS, and Linux.

Optional connectors (install only what you need):

```
pip install finch-epm[sqlserver]     # SQL Server / Azure SQL
pip install finch-epm[postgres]      # PostgreSQL
pip install finch-epm[snowflake]     # Snowflake
pip install finch-epm[bigquery]      # Google BigQuery
pip install finch-epm[all]           # Everything
```

## Step 2: Run setup

```
finch-epm setup
```

The setup wizard will:

1. Ask which data source you want to connect (NetSuite, SQL Server, PostgreSQL, Snowflake, BigQuery, or any ODBC source)
2. Show you exactly what credentials and permissions you need
3. Import your credentials securely into the OS keychain
4. Validate the connection against the live system
5. Discover all tables and fields available to you
6. Offer to set up automatic background sync
7. Start syncing data in the background so dashboards are ready when you need them

You can add multiple data sources in one setup session. Each gets its own named profile.

## What you need before setup

### NetSuite

- An Integration record in NetSuite with OAuth 2.0 Client Credentials enabled
- A certificate (EC or RSA key pair) uploaded to the integration
- A role with these permissions: SuiteQL (Reports), REST Web Services (Setup), read access on the record types you want to query
- A `.env` file with your account ID, client ID, and certificate ID
- The private key PEM file matching the uploaded certificate

### SQL Server / Azure SQL

- A SQL login with SELECT permissions on the tables you want
- An ODBC driver installed (ODBC Driver 17 or 18 for SQL Server)
- A `.env` file with your server, database, username, and password
- For Azure SQL: the server FQDN ends in `.database.windows.net`

### PostgreSQL

- A database user with SELECT permissions
- A `.env` file with host, port, database, username, and password

### Snowflake

- A Snowflake account with a compute warehouse
- A `.env` file with account, warehouse, database, schema, username, and password

### BigQuery

- A GCP project with BigQuery enabled
- A service account JSON key file with BigQuery Data Viewer role
- A `.env` file with project ID, dataset name, and the path to the JSON key

### ODBC (OneStream, SAP, Oracle, etc.)

- An ODBC driver for your data source installed on your machine
- A `.env` file with the full ODBC connection string

## Step 3: Open a dashboard

After setup, your data syncs automatically in the background. Open a template dashboard to see it working:

```
finch-epm open examples/multi_tab_financial.fdash
```

This opens a tabbed dashboard in your browser with charts, KPI tiles, and tables rendered against your locally cached data.

## Step 4: Build your own dashboard

There are three ways to create dashboards:

### Option A: Use AI

If you have Claude Code installed, type `/dashboard` in any Claude Code session. Claude will check what data you have synced, ask what you want to see, and generate a `.fdash` file for you.

You can also paste the contents of `DASHBOARDS.md` into ChatGPT, Gemini, or any other AI and ask it to generate a dashboard.

### Option B: Copy and modify a template

Look in the `examples/` directory for ready-made dashboards:

| Template | What it shows |
|---|---|
| `netsuite_gl_overview.fdash` | Revenue, expense, subsidiary breakdown from NetSuite GL |
| `multi_tab_financial.fdash` | Multi-tab: P&L, Revenue Cycle, Organization |
| `cfo_ar_timing.fdash` | AR timing, cash collection, payor analysis |
| `cfo_payor_analysis.fdash` | Payor class breakdown with yield percentages |
| `account_overview.fdash` | Account types, subsidiaries, departments |
| `site_pl.fdash` | Site-level P&L (minimal example) |

Copy any of these, modify the SQL queries to match your data, and open it.

### Option C: Write from scratch

See `DASHBOARDS.md` for the complete specification. A minimal dashboard:

```yaml
name: My Dashboard
sources:
  - netsuite

queries:
  - name: summary
    sql: SELECT accttype, COUNT(*) AS count FROM Account GROUP BY accttype

charts:
  - type: bar
    title: Accounts by Type
    data: summary
    x: accttype
    y: count
```

Save as `my_dashboard.fdash` and open with `finch-epm open my_dashboard.fdash`.

## Step 5: Share a dashboard

Send any `.fdash` file to a colleague via email, Slack, Teams, or GitHub. They:

1. Install finch-epm
2. Run `finch-epm setup` with their own credentials
3. Open the `.fdash` file with `finch-epm open your_file.fdash`

The dashboard renders against their own data access. No data is stored in the file.

## Step 6: Import CSV or Excel data

You can load files directly into the local cache alongside database data:

```
finch-epm import budget_2024.csv
finch-epm import reference.xlsx --sheet Locations --table locations
```

The imported data becomes a table you can query in `.fdash` SQL.

## Useful commands

```
finch-epm catalog --tables -c netsuite -p production    # See available tables
finch-epm catalog --columns Account -c netsuite -p production  # See columns
finch-epm sync -c netsuite -p production -t Account     # Manually sync a table
finch-epm service                                       # Run sync service
finch-epm import data.csv                               # Import a file
finch-epm open dashboard.fdash                          # Open a dashboard
```

## Where things are stored

| What | Where |
|---|---|
| Cached data | `AppData/Local/finch-epm/cache.duckdb` (Windows) |
| Schema catalog | `AppData/Local/finch-epm/catalog.duckdb` |
| Profile config | `AppData/Local/finch-epm/profiles.json` |
| Credentials | Windows Credential Manager (never on disk) |
| Sync config | `AppData/Local/finch-epm/sync_service.json` |
| Dashboard spec | `DASHBOARDS.md` in the finch-epm repository |
| Templates | `examples/` directory |
