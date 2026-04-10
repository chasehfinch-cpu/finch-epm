"""Scheduled background sync.

Registers sync schedules that run automatically at specified intervals.
Schedules are stored in the config directory and can be managed via CLI.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from finch_epm.paths import config_dir

logger = logging.getLogger(__name__)

_SCHEDULE_FILE = "sync_schedules.json"


@dataclass
class SyncSchedule:
    """A registered sync schedule."""

    connector_type: str
    profile_name: str
    tables: list[str]
    interval_minutes: int
    mode: str = "incremental"
    enabled: bool = True
    last_run: str | None = None


class SyncScheduler:
    """Manages and executes scheduled syncs.

    Stores schedule configuration in the config directory.
    Runs syncs in background threads at specified intervals.
    """

    def __init__(self) -> None:
        self._schedules: list[SyncSchedule] = []
        self._running = False
        self._thread: threading.Thread | None = None
        self._load()

    def _schedule_path(self) -> Path:
        return config_dir() / _SCHEDULE_FILE

    def _load(self) -> None:
        path = self._schedule_path()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self._schedules = [
                SyncSchedule(**s) for s in data.get("schedules", [])
            ]

    def _save(self) -> None:
        path = self._schedule_path()
        data = {
            "schedules": [
                {
                    "connector_type": s.connector_type,
                    "profile_name": s.profile_name,
                    "tables": s.tables,
                    "interval_minutes": s.interval_minutes,
                    "mode": s.mode,
                    "enabled": s.enabled,
                    "last_run": s.last_run,
                }
                for s in self._schedules
            ]
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def add_schedule(
        self,
        connector_type: str,
        profile_name: str,
        tables: list[str],
        interval_minutes: int,
        mode: str = "incremental",
    ) -> None:
        """Add a new sync schedule."""
        schedule = SyncSchedule(
            connector_type=connector_type,
            profile_name=profile_name,
            tables=tables,
            interval_minutes=interval_minutes,
            mode=mode,
        )
        self._schedules.append(schedule)
        self._save()

    def list_schedules(self) -> list[SyncSchedule]:
        """Return all registered schedules."""
        return list(self._schedules)

    def remove_schedule(self, index: int) -> None:
        """Remove a schedule by index."""
        if 0 <= index < len(self._schedules):
            self._schedules.pop(index)
            self._save()

    def run_once(
        self,
        schedule: SyncSchedule,
        progress_callback: Callable[[str, int], None] | None = None,
    ) -> None:
        """Execute a single scheduled sync."""
        from finch_epm.cache.local import LocalCacheEngine
        from finch_epm.cache.sync import SyncEngine
        from finch_epm.paths import cache_db_path

        # Import connector dynamically
        if schedule.connector_type == "netsuite":
            import finch_epm.connectors.netsuite.connector  # noqa: F401
        elif schedule.connector_type == "sqlserver":
            import finch_epm.connectors.sqlserver.connector  # noqa: F401
        elif schedule.connector_type == "postgres":
            import finch_epm.connectors.postgres.connector  # noqa: F401

        from finch_epm.connectors.registry import get_connector_class

        cls = get_connector_class(schedule.connector_type)
        conn = cls(schedule.profile_name)
        cache = LocalCacheEngine(str(cache_db_path()))

        try:
            conn.connect()
            engine = SyncEngine(conn, cache)
            report = engine.sync_tables(
                schedule.tables,
                mode=schedule.mode,
                progress_callback=progress_callback,
            )

            schedule.last_run = datetime.now().isoformat()
            self._save()

            logger.info(
                "Scheduled sync complete: %s/%s, %d rows in %.1fs",
                schedule.connector_type,
                schedule.profile_name,
                report.total_rows,
                report.elapsed_seconds,
            )
        finally:
            conn.close()
            cache.close()

    def start_daemon(self) -> None:
        """Start the background scheduler thread.

        Checks all enabled schedules every minute and runs any that are due.
        """
        self._running = True
        self._thread = threading.Thread(target=self._daemon_loop, daemon=True)
        self._thread.start()
        logger.info("Sync scheduler started")

    def stop_daemon(self) -> None:
        """Stop the background scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Sync scheduler stopped")

    def _daemon_loop(self) -> None:
        while self._running:
            for schedule in self._schedules:
                if not schedule.enabled:
                    continue

                # Check if it is time to run
                if schedule.last_run:
                    try:
                        last = datetime.fromisoformat(schedule.last_run)
                        elapsed = (datetime.now() - last).total_seconds() / 60
                        if elapsed < schedule.interval_minutes:
                            continue
                    except ValueError:
                        pass

                try:
                    logger.info(
                        "Running scheduled sync: %s/%s",
                        schedule.connector_type,
                        schedule.profile_name,
                    )
                    self.run_once(schedule)
                except Exception as e:
                    logger.error("Scheduled sync failed: %s", e)

            # Sleep 60 seconds between checks
            for _ in range(60):
                if not self._running:
                    break
                time.sleep(1)
