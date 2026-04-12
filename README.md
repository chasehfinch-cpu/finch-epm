# finch-epm

**A local-first, portable analytics layer for EPM and database systems.**

finch-epm lets you connect to structured data sources (NetSuite, SQL Server, PostgreSQL, Snowflake, BigQuery, or any ODBC-accessible system), automatically map their schemas, cache data locally in a fast columnar engine, and share interactive dashboards as small portable files -- no server, no cloud, no spreadsheet exports.

## Current status

v0.1, v0.2, and v0.3 are complete. The tool is functional end-to-end.

**What works today:**

- 7 data source connectors: NetSuite, SQL Server, PostgreSQL, Snowflake, BigQuery, Generic ODBC, and a Fake connector for testing
- Exhaustive schema introspection (probes all 200+ standard NetSuite record types, INFORMATION_SCHEMA for SQL databases)
- Local DuckDB catalog that persists schema metadata between sessions
- Local DuckDB cache with incremental sync, watermark tracking, and atomic cache swap
- Background sync service with OS task scheduler integration (Windows, macOS, Linux)
- `.fdash` dashboard parser, resolver, and web renderer
- Multi-page tabbed dashboards (one .fdash file, multiple pages with shared filters)
- 10 chart types: bar, line, area, scatter, time series, KPI, table, pivot, variance table, custom (Vega-Lite)
- Multi-series support, color customization, layout control, and CSV export
- Dashboard-level filter dropdowns and cross-chart filtering
- Variance mode: actual vs budget side-by-side with automatic delta calculation
- Custom charts via Vega-Lite specifications for any visualization not covered by built-in types
- CSV and Excel file import for budget, forecast, and reference data
- Configurable P&L engine with user-defined chart of accounts hierarchy
- Dimension mapping layer for rollups, hierarchies, and binary flag filters
- CLI commands: `setup`, `auth`, `catalog`, `sync`, `open`, `import`, `service`
- Desktop installer infrastructure (PyInstaller spec, .fdash file association, build script)
- IT administrator deployment script (PowerShell, pushable via Intune/SCCM/GPO)
- AI-readable dashboard specification (DASHBOARDS.md) and Claude Code /dashboard command
- 165 passing tests (125 unit + 40 walkthrough)
- Complete documentation: README, GETTING_STARTED, DASHBOARDS, CONTRIBUTING, CHANGELOG

**What is planned for future releases:**

- Federated query mode (push queries to remote sources instead of caching locally)
- Multi-source JOINs in a single .fdash query (NetSuite + SQL Server in one SQL statement)
- Semantic layer for cross-source logical models
- Community connector library and plugin API

## What it is

finch-epm is a Python package you install on your own computer. It connects to your own data sources using your own credentials, builds a local catalog of every table and field it can see, caches the data in an embedded analytical database, and renders dashboards defined in plain `.fdash` files. Dashboards are shareable: send the file to a colleague, and as long as they have valid credentials to the underlying source, finch-epm renders it for them against their own access.

Nothing about your data, your credentials, or your usage ever leaves your machine. There is no finch-epm cloud. There is no account to create. There is no telemetry.

## What it is not

- Not a hosted BI tool. There is no server, no SaaS, no login page.
- Not a data warehouse. The cache is local and scoped to what you query.
- Not a replacement for governed enterprise BI. It is a tool for analysts, controllers, and operators who want fast, shareable views of their own systems.
- Not a way to bypass source-system permissions. Every query runs under the user's own credentials and respects whatever access they have.

## Install

```
pip install finch-epm
```

Requires Python 3.10 or later. Works on macOS, Linux, and Windows.

## Quick start

### 1. Authenticate

Import your NetSuite credentials into the OS keychain. This reads the `.env` and private key file once, stores them securely, and never touches the files again.

```
finch-epm auth -c netsuite -p production \
  --env-file /path/to/.env \
  --key-file /path/to/private.pem
```

The `.env` file should contain:

```
NS_ACCOUNT_ID=your_account_id
NS_CLIENT_ID=your_client_id
NS_CERTIFICATE_ID=your_certificate_id
NS_PRIVATE_KEY_PATH=path/to/private.pem
```

Validate that credentials work:

```
finch-epm auth -c netsuite -p production --validate
```

### 2. Crawl the schema

Discover every table, column, custom field, and dimension in your NetSuite instance:

```
finch-epm catalog --crawl -c netsuite -p production
```

This probes all known NetSuite record types and reports three states for each: accessible, restricted (exists but your role lacks permission), and not found (not present in your instance).

Browse the results:

```
finch-epm catalog --tables -c netsuite -p production
finch-epm catalog --tables --accessible-only -c netsuite -p production
finch-epm catalog --columns Transaction -c netsuite -p production
finch-epm catalog --dimensions -c netsuite -p production
```

### 3. Sync data

Pull data from NetSuite into your local DuckDB cache:

```
finch-epm sync -c netsuite -p production -t Account -t Subsidiary -t Department
finch-epm sync -c netsuite -p production -t TransactionAccountingLine --full
finch-epm sync -c netsuite -p production --all --incremental
```

After sync, your data is queryable locally at millisecond speed. No network calls.

### 4. Open a dashboard

```
finch-epm open path/to/dashboard.fdash
```

This launches a local web server and opens the dashboard in your browser. The dashboard renders immediately against cached data with a staleness indicator.

## Dashboard format

Dashboards are `.fdash` files. The contents are YAML; the extension is finch-epm-specific so that the desktop installer can claim the file association cleanly. A minimal example:

```yaml
name: Site P&L
description: Revenue and expense by site, current quarter
sources:
  - netsuite

queries:
  - name: site_pl
    sql: |
      SELECT
        site,
        SUM(CASE WHEN account_type = 'Income' THEN amount ELSE 0 END) AS revenue,
        SUM(CASE WHEN account_type = 'Expense' THEN amount ELSE 0 END) AS expense
      FROM gl_detail
      WHERE period BETWEEN :start_period AND :end_period
      GROUP BY site

parameters:
  start_period:
    type: period
    default: current_quarter_start
  end_period:
    type: period
    default: current_quarter_end

charts:
  - type: bar
    title: Revenue by Site
    data: site_pl
    x: site
    y: revenue
  - type: table
    title: P&L Detail
    data: site_pl
```

Dashboards are portable. They contain no data, no credentials, and no machine-specific paths. Share them via email, GitHub, Slack, or any other channel.

## Built-in chart types

- Table
- Bar
- Line
- Area
- KPI tile
- Pivot
- Time series
- Scatter
- Variance table (actual vs budget with automatic delta calculation)
- Custom (Vega-Lite specification for any visualization)

Each chart type implements a generic chart renderer interface. Custom charts use Vega-Lite specs, so any visualization not covered by built-in types can be added without touching the rendering pipeline.

## How it works

finch-epm has four layers, each designed to be extended without rewriting the others:

1. **Connectors.** A connector is an adapter for a specific kind of data source. Seven connectors ship today: NetSuite (SuiteQL + REST metadata), SQL Server, PostgreSQL, Snowflake, BigQuery, Generic ODBC, and a Fake connector for testing. Each connector implements a small abstract interface -- `list_dimensions`, `get_hierarchy`, `fetch_facts`, `introspect_schema`, `plan_scope` -- that the rest of the system depends on. New connectors are added by implementing the interface; the catalog, cache, and renderer never change.

2. **Catalog.** The catalog is a local DuckDB database that stores the schema discovered by introspection: table names, column types, access status, dimensional hierarchies, and category metadata. The catalog tracks every record type the source exposes, including those the current user cannot access, so users always know what exists versus what their role can see.

3. **Cache.** The cache is also DuckDB, storing the actual fact and dimension data pulled from the source. Sync is incremental and scoped -- finch-epm only pulls the data that dashboards actually need, watermarked by last-modified date where the source supports it. DuckDB handles tens to hundreds of millions of rows comfortably on a laptop. The cache layer exposes a generic query interface, so v0.4's planned federated mode (where queries against fast remote backends like Snowflake are pushed down to the source instead of cached locally) can plug in without changing the renderer.

4. **Dashboard runtime.** A small local web server reads the `.fdash` file, resolves logical names against the catalog, executes queries against the cache (or, in federated mode, pushes them down), and renders the results in a browser. Charts are interactive. Filters re-run queries against the local engine, so interactivity is instantaneous. The renderer talks to a chart interface, not to specific chart implementations, so adding new chart types does not require rewriting any built-in chart.

## Security model

Credentials are stored in the operating system's native credential manager (Windows Credential Manager, macOS Keychain, or Linux Secret Service) via the `keyring` library. They are never written to disk in plaintext, never stored in environment variables at runtime, and never included in dashboard files.

Authentication to NetSuite uses OAuth 2.0 Client Credentials with certificate-based JWT signing (ES256 or PS256 depending on key type). Access tokens are short-lived and refresh automatically.

Multiple named profiles are supported per connector type. A team can share one NetSuite integration record while each user's permissions determine what data they see.

## NetSuite permissions

The connecting role needs:

- OAuth 2.0 client credentials authentication enabled (integration record in NetSuite)
- A certificate mapped to the integration
- Read access to the record types you want to query
- Permission to run SuiteQL queries via the REST API

finch-epm introspects all record types exhaustively and reports which ones are accessible, restricted, or not found for the current role.

## Performance

Queries run against a local columnar engine, so typical dashboard interactions -- filters, drilldowns, period changes -- return in milliseconds. The slow path is the initial sync from the source system, which is bounded by the source's API throughput and rate limits. finch-epm mitigates this with scoped sync, incremental watermarks, and background refresh.

DuckDB compresses analytical data well; expect roughly 5-10x compression over raw row data. A few years of GL detail for a mid-sized company is typically a few hundred megabytes on disk.

## Roadmap

**v0.1 (complete).** NetSuite connector. DuckDB catalog and cache. `.fdash` dashboard format. Eight built-in chart types. Local web renderer. CLI: `setup`, `auth`, `sync`, `open`, `catalog`. Pip install only.

**v0.2 (complete).** SQL Server and Postgres connectors. Desktop installer infrastructure (PyInstaller). Scheduled background sync service. Dashboard parameters, filters, and cross-chart filtering. CSV/Excel file import. Multi-page tabbed dashboards. Variance tables. IT deployment script.

**v0.3 (complete).** Snowflake, BigQuery, and Generic ODBC connectors. Custom chart types via Vega-Lite specs. Configurable P&L engine with user-defined chart of accounts. Dimension mapping layer for rollups and flag filters.

**v0.4 (planned).** Multi-source JOINs in a single query. Semantic layer for cross-source logical models. Optional team-shared catalogs. Federated query mode for fast remote backends.

The architecture is built so that every item on this roadmap can be added without rewriting the core.

## Development

```
git clone https://github.com/chasehfinch-cpu/finch-epm.git
cd finch-epm
pip install -e ".[dev]"
pytest
```

See `CONTRIBUTING.md` for architecture details, how to add connectors, and testing patterns.

## Contributing

finch-epm is open source under the MIT license. The Connector interface and ChartRenderer interface are the two main extension points -- if you want to add support for a new data source or chart type, implement the relevant interface and submit a pull request. See `CONTRIBUTING.md` for details.

## License

MIT
