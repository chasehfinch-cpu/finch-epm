"""Named credential profile management.

Non-secret configuration is stored in a JSON file under the platformdirs
data directory. Secrets (tokens, passwords) are stored in the OS keychain
via the ``keyring`` package. Multiple named profiles per connector type
are supported from day one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import keyring

from finch_epm.paths import profiles_config_path

_SERVICE_PREFIX = "finch-epm"


class ProfileManager:
    """Manages named credential profiles for connectors.

    Each profile is identified by ``(connector_type, profile_name)``
    and stores:
        - Non-secret config (account ID, instance URL, etc.) in a JSON file
        - Secrets (tokens, passwords) in the OS keychain via keyring
    """

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path or profiles_config_path()
        self._profiles: dict[str, dict[str, dict[str, Any]]] = {}
        self._load()

    def _load(self) -> None:
        if self._config_path.exists():
            self._profiles = json.loads(self._config_path.read_text(encoding="utf-8"))
        else:
            self._profiles = {}

    def _save(self) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(self._profiles, indent=2), encoding="utf-8"
        )

    def list_profiles(self, connector_type: str | None = None) -> list[tuple[str, str]]:
        """List all profiles as (connector_type, profile_name) tuples.

        Args:
            connector_type: If given, filter to this connector type only.
        """
        result: list[tuple[str, str]] = []
        for ct, profiles in self._profiles.items():
            if connector_type is not None and ct != connector_type:
                continue
            for name in profiles:
                result.append((ct, name))
        return sorted(result)

    def get_config(self, connector_type: str, profile_name: str) -> dict[str, Any]:
        """Get the non-secret configuration for a profile.

        Raises:
            KeyError: If the profile does not exist.
        """
        try:
            return dict(self._profiles[connector_type][profile_name])
        except KeyError:
            raise KeyError(
                f"Profile not found: {connector_type}/{profile_name}"
            ) from None

    def set_config(
        self, connector_type: str, profile_name: str, config: dict[str, Any]
    ) -> None:
        """Store non-secret configuration for a profile."""
        if connector_type not in self._profiles:
            self._profiles[connector_type] = {}
        self._profiles[connector_type][profile_name] = config
        self._save()

    def delete_profile(self, connector_type: str, profile_name: str) -> None:
        """Delete a profile and its secrets."""
        if connector_type in self._profiles:
            self._profiles[connector_type].pop(profile_name, None)
            if not self._profiles[connector_type]:
                del self._profiles[connector_type]
            self._save()
        # Clear all known secret keys
        for key_suffix in ["consumer_key", "consumer_secret", "token_id", "token_secret"]:
            self.delete_secret(connector_type, profile_name, key_suffix)

    def get_secret(
        self, connector_type: str, profile_name: str, key: str
    ) -> str | None:
        """Retrieve a secret from the OS keychain.

        Args:
            connector_type: e.g. ``"netsuite"``
            profile_name: e.g. ``"production"``
            key: Secret key name, e.g. ``"token_secret"``

        Returns:
            The secret string, or None if not found.
        """
        service = f"{_SERVICE_PREFIX}/{connector_type}/{profile_name}"
        return keyring.get_password(service, key)

    def set_secret(
        self, connector_type: str, profile_name: str, key: str, value: str
    ) -> None:
        """Store a secret in the OS keychain."""
        service = f"{_SERVICE_PREFIX}/{connector_type}/{profile_name}"
        keyring.set_password(service, key, value)

    def delete_secret(
        self, connector_type: str, profile_name: str, key: str
    ) -> None:
        """Remove a secret from the OS keychain (no-op if not found)."""
        service = f"{_SERVICE_PREFIX}/{connector_type}/{profile_name}"
        try:
            keyring.delete_password(service, key)
        except keyring.errors.PasswordDeleteError:
            pass

    def profile_exists(self, connector_type: str, profile_name: str) -> bool:
        """Check if a profile exists."""
        return (
            connector_type in self._profiles
            and profile_name in self._profiles[connector_type]
        )
