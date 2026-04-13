"""System prompt builder for the ``ask`` command.

Assembles the LLM system prompt from:
    1. The full DASHBOARDS.md specification (loaded from the installed package)
    2. A compact JSON summary of accessible tables and columns
    3. Sample rows from each relevant table
    4. Rules and constraints for generating valid .fdash files
"""

from __future__ import annotations

import json
import logging
from importlib import resources as importlib_resources
from pathlib import Path
from typing import Any

from finch_epm.cache.base import CacheEngine
from finch_epm.cache.models import QueryRequest
from finch_epm.catalog.catalog import CatalogStore

logger = logging.getLogger(__name__)

# Try to load DASHBOARDS.md from the package root (development) or fallback
_DASHBOARDS_MD: str | None = None


def _load_dashboards_md() -> str:
    """Load the DASHBOARDS.md specification."""
    global _DASHBOARDS_MD
    if _DASHBOARDS_MD is not None:
        return _DASHBOARDS_MD

    # Try common locations relative to the project
    candidates = [
        Path(__file__).parent.parent.parent.parent / "DASHBOARDS.md",
        Path.cwd() / "DASHBOARDS.md",
    ]
    for p in candidates:
        if p.exists():
            _DASHBOARDS_MD = p.read_text(encoding="utf-8")
            return _DASHBOARDS_MD

    _DASHBOARDS_MD = "(DASHBOARDS.md not found -- generate a valid .fdash YAML file)"
    return _DASHBOARDS_MD


def build_catalog_summary(
    catalog: CatalogStore,
    profiles: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Build a compact catalog summary for the system prompt.

    Args:
        catalog: The catalog store.
        profiles: List of (connector_type, profile_name) tuples.

    Returns:
        List of dicts, each describing one table with columns.
    """
    tables_summary: list[dict[str, Any]] = []

    for connector_type, profile_name in profiles:
        # Include all tables -- accessible filter is too restrictive when
        # connectors don't set access_status metadata (e.g. Fake, ODBC)
        accessible = catalog.list_tables(connector_type, profile_name)
        for table in accessible:
            table_name = table.get("table_name") if isinstance(table, dict) else table[2]
            columns = catalog.list_columns(connector_type, profile_name, table_name)
            col_list = []
            for col in columns:
                if isinstance(col, dict):
                    col_list.append({
                        "name": col.get("column_name", ""),
                        "type": col.get("column_type", "VARCHAR"),
                    })
                else:
                    col_list.append({"name": col[3], "type": col[4]})

            tables_summary.append({
                "source": f"{connector_type}/{profile_name}",
                "table": table_name,
                "columns": col_list,
            })

    return tables_summary


def build_sample_rows(
    cache: CacheEngine,
    table_names: list[str],
    limit: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch sample rows from the cache for each table.

    Args:
        cache: The cache engine.
        table_names: Tables to sample.
        limit: Max rows per table.

    Returns:
        Dict mapping table name -> list of row dicts.
    """
    samples: dict[str, list[dict[str, Any]]] = {}

    for table in table_names:
        try:
            result = cache.execute_query(
                QueryRequest(
                    sql=f'SELECT * FROM "{table}" LIMIT {limit}',
                    parameters={},
                    source_name="",
                )
            )
            rows = []
            for row in result.rows:
                row_dict = {}
                for i, col_name in enumerate(result.column_names):
                    val = row[i]
                    # Truncate long strings for prompt brevity
                    if isinstance(val, str) and len(val) > 100:
                        val = val[:100] + "..."
                    row_dict[col_name] = val
                rows.append(row_dict)
            samples[table] = rows
        except Exception:
            logger.debug("Could not sample table %s", table, exc_info=True)

    return samples


def build_system_prompt(
    catalog: CatalogStore,
    cache: CacheEngine | None,
    profiles: list[tuple[str, str]],
) -> str:
    """Assemble the full system prompt for dashboard generation.

    Args:
        catalog: The catalog store for schema metadata.
        cache: The cache engine for sample rows.
        profiles: List of (connector_type, profile_name) tuples.

    Returns:
        Complete system prompt string.
    """
    dashboards_md = _load_dashboards_md()
    catalog_summary = build_catalog_summary(catalog, profiles)

    # Get unique table names for sampling
    table_names = [t["table"] for t in catalog_summary]
    samples = build_sample_rows(cache, table_names) if cache else {}

    # Estimate prompt size
    prompt_parts: list[str] = []

    prompt_parts.append(
        "You are a dashboard generator for finch-epm. "
        "Your task is to generate a valid .fdash dashboard file based on the "
        "user's request. The .fdash file must be valid YAML that conforms to "
        "the specification below.\n\n"
        "IMPORTANT: Output ONLY the .fdash YAML content wrapped in ```yaml fences. "
        "Do not include any explanatory text outside the YAML block.\n"
    )

    prompt_parts.append("# Dashboard Specification\n\n")
    prompt_parts.append(dashboards_md)
    prompt_parts.append("\n\n")

    prompt_parts.append("# Available Data\n\n")
    prompt_parts.append("The following tables and columns are available in the local cache. ")
    prompt_parts.append("All queries run against DuckDB (PostgreSQL-compatible dialect).\n\n")

    if catalog_summary:
        prompt_parts.append("```json\n")
        prompt_parts.append(json.dumps(catalog_summary, indent=2))
        prompt_parts.append("\n```\n\n")
    else:
        prompt_parts.append("(No tables found in catalog. Generate a demo dashboard "
                            "using example data.)\n\n")

    if samples:
        prompt_parts.append("# Sample Rows\n\n")
        prompt_parts.append("Here are sample rows from each table so you can see "
                            "real column values and data types:\n\n")
        for table_name, rows in samples.items():
            if rows:
                prompt_parts.append(f"## {table_name}\n```json\n")
                prompt_parts.append(json.dumps(rows, indent=2, default=str))
                prompt_parts.append("\n```\n\n")

    # Include classification context if available
    try:
        from finch_epm.engine.classification_models import ClassificationStore, DataClass
        cls_store = ClassificationStore.load()
        classified_tables: list[dict[str, str]] = []
        for source_key, tables in cls_store.tables.items():
            for tname, tc in tables.items():
                if tc.data_class != DataClass.UNDETERMINED:
                    classified_tables.append({
                        "source": source_key,
                        "table": tname,
                        "classification": tc.data_class.display_name,
                    })
        if classified_tables:
            prompt_parts.append("# Data Classifications\n\n")
            prompt_parts.append(
                "The following tables have been classified by the user. "
                "Use these classifications to choose appropriate chart types "
                "and data handling:\n\n"
            )
            prompt_parts.append("```json\n")
            prompt_parts.append(json.dumps(classified_tables, indent=2))
            prompt_parts.append("\n```\n\n")
    except Exception:
        pass  # Classification store not available -- skip

    # Include table links for cross-source JOIN awareness
    try:
        from finch_epm.engine.table_linker import TableLinker
        linker = TableLinker.load()
        if linker.links:
            prompt_parts.append("# Cross-Source Table Links\n\n")
            prompt_parts.append(
                "The user has linked these tables across data sources. "
                "Use these links when building JOINs in queries:\n\n"
            )
            for link in linker.links:
                prompt_parts.append(
                    f"- {link.source_table}.{link.source_column} "
                    f"<-> {link.target_table}.{link.target_column}\n"
                )
            prompt_parts.append("\n")
        if linker.dimensions:
            prompt_parts.append("# Dimension Tables\n\n")
            for dim in linker.dimensions:
                prompt_parts.append(
                    f"- {dim.name}: table={dim.dimension_table}, "
                    f"id={dim.id_column}, label={dim.label_column}, "
                    f"join on fact.{dim.fact_join_column}\n"
                )
                if dim.rollup_columns:
                    prompt_parts.append(
                        f"  Rollups: {', '.join(dim.rollup_columns)}\n"
                    )
            prompt_parts.append("\n")
    except Exception:
        pass

    # Include COA summary for P&L awareness
    try:
        from finch_epm.engine.coa import ChartOfAccounts
        coa = ChartOfAccounts.load()
        if coa.accounts:
            counts = coa.count_by_category()
            prompt_parts.append("# Chart of Accounts\n\n")
            prompt_parts.append(
                f"The user has a {len(coa.level_names)}-level P&L hierarchy "
                f"with {len(coa.accounts)} accounts:\n"
            )
            for cat, count in sorted(counts.items()):
                prompt_parts.append(f"- {cat}: {count} accounts\n")
            prompt_parts.append(
                "\nWhen building P&L dashboards, group by account type "
                "(Income, Expense, COGS, etc.) and use the COA hierarchy "
                "for sub-groupings.\n\n"
            )
    except Exception:
        pass

    prompt_parts.append(
        "# Additional Rules\n\n"
        "- All NetSuite data is stored as VARCHAR. Use CAST() for numeric operations.\n"
        "- SQL Server/Postgres tables use double underscores for dots: "
        "dbo.Table becomes dbo__Table in cache.\n"
        "- Always include at least one query and one chart.\n"
        "- Match column names in chart specs exactly to SQL aliases.\n"
        "- Use DuckDB SQL dialect.\n"
        "- Output only the YAML inside ```yaml fences. No explanation.\n"
    )

    full_prompt = "".join(prompt_parts)

    # Warn if prompt is very large
    estimated_tokens = len(full_prompt) // 4
    if estimated_tokens > 50000:
        logger.warning(
            "System prompt is ~%d tokens. Consider reducing the number of "
            "tables or using --profile to scope to relevant data.",
            estimated_tokens,
        )

    return full_prompt
