"""Mapping API endpoints for the data linking web UI.

Provides the backend for the visual table-linking interface where users
click column headers to discover and establish cross-source data links.
The key innovation is value-based matching: when a user clicks a column,
the system scans all other tables for columns containing matching values,
not just matching names.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from finch_epm.cache.local import LocalCacheEngine
from finch_epm.cache.models import QueryRequest

logger = logging.getLogger(__name__)


def get_all_tables(cache: LocalCacheEngine) -> list[dict[str, Any]]:
    """List all cached tables with row counts, sorted by size."""
    result = cache.execute_query(QueryRequest(
        sql="""SELECT table_name FROM information_schema.tables
               WHERE table_schema='main'
               ORDER BY table_name"""
    ))
    tables = []
    for row in result.rows:
        tname = row[0]
        if tname.startswith("_"):
            continue
        try:
            cnt = cache.execute_query(QueryRequest(sql=f'SELECT COUNT(*) FROM "{tname}"'))
            row_count = cnt.rows[0][0]
        except Exception:
            row_count = 0
        tables.append({
            "name": tname,
            "rows": row_count,
            "type": "reference" if row_count <= 5000 else "fact",
        })
    return sorted(tables, key=lambda t: t["rows"])


def get_table_columns(cache: LocalCacheEngine, table_name: str) -> list[dict[str, Any]]:
    """Get columns for a table with types and sample values."""
    try:
        # Get column names and types
        cols_result = cache.execute_query(QueryRequest(
            sql=f"""SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_name = '{table_name}'
                    ORDER BY ordinal_position"""
        ))

        # Get sample row
        sample = cache.execute_query(QueryRequest(
            sql=f'SELECT * FROM "{table_name}" LIMIT 5'
        ))

        columns = []
        for i, row in enumerate(cols_result.rows):
            col_name = row[0]
            col_type = row[1]

            # Get distinct count
            try:
                distinct = cache.execute_query(QueryRequest(
                    sql=f'SELECT COUNT(DISTINCT "{col_name}") FROM "{table_name}"'
                ))
                distinct_count = distinct.rows[0][0]
            except Exception:
                distinct_count = 0

            # Sample values
            samples = []
            col_idx = sample.column_names.index(col_name) if col_name in sample.column_names else -1
            if col_idx >= 0:
                for srow in sample.rows[:5]:
                    val = srow[col_idx]
                    if val is not None:
                        samples.append(str(val))

            columns.append({
                "name": col_name,
                "type": col_type,
                "distinct_count": distinct_count,
                "samples": samples[:5],
            })

        return columns
    except Exception as e:
        logger.warning("Failed to get columns for %s: %s", table_name, e)
        return []


def find_value_matches(
    cache: LocalCacheEngine,
    source_table: str,
    source_column: str,
) -> list[dict[str, Any]]:
    """Find columns in other tables that contain matching values.

    The core of the mapping UI: takes the values from one column,
    tries common transforms (strip prefix, cast to int, lowercase),
    and checks every column in every other table for overlap.

    Returns matches ranked by match rate.
    """
    # Get distinct values from the source column
    try:
        src_vals = cache.execute_query(QueryRequest(
            sql=f'SELECT DISTINCT CAST("{source_column}" AS VARCHAR) FROM "{source_table}" WHERE "{source_column}" IS NOT NULL LIMIT 500'
        ))
        source_values = {str(row[0]) for row in src_vals.rows if row[0]}
    except Exception:
        return []

    if not source_values:
        return []

    # Generate transformed value sets for prefix-stripping
    transforms = {"raw": source_values}

    # Common prefixes: L, D, E (NetSuite convention)
    for prefix in ["L", "D", "E"]:
        stripped = set()
        for v in source_values:
            if v.startswith(prefix) and len(v) > 1 and v[1:].isdigit():
                stripped.add(v[1:])
        if stripped:
            transforms[f"strip_{prefix}"] = stripped

    # Also try adding prefixes (for matching the other direction)
    for prefix in ["L", "D", "E"]:
        prefixed = set()
        for v in source_values:
            if v.isdigit():
                prefixed.add(f"{prefix}{v}")
        if prefixed:
            transforms[f"add_{prefix}"] = prefixed

    # Get all other tables
    all_tables = get_all_tables(cache)
    matches: list[dict[str, Any]] = []

    for table in all_tables:
        tname = table["name"]
        if tname == source_table:
            continue

        try:
            # Get columns for this table
            cols = cache.execute_query(QueryRequest(
                sql=f"""SELECT column_name FROM information_schema.columns
                        WHERE table_name = '{tname}'
                        ORDER BY ordinal_position"""
            ))

            for col_row in cols.rows:
                col_name = col_row[0]
                if col_name.startswith("_") or col_name.startswith("ledger_"):
                    continue

                # Get distinct values from this column
                try:
                    tgt_vals = cache.execute_query(QueryRequest(
                        sql=f'SELECT DISTINCT CAST("{col_name}" AS VARCHAR) FROM "{tname}" WHERE "{col_name}" IS NOT NULL LIMIT 500'
                    ))
                    target_values = {str(r[0]) for r in tgt_vals.rows if r[0]}
                except Exception:
                    continue

                if not target_values:
                    continue

                # Try each transform
                best_match = 0.0
                best_transform = "raw"

                for transform_name, transformed_source in transforms.items():
                    if not transformed_source:
                        continue
                    overlap = transformed_source & target_values
                    if not overlap:
                        continue
                    # Jaccard-like: overlap / source size
                    match_rate = len(overlap) / len(transformed_source)
                    if match_rate > best_match:
                        best_match = match_rate
                        best_transform = transform_name

                if best_match >= 0.1:  # At least 10% match
                    matches.append({
                        "table": tname,
                        "column": col_name,
                        "match_rate": round(best_match * 100, 1),
                        "transform": best_transform,
                        "table_rows": table["rows"],
                    })

        except Exception:
            continue

    # Sort by match rate descending
    matches.sort(key=lambda m: -m["match_rate"])
    return matches[:20]  # Top 20


def get_mapping_health(cache: LocalCacheEngine) -> dict[str, Any]:
    """Compute mapping coverage statistics."""
    from finch_epm.engine.compilation_map import CompilationMap

    cmap = CompilationMap.load()
    health: dict[str, Any] = {
        "references": len(cmap.references),
        "total_links": sum(len(r.source_links) for r in cmap.references),
        "coverage": [],
    }

    # For each reference, check what % of fact rows map
    for ref in cmap.references:
        ref_info: dict[str, Any] = {
            "name": ref.name,
            "table": ref.table,
            "links": len(ref.source_links),
        }

        for link in ref.source_links:
            try:
                # Count total rows in the fact table
                total = cache.execute_query(QueryRequest(
                    sql=f'SELECT COUNT(*) FROM "{link.table}"'
                ))
                total_rows = total.rows[0][0]

                # Count rows that match the reference
                join_sql = cmap.generate_join_sql(ref.name, link.name)
                if join_sql:
                    matched = cache.execute_query(QueryRequest(
                        sql=f'SELECT COUNT(*) FROM "{link.table}" {join_sql} WHERE ref_{ref.name}.{ref.id_column} IS NOT NULL'
                    ))
                    matched_rows = matched.rows[0][0]
                else:
                    matched_rows = 0

                pct = round(matched_rows / total_rows * 100, 1) if total_rows > 0 else 0
                ref_info[f"coverage_{link.name}"] = {
                    "fact_table": link.table,
                    "total_rows": total_rows,
                    "matched_rows": matched_rows,
                    "coverage_pct": pct,
                }
            except Exception as e:
                ref_info[f"coverage_{link.name}"] = {"error": str(e)[:80]}

        health["coverage"].append(ref_info)

    return health


def get_current_map() -> dict[str, Any]:
    """Return the current compilation map as a JSON-serializable dict."""
    from finch_epm.engine.compilation_map import CompilationMap

    cmap = CompilationMap.load()
    return {
        "name": cmap.name,
        "references": [
            {
                "name": ref.name,
                "table": ref.table,
                "id_column": ref.id_column,
                "display_column": ref.display_column,
                "source_links": [
                    {
                        "name": sl.name,
                        "table": sl.table,
                        "join_column": sl.join_column,
                        "transform": sl.transform,
                    }
                    for sl in ref.source_links
                ],
                "rollups": [
                    {"column": r.column, "display": r.display}
                    for r in ref.rollups
                ],
                "flag_groups": [
                    {
                        "name": fg.name,
                        "display": fg.display,
                        "flags": [{"column": f.column, "display": f.display} for f in fg.flags],
                    }
                    for fg in ref.flag_groups
                ],
            }
            for ref in cmap.references
        ],
    }


def add_link(
    reference_name: str,
    source_table: str,
    source_column: str,
    transform: str = "",
) -> dict[str, Any]:
    """Add a link from a fact table column to a reference table."""
    from finch_epm.engine.compilation_map import CompilationMap, SourceLink

    cmap = CompilationMap.load()
    ref = cmap.get_reference(reference_name)
    if not ref:
        return {"error": f"Reference '{reference_name}' not found"}

    # Check for duplicate
    for existing in ref.source_links:
        if existing.table == source_table and existing.join_column == source_column:
            return {"error": "Link already exists", "link": existing.name}

    link = SourceLink(
        name=source_table.split("__")[-1].lower(),
        table=source_table,
        join_column=source_column,
        transform=transform,
    )
    ref.source_links.append(link)
    cmap.save()

    return {"success": True, "link": link.name}


def remove_link(reference_name: str, link_name: str) -> dict[str, Any]:
    """Remove a link from the compilation map."""
    from finch_epm.engine.compilation_map import CompilationMap

    cmap = CompilationMap.load()
    ref = cmap.get_reference(reference_name)
    if not ref:
        return {"error": f"Reference '{reference_name}' not found"}

    before = len(ref.source_links)
    ref.source_links = [sl for sl in ref.source_links if sl.name != link_name]
    after = len(ref.source_links)

    if before == after:
        return {"error": f"Link '{link_name}' not found"}

    cmap.save()
    return {"success": True, "removed": link_name}
