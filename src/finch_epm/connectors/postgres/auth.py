"""PostgreSQL connection builder.

Retrieves credentials from the OS keychain and builds a psycopg2
connection. Supports standard PostgreSQL and cloud-hosted instances
(AWS RDS, Azure Database for PostgreSQL, Google Cloud SQL).
"""

from __future__ import annotations

from typing import Any

from finch_epm.connectors.base import ConnectorAuthError
from finch_epm.profiles.manager import ProfileManager


def build_connection_params(
    connector_type: str,
    profile_name: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build psycopg2 connection keyword arguments from stored config + keyring.

    Config fields (stored in profiles.json):
        host: hostname or IP
        port: port number (default 5432)
        database: database name
        username: login username
        sslmode: SSL mode (default "prefer")

    Secret fields (stored in keychain):
        password: login password

    Returns:
        Dict of keyword arguments for psycopg2.connect().
    """
    pm = ProfileManager()

    if config is None:
        if not pm.profile_exists(connector_type, profile_name):
            raise ConnectorAuthError(
                f"No profile '{profile_name}' found for {connector_type}. "
                "Run: finch-epm auth -c postgres -p <profile> --env-file <path>"
            )
        config = pm.get_config(connector_type, profile_name)

    password = pm.get_secret(connector_type, profile_name, "password")
    if not password:
        raise ConnectorAuthError(
            f"Password not found in OS keychain for profile '{profile_name}'. "
            "Re-import with: finch-epm auth -c postgres --env-file <path>"
        )

    return {
        "host": config.get("host", "localhost"),
        "port": int(config.get("port", 5432)),
        "dbname": config.get("database", ""),
        "user": config.get("username", ""),
        "password": password,
        "sslmode": config.get("sslmode", "prefer"),
        "connect_timeout": 30,
    }
