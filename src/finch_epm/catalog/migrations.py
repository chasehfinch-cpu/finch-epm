"""Catalog database schema creation and versioning.

The catalog stores introspection results (tables, columns, dimensions)
in a DuckDB database separate from the data cache.
"""

from __future__ import annotations

import duckdb

_SCHEMA_VERSION = 1

_CREATE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS catalog_sources (
        source_name        VARCHAR NOT NULL,
        profile_name       VARCHAR NOT NULL,
        connector_type     VARCHAR NOT NULL,
        last_introspected_at TIMESTAMP,
        metadata_json      VARCHAR,
        PRIMARY KEY (source_name, profile_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS catalog_tables (
        source_name        VARCHAR NOT NULL,
        profile_name       VARCHAR NOT NULL,
        table_name         VARCHAR NOT NULL,
        display_name       VARCHAR,
        is_custom          BOOLEAN DEFAULT FALSE,
        access_status      VARCHAR,
        category           VARCHAR,
        row_count_estimate BIGINT,
        introspected_at    TIMESTAMP,
        metadata_json      VARCHAR,
        PRIMARY KEY (source_name, profile_name, table_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS catalog_columns (
        source_name        VARCHAR NOT NULL,
        profile_name       VARCHAR NOT NULL,
        table_name         VARCHAR NOT NULL,
        column_name        VARCHAR NOT NULL,
        display_name       VARCHAR,
        column_type        VARCHAR,
        is_custom          BOOLEAN DEFAULT FALSE,
        is_nullable        BOOLEAN DEFAULT TRUE,
        ordinal_position   INTEGER,
        metadata_json      VARCHAR,
        PRIMARY KEY (source_name, profile_name, table_name, column_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS catalog_dimensions (
        source_name        VARCHAR NOT NULL,
        profile_name       VARCHAR NOT NULL,
        dimension_name     VARCHAR NOT NULL,
        display_name       VARCHAR,
        table_name         VARCHAR NOT NULL,
        id_column          VARCHAR NOT NULL,
        label_column       VARCHAR NOT NULL,
        supports_hierarchy BOOLEAN DEFAULT FALSE,
        parent_column      VARCHAR,
        metadata_json      VARCHAR,
        PRIMARY KEY (source_name, profile_name, dimension_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS catalog_meta (
        key   VARCHAR PRIMARY KEY,
        value VARCHAR
    )
    """,
]


def ensure_catalog_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create all catalog tables if they don't exist.

    Safe to call on every startup — uses CREATE TABLE IF NOT EXISTS.
    """
    for stmt in _CREATE_STATEMENTS:
        conn.execute(stmt)

    # Track schema version
    conn.execute(
        "INSERT OR REPLACE INTO catalog_meta (key, value) VALUES ('schema_version', ?)",
        [str(_SCHEMA_VERSION)],
    )
