"""finch-epm CLI entry point.

Subcommands: setup, auth, sync, open, catalog.
"""

from __future__ import annotations

from pathlib import Path
from typing import Type

import click

from finch_epm import __version__
from finch_epm.connectors.base import ConnectorBase


def _make_connector(connector_type: str, profile_name: str) -> ConnectorBase:
    """Import a connector module and return an instance.

    Importing the module triggers the @register_connector decorator
    which populates the registry.
    """
    _CONNECTOR_IMPORTS = {
        "netsuite": "finch_epm.connectors.netsuite.connector",
        "sqlserver": "finch_epm.connectors.sqlserver.connector",
        "postgres": "finch_epm.connectors.postgres.connector",
        "snowflake": "finch_epm.connectors.snowflake.connector",
        "bigquery": "finch_epm.connectors.bigquery.connector",
        "odbc": "finch_epm.connectors.odbc.connector",
        "fake": "finch_epm.connectors.fake",
    }
    import importlib
    module_path = _CONNECTOR_IMPORTS.get(connector_type)
    if module_path:
        importlib.import_module(module_path)
    else:
        raise click.ClickException(
            f"Unknown connector type: {connector_type}. "
            f"Available: {', '.join(sorted(_CONNECTOR_IMPORTS.keys()))}"
        )

    from finch_epm.connectors.registry import get_connector_class
    cls = get_connector_class(connector_type)
    return cls(profile_name)


@click.group()
@click.version_option(version=__version__, prog_name="finch-epm")
def cli() -> None:
    """finch-epm: Local-first portable analytics for EPM and database systems."""


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--connector", "-c", help="Connector type (e.g. netsuite)")
@click.option("--profile", "-p", help="Profile name")
@click.option(
    "--env-file",
    type=click.Path(exists=True, dir_okay=False),
    help="Path to .env file for one-time credential import",
)
@click.option(
    "--key-file",
    type=click.Path(exists=True, dir_okay=False),
    help="Path to private key PEM file (for NetSuite OAuth 2.0)",
)
@click.option("--validate", is_flag=True, help="Validate stored credentials")
def auth(
    connector: str | None,
    profile: str | None,
    env_file: str | None,
    key_file: str | None,
    validate: bool,
) -> None:
    """Authenticate with a data source.

    Import credentials from a .env file into the OS keychain:

        finch-epm auth -c netsuite -p myprofile --env-file /path/to/.env --key-file /path/to/key.pem

    After import, the .env and key file are never needed again.
    Validate stored credentials:

        finch-epm auth -c netsuite -p myprofile --validate
    """
    if connector is None:
        connector = click.prompt(
            "Connector type",
            type=click.Choice(["netsuite"]),
            default="netsuite",
        )

    if profile is None:
        profile = click.prompt("Profile name", default="default")

    if validate:
        _validate_credentials(connector, profile)
        return

    if env_file:
        _import_credentials(connector, profile, env_file, key_file)
    else:
        click.echo(
            "Use --env-file to import credentials from a .env file, "
            "or --validate to test stored credentials."
        )


def _import_credentials(
    connector: str,
    profile: str,
    env_file: str,
    key_file: str | None,
) -> None:
    """Read .env + key file once, store everything in keyring."""
    from finch_epm.profiles.manager import ProfileManager

    pm = ProfileManager()

    env_path = Path(env_file)
    env_vars: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            value = value.strip().strip("'\"")
            env_vars[key.strip()] = value

    env_vars["_env_dir"] = str(env_path.parent.resolve())

    if connector == "netsuite":
        _import_netsuite(pm, profile, env_vars, key_file)
    elif connector == "sqlserver":
        _import_sqlserver(pm, profile, env_vars)
    elif connector == "postgres":
        _import_postgres(pm, profile, env_vars)
    else:
        click.echo(f"Credential import not yet supported for: {connector}")


def _import_netsuite(
    pm: "ProfileManager",
    profile: str,
    env_vars: dict[str, str],
    key_file: str | None,
) -> None:
    """Import NetSuite credentials into keyring."""
    required = ["NS_ACCOUNT_ID", "NS_CLIENT_ID", "NS_CERTIFICATE_ID"]
    missing = [k for k in required if k not in env_vars]
    if missing:
        click.echo(f"Error: Missing required keys in .env: {', '.join(missing)}")
        raise SystemExit(1)

    account_id = env_vars["NS_ACCOUNT_ID"]
    client_id = env_vars["NS_CLIENT_ID"]
    certificate_id = env_vars["NS_CERTIFICATE_ID"]

    key_path_str = key_file or env_vars.get("NS_PRIVATE_KEY_PATH")
    if not key_path_str:
        click.echo(
            "Error: No private key. Provide --key-file or set "
            "NS_PRIVATE_KEY_PATH in the .env file."
        )
        raise SystemExit(1)

    key_path = Path(key_path_str)
    if not key_path.is_absolute():
        env_dir = Path(env_vars.get("_env_dir", "."))
        key_path = env_dir / key_path

    if not key_path.exists():
        click.echo(f"Error: Private key file not found: {key_path}")
        raise SystemExit(1)

    private_key_pem = key_path.read_text(encoding="utf-8")

    try:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    except Exception as e:
        click.echo(f"Error: Invalid private key file: {e}")
        raise SystemExit(1)

    pm.set_config("netsuite", profile, {
        "account_id": account_id,
        "client_id": client_id,
        "certificate_id": certificate_id,
    })
    pm.set_secret("netsuite", profile, "private_key_pem", private_key_pem)

    click.echo(f"NetSuite credentials stored for profile '{profile}':")
    click.echo(f"  Account ID:     {account_id}")
    click.echo(f"  Client ID:      {client_id[:8]}...{client_id[-4:]}")
    click.echo(f"  Certificate ID: {certificate_id[:8]}...{certificate_id[-4:]}")
    click.echo(f"  Private key:    stored in OS keychain ({len(private_key_pem)} bytes)")
    click.echo()
    click.echo("The .env and key files are no longer needed by finch-epm.")
    click.echo(f"Run 'finch-epm auth -c netsuite -p {profile} --validate' to test.")


def _import_sqlserver(
    pm: "ProfileManager",
    profile: str,
    env_vars: dict[str, str],
) -> None:
    """Import SQL Server credentials into keyring."""
    # Map env var names (support both AZURE_SQL_* and generic SQL_* patterns)
    server = env_vars.get("AZURE_SQL_SERVER", env_vars.get("SQL_SERVER", ""))
    database = env_vars.get("AZURE_SQL_DATABASE", env_vars.get("SQL_DATABASE", ""))
    username = env_vars.get("AZURE_SQL_USER", env_vars.get("SQL_USER", ""))
    password = env_vars.get("AZURE_SQL_PASSWORD", env_vars.get("SQL_PASSWORD", ""))

    if not server:
        click.echo("Error: Missing AZURE_SQL_SERVER (or SQL_SERVER) in .env")
        raise SystemExit(1)
    if not database:
        click.echo("Error: Missing AZURE_SQL_DATABASE (or SQL_DATABASE) in .env")
        raise SystemExit(1)
    if not password:
        click.echo("Error: Missing AZURE_SQL_PASSWORD (or SQL_PASSWORD) in .env")
        raise SystemExit(1)

    # Store non-secret config
    pm.set_config("sqlserver", profile, {
        "server": server,
        "database": database,
        "username": username,
    })

    # Store password in OS keychain
    pm.set_secret("sqlserver", profile, "password", password)

    click.echo(f"SQL Server credentials stored for profile '{profile}':")
    click.echo(f"  Server:   {server}")
    click.echo(f"  Database: {database}")
    click.echo(f"  Username: {username}")
    click.echo(f"  Password: stored in OS keychain")
    click.echo()
    click.echo("The .env file is no longer needed by finch-epm.")
    click.echo(f"Run 'finch-epm auth -c sqlserver -p {profile} --validate' to test.")


def _import_postgres(
    pm: "ProfileManager",
    profile: str,
    env_vars: dict[str, str],
) -> None:
    """Import PostgreSQL credentials into keyring."""
    host = env_vars.get("PG_HOST", env_vars.get("POSTGRES_HOST", "localhost"))
    port = env_vars.get("PG_PORT", env_vars.get("POSTGRES_PORT", "5432"))
    database = env_vars.get("PG_DATABASE", env_vars.get("POSTGRES_DATABASE", ""))
    username = env_vars.get("PG_USER", env_vars.get("POSTGRES_USER", ""))
    password = env_vars.get("PG_PASSWORD", env_vars.get("POSTGRES_PASSWORD", ""))

    if not database:
        click.echo("Error: Missing PG_DATABASE (or POSTGRES_DATABASE) in .env")
        raise SystemExit(1)
    if not password:
        click.echo("Error: Missing PG_PASSWORD (or POSTGRES_PASSWORD) in .env")
        raise SystemExit(1)

    pm.set_config("postgres", profile, {
        "host": host,
        "port": port,
        "database": database,
        "username": username,
    })
    pm.set_secret("postgres", profile, "password", password)

    click.echo(f"PostgreSQL credentials stored for profile '{profile}':")
    click.echo(f"  Host:     {host}:{port}")
    click.echo(f"  Database: {database}")
    click.echo(f"  Username: {username}")
    click.echo(f"  Password: stored in OS keychain")
    click.echo()
    click.echo("The .env file is no longer needed by finch-epm.")
    click.echo(f"Run 'finch-epm auth -c postgres -p {profile} --validate' to test.")


def _validate_credentials(connector: str, profile: str) -> None:
    """Test stored credentials against the live service."""
    from finch_epm.profiles.manager import ProfileManager

    pm = ProfileManager()

    if not pm.profile_exists(connector, profile):
        click.echo(f"Error: No profile found: {connector}/{profile}")
        click.echo("Run 'finch-epm auth' with --env-file to import credentials first.")
        raise SystemExit(1)

    if connector == "netsuite":
        config = pm.get_config("netsuite", profile)
        private_key = pm.get_secret("netsuite", profile, "private_key_pem")

        if not private_key:
            click.echo("Error: Private key not found in OS keychain.")
            click.echo("Re-import with: finch-epm auth -c netsuite --env-file ...")
            raise SystemExit(1)

        click.echo(f"Validating NetSuite credentials for profile '{profile}'...")
        from finch_epm.connectors.netsuite.auth import (
            NetSuiteAuthenticator,
            NetSuiteCredentials,
        )

        creds = NetSuiteCredentials(
            account_id=config["account_id"],
            client_id=config["client_id"],
            certificate_id=config["certificate_id"],
        )
        authenticator = NetSuiteAuthenticator(creds, private_key)

        if authenticator.validate():
            click.echo("Credentials are valid. Access token obtained successfully.")
        else:
            click.echo("Credential validation failed. Check your NetSuite configuration.")
            raise SystemExit(1)

        authenticator.close()
    elif connector in ("sqlserver", "postgres"):
        label = "SQL Server" if connector == "sqlserver" else "PostgreSQL"
        click.echo(f"Validating {label} credentials for profile '{profile}'...")
        conn = _make_connector(connector, profile)
        try:
            conn.connect()
            if conn.validate_credentials():
                click.echo("Credentials are valid. Connection successful.")
            else:
                click.echo("Credential validation failed.")
                raise SystemExit(1)
        except Exception as e:
            click.echo(f"Connection failed: {e}")
            raise SystemExit(1)
        finally:
            conn.close()
    else:
        click.echo(f"Validation not yet supported for: {connector}")


# ---------------------------------------------------------------------------
# catalog
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--connector", "-c", required=True, help="Connector type (e.g. netsuite)")
@click.option("--profile", "-p", required=True, help="Profile name")
@click.option("--crawl", is_flag=True, help="Run introspection and save to catalog")
@click.option("--tables", is_flag=True, help="List cataloged tables")
@click.option("--columns", help="List columns for a specific table")
@click.option("--dimensions", is_flag=True, help="List cataloged dimensions")
@click.option("--accessible-only", is_flag=True, help="Show only accessible tables")
def catalog(
    connector: str,
    profile: str,
    crawl: bool,
    tables: bool,
    columns: str | None,
    dimensions: bool,
    accessible_only: bool,
) -> None:
    """Browse or update the local schema catalog.

    Crawl (introspect and save):

        finch-epm catalog --crawl -c netsuite -p myprofile

    List tables:

        finch-epm catalog --tables -c netsuite -p myprofile
        finch-epm catalog --tables --accessible-only -c netsuite -p myprofile

    List columns for a table:

        finch-epm catalog --columns Transaction -c netsuite -p myprofile

    List dimensions:

        finch-epm catalog --dimensions -c netsuite -p myprofile
    """
    from finch_epm.catalog.catalog import CatalogStore
    from finch_epm.paths import catalog_db_path

    if crawl:
        _catalog_crawl(connector, profile)
        return

    # Read operations — open catalog
    store = CatalogStore(str(catalog_db_path()))
    try:
        source = store.get_source(connector, profile)
        if source is None:
            click.echo(
                f"No catalog found for {connector}/{profile}. "
                "Run 'finch-epm catalog --crawl' first."
            )
            raise SystemExit(1)

        if tables:
            status_filter = "accessible" if accessible_only else None
            rows = store.list_tables(connector, profile, access_status=status_filter)
            if not rows:
                click.echo("No tables found.")
                return
            click.echo(f"{'Table':<40} {'Status':<12} {'Category':<15} {'Rows':>10}")
            click.echo("-" * 80)
            for r in rows:
                row_count = r["row_count_estimate"]
                row_str = f"{row_count:>10,}" if row_count else "         -"
                click.echo(
                    f"{r['table_name']:<40} {r['access_status']:<12} "
                    f"{r['category']:<15} {row_str}"
                )
            click.echo(f"\nTotal: {len(rows)} tables")

        elif columns:
            cols = store.list_columns(connector, profile, columns)
            if not cols:
                click.echo(f"No columns found for table '{columns}'.")
                return
            click.echo(f"Columns for {columns}:")
            click.echo(f"  {'Column':<35} {'Type':<12} {'Custom':>6}")
            click.echo("  " + "-" * 55)
            for c in cols:
                custom_flag = "yes" if c["is_custom"] else ""
                click.echo(
                    f"  {c['column_name']:<35} {c['column_type']:<12} {custom_flag:>6}"
                )
            click.echo(f"\n  Total: {len(cols)} columns")

        elif dimensions:
            dims = store.list_dimensions(connector, profile)
            if not dims:
                click.echo("No dimensions found.")
                return
            click.echo(f"{'Dimension':<25} {'Table':<25} {'Hierarchy':>10}")
            click.echo("-" * 62)
            for d in dims:
                hier = "yes" if d["supports_hierarchy"] else "no"
                click.echo(
                    f"{d['dimension_name']:<25} {d['table_name']:<25} {hier:>10}"
                )

        else:
            click.echo("Specify --tables, --columns TABLE, or --dimensions. Use --help for details.")
    finally:
        store.close()


def _catalog_crawl(connector: str, profile: str) -> None:
    """Run introspection and save results to the catalog."""
    from finch_epm.catalog.catalog import CatalogStore
    from finch_epm.paths import catalog_db_path

    click.echo(f"Connecting to {connector}/{profile}...")
    conn = _make_connector(connector, profile)
    conn.connect()

    try:
        click.echo("Introspecting schema (this may take a few minutes)...")
        schema = conn.introspect_schema()

        click.echo("Discovering dimensions...")
        dims = conn.list_dimensions()

        store = CatalogStore(str(catalog_db_path()))
        try:
            store.save_schema(schema)
            store.save_dimensions(schema.source_name, schema.profile_name, dims)

            accessible = sum(
                1 for t in schema.tables
                if t.metadata.get("access_status") == "accessible"
            )
            restricted = sum(
                1 for t in schema.tables
                if t.metadata.get("access_status") == "restricted"
            )

            click.echo(f"\nCatalog saved:")
            click.echo(f"  Total records:  {len(schema.tables)}")
            click.echo(f"  Accessible:     {accessible}")
            click.echo(f"  Restricted:     {restricted}")
            click.echo(f"  Dimensions:     {len(dims)}")
            click.echo(
                f"\nRun 'finch-epm catalog --tables -c {connector} -p {profile}' "
                "to browse."
            )
        finally:
            store.close()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--connector", "-c", required=True, help="Connector type")
@click.option("--profile", "-p", required=True, help="Profile name")
@click.option("--tables", "-t", multiple=True, help="Tables to sync")
@click.option("--all", "sync_all", is_flag=True, help="Sync all accessible tables")
@click.option(
    "--incremental/--full",
    default=True,
    help="Incremental (default) or full sync",
)
def sync(
    connector: str,
    profile: str,
    tables: tuple[str, ...],
    sync_all: bool,
    incremental: bool,
) -> None:
    """Sync data from a source into the local cache.

    Sync specific tables:

        finch-epm sync -c netsuite -p myprofile -t Account -t Subsidiary

    Sync all accessible tables:

        finch-epm sync -c netsuite -p myprofile --all

    Full sync (replace cached data):

        finch-epm sync -c netsuite -p myprofile -t Account --full
    """
    from finch_epm.cache.local import LocalCacheEngine
    from finch_epm.cache.sync import SyncEngine
    from finch_epm.catalog.catalog import CatalogStore
    from finch_epm.paths import cache_db_path, catalog_db_path

    if not tables and not sync_all:
        click.echo("Error: specify tables with -t or use --all.")
        raise SystemExit(1)

    mode = "incremental" if incremental else "full"

    click.echo(f"Connecting to {connector}/{profile}...")
    conn = _make_connector(connector, profile)
    conn.connect()

    cache = LocalCacheEngine(str(cache_db_path()))
    catalog_store = CatalogStore(str(catalog_db_path())) if sync_all else None

    try:
        engine = SyncEngine(conn, cache, catalog_store)

        def on_progress(table: str, rows: int) -> None:
            click.echo(f"  {table}: {rows:,} rows synced")

        click.echo(f"Syncing ({mode} mode)...")

        if sync_all:
            report = engine.sync_all_accessible(mode, progress_callback=on_progress)
        else:
            report = engine.sync_tables(list(tables), mode, progress_callback=on_progress)

        click.echo(f"\nSync complete:")
        click.echo(f"  Tables synced:  {report.tables_synced}")
        click.echo(f"  Tables failed:  {report.tables_failed}")
        click.echo(f"  Total rows:     {report.total_rows:,}")
        click.echo(f"  Elapsed:        {report.elapsed_seconds:.1f}s")

        # Warn about truncated tables
        truncated = [r for r in report.per_table if r.truncated]
        if truncated:
            click.echo("\nWARNING -- Data truncation detected:")
            for r in truncated:
                total = f"{r.total_available:,}" if r.total_available else "unknown"
                click.echo(
                    f"  {r.table_name}: synced {r.rows_synced:,} of {total} rows"
                )
            click.echo(
                "\n  The data source limits how many rows can be fetched per query."
                "\n  To get more data, run sync again with --incremental to fetch"
                "\n  newer rows, or sync specific date ranges in your .fdash queries."
            )

        if report.errors:
            click.echo("\nErrors:")
            for err in report.errors:
                click.echo(f"  {err}")

    finally:
        conn.close()
        cache.close()
        if catalog_store:
            catalog_store.close()


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------


@cli.command(name="import")
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--table", "-t", help="Table name in the cache (default: filename)")
@click.option("--sheet", "-s", help="Excel sheet name (default: active sheet)")
def import_file(file_path: str, table: str | None, sheet: str | None) -> None:
    """Import a CSV or Excel file into the local cache.

    The file becomes a queryable table in dashboards, alongside
    data synced from NetSuite, SQL Server, or PostgreSQL.

        finch-epm import budget_2024.csv
        finch-epm import reference.xlsx --sheet Locations --table locations
        finch-epm import forecast.xlsx --sheet Q4 --table forecast_q4

    After import, use the table name in .fdash SQL queries.
    """
    from pathlib import Path as P

    from finch_epm.cache.local import LocalCacheEngine
    from finch_epm.paths import cache_db_path

    path = P(file_path)
    cache = LocalCacheEngine(str(cache_db_path()))

    try:
        if path.suffix.lower() == ".csv":
            from finch_epm.connectors.file.connector import import_csv
            rows = import_csv(path, cache, table_name=table)
        elif path.suffix.lower() in (".xlsx", ".xls"):
            from finch_epm.connectors.file.connector import import_excel
            if sheet is None and path.suffix.lower() in (".xlsx", ".xls"):
                from finch_epm.connectors.file.connector import list_excel_sheets
                sheets = list_excel_sheets(path)
                if len(sheets) > 1:
                    click.echo(f"Available sheets: {', '.join(sheets)}")
                    sheet = click.prompt("Which sheet?", type=click.Choice(sheets))
            rows = import_excel(path, cache, sheet_name=sheet, table_name=table)
        else:
            click.echo(f"Unsupported file type: {path.suffix}")
            click.echo("Supported: .csv, .xlsx")
            raise SystemExit(1)

        final_name = table or path.stem.replace(" ", "_").replace("-", "_")
        click.echo(f"Imported {rows:,} rows into table '{final_name}'")
        click.echo(f"Query it in .fdash SQL: SELECT * FROM {final_name}")
    finally:
        cache.close()


# ---------------------------------------------------------------------------
# open
# ---------------------------------------------------------------------------


@cli.command(name="open")
@click.argument("dashboard", type=click.Path(exists=True))
@click.option("--port", default=8765, help="Local server port")
@click.option("--no-browser", is_flag=True, help="Don't open browser automatically")
def open_dashboard(dashboard: str, port: int, no_browser: bool) -> None:
    """Open a .fdash dashboard in the browser.

    Starts a local web server and renders the dashboard against
    cached data. Ctrl+C stops the server.

        finch-epm open path/to/dashboard.fdash
        finch-epm open dashboard.fdash --port 9000 --no-browser
    """
    from finch_epm.cache.local import LocalCacheEngine
    from finch_epm.paths import cache_db_path
    from finch_epm.server.app import DashboardServer

    try:
        # Open cache in read-only mode so sync can run concurrently
        cache = LocalCacheEngine(str(cache_db_path()), read_only=True)
    except Exception as e:
        if "being used by another process" in str(e):
            click.echo(
                "Error: Cache database is locked by another process.\n"
                "Close any running sync or dashboard server first."
            )
        else:
            click.echo(f"Error opening cache database: {e}")
        raise SystemExit(1)

    try:
        from finch_epm.dashboard.fdash import FdashError
        server = DashboardServer(dashboard, cache)
        server.start(port=port, open_browser=not no_browser)
    except FdashError as e:
        click.echo(f"Invalid dashboard file: {e}")
        raise SystemExit(1)
    except OSError as e:
        if "Address already in use" in str(e) or "Only one usage" in str(e):
            click.echo(
                f"Error: Port {port} is already in use.\n"
                f"Try a different port: finch-epm open {dashboard} --port {port + 1}"
            )
        else:
            click.echo(f"Server error: {e}")
        raise SystemExit(1)
    finally:
        cache.close()


# ---------------------------------------------------------------------------
# service
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--interval", default=15, help="Sync interval in minutes (default 15)")
@click.option("--once", is_flag=True, help="Run one sync cycle and exit")
def service(interval: int, once: bool) -> None:
    """Run the background sync service.

    Keeps the local cache warm by syncing all configured data sources
    on a schedule. The dashboard reads from the cache and never waits.

    Run continuously:

        finch-epm service
        finch-epm service --interval 5

    Run once (for task scheduler / cron):

        finch-epm service --once
    """
    from finch_epm.cache.service import run_service, run_sync_cycle

    if once:
        click.echo("Running one sync cycle...")
        report = run_sync_cycle()
        total = sum(p.get("total_rows", 0) for p in report.get("profiles", []))
        errors = sum(len(p.get("errors", [])) for p in report.get("profiles", []))
        click.echo(f"Complete: {total:,} rows synced, {errors} errors")
        for p in report.get("profiles", []):
            if p.get("errors"):
                for e in p["errors"]:
                    click.echo(f"  {p['connector']}/{p['profile']}: {e}")
    else:
        try:
            run_service(interval_minutes=interval)
        except KeyboardInterrupt:
            click.echo("\nSync service stopped.")


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------


@cli.command()
def setup() -> None:
    """Interactive setup wizard for configuring data sources.

    Walks through what you need, connects your data sources, syncs
    data in the background, and shows you how to build dashboards.
    """
    from finch_epm.paths import data_dir

    # Welcome
    click.echo()
    click.echo("  finch-epm setup")
    click.echo("  " + "=" * 50)
    click.echo()
    click.echo("  Welcome to finch-epm. This wizard will:")
    click.echo("    1. Connect your data sources (NetSuite, SQL Server, etc.)")
    click.echo("    2. Discover what tables and fields are available")
    click.echo("    3. Start syncing data in the background")
    click.echo("    4. Show you how to build and open dashboards")
    click.echo()
    click.echo("  Before you begin, make sure you have:")
    click.echo("    - A .env file with your connection credentials")
    click.echo("    - For NetSuite: a private key PEM file")
    click.echo("    - For SQL Server: an ODBC driver installed")
    click.echo()
    click.echo("  See GETTING_STARTED.md for detailed prerequisites per source.")
    click.echo()

    configured: list[tuple[str, str]] = []
    connection_number = 1

    while True:
        if connection_number > 1:
            click.echo()
            click.echo(f"  --- Connection {connection_number} ---")

        # Step 1: Choose connector with prerequisite info
        click.echo("  Available data sources:")
        click.echo("    netsuite   - Oracle NetSuite (SuiteQL + REST API)")
        click.echo("    sqlserver  - Microsoft SQL Server / Azure SQL")
        click.echo("    postgres   - PostgreSQL")
        click.echo("    snowflake  - Snowflake Data Cloud")
        click.echo("    bigquery   - Google BigQuery")
        click.echo("    odbc       - Any ODBC source (OneStream, SAP, Oracle, etc.)")
        click.echo()

        connector = click.prompt(
            "  Which data source?",
            type=click.Choice(["netsuite", "sqlserver", "postgres", "snowflake", "bigquery", "odbc"]),
        )

        # Show what they need BEFORE asking for credentials
        click.echo()
        _show_prerequisites(connector)

        ready = click.confirm("  Do you have these ready?", default=True)
        if not ready:
            click.echo("  No problem. You can re-run setup later when ready.")
            if configured:
                break
            continue

        # Profile name
        default_profile = connector if connection_number == 1 else f"{connector}_{connection_number}"
        profile = click.prompt("  Profile name", default=default_profile)

        # Authentication
        click.echo()
        env_file = click.prompt("  Path to .env file")
        key_file = None
        if connector == "netsuite":
            key_file = click.prompt("  Path to private key PEM file", default="")
            key_file = key_file or None

        try:
            ctx = click.get_current_context()
            ctx.invoke(auth, connector=connector, profile=profile,
                       env_file=env_file, key_file=key_file, validate=False)
        except SystemExit:
            click.echo("  Credential import failed. Check your .env file and try again.")
            continue

        # Validate
        click.echo()
        click.echo("  Validating connection...")
        try:
            _validate_credentials(connector, profile)
        except SystemExit:
            click.echo("  Connection failed. Check credentials and permissions.")
            continue

        # Crawl
        click.echo()
        click.echo("  Discovering schema (tables, columns, dimensions)...")
        _catalog_crawl(connector, profile)

        configured.append((connector, profile))
        connection_number += 1

        click.echo()
        add_more = click.confirm("  Add another data source?", default=False)
        if not add_more:
            break

    if not configured:
        click.echo("  No connections configured. Run finch-epm setup again when ready.")
        return

    # Background sync setup
    click.echo()
    click.echo("  " + "=" * 50)
    click.echo(f"  {len(configured)} connection(s) configured:")
    for ct, pn in configured:
        click.echo(f"    {ct}/{pn}")
    click.echo()
    click.echo("  STEP: Background Sync")
    click.echo("  finch-epm will sync your data automatically so dashboards")
    click.echo("  are always ready when you open them. The initial sync may")
    click.echo("  take several minutes for large datasets. You can continue")
    click.echo("  working while it runs.")
    click.echo()

    setup_sync = click.confirm("  Set up automatic background sync?", default=True)
    if setup_sync:
        _setup_background_sync(configured)

    # Start initial sync in background
    click.echo()
    click.echo("  Starting initial data sync in the background...")
    click.echo("  This runs alongside your normal work. No need to wait.")

    import subprocess
    import sys
    subprocess.Popen(
        [sys.executable, "-m", "finch_epm.cli.main", "service", "--once"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    click.echo("  Sync started. It will run in the background.")

    # Instruction guide
    click.echo()
    click.echo("  " + "=" * 50)
    click.echo("  SETUP COMPLETE")
    click.echo("  " + "=" * 50)
    click.echo()
    click.echo("  Your data is syncing in the background. Here is what to do next:")
    click.echo()
    click.echo("  1. BROWSE YOUR DATA")
    click.echo("     See what tables are available:")
    for ct, pn in configured:
        click.echo(f"       finch-epm catalog --tables --accessible-only -c {ct} -p {pn}")
    click.echo()
    click.echo("  2. OPEN A TEMPLATE DASHBOARD")
    click.echo("     finch-epm ships with example dashboards you can try right away:")
    click.echo(f"       finch-epm open examples/netsuite_gl_overview.fdash")
    click.echo(f"       finch-epm open examples/multi_tab_financial.fdash")
    click.echo()
    click.echo("  3. BUILD YOUR OWN DASHBOARD")
    click.echo("     Option A: Use AI -- open Claude Code and type /dashboard")
    click.echo("     Option B: Copy a template and modify the SQL queries")
    click.echo("     Option C: Write a .fdash file from scratch (see DASHBOARDS.md)")
    click.echo()
    click.echo("  4. SHARE A DASHBOARD")
    click.echo("     Send any .fdash file to a colleague. They install finch-epm,")
    click.echo("     run setup with their own credentials, and open the same file.")
    click.echo("     No data is in the file -- it renders against their own access.")
    click.echo()
    click.echo("  5. IMPORT CSV OR EXCEL DATA")
    click.echo("     finch-epm import budget.csv")
    click.echo("     finch-epm import reference.xlsx --sheet Locations")
    click.echo()
    click.echo("  KEY FILES:")
    click.echo(f"    Local data:     {data_dir()}")
    click.echo(f"    Dashboard spec: DASHBOARDS.md (complete reference for .fdash format)")
    click.echo(f"    Templates:      examples/ (ready-to-use .fdash files)")
    click.echo(f"    AI prompt:      /dashboard command in Claude Code")
    click.echo()


def _show_prerequisites(connector: str) -> None:
    """Show what the user needs before connecting to a data source."""
    if connector == "netsuite":
        click.echo("  What you need for NetSuite:")
        click.echo("    [ ] Integration record with OAuth 2.0 Client Credentials")
        click.echo("    [ ] Certificate (EC or RSA) uploaded to the integration")
        click.echo("    [ ] Role with SuiteQL + REST Web Services permissions")
        click.echo("    [ ] .env file containing:")
        click.echo("          NS_ACCOUNT_ID=your_account_id")
        click.echo("          NS_CLIENT_ID=your_client_id")
        click.echo("          NS_CERTIFICATE_ID=your_cert_id")
        click.echo("    [ ] Private key PEM file (matching the uploaded certificate)")
    elif connector == "sqlserver":
        click.echo("  What you need for SQL Server:")
        click.echo("    [ ] SQL login with SELECT on target tables")
        click.echo("    [ ] ODBC Driver 17 or 18 installed on this machine")
        click.echo("    [ ] .env file containing:")
        click.echo("          AZURE_SQL_SERVER=server.database.windows.net")
        click.echo("          AZURE_SQL_DATABASE=your_database")
        click.echo("          AZURE_SQL_USER=your_username")
        click.echo("          AZURE_SQL_PASSWORD=your_password")
    elif connector == "postgres":
        click.echo("  What you need for PostgreSQL:")
        click.echo("    [ ] Database user with SELECT on target tables")
        click.echo("    [ ] .env file containing:")
        click.echo("          PG_HOST=your_host")
        click.echo("          PG_PORT=5432")
        click.echo("          PG_DATABASE=your_database")
        click.echo("          PG_USER=your_username")
        click.echo("          PG_PASSWORD=your_password")
    elif connector == "snowflake":
        click.echo("  What you need for Snowflake:")
        click.echo("    [ ] Snowflake account with a warehouse")
        click.echo("    [ ] .env file containing:")
        click.echo("          SF_ACCOUNT=xy12345.us-east-1")
        click.echo("          SF_WAREHOUSE=your_warehouse")
        click.echo("          SF_DATABASE=your_database")
        click.echo("          SF_SCHEMA=PUBLIC")
        click.echo("          SF_USER=your_username")
        click.echo("          SF_PASSWORD=your_password")
    elif connector == "bigquery":
        click.echo("  What you need for BigQuery:")
        click.echo("    [ ] GCP project with BigQuery enabled")
        click.echo("    [ ] Service account JSON key file")
        click.echo("    [ ] .env file containing:")
        click.echo("          BQ_PROJECT=your_project_id")
        click.echo("          BQ_DATASET=your_dataset")
        click.echo("          BQ_CREDENTIALS_FILE=path/to/service-account.json")
    elif connector == "odbc":
        click.echo("  What you need for ODBC (OneStream, SAP, Oracle, etc.):")
        click.echo("    [ ] ODBC driver for your data source installed")
        click.echo("    [ ] .env file containing:")
        click.echo("          ODBC_CONNECTION_STRING=DRIVER={...};SERVER=...;DATABASE=...")
        click.echo("          ODBC_PASSWORD=your_password (optional, appended to string)")
    click.echo()


def _setup_background_sync(configured: list[tuple[str, str]]) -> None:
    """Set up automatic background sync via OS task scheduler."""
    import sys

    from finch_epm.cache.service import save_service_config

    interval = click.prompt("Sync interval (minutes)", default=15, type=int)

    # Save service config
    config = {
        "interval_minutes": interval,
        "sync_on_start": True,
        "profiles": [
            {"connector": ct, "profile": pn}
            for ct, pn in configured
        ],
    }
    save_service_config(config)
    click.echo(f"  Sync config saved (every {interval} minutes).")

    # Platform-specific task scheduler setup
    if sys.platform == "win32":
        _setup_windows_task(interval)
    elif sys.platform == "darwin":
        _setup_macos_launchd(interval)
    else:
        _setup_linux_cron(interval)


def _setup_windows_task(interval: int) -> None:
    """Register a Windows Task Scheduler job for background sync."""
    import subprocess
    import sys

    python_exe = sys.executable
    task_name = "finch-epm-sync"

    # Build the schtasks command
    # Runs on login + repeats every N minutes
    cmd = [
        "schtasks", "/Create",
        "/TN", task_name,
        "/TR", f'"{python_exe}" -m finch_epm.cli.main service --once',
        "/SC", "MINUTE",
        "/MO", str(interval),
        "/F",  # Force overwrite if exists
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        if result.returncode == 0:
            click.echo(f"  Windows Task Scheduler: '{task_name}' registered (every {interval} min).")
            click.echo(f"  To remove: schtasks /Delete /TN {task_name} /F")
        else:
            click.echo(f"  Could not register Windows task (may need admin).")
            click.echo(f"  Manual setup: schtasks /Create /TN {task_name} /TR \"{python_exe} -m finch_epm.cli.main service --once\" /SC MINUTE /MO {interval}")
    except Exception as e:
        click.echo(f"  Task scheduler registration failed: {e}")
        click.echo(f"  You can run the sync service manually: finch-epm service")


def _setup_macos_launchd(interval: int) -> None:
    """Create a launchd plist for background sync on macOS."""
    import sys
    from pathlib import Path

    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / "com.finch-epm.sync.plist"

    python_exe = sys.executable
    interval_seconds = interval * 60

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.finch-epm.sync</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_exe}</string>
        <string>-m</string>
        <string>finch_epm.cli.main</string>
        <string>service</string>
        <string>--once</string>
    </array>
    <key>StartInterval</key>
    <integer>{interval_seconds}</integer>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>"""

    plist_path.write_text(plist_content)
    click.echo(f"  macOS launchd: {plist_path}")
    click.echo(f"  Load with: launchctl load {plist_path}")
    click.echo(f"  Remove with: launchctl unload {plist_path}")


def _setup_linux_cron(interval: int) -> None:
    """Show cron setup instructions for Linux."""
    import sys
    python_exe = sys.executable
    click.echo(f"  Add to crontab (crontab -e):")
    click.echo(f"  */{interval} * * * * {python_exe} -m finch_epm.cli.main service --once")
