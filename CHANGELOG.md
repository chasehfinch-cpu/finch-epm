# Changelog

## v0.1.0-dev (2026-04-10)

Initial development release. Data pipeline is functional; dashboard UI is not yet built.

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
- **96 automated tests**: Full coverage of connector interface, catalog store, sync engine, cache, chart renderers, profiles, and NetSuite auth JWT construction.
- **Platform paths**: Uses `platformdirs` for all file storage. No hardcoded paths. Compatible with future PyInstaller/Briefcase bundling.

### Known limitations

- SuiteQL returns a maximum of 100,000 rows per query. Tables larger than this require multiple incremental syncs.
- Cache inserts data row by row. Batch insert optimization planned.
- All synced data is stored as VARCHAR in DuckDB. Type-aware column creation from catalog metadata is planned.
- Dashboard parser, web server, and chart rendering are not yet implemented.
