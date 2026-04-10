# Contributing to finch-epm

## Architecture

finch-epm has four layers. Each can be extended independently.

```
Connectors          Catalog           Cache             Dashboard
(NetSuite, etc.)    (DuckDB schema)   (DuckDB data)     (web renderer)
      |                  |                |                   |
      v                  v                v                   v
ConnectorBase  -->  CatalogStore  --> LocalCacheEngine --> ChartRenderer
(abstract)          (persists         (ingests data,      (abstract)
                     schema)           tracks watermarks)
```

### Connectors (`src/finch_epm/connectors/`)

A connector adapts a data source to the ConnectorBase interface. Each connector implements seven methods:

- `connect()` / `close()` -- lifecycle
- `validate_credentials()` -- lightweight auth test
- `introspect_schema()` -- discover all tables and columns
- `list_dimensions()` -- enumerate dimensional entities
- `get_hierarchy(dimension_name)` -- parent-child trees
- `plan_scope(ScopeDescription)` -- translate a generic scope to a native fetch plan
- `fetch_facts(FetchPlan)` -- execute the plan and return tabular data

The `@register_connector` decorator auto-registers a connector by its `connector_type` class variable.

### Catalog (`src/finch_epm/catalog/`)

The CatalogStore persists introspection results in `catalog.duckdb`. Tables: `catalog_sources`, `catalog_tables`, `catalog_columns`, `catalog_dimensions`. The catalog tracks access status (accessible, restricted, not_found) for every record type.

### Cache (`src/finch_epm/cache/`)

The LocalCacheEngine stores synced data in `cache.duckdb`. The SyncEngine orchestrates pulling data from connectors into the cache, table by table, with watermark-based incremental sync.

### Dashboard (`src/finch_epm/dashboard/`)

The ChartRenderer interface defines how each chart type produces output. Eight built-in types are registered as stubs. The web server and rendering pipeline are not yet implemented.

## Directory structure

```
src/finch_epm/
    __init__.py                  Version string
    paths.py                     Platform-appropriate data/config/cache directories
    connectors/
        base.py                  ConnectorBase ABC
        types.py                 Shared data structures (SchemaInfo, FactResult, etc.)
        registry.py              Connector type registry
        fake.py                  In-memory test connector
        netsuite/
            connector.py         NetSuite ConnectorBase implementation
            auth.py              OAuth 2.0 certificate auth (JWT signing)
            suiteql.py           SuiteQL query execution with pagination
            metadata.py          REST metadata-catalog client
            records.py           Exhaustive registry of all NetSuite record types
    catalog/
        catalog.py               CatalogStore (DuckDB-backed)
        migrations.py            Schema creation for catalog tables
    cache/
        base.py                  CacheEngine ABC
        local.py                 LocalCacheEngine (DuckDB-backed)
        models.py                QueryRequest, QueryResult, SyncWatermark, SyncReport
        sync.py                  SyncEngine (incremental sync orchestrator)
    dashboard/
        renderer/
            base.py              ChartRenderer ABC
            registry.py          Chart type registry
            builtins.py          Eight built-in chart type stubs
            types.py             RenderContext, RenderOutput
    profiles/
        manager.py               Named profiles + OS keychain integration
    cli/
        main.py                  Click CLI (setup, auth, sync, open, catalog)
    server/
        app.py                   Local web server (placeholder)
```

## Adding a new connector

1. Create a new directory under `src/finch_epm/connectors/` (e.g., `sqlserver/`).
2. Implement a class that inherits from `ConnectorBase`.
3. Set `connector_type` and `display_name` as class variables.
4. Implement all seven abstract methods.
5. Decorate the class with `@register_connector`.
6. Add tests in `tests/` that exercise the full interface.
7. Update `cli/main.py` `_make_connector()` to import the new module.

The FakeConnector (`connectors/fake.py`) is a complete reference implementation.

## Adding a new chart type

1. Create a class that inherits from `ChartRenderer`.
2. Set `chart_type` and `display_name` as class variables.
3. Implement `validate_spec()`, `render()`, and optionally `get_required_columns()`.
4. Register it with `register_chart(YourRenderer())` in `builtins.py` or a new file.

## Testing

```
pip install -e ".[dev]"
pytest
```

All tests use the FakeConnector with in-memory DuckDB databases. No external services are needed to run the test suite. Tests against live NetSuite require credentials and are not included in the automated suite.

Key test files:

- `test_connector_interface.py` -- contract tests that any ConnectorBase must pass
- `test_fake_connector.py` -- validates the built-in test data
- `test_netsuite_auth.py` -- OAuth 2.0 JWT construction (no live calls)
- `test_catalog_store.py` -- CatalogStore CRUD operations
- `test_sync_engine.py` -- SyncEngine with FakeConnector
- `test_cache.py` -- LocalCacheEngine ingest, query, watermarks
- `test_chart_renderer.py` -- renderer registration and validation
- `test_profiles.py` -- profile config persistence

## Code style

- Python 3.10+ with type hints throughout
- `ruff` for linting (100-char line length)
- `mypy` in strict mode
- Frozen dataclasses for all value types passed between layers
- No emojis in code, comments, or documentation
