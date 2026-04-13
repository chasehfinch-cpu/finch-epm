# finch-epm

**Local-first BI that installs in one day and works forever.**

Dashboards share like Excel files. Any LLM can build them. Your data never leaves your network.

finch-epm connects to NetSuite, SQL Server, PostgreSQL, Snowflake, BigQuery, or any ODBC source. It caches everything locally in a fast columnar engine. Dashboards are portable `.fdash` files — send one to a colleague and it renders against their own data using their own credentials. No server, no cloud, no subscriptions.

## How it works

**IT sets it up once.** Connect data sources, sync data, configure the chart of accounts and compilation map. Push the configuration to every machine via GPO, Intune, or a network share. End users never see a terminal.

**Users open dashboards.** Double-click a `.fdash` file. It opens in the browser with live data, filters, and charts. Share it over email, Slack, or Git — the file contains no data, just the layout.

**AI builds dashboards.** Any LLM (Claude, GPT, Gemini, Ollama, or any MCP client) can generate dashboards from a plain-English prompt, grounded in your actual data schema.

## Install

```
pip install finch-epm
```

Requires Python 3.10+. Works on Windows, macOS, and Linux.

For IT deployment across an organization:

```powershell
# Push via Intune, SCCM, or GPO
.\installer\deploy.ps1
```

## For IT administrators

### First-time setup

```
finch-epm setup
```

The wizard walks through:
1. Connecting data sources (NetSuite, SQL Server, etc.)
2. Syncing all data to the local cache (runs in background, ~15-30 min)
3. Auto-generating a chart of accounts from your GL
4. Importing or creating the compilation map that links your data sources

### Compilation map

The compilation map is the single source of truth that links all data sources together. It maps NetSuite Location IDs to SQL Server Divisions through a shared reference table, defines rollup hierarchies (Site -> Group -> State), and configures binary flags (Active, Terminated, CoreFY25).

```
finch-epm map setup          # Interactive: detect reference tables, configure links
finch-epm map show           # View the current map
finch-epm map import map.yaml    # Import a team-shared map
finch-epm map use "\\server\share\compilation_map.yaml"   # Point all users to one shared file
```

### Chart of accounts

The chart of accounts defines how GL accounts roll up into P&L sections. Unlimited hierarchy levels. Importable from YAML, JSON, or CSV templates. Shareable across the team.

```
finch-epm coa setup           # Auto-generate from cached Account data
finch-epm coa import team.yaml    # Import a team template
finch-epm coa show            # View the hierarchy
finch-epm coa edit            # Open in your editor
```

### Silent deployment

Pre-load a configuration bundle so users never run setup:

```
finch-epm setup --config "\\server\share\finch-epm-config\"
```

The config directory contains `compilation_map.yaml`, `coa.yaml`, and `flags.yaml`. Every machine gets the same configuration.

## For end users

### Open a dashboard

Double-click any `.fdash` file. Or from the command line:

```
finch-epm open dashboard.fdash
```

### Generate a dashboard with AI

```
finch-epm ask "build me a P&L dashboard by subsidiary" --open
finch-epm ask "monthly revenue trend" --open
finch-epm ask "top 10 expenses by department" --open
```

Works with any LLM: Anthropic (Claude), OpenAI (GPT), Google (Gemini), Ollama (local), or any OpenAI-compatible endpoint.

### Share a dashboard

Send the `.fdash` file to a colleague. They open it and see the same dashboard rendered against their own data access. No data in the file, no credentials, no server.

## Data sources

| Connector | Authentication | Notes |
|-----------|---------------|-------|
| NetSuite | OAuth 2.0 + certificate | Full SuiteQL access, all record types |
| SQL Server | Username/password | Azure SQL and on-prem |
| PostgreSQL | Username/password | Any Postgres-compatible |
| Snowflake | Username/password | Warehouse, database, schema |
| BigQuery | Service account JSON | Project and dataset |
| Generic ODBC | Connection string | OneStream, SAP, Oracle, Access |

All credentials are stored in the OS keychain (Windows Credential Manager, macOS Keychain, Linux Secret Service). Never written to disk in plaintext.

## Dashboard features

- 10 chart types: bar, line, area, scatter, time series, KPI, table, pivot, variance table, custom (Vega-Lite)
- 7 built-in themes: modern_light, modern_dark, financial, financial_terminal, executive, wsj, monospace
- Multi-page tabbed dashboards with shared filters
- Cross-chart filtering (click a bar to filter all other charts)
- Variance mode: actual vs budget with green/red delta coloring
- Layout control: full, half, third, quarter width
- Brand block: company logo, name, and footer
- Custom CSS injection (scoped to the dashboard)
- Markdown narrative blocks with value substitution
- Print support with color preservation
- Graceful degradation: missing data shows actionable error messages, not blank charts

## MCP server

finch-epm is a first-class MCP server. Claude Desktop, Claude Code, Cursor, and any MCP client can interact with your data catalog and cache.

```json
{
  "mcpServers": {
    "finch-epm": {
      "command": "finch-epm",
      "args": ["mcp"]
    }
  }
}
```

10 tools (list tables, query cache, validate dashboards, etc.) and 4 resources (dashboard spec, catalog, themes, examples). SQL injection protection via sqlglot. See `docs/mcp.md`.

## Architecture

Four layers, each independently extensible:

1. **Connectors** — adapters for each data source (7 built-in, plugin API for more)
2. **Catalog** — DuckDB-backed schema store with access status tracking
3. **Cache** — DuckDB data cache with incremental sync, deduplication, and watermarks
4. **Dashboard** — `.fdash` parser, theme engine, chart renderers, and local web server

The compilation map and chart of accounts sit on top of these layers, providing the business logic that turns raw data into structured financial reports.

## Security

- Credentials in OS keychain, never in plaintext files
- No telemetry, no cloud, no accounts to create
- Data stays on your machine (or your company's network)
- Source-system permissions are respected — finch-epm shows what your role can see
- MCP query_cache tool restricted to read-only SELECT statements

## Development

```
git clone https://github.com/chasehfinch-cpu/finch-epm.git
cd finch-epm
pip install -e ".[dev]"
pytest
```

383 tests. See `CONTRIBUTING.md` for architecture details.

## License

MIT
