"""Federated query routing.

Decides per-query whether to execute against the local DuckDB cache
or push SQL directly to a remote data source.

Decision logic:
    1. Cross-source JOINs (multiple source prefixes) → always local
    2. Single source in ``prefer_local`` → local
    3. Single source in ``prefer_remote`` and supports direct query → remote
    4. Single source with stale cache and supports direct query → remote
    5. Default → local
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from finch_epm.cache.base import CacheEngine
from finch_epm.cache.models import (
    QueryRequest,
    QueryResult,
    SourceTableRef,
    StalenessInfo,
    StalenessLevel,
)
from finch_epm.connectors.base import ConnectorBase
from finch_epm.connectors.types import ColumnType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FederationConfig:
    """Configuration for federated query routing."""

    prefer_remote: list[str] = field(default_factory=list)
    """Source prefixes that should prefer remote execution."""

    prefer_local: list[str] = field(default_factory=list)
    """Source prefixes that should always use the local cache."""

    staleness_threshold: timedelta = field(
        default_factory=lambda: timedelta(hours=1)
    )
    """How stale the cache must be before considering remote execution."""

    row_count_threshold: int = 1_000_000
    """Unused for now — reserved for future size-based routing."""


@dataclass(frozen=True)
class ExecutionPlan:
    """Describes how a query will be executed."""

    strategy: str  # "local" or "remote"
    reason: str
    source_prefix: str | None = None
    tables: list[str] = field(default_factory=list)
    staleness: StalenessInfo | None = None


class FederatedQueryRouter:
    """Routes queries to local cache or remote data sources.

    Usage::

        router = FederatedQueryRouter(
            cache=cache_engine,
            connectors={"sf": snowflake_conn, "ns": netsuite_conn},
            config=FederationConfig(prefer_remote=["sf"]),
        )
        result = router.execute(sql)
    """

    def __init__(
        self,
        cache: CacheEngine,
        connectors: dict[str, ConnectorBase],
        config: FederationConfig | None = None,
    ) -> None:
        self._cache = cache
        self._connectors = connectors
        self._config = config or FederationConfig()

    def plan_execution(
        self, sql: str, source_hint: str | None = None
    ) -> ExecutionPlan:
        """Decide whether to execute locally or remotely."""
        tables = _extract_tables_from_sql(sql)
        prefixes = set()

        for table in tables:
            try:
                ref = SourceTableRef.parse(table)
                prefixes.add(ref.source_prefix)
            except ValueError:
                # Un-prefixed table — assume local
                return ExecutionPlan(
                    strategy="local",
                    reason="un-prefixed table, defaulting to local",
                    tables=tables,
                )

        # If no tables found, execute locally
        if not prefixes:
            return ExecutionPlan(
                strategy="local",
                reason="no tables detected in query",
                tables=tables,
            )

        # Cross-source JOIN → always local
        if len(prefixes) > 1:
            return ExecutionPlan(
                strategy="local",
                reason=f"cross-source JOIN across {sorted(prefixes)}",
                tables=tables,
            )

        prefix = next(iter(prefixes))

        # Check prefer_local override
        if prefix in self._config.prefer_local:
            return ExecutionPlan(
                strategy="local",
                reason=f"source {prefix!r} in prefer_local",
                source_prefix=prefix,
                tables=tables,
            )

        connector = self._connectors.get(prefix)
        if connector is None or not connector.supports_direct_query():
            return ExecutionPlan(
                strategy="local",
                reason=f"no direct query support for {prefix!r}",
                source_prefix=prefix,
                tables=tables,
            )

        # Check prefer_remote override
        if prefix in self._config.prefer_remote:
            return ExecutionPlan(
                strategy="remote",
                reason=f"source {prefix!r} in prefer_remote",
                source_prefix=prefix,
                tables=tables,
            )

        # Check staleness — route remote if cache is stale
        if hasattr(self._cache, "get_staleness_multi_source"):
            staleness = self._cache.get_staleness_multi_source(  # type: ignore[attr-defined]
                tables, self._config.staleness_threshold
            )
            if staleness.level == StalenessLevel.STALE:
                return ExecutionPlan(
                    strategy="remote",
                    reason=f"cache is stale for {prefix!r}",
                    source_prefix=prefix,
                    tables=tables,
                    staleness=staleness,
                )

        # Default: local
        return ExecutionPlan(
            strategy="local",
            reason="cache is fresh, defaulting to local",
            source_prefix=prefix,
            tables=tables,
        )

    def execute(
        self, sql: str, source_hint: str | None = None
    ) -> QueryResult:
        """Execute a query, routing to local cache or remote source."""
        plan = self.plan_execution(sql, source_hint)

        if plan.strategy == "remote" and plan.source_prefix:
            connector = self._connectors[plan.source_prefix]
            remote_sql = _strip_source_prefixes(sql, plan.source_prefix)

            start = time.monotonic()
            try:
                fact_result = connector.execute_direct_query(remote_sql)
            except Exception as e:
                logger.warning(
                    "Remote query failed for %s, falling back to local: %s",
                    plan.source_prefix, e,
                )
                return self._cache.execute_query(QueryRequest(sql=sql))

            elapsed = (time.monotonic() - start) * 1000
            return QueryResult(
                column_names=list(fact_result.column_names),
                column_types=[ct.value if isinstance(ct, ColumnType) else str(ct)
                              for ct in fact_result.column_types],
                rows=[list(row) for row in fact_result.rows],
                row_count=len(fact_result.rows),
                staleness=StalenessInfo(level=StalenessLevel.FRESH),
                execution_time_ms=elapsed,
                served_from=f"remote:{plan.source_prefix}",
            )
        else:
            return self._cache.execute_query(QueryRequest(sql=sql))


def _extract_tables_from_sql(sql: str) -> list[str]:
    """Best-effort extraction of table names from FROM/JOIN clauses."""
    pattern = r"(?:FROM|JOIN)\s+(?:\"([^\"]+)\"|([A-Za-z_][A-Za-z0-9_]*))"
    matches = re.findall(pattern, sql, re.IGNORECASE)
    tables: list[str] = []
    seen: set[str] = set()
    skip = {"SELECT", "WHERE", "GROUP", "ORDER", "HAVING", "LIMIT",
            "UNION", "EXCEPT", "INTERSECT", "VALUES", "SET"}
    for quoted, unquoted in matches:
        name = quoted or unquoted
        if name.upper() in skip:
            continue
        if name not in seen:
            seen.add(name)
            tables.append(name)
    return tables


def _strip_source_prefixes(sql: str, prefix: str) -> str:
    """Rewrite namespaced table names to their original form.

    ``sf__PUBLIC__EVENTS`` becomes ``PUBLIC.EVENTS`` (double underscores
    after stripping the prefix become dots again).
    """
    pattern = rf"\b{re.escape(prefix)}__(\S+)"

    def replace_match(m: re.Match[str]) -> str:
        raw = m.group(1)
        # Convert remaining __ back to dots for schema-qualified names
        return raw.replace("__", ".")

    return re.sub(pattern, replace_match, sql)
