"""Background sync service.

Keeps the local DuckDB cache warm by syncing data from all configured
sources on a schedule. The dashboard never waits for sync -- it always
reads from a cache that is already populated.

Architecture:
    1. Sync writes to a staging database (cache_staging.duckdb)
    2. When sync completes, the staging file replaces the main cache
       via atomic rename (on the same filesystem, this is instant)
    3. Dashboard reads from cache.duckdb (always complete, never partial)
    4. No file locking conflicts between sync and dashboard

The service can run as:
    - A foreground process: finch-epm service start
    - A Windows Task Scheduler job (runs on login, then every N minutes)
    - A launchd plist on macOS
    - A systemd timer on Linux
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from finch_epm.paths import cache_db_path, config_dir, data_dir

logger = logging.getLogger(__name__)

_SERVICE_CONFIG_FILE = "sync_service.json"


def staging_db_path() -> Path:
    """Path to the staging DuckDB file (written during sync)."""
    return data_dir() / "cache_staging.duckdb"


def load_service_config() -> dict[str, Any]:
    """Load the service configuration."""
    path = config_dir() / _SERVICE_CONFIG_FILE
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "interval_minutes": 15,
        "sync_on_start": True,
        "profiles": [],
    }


def save_service_config(config: dict[str, Any]) -> None:
    """Save the service configuration."""
    path = config_dir() / _SERVICE_CONFIG_FILE
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def run_sync_cycle(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run one complete sync cycle across all configured profiles.

    Syncs into a staging database, then swaps it into place atomically.
    Returns a report dict with results per profile.

    This function is safe to call while a dashboard is reading from
    cache.duckdb -- the swap only happens after sync is complete.
    """
    if config is None:
        config = load_service_config()

    from finch_epm.cache.local import LocalCacheEngine
    from finch_epm.cache.sync import SyncEngine
    from finch_epm.catalog.catalog import CatalogStore
    from finch_epm.paths import catalog_db_path
    from finch_epm.profiles.manager import ProfileManager

    pm = ProfileManager()
    all_profiles = pm.list_profiles()

    # Filter to configured profiles (or all if none specified)
    target_profiles = config.get("profiles", [])
    if not target_profiles:
        target_profiles = [
            {"connector": ct, "profile": pn}
            for ct, pn in all_profiles
        ]

    main_cache = cache_db_path()
    staging = staging_db_path()

    # Copy current cache to staging (preserves existing data)
    if main_cache.exists():
        shutil.copy2(str(main_cache), str(staging))

    # Open staging for writes
    cache = LocalCacheEngine(str(staging))
    catalog = CatalogStore(str(catalog_db_path()))

    report: dict[str, Any] = {
        "started_at": datetime.now().isoformat(),
        "profiles": [],
    }

    try:
        for target in target_profiles:
            ct = target.get("connector", target.get("connector_type", ""))
            pn = target.get("profile", target.get("profile_name", ""))

            if not ct or not pn:
                continue

            profile_report = {
                "connector": ct,
                "profile": pn,
                "tables_synced": 0,
                "total_rows": 0,
                "errors": [],
            }

            try:
                # Import and connect
                _import_connector(ct)
                from finch_epm.connectors.registry import get_connector_class
                cls = get_connector_class(ct)
                conn = cls(pn)
                conn.connect()

                try:
                    # Get accessible tables from catalog
                    table_names = catalog.get_accessible_table_names(ct, pn)

                    if not table_names:
                        profile_report["errors"].append("No accessible tables in catalog. Run: finch-epm catalog --crawl")
                    else:
                        engine = SyncEngine(conn, cache, catalog)
                        sync_report = engine.sync_tables(
                            table_names,
                            mode="incremental",
                        )
                        profile_report["tables_synced"] = sync_report.tables_synced
                        profile_report["total_rows"] = sync_report.total_rows
                        profile_report["errors"] = sync_report.errors
                finally:
                    conn.close()

            except Exception as e:
                profile_report["errors"].append(str(e))
                logger.error("Sync failed for %s/%s: %s", ct, pn, e)

            report["profiles"].append(profile_report)

    finally:
        cache.close()
        catalog.close()

    # Atomic swap: staging -> main cache
    # On the same filesystem, os.replace is atomic on most platforms
    try:
        if staging.exists():
            os.replace(str(staging), str(main_cache))
            logger.info("Cache swapped successfully")
    except OSError as e:
        # On Windows, os.replace can fail if the file is open
        # Fall back to copy + delete
        try:
            shutil.copy2(str(staging), str(main_cache))
            staging.unlink(missing_ok=True)
        except Exception:
            logger.error("Failed to swap cache: %s", e)

    report["completed_at"] = datetime.now().isoformat()
    return report


def run_service(interval_minutes: int = 15) -> None:
    """Run the sync service in a loop.

    This is the main entry point for the background service.
    Syncs immediately on start, then every interval_minutes.
    """
    config = load_service_config()
    interval = config.get("interval_minutes", interval_minutes)

    logger.info("Sync service starting (interval: %d minutes)", interval)
    print(f"Sync service running. Interval: {interval} minutes. Ctrl+C to stop.")

    while True:
        try:
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Starting sync cycle...")
            report = run_sync_cycle(config)

            total_rows = sum(p.get("total_rows", 0) for p in report.get("profiles", []))
            total_errors = sum(len(p.get("errors", [])) for p in report.get("profiles", []))
            print(f"  Sync complete: {total_rows:,} rows, {total_errors} errors")

            for p in report.get("profiles", []):
                status = "ok" if not p["errors"] else "errors"
                print(f"  {p['connector']}/{p['profile']}: {p['tables_synced']} tables, {p['total_rows']:,} rows [{status}]")

        except Exception as e:
            logger.error("Sync cycle failed: %s", e)
            print(f"  Sync cycle failed: {e}")

        # Sleep in 1-second intervals so Ctrl+C is responsive
        for _ in range(interval * 60):
            time.sleep(1)


def _import_connector(connector_type: str) -> None:
    """Import a connector module to trigger registration."""
    import importlib
    modules = {
        "netsuite": "finch_epm.connectors.netsuite.connector",
        "sqlserver": "finch_epm.connectors.sqlserver.connector",
        "postgres": "finch_epm.connectors.postgres.connector",
        "snowflake": "finch_epm.connectors.snowflake.connector",
        "bigquery": "finch_epm.connectors.bigquery.connector",
        "odbc": "finch_epm.connectors.odbc.connector",
    }
    module_path = modules.get(connector_type)
    if module_path:
        importlib.import_module(module_path)
