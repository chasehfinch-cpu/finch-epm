# finch-epm

**A local-first, portable analytics layer for EPM and database systems.**

finch-epm lets you connect to NetSuite (and, over time, any structured data source), automatically map its schema, cache data locally in a fast columnar engine, and share interactive dashboards as small portable files — no server, no cloud, no spreadsheet exports.

## What it is

finch-epm is a Python package you install on your own computer. It connects to your own data sources using your own credentials, builds a local catalog of every table and field it can see, caches the data in an embedded analytical database, and renders dashboards defined in plain `.fdash` files. Dashboards are shareable: send the file to a colleague, and as long as they have valid credentials to the underlying source, finch-epm renders it for them against their own access.

Nothing about your data, your credentials, or your usage ever leaves your machine. There is no finch-epm cloud. There is no account to create. There is no telemetry.

## What it is not

- Not a hosted BI tool. There is no server, no SaaS, no login page.
- Not a data warehouse. The cache is local and scoped to what you query.
- Not a replacement for governed enterprise BI. It is a tool for analysts, controllers, and operators who want fast, shareable views of their own systems.
- Not a way to bypass source-system permissions. Every query runs under the user's own credentials and respects whatever access they have.

## Audience for v0.1

v0.1 ships as a pip package and is intended for users comfortable installing Python packages — analysts, controllers, FP&A teams, and engineers. A double-clickable desktop installer for non-technical viewers (CFOs, executives) is planned for v0.2; see the roadmap. The dashboard file format and architecture are designed from v0.1 to support that experience cleanly when the installer ships.

## Install

```
pip install finch-epm
```

Requires Python 3.10 or later. Works on macOS, Linux, and Windows.

## Quick start

```
finch-epm setup
```

The setup wizard walks you through:

1. **Choosing your data sources.** v0.1 supports NetSuite. v0.2 will add SQL Server and Postgres; v0.3 will add Snowflake and BigQuery. All future connectors plug into the same interface and the same setup flow.
2. **Granting permissions.** For each source, finch-epm tells you exactly which roles, scopes, or permissions the connecting user needs in the source system to give finch-epm full read access to the relevant areas. For NetSuite, this means a specific set of permissions on a custom role, documented in the wizard.
3. **Authenticating.** finch-epm uses token-based authentication for NetSuite and stores tokens in your operating system's keychain via the `keyring` library. Credentials are never written to disk in plaintext. Multiple named profiles are supported per connector, so you can connect to more than one NetSuite instance, or later more than one database, without conflict.
4. **Crawling the schema.** finch-epm queries the source's metadata APIs to discover every table, column, custom field, and dimensional hierarchy you have access to. The result is written to a local catalog stored in the platform-appropriate user data directory (for example, `~/Library/Application Support/finch-epm/` on macOS).

Setup typically takes a few minutes. Initial data sync runs separately and can be scoped to the periods and entities you actually need.

## Opening a dashboard

```
finch-epm open path/to/dashboard.fdash
```

This launches a local web server (default port 8765) and opens the dashboard in your browser. The dashboard renders immediately against whatever data is already in your local cache, with a staleness indicator showing when the data was last refreshed. If new data is available from the source, finch-epm syncs it in the background and the dashboard updates live.

If the dashboard references data your local catalog hasn't seen yet, finch-epm prompts you to authenticate and pulls just the scope the dashboard needs.

When the v0.2 desktop installer ships, double-clicking a `.fdash` file in your file browser will open it directly in finch-epm without using the command line.

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

## Built-in chart types (v0.1)

- Table
- Bar
- Line
- Area
- KPI tile
- Pivot
- Time series
- Scatter

Each chart type is an instance of a generic chart renderer interface, so v0.3 can add custom charts (Vega-Lite specs, user-supplied JavaScript) without rewriting the rendering pipeline.

## How it works

finch-epm has four layers, each designed to be extended without rewriting the others:

1. **Connectors.** A connector is an adapter for a specific kind of data source. v0.1 ships with a NetSuite connector that uses SuiteQL and the REST metadata APIs. Each connector implements a small abstract interface — `list_dimensions`, `get_hierarchy`, `fetch_facts`, `introspect_schema`, `plan_scope` — that the rest of the system depends on. New connectors are added by implementing the interface; the catalog, cache, and renderer never change.

2. **Catalog.** The catalog is a local DuckDB database that stores the schema discovered by introspection: table names, column types, relationships, dimensional hierarchies, and any user-defined logical names. The catalog is consulted whenever a dashboard query runs, so queries can reference logical names that resolve against the actual underlying schema. Multi-source catalogs (one dashboard pulling from NetSuite and a SQL database simultaneously) are a v0.4 feature, but the catalog schema is designed from v0.1 to support them.

3. **Cache.** The cache is also DuckDB, storing the actual fact and dimension data pulled from the source. Sync is incremental and scoped — finch-epm only pulls the data that dashboards actually need, watermarked by last-modified date where the source supports it. DuckDB handles tens to hundreds of millions of rows comfortably on a laptop. The cache layer exposes a generic "give me results for this query" interface, so v0.3's federated mode (where queries against fast remote backends like Snowflake are pushed down to the source instead of cached locally) plugs in without changing the renderer.

4. **Dashboard runtime.** A small local web server reads the `.fdash` file, resolves logical names against the catalog, executes queries against the cache (or, in federated mode, pushes them down), and renders the results in a browser. Charts are interactive. Filters re-run queries against the local engine, so interactivity is instantaneous. The renderer talks to a chart interface, not to specific chart implementations, so adding custom chart types in v0.3 does not require rewriting any built-in chart.

## Performance

Queries run against a local columnar engine, so typical dashboard interactions — filters, drilldowns, period changes — return in milliseconds. The slow path is the initial sync from the source system, which is bounded by the source's API throughput and rate limits. finch-epm mitigates this with scoped sync, incremental watermarks, and background refresh, so opening a stale dashboard is near-instantaneous to first paint.

DuckDB compresses analytical data well; expect roughly 5-10x compression over raw row data. A few years of GL detail for a mid-sized company is typically a few hundred megabytes on disk. Storage scales with the data you cache, not with the size of the source system.

NetSuite API usage is bounded by your account's governance limits. finch-epm respects these by scoping every sync to exactly what dashboards need and watermarking incremental pulls.

## NetSuite permissions

The setup wizard documents the exact NetSuite permissions required. At minimum, the connecting role needs:

- Token-based authentication enabled
- Read access to the record types you want to query
- Permission to run SuiteQL queries via the REST API

The wizard generates a checklist tailored to the data sources you've selected.

## Roadmap

**v0.1 (current).** NetSuite connector. DuckDB catalog and cache. `.fdash` dashboard format. Eight built-in chart types. Local web renderer. CLI: `setup`, `auth`, `sync`, `open`, `catalog`. Pip install only.

**v0.2.** SQL Server and Postgres connectors. Desktop installer for macOS, Windows, and Linux that bundles Python and finch-epm into a double-clickable application, registers the `.fdash` file association, and gives non-technical users (CFOs, executives) a true email-and-double-click experience. Scheduled background sync. Dashboard parameters and cross-filters.

**v0.3.** Snowflake and BigQuery connectors. Federated query mode: for fast remote backends, push queries down to the source instead of caching locally. Custom chart types via Vega-Lite specs and user-supplied JavaScript. Plugin API for community-contributed chart types.

**v0.4.** Multi-source dashboards: a single `.fdash` file that joins data across NetSuite and a SQL database in the same query. Semantic layer for cross-source logical models. Optional team-shared catalogs for organizations that want them.

**Beyond.** Community connector library. Dashboard sharing conventions and a public dashboard gallery. Optional hosted catalog for teams that want a shared semantic layer without managing local installs.

The architecture in v0.1 is built so that every item on this roadmap can be added without rewriting the core. If something on the roadmap would require changing the Connector interface, the cache layer, the renderer, or the dashboard format in a breaking way, that is a bug in v0.1 and will be fixed before the relevant version ships.

## Contributing

finch-epm is open source under the MIT license. The Connector interface is the most important extension point — if you want to add support for a new data source, implement the interface and submit a pull request. The ChartRenderer interface is the second extension point and will be opened to community contributions in v0.3. See `CONTRIBUTING.md` for details.

## License

MIT
