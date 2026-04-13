"""Abstract base class for all finch-epm data source connectors.

Every connector (NetSuite, SQL Server, Postgres, Snowflake, BigQuery)
implements this interface. The catalog, cache, and renderer depend only
on ConnectorBase — they never import a specific connector.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Generator

from finch_epm.connectors.types import (
    DimensionInfo,
    FactResult,
    FetchPlan,
    HierarchyNode,
    SchemaInfo,
    ScopeDescription,
)


class ConnectorAuthError(Exception):
    """Raised when authentication fails or credentials are missing."""


class ConnectorError(Exception):
    """Base exception for connector-level errors."""


class ConnectorBase(ABC):
    """Abstract base class for data source connectors.

    Lifecycle::

        connector = SomeConnector("profile_name", config)
        connector.connect()        # retrieve creds from keyring, validate
        schema = connector.introspect_schema()
        connector.close()

    Or as a context manager::

        with SomeConnector("profile_name", config) as conn:
            schema = conn.introspect_schema()
    """

    connector_type: ClassVar[str]
    """Unique identifier for this connector type, e.g. ``"netsuite"``."""

    display_name: ClassVar[str]
    """Human-readable name, e.g. ``"NetSuite"``."""

    source_prefix: ClassVar[str]
    """Short prefix for cache table namespacing, e.g. ``"ns"``."""

    def __init__(self, profile_name: str, config: dict[str, Any]) -> None:
        """Initialize connector with a named profile and its configuration.

        Args:
            profile_name: User-chosen profile name (e.g. ``"production"``).
            config: Profile-specific config dict. Does NOT contain secrets —
                those are retrieved from keyring at connect() time.
        """
        self.profile_name = profile_name
        self.config = config
        self._connected = False

    # --- Lifecycle ---

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to the data source.

        Retrieves credentials from keyring, validates them, and prepares
        the connector for queries.

        Raises:
            ConnectorAuthError: If credentials are missing or invalid.
            ConnectorError: If connection fails for other reasons.
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """Release any resources (HTTP sessions, connections, etc.)."""
        ...

    def __enter__(self) -> ConnectorBase:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        self.close()

    @property
    def is_connected(self) -> bool:
        """Whether this connector has an active connection."""
        return self._connected

    # --- Schema discovery ---

    @abstractmethod
    def introspect_schema(self) -> SchemaInfo:
        """Discover all tables, columns, and custom fields visible to the user.

        This is the full crawl used during ``finch-epm setup``.

        Returns:
            Complete schema information for this source and profile.
        """
        ...

    @abstractmethod
    def list_dimensions(self) -> list[DimensionInfo]:
        """Enumerate dimensional entities available for filtering/grouping.

        Returns:
            List of dimensions (subsidiary, department, location, etc.).
        """
        ...

    @abstractmethod
    def get_hierarchy(self, dimension_name: str) -> list[HierarchyNode]:
        """Retrieve the parent-child tree for a dimension.

        Args:
            dimension_name: Must match ``DimensionInfo.name`` from
                :meth:`list_dimensions`.

        Returns:
            Root-level nodes, each containing children recursively.

        Raises:
            ValueError: If the dimension doesn't support hierarchies.
        """
        ...

    # --- Data fetching ---

    @abstractmethod
    def plan_scope(self, scope: ScopeDescription) -> FetchPlan:
        """Translate a connector-agnostic scope into a native fetch plan.

        Lets the UI show estimated row counts and API calls before syncing.

        Args:
            scope: What data the caller wants.

        Returns:
            Execution plan the caller passes back to :meth:`fetch_facts`.
        """
        ...

    @abstractmethod
    def fetch_facts(self, plan: FetchPlan) -> FactResult:
        """Execute a fetch plan and return tabular data.

        Handles pagination, rate limiting, and retries internally.

        Args:
            plan: A plan previously returned by :meth:`plan_scope`.

        Returns:
            Tabular data with column names, types, and rows.
        """
        ...

    def fetch_facts_chunked(
        self,
        plan: FetchPlan,
        chunk_size: int = 50_000,
    ) -> "Generator[FactResult, None, None]":
        """Yield data in chunks instead of loading everything into memory.

        Default implementation calls ``fetch_facts()`` and yields one chunk.
        Connectors with large datasets should override this to fetch and
        yield in batches, keeping memory usage constant.

        Args:
            plan: A plan previously returned by :meth:`plan_scope`.
            chunk_size: Target rows per chunk.

        Yields:
            FactResult objects, each with up to ``chunk_size`` rows.
        """
        result = self.fetch_facts(plan)
        if len(result.rows) <= chunk_size:
            yield result
            return
        # Split the result into chunks
        for i in range(0, len(result.rows), chunk_size):
            chunk_rows = result.rows[i : i + chunk_size]
            yield FactResult(
                column_names=result.column_names,
                column_types=result.column_types,
                rows=chunk_rows,
                total_rows_available=result.total_rows_available,
                truncated=result.truncated and (i + chunk_size >= len(result.rows)),
                watermark=result.watermark,
            )

    # --- Validation ---

    @abstractmethod
    def validate_credentials(self) -> bool:
        """Test that stored credentials are valid.

        Used by ``finch-epm auth`` and the setup wizard. Does not perform
        a full introspection.

        Returns:
            True if credentials are valid, False otherwise.
        """
        ...

    # --- Federated query (v0.4) ---

    def supports_direct_query(self) -> bool:
        """Whether this connector can execute arbitrary SQL directly.

        Override and return ``True`` for SQL-capable sources like
        Snowflake, BigQuery, PostgreSQL, and SQL Server.

        Returns:
            False by default. Subclasses override to enable federation.
        """
        return False

    def execute_direct_query(
        self, sql: str, parameters: dict[str, Any] | None = None
    ) -> FactResult:
        """Execute SQL against the remote source without caching.

        Only called when :meth:`supports_direct_query` returns True.

        Args:
            sql: The SQL to execute (in the source's native dialect).
            parameters: Optional query parameters.

        Returns:
            Tabular result data.

        Raises:
            NotImplementedError: If the connector does not support
                direct queries.
        """
        raise NotImplementedError(
            f"{self.display_name} does not support direct queries."
        )
