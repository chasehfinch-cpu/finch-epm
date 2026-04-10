"""DuckDB-backed persistent schema catalog.

Stores introspection results (tables, columns, dimensions) so they
survive between CLI sessions. Uses a separate DuckDB database from
the data cache.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import duckdb

from finch_epm.catalog.migrations import ensure_catalog_schema
from finch_epm.connectors.types import DimensionInfo, SchemaInfo
from finch_epm.paths import catalog_db_path


class CatalogStore:
    """Persistent schema catalog backed by DuckDB.

    Args:
        db_path: Path to the DuckDB database file. Use ``":memory:"`` for
            testing. If None, uses the platform-appropriate default.
    """

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            db_path = str(catalog_db_path())
        self._conn = duckdb.connect(db_path)
        ensure_catalog_schema(self._conn)

    def close(self) -> None:
        """Close the DuckDB connection."""
        self._conn.close()

    # --- Write operations ---

    def save_schema(self, schema: SchemaInfo) -> None:
        """Persist a SchemaInfo from introspect_schema().

        Does a full replace for this source/profile: deletes all existing
        tables and columns, then inserts everything fresh. This ensures
        removed records (e.g., deleted custom records) disappear on re-crawl.
        """
        src = schema.source_name
        prof = schema.profile_name
        now = datetime.now()

        # Upsert source record
        self._conn.execute(
            "DELETE FROM catalog_sources WHERE source_name = ? AND profile_name = ?",
            [src, prof],
        )
        self._conn.execute(
            "INSERT INTO catalog_sources (source_name, profile_name, connector_type, "
            "last_introspected_at, metadata_json) VALUES (?, ?, ?, ?, ?)",
            [src, prof, src, now, json.dumps(schema.metadata)],
        )

        # Delete existing tables and columns
        self._conn.execute(
            "DELETE FROM catalog_columns WHERE source_name = ? AND profile_name = ?",
            [src, prof],
        )
        self._conn.execute(
            "DELETE FROM catalog_tables WHERE source_name = ? AND profile_name = ?",
            [src, prof],
        )

        # Insert tables and columns
        for table in schema.tables:
            self._conn.execute(
                "INSERT INTO catalog_tables "
                "(source_name, profile_name, table_name, display_name, is_custom, "
                "access_status, category, row_count_estimate, introspected_at, metadata_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    src,
                    prof,
                    table.name,
                    table.display_name,
                    table.is_custom,
                    table.metadata.get("access_status", "unknown"),
                    table.metadata.get("category", ""),
                    table.row_count_estimate,
                    now,
                    json.dumps(table.metadata),
                ],
            )

            for i, col in enumerate(table.columns):
                meta = dict(col.metadata)
                if col.reference_target:
                    meta["reference_target"] = col.reference_target
                self._conn.execute(
                    "INSERT INTO catalog_columns "
                    "(source_name, profile_name, table_name, column_name, display_name, "
                    "column_type, is_custom, is_nullable, ordinal_position, metadata_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        src,
                        prof,
                        table.name,
                        col.name,
                        col.display_name,
                        col.column_type.value,
                        col.is_custom,
                        col.is_nullable,
                        i,
                        json.dumps(meta) if meta else None,
                    ],
                )

    def save_dimensions(
        self,
        source_name: str,
        profile_name: str,
        dimensions: list[DimensionInfo],
    ) -> None:
        """Persist dimension list from list_dimensions().

        Full replace for this source/profile.
        """
        self._conn.execute(
            "DELETE FROM catalog_dimensions WHERE source_name = ? AND profile_name = ?",
            [source_name, profile_name],
        )

        for dim in dimensions:
            self._conn.execute(
                "INSERT INTO catalog_dimensions "
                "(source_name, profile_name, dimension_name, display_name, table_name, "
                "id_column, label_column, supports_hierarchy, parent_column, metadata_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    source_name,
                    profile_name,
                    dim.name,
                    dim.display_name,
                    dim.table_name,
                    dim.id_column,
                    dim.label_column,
                    dim.supports_hierarchy,
                    dim.metadata.get("parent_column"),
                    json.dumps(dim.metadata),
                ],
            )

    # --- Read operations ---

    def get_source(
        self, source_name: str, profile_name: str
    ) -> dict[str, Any] | None:
        """Return the source record, or None if not found."""
        row = self._conn.execute(
            "SELECT * FROM catalog_sources "
            "WHERE source_name = ? AND profile_name = ?",
            [source_name, profile_name],
        ).fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self._conn.description]
        return dict(zip(cols, row))

    def list_tables(
        self,
        source_name: str,
        profile_name: str,
        access_status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all cataloged tables. Optionally filter by access_status."""
        sql = (
            "SELECT table_name, display_name, is_custom, access_status, "
            "category, row_count_estimate FROM catalog_tables "
            "WHERE source_name = ? AND profile_name = ?"
        )
        params: list[Any] = [source_name, profile_name]

        if access_status:
            sql += " AND access_status = ?"
            params.append(access_status)

        sql += " ORDER BY table_name"
        rows = self._conn.execute(sql, params).fetchall()
        cols = ["table_name", "display_name", "is_custom", "access_status",
                "category", "row_count_estimate"]
        return [dict(zip(cols, row)) for row in rows]

    def list_columns(
        self, source_name: str, profile_name: str, table_name: str
    ) -> list[dict[str, Any]]:
        """Return all columns for a table, ordered by ordinal_position."""
        rows = self._conn.execute(
            "SELECT column_name, display_name, column_type, is_custom, "
            "is_nullable, ordinal_position FROM catalog_columns "
            "WHERE source_name = ? AND profile_name = ? AND table_name = ? "
            "ORDER BY ordinal_position",
            [source_name, profile_name, table_name],
        ).fetchall()
        cols = ["column_name", "display_name", "column_type", "is_custom",
                "is_nullable", "ordinal_position"]
        return [dict(zip(cols, row)) for row in rows]

    def list_dimensions(
        self, source_name: str, profile_name: str
    ) -> list[dict[str, Any]]:
        """Return all dimensions for a source/profile."""
        rows = self._conn.execute(
            "SELECT dimension_name, display_name, table_name, id_column, "
            "label_column, supports_hierarchy, parent_column FROM catalog_dimensions "
            "WHERE source_name = ? AND profile_name = ? "
            "ORDER BY dimension_name",
            [source_name, profile_name],
        ).fetchall()
        cols = ["dimension_name", "display_name", "table_name", "id_column",
                "label_column", "supports_hierarchy", "parent_column"]
        return [dict(zip(cols, row)) for row in rows]

    def get_accessible_table_names(
        self, source_name: str, profile_name: str
    ) -> list[str]:
        """Return table names where access_status='accessible'.

        Used by ``sync --all`` to determine what can be synced.
        """
        rows = self._conn.execute(
            "SELECT table_name FROM catalog_tables "
            "WHERE source_name = ? AND profile_name = ? AND access_status = 'accessible' "
            "ORDER BY table_name",
            [source_name, profile_name],
        ).fetchall()
        return [row[0] for row in rows]
