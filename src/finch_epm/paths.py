"""Platform-appropriate directory paths for finch-epm data, config, and cache.

Uses platformdirs so that paths work identically whether running from a
terminal, a PyInstaller bundle, a Briefcase app, or a Tauri sidecar.
"""

from __future__ import annotations

from pathlib import Path

from platformdirs import PlatformDirs

_dirs = PlatformDirs(appname="finch-epm", appauthor=False)


def data_dir() -> Path:
    """User data directory (catalog DB, cache DB, profiles config).

    Examples:
        macOS:   ~/Library/Application Support/finch-epm/
        Linux:   ~/.local/share/finch-epm/
        Windows: C:/Users/<user>/AppData/Local/finch-epm/
    """
    p = Path(_dirs.user_data_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_dir() -> Path:
    """User config directory (settings that aren't secrets).

    Examples:
        macOS:   ~/Library/Application Support/finch-epm/
        Linux:   ~/.config/finch-epm/
        Windows: C:/Users/<user>/AppData/Local/finch-epm/
    """
    p = Path(_dirs.user_config_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    """User cache directory (temporary/expendable data).

    Examples:
        macOS:   ~/Library/Caches/finch-epm/
        Linux:   ~/.cache/finch-epm/
        Windows: C:/Users/<user>/AppData/Local/finch-epm/Cache/
    """
    p = Path(_dirs.user_cache_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def catalog_db_path() -> Path:
    """Path to the DuckDB catalog database."""
    return data_dir() / "catalog.duckdb"


def cache_db_path() -> Path:
    """Path to the DuckDB cache database."""
    return data_dir() / "cache.duckdb"


def profiles_config_path() -> Path:
    """Path to the profiles configuration file (non-secret metadata)."""
    return config_dir() / "profiles.json"
