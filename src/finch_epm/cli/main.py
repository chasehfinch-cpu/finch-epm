"""finch-epm CLI entry point.

Subcommands: setup, auth, sync, open, catalog.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Type

import click

logger = logging.getLogger(__name__)

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
    from finch_epm.connectors.registry import discover_plugins

    discover_plugins()


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
    from finch_epm.catalog.change_detector import detect_changes
    from finch_epm.engine.classification_models import ClassificationStore
    from finch_epm.engine.classifier import DataClassifier
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
            # Snapshot current state before replacing
            old_tables, old_columns = store.get_schema_snapshot(
                schema.source_name, schema.profile_name
            )

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

            # Detect schema changes
            if old_tables:  # Skip on first crawl (no previous data)
                changes = detect_changes(old_tables, old_columns, schema)
                if changes.has_changes:
                    click.echo(f"\n  Schema changes detected: {changes.summary()}")

                    # Load classification store and prompt user
                    cls_store = ClassificationStore.load()
                    classifier = DataClassifier(cls_store, connector, profile)

                    if changes.new_tables:
                        click.echo(f"\n  {len(changes.new_tables)} new table(s) need classification:")
                        classify_now = click.confirm(
                            "  Classify new items now?", default=True
                        )
                        if classify_now:
                            classified = classifier.classify_new_tables(changes.new_tables)
                            click.echo(f"  Classified {classified} table(s).")
                        else:
                            classifier.add_pending_for_changes(changes)
                            click.echo(
                                "  Items saved as pending. "
                                "Run 'finch-epm classify' later."
                            )

                    if changes.new_columns:
                        click.echo(f"\n  {len(changes.new_columns)} new column(s) detected.")
                        classifier.add_pending_for_changes(changes)

                    if changes.removed_tables:
                        click.echo(f"\n  {len(changes.removed_tables)} table(s) removed:")
                        for rt in changes.removed_tables:
                            click.echo(f"    - {rt.name}")

                    cls_store.save()
                else:
                    click.echo("\n  No schema changes since last crawl.")

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

        # Detect binary flag columns in small (reference) tables
        _detect_flags_in_synced_tables(cache, report)

    finally:
        conn.close()
        cache.close()
        if catalog_store:
            catalog_store.close()


def _detect_flags_in_synced_tables(cache: Any, report: Any) -> None:
    """After sync, scan small tables for binary flag columns and prompt user."""
    from finch_epm.cache.models import QueryRequest
    from finch_epm.engine.flags import (
        FlagStore,
        classify_flags_interactive,
        detect_binary_columns,
    )

    flag_store = FlagStore.load()
    new_flags_found = False

    for table_result in report.per_table:
        if not table_result.success:
            continue
        # Only scan small tables (likely reference/dimension tables)
        if table_result.rows_synced > 5000:
            continue
        if table_result.rows_synced == 0:
            continue

        table_name = table_result.table_name
        # Check if we already have flags for this table
        existing = flag_store.get_flag_set(table_name)

        # Fetch sample data to detect binary columns
        try:
            # Find the actual cache table name
            cache_tables = cache.execute_query(QueryRequest(
                sql=f"""SELECT table_name FROM information_schema.tables
                        WHERE table_schema='main'
                        AND table_name LIKE '%{table_name.replace(".", "__")}%'"""
            ))
            if not cache_tables.rows:
                continue
            cache_table = cache_tables.rows[0][0]

            sample = cache.execute_query(QueryRequest(
                sql=f'SELECT * FROM "{cache_table}" LIMIT 100'
            ))
            if not sample.rows:
                continue

            candidates = detect_binary_columns(
                cache_table, sample.column_names, sample.rows
            )

            if not candidates:
                continue

            # Filter out columns we've already classified
            if existing:
                known_cols = {f.column_name for f in existing.flags}
                new_candidates = [c for c in candidates if c["column_name"] not in known_cols]
            else:
                new_candidates = candidates

            if not new_candidates:
                continue

            new_flags_found = True
            click.echo(
                f"\n  Detected {len(new_candidates)} binary flag column(s) "
                f"in {cache_table} ({table_result.rows_synced} rows):"
            )
            for c in new_candidates:
                click.echo(
                    f"    {c['column_name']} (suggested: {c['suggested_type']})"
                )

            classify_now = click.confirm(
                "  Classify these flags now?", default=True
            )
            if classify_now:
                flag_set = classify_flags_interactive(cache_table, new_candidates)
                # Merge with existing
                if existing:
                    existing.flags.extend(flag_set.flags)
                    flag_store.set_flag_set(existing)
                else:
                    flag_store.set_flag_set(flag_set)
            else:
                click.echo("  Skipped. Run 'finch-epm links setup' to classify later.")

        except Exception as e:
            logger.debug("Flag detection failed for %s: %s", table_name, e)

    if new_flags_found:
        flag_store.save()
        click.echo(f"\n  Flag definitions saved.")


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
@click.option(
    "--config",
    type=click.Path(exists=True, dir_okay=True),
    help="Config bundle path (for IT silent deployment). Directory or YAML "
    "containing compilation_map.yaml, coa.yaml, and/or credentials .env files.",
)
def setup(config: str | None) -> None:
    """Interactive setup wizard for configuring data sources.

    For IT administrators: walks through connecting data sources, syncing
    data, setting up the chart of accounts, and configuring the compilation
    map. Run once per machine.

    For silent deployment, use --config to pre-load a config bundle:

        finch-epm setup --config \\\\server\\share\\finch-epm-config\\

    The config directory can contain:
        compilation_map.yaml  — imported as the compilation map
        coa.yaml              — imported as the chart of accounts
        flags.yaml            — imported as flag definitions
    """
    from finch_epm.paths import data_dir

    # Handle silent config bundle import
    if config:
        _import_config_bundle(config)
        return

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

    # ── STEP: Chart of Accounts ──
    click.echo()
    click.echo("  " + "=" * 50)
    click.echo("  STEP: Chart of Accounts")
    click.echo("  The chart of accounts defines how GL accounts map into")
    click.echo("  your P&L hierarchy (Revenue, Expense, EBITDA, etc.).")
    click.echo()

    setup_coa = click.confirm("  Set up chart of accounts now?", default=True)
    if setup_coa:
        try:
            from finch_epm.cache.local import LocalCacheEngine as _LCE
            from finch_epm.cache.models import QueryRequest as _QR
            from finch_epm.engine.coa import ChartOfAccounts
            from finch_epm.paths import cache_db_path as _cdbp

            _cache = _LCE(str(_cdbp()), read_only=True)
            _account_rows: list[dict] = []
            for _tname in ["Account", "ns__Account"]:
                try:
                    _r = _cache.execute_query(_QR(sql=f'SELECT * FROM "{_tname}"'))
                    _account_rows = [dict(zip(_r.column_names, row)) for row in _r.rows]
                    break
                except Exception:
                    continue
            _cache.close()

            if _account_rows:
                _coa = ChartOfAccounts.from_accounts(_account_rows)
                _path = _coa.save()
                _counts = _coa.count_by_category()
                click.echo(f"  Generated chart of accounts ({len(_coa.accounts)} accounts):")
                for _cat, _cnt in sorted(_counts.items()):
                    click.echo(f"    {_cat}: {_cnt}")
                click.echo(f"  Saved to: {_path}")
                click.echo(f"  Customize later: finch-epm coa edit")
            else:
                click.echo("  Account data not yet synced. Run 'finch-epm coa setup' after sync.")
        except Exception as e:
            click.echo(f"  Could not auto-generate COA: {e}")
            click.echo("  Run 'finch-epm coa setup' after sync completes.")
    else:
        click.echo("  Skipped. Run 'finch-epm coa setup' when ready.")
        click.echo("  Or import a team template: finch-epm coa import template.yaml")

    # ── STEP: Compilation Map ──
    click.echo()
    click.echo("  " + "=" * 50)
    click.echo("  STEP: Compilation Map (Data Linking)")
    click.echo("  The compilation map links your data sources together")
    click.echo("  through shared reference tables (Location, Department, etc.).")
    click.echo("  This is the single source of truth for all dashboards.")
    click.echo()

    existing_map = click.prompt(
        "  Options:\n"
        "    1. Auto-detect reference tables from synced data (recommended)\n"
        "    2. Import a team-shared compilation map\n"
        "    3. Point to a map on a network share\n"
        "    4. Skip for now\n"
        "  Choice",
        type=int,
        default=1,
    )

    if existing_map == 2:
        map_file = click.prompt("  Path to compilation map file")
        try:
            from finch_epm.engine.compilation_map import CompilationMap
            _cmap = CompilationMap.load(map_file)
            _cmap.save()
            click.echo(f"  Imported: {_cmap.name} ({len(_cmap.references)} references)")
        except Exception as e:
            click.echo(f"  Import failed: {e}")
    elif existing_map == 3:
        net_path = click.prompt("  Network path (e.g., \\\\server\\share\\compilation_map.yaml)")
        from finch_epm.engine.compilation_map import CompilationMap
        CompilationMap.use_network_path(net_path)
        click.echo(f"  Pointed to: {net_path}")
    elif existing_map == 1:
        click.echo("  Run 'finch-epm map setup' after sync completes to configure.")
        click.echo("  The wizard will walk you through selecting reference tables.")
    else:
        click.echo("  Skipped. Run 'finch-epm map setup' when ready.")

    # Instruction guide
    click.echo()
    click.echo("  " + "=" * 50)
    click.echo("  SETUP COMPLETE")
    click.echo("  " + "=" * 50)
    click.echo()
    click.echo("  Your data is syncing in the background. Next steps:")
    click.echo()
    click.echo("  FOR IT:")
    click.echo("    After sync completes (~15-30 min for large datasets):")
    click.echo("      finch-epm map setup              # Link your reference tables")
    click.echo("      finch-epm coa edit               # Customize the P&L hierarchy")
    click.echo("    Then share with the team:")
    click.echo(f"      Copy compilation_map.yaml and coa.yaml from {data_dir()}")
    click.echo("      to your network share for other users to import.")
    click.echo()
    click.echo("  FOR END USERS:")
    click.echo("    Double-click any .fdash file to open a dashboard.")
    click.echo("    Or generate one with AI:")
    click.echo("      finch-epm ask \"build me a revenue dashboard\" --open")
    click.echo()
    click.echo("  TEMPLATES:")
    click.echo("    finch-epm open examples/netsuite_gl_overview.fdash")
    click.echo("    finch-epm open examples/multi_tab_financial.fdash")
    click.echo()
    click.echo("  KEY FILES:")
    click.echo(f"    Local data:        {data_dir()}")
    click.echo(f"    Compilation map:   finch-epm map show")
    click.echo(f"    Chart of accounts: finch-epm coa show")
    click.echo(f"    Dashboard spec:    DASHBOARDS.md")
    click.echo()


def _import_config_bundle(config_path: str) -> None:
    """Import a pre-built config bundle for silent IT deployment.

    The bundle directory can contain:
        compilation_map.yaml — imported as the compilation map
        coa.yaml — imported as the chart of accounts
        flags.yaml — imported as flag definitions
    """
    from finch_epm.paths import config_dir

    bundle = Path(config_path)
    if bundle.is_file():
        bundle = bundle.parent

    imported = []

    # Import compilation map
    map_file = bundle / "compilation_map.yaml"
    if map_file.exists():
        from finch_epm.engine.compilation_map import CompilationMap
        cmap = CompilationMap.load(str(map_file))
        cmap.save()
        imported.append(f"Compilation map: {cmap.name} ({len(cmap.references)} references)")

    # Import chart of accounts
    coa_file = bundle / "coa.yaml"
    if coa_file.exists():
        from finch_epm.engine.coa import ChartOfAccounts
        coa = ChartOfAccounts.load(str(coa_file))
        coa.save()
        imported.append(f"Chart of accounts: {len(coa.accounts)} accounts")

    # Import flags
    flags_file = bundle / "flags.yaml"
    if flags_file.exists():
        from finch_epm.engine.flags import FlagStore
        flags = FlagStore.load(str(flags_file))
        flags.save()
        imported.append(f"Flags: {sum(len(fs.flags) for fs in flags.flag_sets.values())} definitions")

    if imported:
        click.echo("Config bundle imported:")
        for item in imported:
            click.echo(f"  {item}")
        click.echo(f"\nFiles saved to: {config_dir()}")
    else:
        click.echo(f"No config files found in: {bundle}")
        click.echo("Expected: compilation_map.yaml, coa.yaml, flags.yaml")


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


# ---------------------------------------------------------------------------
# llm
# ---------------------------------------------------------------------------


@cli.group()
def llm() -> None:
    """Manage LLM provider configurations for AI dashboard generation."""


@llm.command(name="configure")
@click.option("--name", "-n", default="default", help="LLM profile name")
def llm_configure(name: str) -> None:
    """Configure an LLM provider for AI dashboard generation.

    Walks through provider selection and credential setup.
    Credentials are stored securely in the OS keychain.

        finch-epm llm configure
        finch-epm llm configure --name work
    """
    import os

    from finch_epm.llm.providers import list_provider_names
    from finch_epm.llm.registry import default_model, list_aliases
    from finch_epm.profiles.manager import ProfileManager

    providers = list_provider_names()
    click.echo("Available LLM providers:")
    for p in providers:
        click.echo(f"  {p}")
    click.echo()

    provider = click.prompt(
        "Provider",
        type=click.Choice(providers),
    )

    # Collect credentials
    api_key = ""
    base_url = ""

    if provider in ("anthropic", "openai", "google"):
        env_var_map = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "google": "GOOGLE_API_KEY",
        }
        env_var = env_var_map[provider]
        existing = os.environ.get(env_var, "")
        if existing:
            use_env = click.confirm(
                f"Found {env_var} in environment. Use it?", default=True
            )
            if use_env:
                api_key = existing
        if not api_key:
            api_key = click.prompt("API key", hide_input=True)

    elif provider == "ollama":
        base_url = click.prompt(
            "Ollama URL", default="http://localhost:11434"
        )

    elif provider == "openai_compatible":
        base_url = click.prompt("Base URL (e.g. http://localhost:1234/v1)")
        api_key = click.prompt("API key (blank if none)", default="", show_default=False)

    # Model selection
    aliases = list_aliases(provider)
    default = default_model(provider)
    click.echo()
    click.echo("Model aliases:")
    for alias, model_id in aliases.items():
        marker = " (default)" if model_id == default else ""
        click.echo(f"  {alias:<12} -> {model_id}{marker}")
    click.echo()
    model = click.prompt("Model (alias or ID)", default="balanced")

    # Save
    pm = ProfileManager()
    config = {"provider": provider, "model": model}
    if base_url:
        config["base_url"] = base_url
    pm.set_config("llm", name, config)
    if api_key:
        pm.set_secret("llm", name, "api_key", api_key)

    click.echo(f"\nLLM profile '{name}' saved ({provider}, model: {model})")
    click.echo(f"Test with: finch-epm llm test --name {name}")


@llm.command(name="list")
def llm_list() -> None:
    """List all configured LLM profiles.

        finch-epm llm list
    """
    from finch_epm.profiles.manager import ProfileManager

    pm = ProfileManager()
    profiles = pm.list_profiles(connector_type="llm")
    if not profiles:
        click.echo("No LLM profiles configured.")
        click.echo("Run: finch-epm llm configure")
        return

    click.echo(f"{'Name':<20} {'Provider':<18} {'Model':<30}")
    click.echo("-" * 70)
    for _, profile_name in profiles:
        try:
            config = pm.get_config("llm", profile_name)
            click.echo(
                f"{profile_name:<20} {config.get('provider', '?'):<18} "
                f"{config.get('model', 'default'):<30}"
            )
        except KeyError:
            click.echo(f"{profile_name:<20} (error reading config)")


@llm.command(name="test")
@click.option("--name", "-n", default="default", help="LLM profile name")
def llm_test(name: str) -> None:
    """Test the connection to a configured LLM provider.

        finch-epm llm test
        finch-epm llm test --name work
    """
    provider = _make_llm_provider(name)
    info = provider.describe()
    click.echo(f"Testing {info['provider']} (model: {info.get('model', '?')})...")

    try:
        provider.test_connection()
        click.echo("Connection successful.")
    except Exception as e:
        click.echo(f"Connection failed: {e}")
        raise SystemExit(1)


def _make_llm_provider(profile_name: str = "default") -> "Provider":
    """Create an LLM Provider from a named profile.

    Checks environment variables first, then falls back to keyring.
    """
    import os

    from finch_epm.llm.base import LLMError, Provider
    from finch_epm.llm.providers import get_provider_class
    from finch_epm.profiles.manager import ProfileManager

    pm = ProfileManager()

    # Try to load saved profile
    try:
        config = pm.get_config("llm", profile_name)
    except KeyError:
        # No saved profile -- try environment variables
        for env_var, provider_name in [
            ("ANTHROPIC_API_KEY", "anthropic"),
            ("OPENAI_API_KEY", "openai"),
            ("GOOGLE_API_KEY", "google"),
        ]:
            key = os.environ.get(env_var, "")
            if key:
                cls = get_provider_class(provider_name)
                return cls(api_key=key)

        raise click.ClickException(
            f"LLM profile '{profile_name}' not found and no API key "
            "environment variables set.\n"
            "Run: finch-epm llm configure\n"
            "Or set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GOOGLE_API_KEY"
        )

    provider_name = config["provider"]
    model = config.get("model")
    base_url = config.get("base_url", "")
    api_key = pm.get_secret("llm", profile_name, "api_key") or ""

    # Also check env vars as fallback for the key
    if not api_key:
        env_map = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "google": "GOOGLE_API_KEY",
        }
        env_var = env_map.get(provider_name, "")
        if env_var:
            api_key = os.environ.get(env_var, "")

    cls = get_provider_class(provider_name)

    kwargs: dict = {}
    if api_key:
        kwargs["api_key"] = api_key
    if model:
        kwargs["model"] = model
    if base_url:
        kwargs["base_url"] = base_url

    return cls(**kwargs)


# ---------------------------------------------------------------------------
# ask
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("prompt")
@click.option("--connector", "-c", help="Connector type for catalog scope")
@click.option("--profile", "-p", help="Data profile name for catalog scope")
@click.option("--llm-profile", default="default", help="LLM profile name")
@click.option("--provider", "provider_override", help="Override LLM provider")
@click.option("--model", "model_override", help="Override LLM model")
@click.option(
    "--output", "-o",
    type=click.Path(),
    help="Output path (default: ./generated/<slug>.fdash)",
)
@click.option("--open", "auto_open", is_flag=True, help="Open dashboard after generation")
@click.option("--dry-run", is_flag=True, help="Print to stdout instead of writing a file")
@click.option("--max-retries", default=2, help="Max self-correction attempts")
def ask(
    prompt: str,
    connector: str | None,
    profile: str | None,
    llm_profile: str,
    provider_override: str | None,
    model_override: str | None,
    output: str | None,
    auto_open: bool,
    dry_run: bool,
    max_retries: int,
) -> None:
    """Generate a dashboard from a natural language prompt.

    Uses your configured LLM to create a .fdash file grounded in your
    actual data catalog.

        finch-epm ask "build me a site P&L dashboard"
        finch-epm ask "monthly revenue trend by subsidiary" -c netsuite -p production
        finch-epm ask "top 10 customers by revenue" --open
        finch-epm ask "expense breakdown" --dry-run
    """
    import re as _re

    from finch_epm.cache.local import LocalCacheEngine
    from finch_epm.catalog.catalog import CatalogStore
    from finch_epm.llm.ask import ask_llm
    from finch_epm.llm.prompt import build_system_prompt
    from finch_epm.paths import cache_db_path, catalog_db_path
    from finch_epm.profiles.manager import ProfileManager

    # Build provider
    if provider_override:
        from finch_epm.llm.providers import get_provider_class
        import os
        cls = get_provider_class(provider_override)
        env_map = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "google": "GOOGLE_API_KEY",
        }
        api_key = os.environ.get(env_map.get(provider_override, ""), "")
        kwargs: dict = {}
        if api_key:
            kwargs["api_key"] = api_key
        if model_override:
            kwargs["model"] = model_override
        llm_provider = cls(**kwargs)
    else:
        llm_provider = _make_llm_provider(llm_profile)

    # Determine which profiles to include in the catalog
    pm = ProfileManager()
    if connector and profile:
        profiles = [(connector, profile)]
    else:
        # Include all data profiles (excluding "llm")
        profiles = [
            (ct, pn) for ct, pn in pm.list_profiles()
            if ct != "llm"
        ]

    if not profiles:
        click.echo(
            "No data profiles configured. Run 'finch-epm setup' or "
            "'finch-epm auth' first to connect a data source."
        )
        raise SystemExit(1)

    click.echo(f"Building catalog context from {len(profiles)} profile(s)...")

    catalog = CatalogStore(str(catalog_db_path()))
    try:
        cache = LocalCacheEngine(str(cache_db_path()), read_only=True)
    except Exception:
        click.echo("Warning: Cache not available. Generating without sample rows.")
        cache = None

    try:
        system_prompt = build_system_prompt(
            catalog, cache, profiles
        ) if cache else build_system_prompt(catalog, None, profiles)

        click.echo(f"Generating dashboard with {llm_provider.describe()['provider']}...")

        result = ask_llm(
            prompt=prompt,
            provider=llm_provider,
            system_prompt=system_prompt,
            model=model_override,
            max_retries=max_retries,
        )

        if not result.success:
            click.echo(f"\nDashboard generation failed after {result.attempts} attempt(s).")
            for err in result.errors:
                click.echo(f"  {err}")
            raise SystemExit(1)

        click.echo(f"Dashboard generated successfully (attempt {result.attempts}/{max_retries + 1})")

        if dry_run:
            click.echo("\n--- Generated .fdash ---")
            click.echo(result.fdash_content)
            return

        # Determine output path
        if output:
            out_path = Path(output)
        else:
            # Generate path from dashboard name
            name = result.spec.name if result.spec else "dashboard"
            slug = _re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
            out_dir = Path("generated")
            out_dir.mkdir(exist_ok=True)
            out_path = out_dir / f"{slug}.fdash"

        out_path.write_text(result.fdash_content, encoding="utf-8")
        click.echo(f"Saved to: {out_path}")

        if auto_open:
            click.echo("Opening dashboard...")
            ctx = click.get_current_context()
            ctx.invoke(open_dashboard, dashboard=str(out_path), port=8765, no_browser=False)

    finally:
        catalog.close()
        if cache:
            cache.close()


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--connector", "-c", help="Connector type (filter to one source)")
@click.option("--profile", "-p", help="Profile name (filter to one source)")
@click.option("--accounts", is_flag=True, help="Classify unmapped GL accounts against the P&L structure")
def classify(connector: str | None, profile: str | None, accounts: bool) -> None:
    """Review and classify unclassified data items.

    After a catalog crawl detects new tables, columns, or accounts,
    this command lets you classify them so dashboards and the P&L
    engine know what the data represents.

        finch-epm classify                        # Review all pending items
        finch-epm classify --accounts -c netsuite -p production  # Classify GL accounts
    """
    from finch_epm.engine.classification_models import ClassificationStore, DataClass
    from finch_epm.engine.classifier import DataClassifier

    cls_store = ClassificationStore.load()

    if accounts:
        if not connector or not profile:
            click.echo("Error: --accounts requires --connector and --profile.")
            raise SystemExit(1)
        _classify_accounts(cls_store, connector, profile)
        return

    # Show pending items
    pending = cls_store.pending
    if not pending:
        click.echo("No items pending classification.")
        total_classified = sum(
            len(tables) for tables in cls_store.tables.values()
        )
        if total_classified:
            click.echo(f"({total_classified} items previously classified)")
        return

    # Filter by source if specified
    if connector and profile:
        source_key = cls_store.source_key(connector, profile)
        pending = [p for p in pending if p.source == source_key]
        if not pending:
            click.echo(f"No pending items for {connector}/{profile}.")
            return

    click.echo(f"\n  {len(pending)} item(s) pending classification:\n")

    # Group by source
    by_source: dict[str, list] = {}
    for p in pending:
        by_source.setdefault(p.source, []).append(p)

    for source, items in sorted(by_source.items()):
        click.echo(f"  Source: {source}")
        parts = source.split("/", 1)
        ct = parts[0]
        pn = parts[1] if len(parts) > 1 else parts[0]

        classifier = DataClassifier(cls_store, ct, pn)

        # Separate tables and columns
        table_items = [i for i in items if i.item_type == "table"]
        column_items = [i for i in items if i.item_type == "column"]
        account_items = [i for i in items if i.item_type == "account"]

        if table_items:
            click.echo(f"    {len(table_items)} new table(s)")
        if column_items:
            click.echo(f"    {len(column_items)} new column(s)")
        if account_items:
            click.echo(f"    {len(account_items)} unmapped account(s)")

    click.echo()
    do_classify = click.confirm("  Classify these items now?", default=True)
    if not do_classify:
        click.echo("  Run 'finch-epm classify' when ready.")
        return

    for source, items in sorted(by_source.items()):
        parts = source.split("/", 1)
        ct = parts[0]
        pn = parts[1] if len(parts) > 1 else parts[0]
        classifier = DataClassifier(cls_store, ct, pn)

        from finch_epm.catalog.change_detector import NewTable, NewColumn

        table_items = [i for i in items if i.item_type == "table"]
        if table_items:
            new_tables = [
                NewTable(
                    name=i.identifier,
                    display_name=i.display_name or i.identifier,
                    column_count=0,
                )
                for i in table_items
            ]
            classifier.classify_new_tables(new_tables)

        column_items = [i for i in items if i.item_type == "column"]
        if column_items:
            new_columns = []
            for i in column_items:
                parts_col = i.identifier.split(".", 1)
                tname = parts_col[0] if len(parts_col) > 1 else ""
                cname = parts_col[1] if len(parts_col) > 1 else i.identifier
                new_columns.append(NewColumn(
                    table_name=tname,
                    column_name=cname,
                    column_type="",
                ))
            classifier.classify_new_columns(new_columns)

    cls_store.save()
    remaining = cls_store.pending_count()
    click.echo(f"\n  Classification saved. {remaining} item(s) still pending.")


def _classify_accounts(
    cls_store: "ClassificationStore",
    connector: str,
    profile: str,
) -> None:
    """Classify unmapped GL accounts against the active P&L structure."""
    from finch_epm.cache.local import LocalCacheEngine
    from finch_epm.cache.models import QueryRequest
    from finch_epm.catalog.change_detector import detect_unmapped_accounts, flatten_pl_sections
    from finch_epm.engine.chart_of_accounts import get_default_pl_structure
    from finch_epm.engine.classifier import DataClassifier
    from finch_epm.paths import cache_db_path

    pl_structure = get_default_pl_structure()
    flat_sections = flatten_pl_sections(pl_structure)

    # Get already-classified account IDs
    source_key = cls_store.source_key(connector, profile)
    classified_ids = set(cls_store.accounts.get(source_key, {}).keys())

    # Query the cached Account table for all accounts
    try:
        cache = LocalCacheEngine(str(cache_db_path()), read_only=True)
    except Exception:
        click.echo("Error: Cache not available. Sync data first.")
        raise SystemExit(1)

    try:
        # Try common account table names
        account_rows: list[dict] = []
        for table_name in ["Account", "ns__Account", "account"]:
            try:
                result = cache.execute_query(QueryRequest(
                    sql=f'SELECT * FROM "{table_name}"',
                    parameters={},
                    source_name="",
                ))
                for row in result.rows:
                    account_rows.append(dict(zip(result.column_names, row)))
                break
            except Exception:
                continue

        if not account_rows:
            click.echo("No Account table found in cache. Sync accounts first:")
            click.echo(f"  finch-epm sync -c {connector} -p {profile} -t Account")
            raise SystemExit(1)

        click.echo(f"  Found {len(account_rows)} accounts in cache.")

        unmapped = detect_unmapped_accounts(
            account_rows, flat_sections, classified_ids
        )

        if not unmapped:
            click.echo("  All accounts are mapped to a P&L section.")
            return

        click.echo(f"  {len(unmapped)} account(s) don't map to any P&L section.")
        do_classify = click.confirm("  Classify them now?", default=True)
        if not do_classify:
            click.echo("  Run 'finch-epm classify --accounts' when ready.")
            return

        classifier = DataClassifier(cls_store, connector, profile)
        classified = classifier.classify_unmapped_accounts(unmapped, pl_structure)
        cls_store.save()
        click.echo(f"\n  Classified {classified} account(s).")

    finally:
        cache.close()


# ---------------------------------------------------------------------------
# mcp
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "--transport", "-t",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="Transport mode: stdio (default, for desktop MCP clients) or sse (HTTP)",
)
@click.option("--port", default=8808, help="HTTP port (only used with --transport sse)")
def mcp(transport: str, port: int) -> None:
    """Run the finch-epm MCP server.

    Desktop MCP clients (Claude Desktop, Claude Code, Cursor) connect
    via stdio. Use --transport sse for HTTP-based clients.

    Stdio (default):

        finch-epm mcp

    HTTP:

        finch-epm mcp --transport sse --port 8808
    """
    from finch_epm.mcp.server import create_mcp_server

    server = create_mcp_server()

    if transport == "sse":
        click.echo(f"Starting MCP server on http://localhost:{port}")
        server.settings.port = port
        server.run(transport="sse")
    else:
        server.run(transport="stdio")


# ---------------------------------------------------------------------------
# coa (chart of accounts)
# ---------------------------------------------------------------------------


@cli.group()
def coa() -> None:
    """Manage the chart of accounts for P&L reporting."""


@coa.command(name="setup")
@click.option("--connector", "-c", help="Connector type")
@click.option("--profile", "-p", help="Profile name")
def coa_setup(connector: str | None, profile: str | None) -> None:
    """Interactive chart of accounts setup.

    Auto-generates a P&L hierarchy from your account data, or import
    a template from a file your team has already created.

        finch-epm coa setup -c netsuite -p production
    """
    from finch_epm.cache.local import LocalCacheEngine
    from finch_epm.cache.models import QueryRequest
    from finch_epm.engine.coa import ChartOfAccounts
    from finch_epm.paths import cache_db_path

    click.echo("\n  Chart of Accounts Setup")
    click.echo("  " + "=" * 50)

    # Try to load accounts from cache
    try:
        cache = LocalCacheEngine(str(cache_db_path()), read_only=True)
    except Exception:
        click.echo("  Cache not available. Sync data first.")
        raise SystemExit(1)

    try:
        account_rows: list[dict] = []
        for table in ["Account", "ns__Account", "account"]:
            try:
                result = cache.execute_query(QueryRequest(sql=f'SELECT * FROM "{table}"'))
                for row in result.rows:
                    account_rows.append(dict(zip(result.column_names, row)))
                break
            except Exception:
                continue

        if account_rows:
            click.echo(f"  Found {len(account_rows)} accounts in cache.\n")
        else:
            click.echo("  No Account table found. Sync accounts first.")
            raise SystemExit(1)

        # Count by type
        type_counts: dict[str, int] = {}
        for r in account_rows:
            t = str(r.get("accttype", "unknown"))
            type_counts[t] = type_counts.get(t, 0) + 1
        click.echo("  Account types:")
        for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
            click.echo(f"    {t}: {c}")

        click.echo("\n  Options:")
        click.echo("    1. Auto-generate P&L structure from account types (recommended)")
        click.echo("    2. Import from file (YAML, JSON, or CSV template)")
        click.echo("    3. Skip for now")

        choice = click.prompt("  Choice", type=int, default=1)

        if choice == 1:
            click.echo()
            level_count = click.prompt(
                "  How many hierarchy levels? (2-6)", type=int, default=4
            )
            level_names = [f"level{i}" for i in range(1, level_count + 1)]
            coa_obj = ChartOfAccounts.from_accounts(account_rows, level_names=level_names)
            path = coa_obj.save()
            counts = coa_obj.count_by_category()
            click.echo(f"\n  Generated chart of accounts:")
            for cat, count in sorted(counts.items()):
                click.echo(f"    {cat}: {count} accounts")
            click.echo(f"\n  Saved to: {path}")
            click.echo(f"  Customize with: finch-epm coa edit")

        elif choice == 2:
            file_path = click.prompt("  Path to template file")
            p = Path(file_path)
            if not p.exists():
                click.echo(f"  File not found: {p}")
                raise SystemExit(1)
            if p.suffix == ".json":
                coa_obj = ChartOfAccounts.from_json(p)
            elif p.suffix == ".csv":
                coa_obj = ChartOfAccounts.from_csv(p)
            else:
                coa_obj = ChartOfAccounts.load(p)
            path = coa_obj.save()
            click.echo(f"  Imported {len(coa_obj.accounts)} accounts from {p.name}")
            click.echo(f"  Saved to: {path}")

        else:
            click.echo("  Skipped. Run 'finch-epm coa setup' when ready.")

    finally:
        cache.close()


@coa.command(name="import")
@click.argument("file_path", type=click.Path(exists=True))
def coa_import(file_path: str) -> None:
    """Import a chart of accounts from a template file.

    Supports YAML, JSON, and CSV formats. Share templates with your team
    so everyone uses the same P&L structure.

        finch-epm coa import template.yaml
        finch-epm coa import team_coa.json
        finch-epm coa import accounts.csv
    """
    from finch_epm.engine.coa import ChartOfAccounts

    p = Path(file_path)
    if p.suffix == ".json":
        coa_obj = ChartOfAccounts.from_json(p)
    elif p.suffix == ".csv":
        coa_obj = ChartOfAccounts.from_csv(p)
    else:
        coa_obj = ChartOfAccounts.load(p)

    path = coa_obj.save()
    counts = coa_obj.count_by_category()
    click.echo(f"Imported {len(coa_obj.accounts)} accounts from {p.name}")
    for cat, count in sorted(counts.items()):
        click.echo(f"  {cat}: {count}")
    click.echo(f"Saved to: {path}")


@coa.command(name="show")
def coa_show() -> None:
    """Show the current chart of accounts hierarchy.

        finch-epm coa show
    """
    from finch_epm.engine.coa import ChartOfAccounts

    coa_obj = ChartOfAccounts.load()
    if not coa_obj.accounts:
        click.echo("No chart of accounts configured.")
        click.echo("Run: finch-epm coa setup")
        return

    click.echo(f"Chart of Accounts ({len(coa_obj.accounts)} accounts)")
    click.echo(f"Levels: {', '.join(coa_obj.level_names)}")
    click.echo()

    counts = coa_obj.count_by_category()
    for cat, count in sorted(counts.items()):
        click.echo(f"  {cat}: {count} accounts")

    unmapped = coa_obj.find_unmapped()
    if unmapped:
        click.echo(f"\n  {len(unmapped)} accounts not yet classified.")
        click.echo("  Run: finch-epm coa setup  (to reclassify)")


@coa.command(name="edit")
def coa_edit() -> None:
    """Open the chart of accounts in your system editor.

        finch-epm coa edit
    """
    import os
    import subprocess
    import sys

    from finch_epm.engine.coa import ChartOfAccounts, _default_path

    path = _default_path()
    if not path.exists():
        click.echo("No chart of accounts found. Run 'finch-epm coa setup' first.")
        raise SystemExit(1)

    click.echo(f"Opening: {path}")
    if sys.platform == "win32":
        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)])
    else:
        editor = os.environ.get("EDITOR", "nano")
        subprocess.run([editor, str(path)])


@coa.command(name="unmapped")
def coa_unmapped() -> None:
    """Show accounts not yet classified in the P&L hierarchy.

        finch-epm coa unmapped
    """
    from finch_epm.engine.coa import ChartOfAccounts

    coa_obj = ChartOfAccounts.load()
    if not coa_obj.accounts:
        click.echo("No chart of accounts configured. Run: finch-epm coa setup")
        return

    unmapped = coa_obj.find_unmapped()
    if not unmapped:
        click.echo("All accounts are classified.")
        return

    click.echo(f"{len(unmapped)} unclassified accounts:\n")
    click.echo(f"  {'ID':<10} {'Name':<40} {'Category'}")
    click.echo("  " + "-" * 65)
    for acct in unmapped[:50]:
        click.echo(f"  {acct.account_id:<10} {acct.account_name[:40]:<40} {acct.category}")
    if len(unmapped) > 50:
        click.echo(f"\n  ... and {len(unmapped) - 50} more.")
    click.echo(f"\nEdit the COA file to classify them: finch-epm coa edit")


# ---------------------------------------------------------------------------
# links (table linking)
# ---------------------------------------------------------------------------


@cli.group()
def links() -> None:
    """Manage cross-source table links and dimension mappings."""


@links.command(name="setup")
def links_setup() -> None:
    """Interactive setup for linking tables across data sources.

    Detects dimension tables and helps you connect columns across
    NetSuite, SQL Server, and other sources.

        finch-epm links setup
    """
    from finch_epm.cache.local import LocalCacheEngine
    from finch_epm.cache.models import QueryRequest
    from finch_epm.catalog.catalog import CatalogStore
    from finch_epm.engine.table_linker import TableLinker
    from finch_epm.paths import cache_db_path, catalog_db_path
    from finch_epm.profiles.manager import ProfileManager

    click.echo("\n  Table Linking Setup")
    click.echo("  " + "=" * 50)
    click.echo("  Link tables across data sources so dashboards can")
    click.echo("  JOIN NetSuite and SQL Server data together.\n")

    cache = LocalCacheEngine(str(cache_db_path()), read_only=True)
    catalog = CatalogStore(str(catalog_db_path()))
    linker = TableLinker.load()

    try:
        # List all cached tables with row counts
        r = cache.execute_query(QueryRequest(
            sql="""SELECT table_name FROM information_schema.tables
                   WHERE table_schema='main' AND table_name NOT LIKE '\\_%' ESCAPE '\\'
                   ORDER BY table_name"""
        ))
        tables = []
        for row in r.rows:
            tname = row[0]
            try:
                cnt = cache.execute_query(QueryRequest(sql=f'SELECT COUNT(*) FROM "{tname}"'))
                tables.append({"table_name": tname, "row_count": cnt.rows[0][0]})
            except Exception:
                tables.append({"table_name": tname, "row_count": 0})

        # Identify dimension candidates (small tables)
        dim_candidates = TableLinker.detect_dimension_tables(tables)
        fact_tables = [t for t in tables if t["row_count"] > 5000]

        if dim_candidates:
            click.echo("  Detected reference/dimension tables (small row count):")
            for i, t in enumerate(dim_candidates, 1):
                click.echo(f"    {i}. {t['table_name']} ({t['row_count']:,} rows)")

        if fact_tables:
            click.echo(f"\n  Fact/transaction tables (large):")
            for t in fact_tables:
                click.echo(f"    {t['table_name']} ({t['row_count']:,} rows)")

        click.echo("\n  To link two tables, I need to know which columns match.")
        click.echo("  Example: Location.id  <-->  dbo__RCMSiteMaster.Division\n")

        while True:
            add_link = click.confirm("  Add a table link?", default=bool(dim_candidates))
            if not add_link:
                break

            # Pick source table
            all_table_names = [t["table_name"] for t in tables]
            click.echo("\n  Available tables:")
            for i, name in enumerate(all_table_names, 1):
                click.echo(f"    {i}. {name}")

            src_idx = click.prompt("  Source table number", type=int) - 1
            src_table = all_table_names[src_idx]

            # Show source columns
            src_cols = cache.execute_query(QueryRequest(
                sql=f"SELECT column_name FROM information_schema.columns WHERE table_name='{src_table}' ORDER BY ordinal_position"
            ))
            src_col_names = [r[0] for r in src_cols.rows]
            click.echo(f"\n  Columns in {src_table}:")
            for i, c in enumerate(src_col_names, 1):
                click.echo(f"    {i}. {c}")
            src_col_idx = click.prompt("  Source column number", type=int) - 1
            src_col = src_col_names[src_col_idx]

            # Pick target table
            tgt_idx = click.prompt("  Target table number", type=int) - 1
            tgt_table = all_table_names[tgt_idx]

            # Show target columns
            tgt_cols = cache.execute_query(QueryRequest(
                sql=f"SELECT column_name FROM information_schema.columns WHERE table_name='{tgt_table}' ORDER BY ordinal_position"
            ))
            tgt_col_names = [r[0] for r in tgt_cols.rows]

            # Auto-suggest matches
            src_col_dicts = [{"column_name": c} for c in src_col_names]
            tgt_col_dicts = [{"column_name": c} for c in tgt_col_names]
            suggestions = TableLinker.detect_linkable_columns(src_col_dicts, tgt_col_dicts)

            if suggestions:
                click.echo(f"\n  Suggested matches:")
                for s in suggestions[:5]:
                    click.echo(f"    {src_table}.{s['source_column']} <-> {tgt_table}.{s['target_column']} ({s['confidence']})")

            click.echo(f"\n  Columns in {tgt_table}:")
            for i, c in enumerate(tgt_col_names, 1):
                click.echo(f"    {i}. {c}")
            tgt_col_idx = click.prompt("  Target column number", type=int) - 1
            tgt_col = tgt_col_names[tgt_col_idx]

            link = linker.add_link(src_table, src_col, tgt_table, tgt_col)
            click.echo(f"\n  Linked: {src_table}.{src_col} <-> {tgt_table}.{tgt_col}")

        path = linker.save()
        click.echo(f"\n  Saved {len(linker.links)} link(s) to: {path}")

    finally:
        cache.close()
        catalog.close()


@links.command(name="show")
def links_show() -> None:
    """Show all configured table links.

        finch-epm links show
    """
    from finch_epm.engine.table_linker import TableLinker

    linker = TableLinker.load()
    if not linker.links and not linker.dimensions:
        click.echo("No table links configured. Run: finch-epm links setup")
        return

    if linker.links:
        click.echo(f"Table Links ({len(linker.links)}):\n")
        for link in linker.links:
            click.echo(f"  {link.source_table}.{link.source_column} <-> {link.target_table}.{link.target_column}")
            if link.description:
                click.echo(f"    {link.description}")

    if linker.dimensions:
        click.echo(f"\nDimension Mappings ({len(linker.dimensions)}):\n")
        for dim in linker.dimensions:
            click.echo(f"  {dim.name}: {dim.dimension_table} (join on {dim.fact_join_column})")
            if dim.rollup_columns:
                click.echo(f"    Rollups: {', '.join(dim.rollup_columns)}")


@links.command(name="import")
@click.argument("file_path", type=click.Path(exists=True))
def links_import(file_path: str) -> None:
    """Import table links from a shared YAML file.

        finch-epm links import team_links.yaml
    """
    from finch_epm.engine.table_linker import TableLinker

    imported = TableLinker.load(file_path)
    # Merge with existing
    existing = TableLinker.load()
    for link in imported.links:
        existing.add_link(
            link.source_table, link.source_column,
            link.target_table, link.target_column,
            name=link.name, description=link.description,
        )
    for dim in imported.dimensions:
        existing.dimensions = [d for d in existing.dimensions if d.name != dim.name]
        existing.dimensions.append(dim)

    path = existing.save()
    click.echo(f"Imported {len(imported.links)} link(s) and {len(imported.dimensions)} dimension(s)")
    click.echo(f"Saved to: {path}")


# ---------------------------------------------------------------------------
# map (compilation map — single source of truth for data linking)
# ---------------------------------------------------------------------------


@cli.group(name="map")
def compilation_map_group() -> None:
    """Manage the compilation map — the single source of truth that links
    all data sources together through one master reference."""


@compilation_map_group.command(name="show")
def map_show() -> None:
    """Display the current compilation map.

    Shows every reference table, how each data source connects to it,
    what rollups and flags are available, and where the map file lives.

        finch-epm map show
    """
    from finch_epm.engine.compilation_map import CompilationMap

    cmap = CompilationMap.load()
    active_path = CompilationMap.get_active_path()

    if not cmap.references:
        click.echo("No compilation map configured.")
        click.echo("Run: finch-epm map setup")
        click.echo("Or:  finch-epm map use <path>  (point to a shared map)")
        return

    click.echo(f"\n  {cmap.name}")
    if cmap.description:
        click.echo(f"  {cmap.description}")
    click.echo(f"  File: {active_path}")
    click.echo()

    for ref in cmap.references:
        click.echo(f"  --- {ref.name.upper()} ---")
        click.echo(f"  Table: {ref.table}")
        click.echo(f"  ID: {ref.id_column}  Display: {ref.display_column}")

        if ref.source_links:
            click.echo(f"  Source Links:")
            for sl in ref.source_links:
                click.echo(f"    {sl.name}: {sl.table}.{sl.join_column} -> {ref.table}.{ref.id_column}")

        if ref.rollups:
            click.echo(f"  Rollups:")
            for rl in ref.rollups:
                click.echo(f"    {rl.display}: {rl.column}")

        if ref.flag_groups:
            click.echo(f"  Flags:")
            for fg in ref.flag_groups:
                flag_names = ", ".join(f.display or f.column for f in fg.flags)
                click.echo(f"    {fg.display or fg.name}: {flag_names}")

        click.echo()


@compilation_map_group.command(name="use")
@click.argument("path", type=click.Path(exists=True))
def map_use(path: str) -> None:
    """Point this install at a shared compilation map.

    Use when IT has pre-loaded the map on a network share and every
    user should use the same one.

        finch-epm map use "\\\\server\\share\\compilation_map.yaml"
        finch-epm map use /mnt/shared/compilation_map.yaml
    """
    from finch_epm.engine.compilation_map import CompilationMap

    # Verify the file is a valid map
    try:
        cmap = CompilationMap.load(path)
    except Exception as e:
        click.echo(f"Error reading map: {e}")
        raise SystemExit(1)

    if not cmap.references:
        click.echo("Warning: Map has no reference tables defined.")

    CompilationMap.use_network_path(str(Path(path).resolve()))
    click.echo(f"Pointed to: {path}")
    click.echo(f"All users who run this command will share this map.")

    if cmap.references:
        click.echo(f"\nReferences: {', '.join(r.name for r in cmap.references)}")


@compilation_map_group.command(name="import")
@click.argument("file_path", type=click.Path(exists=True))
def map_import(file_path: str) -> None:
    """Import a compilation map from a team-shared file.

    Copies the map into your local config. Use ``map use`` instead if
    you want every user to point to the same live file.

        finch-epm map import team_map.yaml
    """
    from finch_epm.engine.compilation_map import CompilationMap

    imported = CompilationMap.load(file_path)
    if not imported.references:
        click.echo("Warning: Imported map has no reference tables.")

    path = imported.save()
    click.echo(f"Imported compilation map: {imported.name}")
    click.echo(f"  References: {len(imported.references)}")
    click.echo(f"  Saved to: {path}")


@compilation_map_group.command(name="setup")
def map_setup() -> None:
    """Interactive compilation map setup.

    Walks through your cached tables, identifies reference tables,
    detects binary flags, and builds the map that links all your
    data sources together.

        finch-epm map setup
    """
    from finch_epm.cache.local import LocalCacheEngine
    from finch_epm.cache.models import QueryRequest
    from finch_epm.engine.compilation_map import (
        CompilationMap,
        FlagDefinition,
        FlagGroup,
        ReferenceTable,
        RollupLevel,
        SourceLink,
    )
    from finch_epm.engine.flags import detect_binary_columns
    from finch_epm.paths import cache_db_path

    click.echo("\n  Compilation Map Setup")
    click.echo("  " + "=" * 50)
    click.echo("  This builds the single source of truth that links")
    click.echo("  all your data sources together.\n")

    try:
        cache = LocalCacheEngine(str(cache_db_path()), read_only=True)
    except Exception:
        click.echo("  Cache is locked (sync may be running). Try again after sync completes.")
        raise SystemExit(1)

    try:
        # List all tables with row counts
        r = cache.execute_query(QueryRequest(
            sql="""SELECT table_name FROM information_schema.tables
                   WHERE table_schema='main' AND table_name NOT LIKE '\\_%' ESCAPE '\\'
                   ORDER BY table_name"""
        ))
        tables: list[dict[str, Any]] = []
        for row in r.rows:
            tname = row[0]
            try:
                cnt = cache.execute_query(QueryRequest(sql=f'SELECT COUNT(*) FROM "{tname}"'))
                tables.append({"name": tname, "rows": cnt.rows[0][0]})
            except Exception:
                tables.append({"name": tname, "rows": 0})

        # Separate into reference (small) and fact (large) tables
        ref_tables = [t for t in tables if 0 < t["rows"] <= 5000]
        fact_tables = [t for t in tables if t["rows"] > 5000]

        click.echo("  Reference tables (candidates for compilation map):")
        for i, t in enumerate(ref_tables, 1):
            click.echo(f"    {i}. {t['name']} ({t['rows']:,} rows)")

        click.echo(f"\n  Fact/transaction tables:")
        for t in fact_tables:
            click.echo(f"    {t['name']} ({t['rows']:,} rows)")

        cmap = CompilationMap(name="Data Compilation Map")

        # For each reference table, let user decide if it's a linking table
        click.echo("\n  Which reference tables link your data sources?")
        click.echo("  (These are the Location, Department, Entity tables)")
        click.echo()

        for ref_t in ref_tables:
            tname = ref_t["name"]
            use = click.confirm(f"  Use {tname} ({ref_t['rows']} rows) as a reference?", default=False)
            if not use:
                continue

            # Show columns
            cols = cache.execute_query(QueryRequest(
                sql=f"SELECT * FROM \"{tname}\" LIMIT 5"
            ))
            click.echo(f"\n  Columns in {tname}:")
            for i, col in enumerate(cols.column_names, 1):
                sample = cols.rows[0][i - 1] if cols.rows else ""
                click.echo(f"    {i}. {col} (e.g., {sample})")

            # Pick ID and display columns
            id_idx = click.prompt("  Which column is the ID?", type=int, default=1) - 1
            id_col = cols.column_names[id_idx]
            disp_idx = click.prompt("  Which column is the display name?", type=int, default=2) - 1
            disp_col = cols.column_names[disp_idx]

            ref_name = click.prompt("  Short name for this reference", default=tname.split("__")[-1].lower())

            # Detect rollup columns (non-binary, non-ID string columns)
            rollups: list[RollupLevel] = []
            click.echo(f"\n  Which columns are rollup/grouping levels?")
            for i, col in enumerate(cols.column_names):
                if col in (id_col, disp_col):
                    continue
                # Check if it's a text column with few distinct values
                try:
                    distinct = cache.execute_query(QueryRequest(
                        sql=f'SELECT COUNT(DISTINCT "{col}") FROM "{tname}"'
                    ))
                    n_distinct = distinct.rows[0][0]
                    if 2 <= n_distinct <= 50:
                        is_rollup = click.confirm(
                            f"    {col} ({n_distinct} distinct values) — use as rollup?",
                            default=True,
                        )
                        if is_rollup:
                            display = click.prompt(f"    Display name for {col}", default=col)
                            rollups.append(RollupLevel(column=col, display=display))
                except Exception:
                    pass

            # Detect binary flags
            candidates = detect_binary_columns(tname, cols.column_names, cols.rows)
            flag_groups: list[FlagGroup] = []
            if candidates:
                click.echo(f"\n  Detected {len(candidates)} binary flag column(s):")
                status_flags: list[FlagDefinition] = []
                period_flags: list[FlagDefinition] = []
                custom_flags: list[FlagDefinition] = []

                for cand in candidates:
                    cn = cand["column_name"]
                    st = cand["suggested_type"]
                    click.echo(f"    {cn} (suggested: {st})")

                    choices = ["status", "period", "custom", "skip"]
                    default_idx = choices.index(st) + 1 if st in choices else 1
                    choice = click.prompt(
                        f"    Type for {cn}",
                        type=click.Choice(choices),
                        default=choices[default_idx - 1],
                    )

                    if choice == "skip":
                        continue

                    display = cn.replace("_", " ").replace("FY", " FY").strip()
                    fd = FlagDefinition(column=cn, display=display, active_value=1)

                    if choice == "status":
                        status_flags.append(fd)
                    elif choice == "period":
                        period_flags.append(fd)
                    else:
                        custom_flags.append(fd)

                if status_flags:
                    flag_groups.append(FlagGroup(name="status", display="Status", flags=status_flags))
                if period_flags:
                    flag_groups.append(FlagGroup(name="periods", display="Period Membership", flags=period_flags))
                if custom_flags:
                    flag_groups.append(FlagGroup(name="custom", display="Custom Filters", flags=custom_flags))

            # Ask which fact tables link to this reference
            source_links: list[SourceLink] = []
            click.echo(f"\n  Which fact tables link to {tname}?")
            for ft in fact_tables:
                link = click.confirm(f"    {ft['name']} ({ft['rows']:,} rows)?", default=False)
                if not link:
                    continue

                ft_cols = cache.execute_query(QueryRequest(
                    sql=f"SELECT column_name FROM information_schema.columns WHERE table_name='{ft['name']}' ORDER BY ordinal_position"
                ))
                ft_col_names = [r[0] for r in ft_cols.rows]
                click.echo(f"    Columns in {ft['name']}:")
                for j, c in enumerate(ft_col_names, 1):
                    click.echo(f"      {j}. {c}")
                jc_idx = click.prompt(f"    Which column joins to {id_col}?", type=int) - 1
                join_col = ft_col_names[jc_idx]

                sl_name = click.prompt("    Link name", default=ft["name"].split("__")[0].lower())
                source_links.append(SourceLink(
                    name=sl_name,
                    table=ft["name"],
                    join_column=join_col,
                ))

            cmap.references.append(ReferenceTable(
                name=ref_name,
                table=tname,
                id_column=id_col,
                display_column=disp_col,
                source_links=source_links,
                rollups=rollups,
                flag_groups=flag_groups,
            ))

        if cmap.references:
            path = cmap.save()
            click.echo(f"\n  Compilation map saved to: {path}")
            click.echo(f"  References: {', '.join(r.name for r in cmap.references)}")
            click.echo(f"\n  View:   finch-epm map show")
            click.echo(f"  Share:  Send {path.name} to your team")
            click.echo(f"  IT:     finch-epm map use \\\\server\\share\\{path.name}")
        else:
            click.echo("\n  No reference tables selected. Run 'finch-epm map setup' when ready.")

    finally:
        cache.close()
