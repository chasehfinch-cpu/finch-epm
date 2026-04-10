# Changelog

## v0.3.0 (2026-04-10)

### Added

- **Multi-page tabbed dashboards**: single .fdash file with multiple `pages`, each with its own charts. Tab bar navigation, shared queries and filters across all pages.
- **Variance table chart type**: side-by-side actual vs budget with automatic Variance $ and Variance % calculation. Green/red color coding for favorable vs unfavorable.
- **Custom chart type (Vega-Lite)**: embed any Vega-Lite specification in a .fdash file. Query data auto-injected. Vega + Vega-Lite + Vega-Embed bundled locally for offline use.
- **Snowflake connector**: via snowflake-connector-python. INFORMATION_SCHEMA introspection. Account, warehouse, database, schema as connection params.
- **BigQuery connector**: via google-cloud-bigquery. Service account JSON stored in OS keychain. INFORMATION_SCHEMA introspection.
- **Generic ODBC connector**: works with any ODBC data source (OneStream, SAP, Oracle, Access). User-supplied connection string.
- **Background sync service**: atomic cache swap pattern (sync writes to staging, then replaces main cache). No file locking conflicts between sync and dashboard. CLI: `finch-epm service` runs continuously or `--once` for schedulers.
- **OS task scheduler integration**: setup wizard registers Windows Task Scheduler, macOS launchd, or Linux cron for automatic background sync.
- **Concurrent sync + dashboard**: dashboard opens cache read-only with temp file fallback when sync is writing.
- **Dashboard-level filters**: dropdown filters defined in .fdash that re-execute all queries on selection.
- **Cross-chart filtering**: click a data point to filter all other charts. Badge shows active filter.
- **CSV export**: every chart card has a CSV download button.
- **IT deployment script**: PowerShell script for remote deployment via Intune/SCCM/GPO. Installs Python, finch-epm, registers file association, sets up scheduled sync, creates desktop shortcut.
- **Desktop installer infrastructure**: PyInstaller spec file (onedir), entry point wrapper, .fdash file association registration, build script.
- **Configurable P&L engine**: user-defined chart of accounts hierarchy via YAML. Default and healthcare-specific examples.
- **Dimension mapping layer**: YAML-based configuration for rollup hierarchies, binary flag filters, and cross-source joins.
- **Data truncation warnings**: sync reports exact row counts when source data exceeds query limits.
- **Permission documentation**: setup wizard shows prerequisite checklist per connector before asking for credentials.
- **Better error handling**: dashboard shows "data not synced" message instead of blank charts. Open command catches file locks, port conflicts, invalid .fdash files.
- **Professional UI styling**: refined cards, typography, tab bar, filter bar, table formatting.
- **40 user walkthrough tests**: comprehensive end-to-end verification of every user path.
- **GETTING_STARTED.md**: complete onboarding guide from install to sharing dashboards.

### Changed

- Chart type count: 8 -> 10 (added variance_table and custom).
- Connector count: 4 -> 7 (added Snowflake, BigQuery, Generic ODBC).
- Test count: 125 unit tests + 40 walkthrough tests = 165 total.
- Setup wizard completely rewritten: shows prerequisites, starts background sync, prints instruction guide.
- DuckDB cache opens read-only for dashboards with temp file fallback.

## v0.2.1-dev (2026-04-10)

### Added

- **PostgreSQL connector**: Full ConnectorBase implementation via psycopg2. INFORMATION_SCHEMA-based introspection, heuristic dimension detection, pg-specific type mapping. Supports standard PostgreSQL and cloud-hosted instances (AWS RDS, Azure, Google Cloud SQL).
- **Multi-series charts**: `y` field accepts a list of column names for bar, line, area, and time series charts. Each series gets its own color and legend entry.
- **Color customization**: `colors` field (list of hex strings) for per-series colors. `color` field (single string) for single-series and KPI tiles. Default 8-color palette when no colors specified.
- **Chart sizing**: `height` field (integer, pixels) and `width` field ("full" or "half") on any chart type. KPI tiles auto-size to their content.
- **KPI formatting**: `format` ("currency", "percent", "number"), `prefix`, `suffix`, and `color` fields on KPI tiles.
- **Table column formatting**: `columns` field with per-column format specs for currency, percent, and number display.
- **DASHBOARDS.md**: Complete AI-readable specification for the .fdash dashboard format. Designed to be pasted into ChatGPT, Claude, or any AI assistant to generate valid dashboards. Documents all 8 chart types with every field, SQL patterns for common dashboards, and rules for AI generators.
- **Better axis formatting**: Large numbers auto-format as K/M on chart axes.
- **Legend support**: Automatic legend for multi-series charts.

### Changed

- Test count increased from 115 to 125.
- ECharts rendering refactored: two-phase init (DOM insertion, then chart creation) fixes blank chart issue.
- Optional dependency for PostgreSQL: `pip install finch-epm[postgres]`.

## v0.2.0-dev (2026-04-10)

### Added

- **SQL Server connector**: Full ConnectorBase implementation via pyodbc. INFORMATION_SCHEMA-based introspection, heuristic dimension detection, T-SQL queries. Supports Azure SQL and on-premises SQL Server.
- **SQL Server authentication**: Connection string built from credentials stored in OS keychain. Auto-detects ODBC driver. Azure SQL encryption enabled automatically.
- **SQL Server CLI support**: `finch-epm auth -c sqlserver` imports credentials from .env files containing AZURE_SQL_SERVER, AZURE_SQL_DATABASE, AZURE_SQL_USER, AZURE_SQL_PASSWORD.
- **Batch insert optimization**: Cache ingestion now uses DuckDB's executemany() instead of row-by-row insert. Orders of magnitude faster for large syncs.
- **Dashboard web server**: Built-in Python HTTP server (zero extra dependencies) serves dashboards as single-page apps.
- **Dashboard frontend**: Interactive charts via Apache ECharts (bundled locally, works offline). All 8 chart types implemented: table, bar, line, area, scatter, time series, KPI tile, pivot table.
- **.fdash parser**: Full YAML parser with validation against registered chart renderers. Typed DashboardSpec, QuerySpec, ChartSpec, ParameterSpec models.
- **Dashboard resolver**: Executes dashboard queries against the cache with parameter substitution. Supports period parameters (current_quarter_start, current_year_end, etc.).
- **CLI open command**: `finch-epm open dashboard.fdash` starts a local server and opens the dashboard in the browser.
- **CLI setup wizard**: Interactive guided setup for connector authentication and schema crawling.
- **Auto-refresh**: Dashboards poll for data changes every 30 seconds and re-render automatically.
- **Staleness indicators**: Every query result shows when data was last synced.
- **Optional dependency**: SQL Server connector installed via `pip install finch-epm[sqlserver]`.

### Changed

- Test count increased from 96 to 115.
- Chart renderer builtins now produce real ECharts configurations instead of placeholder HTML.

## v0.1.0-dev (2026-04-10)

Initial development release.

### Added

- **Connector framework**: Abstract base class (`ConnectorBase`) with registry pattern. Seven abstract methods define the interface for all data sources.
- **FakeConnector**: In-memory test connector with GL-like sample data (gl_detail, subsidiary, account tables with hierarchies). Used by all automated tests.
- **NetSuite connector**: Full implementation with OAuth 2.0 certificate authentication (ES256/PS256), SuiteQL query execution with pagination and rate-limit handling, REST metadata-catalog integration, and exhaustive schema introspection covering 200+ standard record types.
- **Record type registry**: Comprehensive catalog of all known NetSuite SuiteQL table names organized by category (transaction, entity, item, dimension, accounting, etc.). Each record is probed live and assigned an access status.
- **Custom segment discovery**: Dynamically discovers company-specific NetSuite custom segments as additional dimensions.
- **Catalog store**: DuckDB-backed persistent schema catalog. Stores tables, columns, dimensions, and access status. Survives between CLI sessions.
- **Cache engine**: DuckDB-backed local data cache with watermark tracking for incremental sync, staleness detection for the render-first pattern, and a generic query interface that does not expose whether results come from local storage or a remote source.
- **Sync engine**: Orchestrates data sync from connectors into the cache, table by table. Supports full and incremental modes. Partial failures do not lose already-synced data.
- **Profile manager**: Named credential profiles stored in the OS keychain via `keyring`. Non-secret config (account IDs, client IDs) stored in a JSON file under the platform-appropriate user data directory.
- **Chart renderer interface**: Abstract base class with registry pattern. Eight built-in types registered as stubs (table, bar, line, area, kpi, pivot, timeseries, scatter).
- **CLI**: `auth` (credential import and validation), `catalog` (crawl, list tables, list columns, list dimensions), `sync` (specific tables, all accessible, incremental/full).
- **Platform paths**: Uses `platformdirs` for all file storage. No hardcoded paths. Compatible with future PyInstaller/Briefcase bundling.

### Known limitations

- SuiteQL returns a maximum of 100,000 rows per query. Tables larger than this require multiple incremental syncs.
- All synced data from NetSuite is stored as VARCHAR in DuckDB. Type-aware column creation from catalog metadata is planned.
