# Changelog

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
