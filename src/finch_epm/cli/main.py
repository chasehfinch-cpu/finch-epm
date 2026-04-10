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
    if connector_type == "netsuite":
        import finch_epm.connectors.netsuite.connector  # noqa: F401
    elif connector_type == "sqlserver":
        import finch_epm.connectors.sqlserver.connector  # noqa: F401
    elif connector_type == "postgres":
        import finch_epm.connectors.postgres.connector  # noqa: F401
    elif connector_type == "fake":
        import finch_epm.connectors.fake  # noqa: F401

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

        finch-epm auth -c netsuite -p ecp --env-file /path/to/.env --key-file /path/to/key.pem

    After import, the .env and key file are never needed again.
    Validate stored credentials:

        finch-epm auth -c netsuite -p ecp --validate
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

        finch-epm catalog --crawl -c netsuite -p ecp

    List tables:

        finch-epm catalog --tables -c netsuite -p ecp
        finch-epm catalog --tables --accessible-only -c netsuite -p ecp

    List columns for a table:

        finch-epm catalog --columns Transaction -c netsuite -p ecp

    List dimensions:

        finch-epm catalog --dimensions -c netsuite -p ecp
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

        finch-epm sync -c netsuite -p ecp -t Account -t Subsidiary

    Sync all accessible tables:

        finch-epm sync -c netsuite -p ecp --all

    Full sync (replace cached data):

        finch-epm sync -c netsuite -p ecp -t Account --full
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

    cache = LocalCacheEngine(str(cache_db_path()))
    try:
        server = DashboardServer(dashboard, cache)
        server.start(port=port, open_browser=not no_browser)
    finally:
        cache.close()


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------


@cli.command()
def setup() -> None:
    """Interactive setup wizard for configuring data sources.

    Walks through connector selection, authentication, and initial
    schema crawl.
    """
    click.echo("finch-epm setup")
    click.echo("=" * 40)
    click.echo()

    # Step 1: Choose connector
    connector = click.prompt(
        "Which data source?",
        type=click.Choice(["netsuite", "sqlserver", "postgres"]),
        default="netsuite",
    )

    # Step 2: Profile name
    profile = click.prompt("Profile name", default="default")

    # Step 3: Authentication
    click.echo()
    click.echo(f"Step 1: Authenticate with {connector}")

    if connector == "netsuite":
        click.echo("  You need a .env file with: NS_ACCOUNT_ID, NS_CLIENT_ID, NS_CERTIFICATE_ID")
        click.echo("  And a private key PEM file from your NetSuite integration.")
        env_file = click.prompt("  Path to .env file")
        key_file = click.prompt("  Path to private key PEM file", default="")
        args = ["auth", "-c", connector, "-p", profile, "--env-file", env_file]
        if key_file:
            args.extend(["--key-file", key_file])
        ctx = click.get_current_context()
        ctx.invoke(auth, connector=connector, profile=profile, env_file=env_file,
                   key_file=key_file or None, validate=False)
    elif connector == "sqlserver":
        click.echo("  You need a .env file with: AZURE_SQL_SERVER, AZURE_SQL_DATABASE,")
        click.echo("  AZURE_SQL_USER, AZURE_SQL_PASSWORD")
        env_file = click.prompt("  Path to .env file")
        ctx = click.get_current_context()
        ctx.invoke(auth, connector=connector, profile=profile, env_file=env_file,
                   key_file=None, validate=False)
    elif connector == "postgres":
        click.echo("  You need a .env file with: PG_HOST, PG_PORT, PG_DATABASE,")
        click.echo("  PG_USER, PG_PASSWORD")
        env_file = click.prompt("  Path to .env file")
        ctx = click.get_current_context()
        ctx.invoke(auth, connector=connector, profile=profile, env_file=env_file,
                   key_file=None, validate=False)

    # Step 4: Validate
    click.echo()
    click.echo("Step 2: Validating credentials...")
    _validate_credentials(connector, profile)

    # Step 5: Crawl
    click.echo()
    click.echo("Step 3: Crawling schema...")
    _catalog_crawl(connector, profile)

    click.echo()
    click.echo("Setup complete. Next steps:")
    click.echo(f"  finch-epm catalog --tables -c {connector} -p {profile}")
    click.echo(f"  finch-epm sync -c {connector} -p {profile} -t <table_name>")
    click.echo(f"  finch-epm open path/to/dashboard.fdash")
