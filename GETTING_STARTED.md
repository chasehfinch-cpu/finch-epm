# Getting Started with finch-epm

finch-epm has two audiences. **IT administrators** handle the one-time setup: installing the software, connecting data sources, syncing data, and configuring the compilation map and chart of accounts. **End users** (CFOs, controllers, analysts) just open dashboards — they never need to touch a terminal.

---

## Part 1: IT Administrator Setup

### Install

```
pip install finch-epm
```

Requires Python 3.10+. Optional connectors:

```
pip install finch-epm[sqlserver]     # SQL Server / Azure SQL
pip install finch-epm[postgres]      # PostgreSQL
pip install finch-epm[snowflake]     # Snowflake
pip install finch-epm[bigquery]      # Google BigQuery
pip install finch-epm[mcp]           # MCP server for AI clients
pip install finch-epm[all]           # Everything
```

For organization-wide deployment, use the PowerShell script:

```powershell
.\installer\deploy.ps1
```

This installs Python, finch-epm, registers the `.fdash` file association, and sets up a scheduled sync task. Pushable via Intune, SCCM, or GPO.

### Run the setup wizard

```
finch-epm setup
```

The wizard walks through:

1. **Connect data sources** — NetSuite, SQL Server, PostgreSQL, Snowflake, BigQuery, or ODBC. Credentials are stored in the OS keychain, never in plaintext.
2. **Crawl schemas** — discovers every table, column, and dimension in each source.
3. **Sync data** — pulls all data into the local DuckDB cache. Runs in the background. First sync takes 15-30 minutes for large datasets (e.g., 700K+ GL rows). After that, incremental syncs take seconds.
4. **Generate chart of accounts** — auto-creates a P&L hierarchy from your GL account data. Customize it later with `finch-epm coa edit`.
5. **Configure compilation map** — the single source of truth that links all your data sources together.

### What you need before setup

**NetSuite**: Integration record with OAuth 2.0, certificate, role with SuiteQL permissions, `.env` file with account/client/cert IDs, private key PEM.

**SQL Server**: Login with SELECT permissions, ODBC Driver 17/18, `.env` with server/database/username/password.

**PostgreSQL**: User with SELECT, `.env` with host/port/database/username/password.

**Snowflake**: Account + warehouse, `.env` with account/warehouse/database/schema/user/password.

**BigQuery**: Service account JSON key with Data Viewer role, `.env` with project/dataset/key path.

**ODBC**: Driver installed, `.env` with connection string.

### Configure the compilation map

After sync completes, set up the map that links your data sources:

```
finch-epm map setup
```

The wizard detects reference tables (Location, Department, Entity) and walks you through:
- Which table is the master reference (e.g., `IFSLocations`)
- Which columns are the ID and display name
- Which columns are rollup levels (Site, Group, State)
- Which columns are binary flags (Active, Terminated, CoreFY25)
- Which fact tables link to this reference

The result is one `compilation_map.yaml` that every dashboard uses.

### Share the configuration

Copy these files to a network share so every user gets the same setup:

```
finch-epm map show      # Shows file path
finch-epm coa show      # Shows file path
```

The compilation map, chart of accounts, and flag definitions are all portable YAML files.

### Silent deployment for multiple machines

Pre-build a config bundle (compilation_map.yaml + coa.yaml + flags.yaml) and deploy:

```
finch-epm setup --config "\\server\share\finch-epm-config\"
```

Or point all users to a shared compilation map:

```
finch-epm map use "\\server\share\compilation_map.yaml"
```

Every machine that runs this command shares the same map. When finance updates a site (terminates a location, adds CoreFY27), they update the map on the share and every user's dashboards pick up the change.

### Ongoing maintenance

The background sync keeps data fresh automatically. To check status:

```
finch-epm sync -c netsuite -p production --all --incremental   # Manual sync
finch-epm service                                               # Run continuous sync
finch-epm classify                                              # Review unclassified items
finch-epm coa unmapped                                          # Check unmapped GL accounts
```

---

## Part 2: End User Guide

### Open a dashboard

Double-click any `.fdash` file. Or from the command line:

```
finch-epm open dashboard.fdash
```

The dashboard opens in your browser with live data, filters, and charts.

### Use filters

Dashboards have dropdown filters at the top (Year, Subsidiary, Department, etc.). Select a value to filter all charts. Click a bar in a chart to cross-filter other charts.

### Generate a dashboard with AI

If your IT team has configured an LLM provider:

```
finch-epm ask "build me a P&L dashboard by subsidiary" --open
finch-epm ask "monthly revenue trend" --open
finch-epm ask "expense breakdown by department" --open
```

The AI reads your actual data schema and generates a working dashboard.

### Share a dashboard

Send the `.fdash` file to anyone on your team via email, Slack, or Teams. They open it and see the same layout rendered against their own data access. The file contains no data — just the dashboard definition.

### Templates

finch-epm ships with example dashboards:

```
finch-epm open examples/netsuite_gl_overview.fdash
finch-epm open examples/multi_tab_financial.fdash
```

### Import budget or forecast data

```
finch-epm import budget_2024.csv
finch-epm import forecast.xlsx --sheet Q4 --table forecast_q4
```

Imported data becomes queryable in dashboards alongside synced data.

---

## Where things are stored

| What | Location (Windows) |
|------|-------------------|
| Cached data | `%LOCALAPPDATA%\finch-epm\cache.duckdb` |
| Schema catalog | `%LOCALAPPDATA%\finch-epm\catalog.duckdb` |
| Compilation map | `%LOCALAPPDATA%\finch-epm\compilation_map.yaml` |
| Chart of accounts | `%LOCALAPPDATA%\finch-epm\coa.yaml` |
| Flag definitions | `%LOCALAPPDATA%\finch-epm\flags.yaml` |
| Profile config | `%LOCALAPPDATA%\finch-epm\profiles.json` |
| Credentials | Windows Credential Manager (never on disk) |
| Sync config | `%LOCALAPPDATA%\finch-epm\sync_service.json` |

On macOS: `~/Library/Application Support/finch-epm/`
On Linux: `~/.local/share/finch-epm/`
