"""SQL Server connection string builder.

Retrieves credentials from the OS keychain and builds a pyodbc
connection string. Supports Azure SQL and on-premises SQL Server.
"""

from __future__ import annotations

from finch_epm.connectors.base import ConnectorAuthError
from finch_epm.profiles.manager import ProfileManager


def build_connection_string(
    connector_type: str,
    profile_name: str,
    config: dict | None = None,
) -> str:
    """Build a pyodbc connection string from stored profile config + keyring.

    Config fields (stored in profiles.json):
        server: hostname or Azure SQL FQDN
        database: database name
        username: SQL login username
        driver: ODBC driver name (default: auto-detect)

    Secret fields (stored in keychain):
        password: SQL login password

    Returns:
        A pyodbc connection string.
    """
    pm = ProfileManager()

    if config is None:
        if not pm.profile_exists(connector_type, profile_name):
            raise ConnectorAuthError(
                f"No profile '{profile_name}' found for {connector_type}. "
                "Run: finch-epm auth -c sqlserver -p <profile> --env-file <path>"
            )
        config = pm.get_config(connector_type, profile_name)

    server = config.get("server", "")
    database = config.get("database", "")
    username = config.get("username", "")
    driver = config.get("driver", "")

    password = pm.get_secret(connector_type, profile_name, "password")
    if not password:
        raise ConnectorAuthError(
            f"Password not found in OS keychain for profile '{profile_name}'. "
            "Re-import with: finch-epm auth -c sqlserver --env-file <path>"
        )

    if not driver:
        driver = _detect_odbc_driver()

    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server}",
        f"DATABASE={database}",
        f"UID={username}",
        f"PWD={password}",
    ]

    # Azure SQL requires encryption
    if ".database.windows.net" in server.lower():
        parts.append("Encrypt=yes")
        parts.append("TrustServerCertificate=no")

    return ";".join(parts)


def _detect_odbc_driver() -> str:
    """Auto-detect an available ODBC driver for SQL Server.

    Tries common driver names in order of preference.
    """
    try:
        import pyodbc
        available = pyodbc.drivers()
    except ImportError:
        raise ConnectorAuthError(
            "pyodbc is not installed. Install with: pip install finch-epm[sqlserver]"
        )

    preferred = [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13.1 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "SQL Server Native Client 11.0",
        "SQL Server",
    ]

    for driver in preferred:
        if driver in available:
            return driver

    if available:
        # Use whatever is available
        for d in available:
            if "sql" in d.lower():
                return d

    raise ConnectorAuthError(
        "No SQL Server ODBC driver found. Install one from: "
        "https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server"
    )
