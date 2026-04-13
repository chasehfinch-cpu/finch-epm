"""NetSuite connector: SuiteQL + REST metadata APIs with OAuth 2.0 cert auth.

Implements the ConnectorBase interface for NetSuite. Introspection is
exhaustive — it probes ALL known record types and reports three states:
accessible, restricted (exists but role lacks permission), and not_found.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, ClassVar

import httpx

from finch_epm.connectors.base import ConnectorAuthError, ConnectorBase, ConnectorError
from finch_epm.connectors.netsuite.auth import (
    NetSuiteAuthenticator,
    NetSuiteCredentials,
)
from finch_epm.connectors.netsuite.metadata import MetadataClient
from finch_epm.connectors.netsuite.records import (
    AccessStatus,
    ProbedRecord,
    RecordCategory,
    RecordTypeInfo,
    get_all_standard_records,
    get_dimension_records,
    get_record_by_rest_name,
)
from finch_epm.connectors.netsuite.suiteql import SuiteQLClient
from finch_epm.connectors.registry import register_connector
from finch_epm.connectors.types import (
    ColumnInfo,
    ColumnType,
    DimensionInfo,
    FactResult,
    FetchPlan,
    HierarchyNode,
    SchemaInfo,
    ScopeDescription,
    TableInfo,
)
from finch_epm.profiles.manager import ProfileManager

logger = logging.getLogger(__name__)


@register_connector
class NetSuiteConnector(ConnectorBase):
    """NetSuite connector via SuiteQL and REST metadata APIs.

    Introspection is exhaustive: it probes every known record type against
    the live instance and reports access status for each. Tables the current
    role can't see are still cataloged as 'restricted' so that users know
    what exists and can adjust permissions.
    """

    connector_type: ClassVar[str] = "netsuite"
    display_name: ClassVar[str] = "NetSuite"
    source_prefix: ClassVar[str] = "ns"

    def __init__(
        self,
        profile_name: str = "default",
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(profile_name, config or {})
        self._authenticator: NetSuiteAuthenticator | None = None
        self._suiteql: SuiteQLClient | None = None
        self._metadata: MetadataClient | None = None
        self._http_client: httpx.Client | None = None
        self._probed_cache: dict[str, ProbedRecord] = {}

    # --- Lifecycle ---

    def connect(self) -> None:
        """Connect to NetSuite using stored credentials."""
        pm = ProfileManager()

        if not self.config:
            if not pm.profile_exists("netsuite", self.profile_name):
                raise ConnectorAuthError(
                    f"No NetSuite profile '{self.profile_name}' found. "
                    "Run: finch-epm auth -c netsuite -p <profile> --env-file <path>"
                )
            self.config = pm.get_config("netsuite", self.profile_name)

        account_id = self.config["account_id"]
        client_id = self.config["client_id"]
        certificate_id = self.config["certificate_id"]

        private_key_pem = pm.get_secret("netsuite", self.profile_name, "private_key_pem")
        if not private_key_pem:
            raise ConnectorAuthError(
                f"Private key not found in OS keychain for profile "
                f"'{self.profile_name}'. Re-import with: "
                "finch-epm auth -c netsuite --env-file <path> --key-file <path>"
            )

        creds = NetSuiteCredentials(account_id, client_id, certificate_id)
        self._authenticator = NetSuiteAuthenticator(creds, private_key_pem)

        if not self._authenticator.validate():
            raise ConnectorAuthError("Failed to obtain NetSuite access token.")

        self._http_client = httpx.Client(timeout=60.0)
        self._suiteql = SuiteQLClient(
            self._authenticator, account_id, self._http_client
        )
        self._metadata = MetadataClient(
            self._authenticator, account_id, self._suiteql, self._http_client
        )
        self._connected = True

    def close(self) -> None:
        if self._authenticator:
            self._authenticator.close()
            self._authenticator = None
        if self._http_client:
            self._http_client.close()
            self._http_client = None
        self._suiteql = None
        self._metadata = None
        self._probed_cache.clear()
        self._connected = False

    def validate_credentials(self) -> bool:
        if self._authenticator:
            return self._authenticator.validate()
        try:
            self.connect()
            self.close()
            return True
        except ConnectorAuthError:
            return False

    # --- Schema discovery ---

    def introspect_schema(self) -> SchemaInfo:
        """Exhaustive schema discovery across ALL known NetSuite record types.

        Probes every record in the standard registry via SuiteQL, discovers
        columns for accessible records, and fetches custom records from the
        REST metadata catalog. Returns a SchemaInfo where every record is
        cataloged with its access status in the metadata field.
        """
        self._ensure_connected()
        assert self._suiteql is not None
        assert self._metadata is not None

        tables: list[TableInfo] = []

        # Phase 1: Probe ALL standard records via SuiteQL
        for record in get_all_standard_records():
            probed = self._probe_record(record)
            self._probed_cache[record.suiteql_name] = probed

            if probed.status == AccessStatus.ACCESSIBLE:
                columns = self._discover_columns(record.suiteql_name)
                tables.append(TableInfo(
                    name=record.suiteql_name,
                    display_name=record.display_name,
                    columns=columns,
                    is_custom=False,
                    row_count_estimate=probed.row_count,
                    metadata={
                        "access_status": probed.status.value,
                        "category": record.category.value,
                        "rest_name": record.rest_name,
                        "suiteql_name": record.suiteql_name,
                    },
                ))
            else:
                # Record exists but is not accessible — catalog it anyway
                tables.append(TableInfo(
                    name=record.suiteql_name,
                    display_name=record.display_name,
                    columns=[],
                    is_custom=False,
                    row_count_estimate=None,
                    metadata={
                        "access_status": probed.status.value,
                        "category": record.category.value,
                        "rest_name": record.rest_name,
                        "suiteql_name": record.suiteql_name,
                        "error": probed.error_message,
                    },
                ))

        # Phase 2: Discover custom records from REST metadata catalog
        try:
            catalog_data = self._metadata.fetch_record_catalog()
            for item in catalog_data.get("items", []):
                rest_name = item.get("name", "")
                # Skip if we already have it from standard records
                if get_record_by_rest_name(rest_name):
                    continue
                if not rest_name.startswith("customrecord"):
                    continue

                # Try to probe the custom record via SuiteQL
                custom_record = RecordTypeInfo(
                    suiteql_name=rest_name,
                    rest_name=rest_name,
                    display_name=rest_name.replace("customrecord_", "").replace("_", " ").title(),
                    category=RecordCategory.CUSTOM,
                )
                probed = self._probe_record(custom_record)
                columns = (
                    self._discover_columns(rest_name)
                    if probed.status == AccessStatus.ACCESSIBLE
                    else []
                )
                tables.append(TableInfo(
                    name=rest_name,
                    display_name=custom_record.display_name,
                    columns=columns,
                    is_custom=True,
                    row_count_estimate=probed.row_count,
                    metadata={
                        "access_status": probed.status.value,
                        "category": "custom",
                    },
                ))
        except ConnectorError as e:
            logger.warning("Failed to fetch custom records from metadata catalog: %s", e)

        return SchemaInfo(
            tables=tables,
            source_name="netsuite",
            profile_name=self.profile_name,
            introspected_at=datetime.now(),
            metadata={
                "total_records": len(tables),
                "accessible": sum(
                    1 for t in tables
                    if t.metadata.get("access_status") == "accessible"
                ),
                "restricted": sum(
                    1 for t in tables
                    if t.metadata.get("access_status") == "restricted"
                ),
                "not_found": sum(
                    1 for t in tables
                    if t.metadata.get("access_status") == "not_found"
                ),
            },
        )

    def list_dimensions(self) -> list[DimensionInfo]:
        """List ALL dimensional record types — standard AND custom segments.

        Standard dimensions (Account, Subsidiary, Department, Location, Class)
        are probed from the registry. Custom Segments are discovered dynamically
        via SuiteQL. Hierarchy support is always verified live by probing for
        a 'parent' column — never hardcoded.

        Every dimension is returned with its access status, so the caller
        always knows what exists vs. what the current role can see.
        """
        self._ensure_connected()
        assert self._suiteql is not None

        dimensions: list[DimensionInfo] = []
        # Track names we've already added to avoid duplicates
        seen: set[str] = set()

        # Phase 1: Standard dimensions from the registry
        for record in get_dimension_records():
            probed = self._probed_cache.get(record.suiteql_name)
            if probed is None:
                probed = self._probe_record(record)
                self._probed_cache[record.suiteql_name] = probed

            # ALWAYS probe hierarchy support live — never trust the hint alone
            supports_hierarchy = False
            parent_column: str | None = None
            if probed.status == AccessStatus.ACCESSIBLE:
                # Check the hinted parent column first, then fallback to 'parent'
                for candidate in [record.parent_column, "parent"]:
                    if candidate and self._has_column(record.suiteql_name, candidate):
                        supports_hierarchy = True
                        parent_column = candidate
                        break

            dimensions.append(DimensionInfo(
                name=record.suiteql_name,
                display_name=record.display_name,
                table_name=record.suiteql_name,
                id_column=record.id_column,
                label_column=record.label_column,
                supports_hierarchy=supports_hierarchy,
                metadata={
                    "access_status": probed.status.value,
                    "row_count": probed.row_count,
                    "parent_column": parent_column,
                    "source": "standard",
                },
            ))
            seen.add(record.suiteql_name)

        # Phase 2: Discover Custom Segments dynamically
        # Custom Segments are company-specific dimensions added in NetSuite.
        # They appear as additional segment columns on TransactionLine.
        custom_segments = self._discover_custom_segments()
        for seg in custom_segments:
            if seg["name"] in seen:
                continue
            seg_table = seg.get("table_name", seg["name"])

            # Probe the segment's backing record
            probed_seg = self._probe_record(RecordTypeInfo(
                suiteql_name=seg_table,
                rest_name=seg_table.lower(),
                display_name=seg.get("display_name", seg["name"]),
                category=RecordCategory.DIMENSION,
            ))

            supports_hierarchy = False
            parent_column = None
            if probed_seg.status == AccessStatus.ACCESSIBLE:
                if self._has_column(seg_table, "parent"):
                    supports_hierarchy = True
                    parent_column = "parent"

            dimensions.append(DimensionInfo(
                name=seg["name"],
                display_name=seg.get("display_name", seg["name"]),
                table_name=seg_table,
                id_column="id",
                label_column="name",
                supports_hierarchy=supports_hierarchy,
                metadata={
                    "access_status": probed_seg.status.value,
                    "row_count": probed_seg.row_count,
                    "parent_column": parent_column,
                    "source": "custom_segment",
                    "script_id": seg.get("script_id"),
                },
            ))
            seen.add(seg["name"])

        return dimensions

    def get_hierarchy(self, dimension_name: str) -> list[HierarchyNode]:
        """Fetch parent-child hierarchy for a dimension via SuiteQL.

        Works with both standard dimensions and dynamically discovered
        custom segments. The parent column is discovered from the dimension's
        metadata, not hardcoded.
        """
        self._ensure_connected()
        assert self._suiteql is not None

        # Find the dimension — check registry first, then discovered dimensions
        dim_record: RecordTypeInfo | None = None
        parent_column: str | None = None
        label_column: str = "name"

        for r in get_dimension_records():
            if r.suiteql_name == dimension_name:
                dim_record = r
                parent_column = r.parent_column or "parent"
                label_column = r.label_column
                break

        if dim_record is None:
            # Not in registry — might be a custom segment. Probe it directly.
            if not self._has_column(dimension_name, "id"):
                available = [r.suiteql_name for r in get_dimension_records()]
                raise ValueError(
                    f"Unknown dimension: {dimension_name!r}. "
                    f"Standard dimensions: {available}"
                )
            parent_column = "parent"
            label_column = "name"

        # Verify the parent column actually exists
        if not self._has_column(dimension_name, parent_column or "parent"):
            raise ValueError(
                f"Dimension '{dimension_name}' does not support hierarchy "
                f"(no '{parent_column or 'parent'}' column found)."
            )

        label_col = dim_record.label_column
        parent_col = dim_record.parent_column

        try:
            result = self._suiteql.execute(
                f"SELECT id, {label_col} AS label, {parent_col} AS parent "
                f"FROM {dimension_name} ORDER BY id"
            )
        except ConnectorError as e:
            raise ValueError(
                f"Cannot fetch hierarchy for '{dimension_name}': {e}"
            ) from e

        return self._build_tree(result.rows)

    # --- Data fetching ---

    def plan_scope(self, scope: ScopeDescription) -> FetchPlan:
        self._ensure_connected()
        assert self._suiteql is not None

        estimated_rows = 0
        estimated_calls = 0
        for table_name in scope.tables:
            try:
                result = self._suiteql.execute(
                    f"SELECT COUNT(*) AS cnt FROM {table_name}", limit=1
                )
                count = int(result.rows[0].get("cnt", 0)) if result.rows else 0
                estimated_rows += count
                estimated_calls += max(1, count // 1000)
            except ConnectorError:
                estimated_calls += 1

        return FetchPlan(
            scope=scope,
            estimated_rows=estimated_rows,
            estimated_api_calls=estimated_calls,
            native_plan={
                "method": "suiteql",
                "tables": list(scope.tables),
                "filters": dict(scope.filters),
            },
        )

    def fetch_facts(self, plan: FetchPlan) -> FactResult:
        self._ensure_connected()
        assert self._suiteql is not None

        if not plan.scope.tables:
            return FactResult(column_names=[], column_types=[], rows=[])

        all_column_names: list[str] = []
        all_column_types: list[ColumnType] = []
        all_rows: list[list[Any]] = []
        was_truncated = False

        for table_name in plan.scope.tables:
            where_clauses: list[str] = []
            for key, value in plan.scope.filters.items():
                if isinstance(value, list):
                    values_str = ", ".join(f"'{v}'" for v in value)
                    where_clauses.append(f"{key} IN ({values_str})")
                else:
                    where_clauses.append(f"{key} = '{value}'")

            if plan.scope.since:
                since_str = plan.scope.since.strftime("%Y-%m-%d %H:%M:%S")
                where_clauses.append(f"lastmodifieddate >= '{since_str}'")

            # First attempt: fetch all rows in one query
            sql = f"SELECT * FROM {table_name}"
            if where_clauses:
                sql += " WHERE " + " AND ".join(where_clauses)

            result = self._suiteql.execute(sql, limit=plan.scope.limit)
            table_rows = result.rows

            # NetSuite caps at 100,000 rows per query. If we hit that cap,
            # split by year ranges to get all data.
            if len(table_rows) >= 100_000:
                logger.info(
                    "Table %s hit 100K API cap (%d rows). "
                    "Splitting by year to fetch all data.",
                    table_name, len(table_rows),
                )
                table_rows = self._fetch_by_year_chunks(
                    table_name, where_clauses, plan.scope.limit
                )

            if table_rows:
                if not all_column_names:
                    all_column_names = [
                        c for c in (result.column_names if result.rows else list(table_rows[0].keys()))
                        if c != "links"
                    ]
                    all_column_types = [ColumnType.STRING] * len(all_column_names)

                for row_dict in table_rows:
                    all_rows.append([row_dict.get(col) for col in all_column_names])

        return FactResult(
            column_names=all_column_names,
            column_types=all_column_types,
            rows=all_rows,
            total_rows_available=len(all_rows),
            truncated=was_truncated,
            watermark=datetime.now(),
        )

    # Tables that don't have lastmodifieddate and need to chunk
    # via a JOIN to the Transaction table's lastmodifieddate instead.
    _JUNCTION_TABLES = {
        "transactionaccountingline",
        "transactionline",
    }

    def _fetch_by_year_chunks(
        self,
        table_name: str,
        base_where: list[str],
        limit: int | None,
    ) -> list[dict[str, Any]]:
        """Fetch a large table by splitting into year-based chunks.

        NetSuite's SuiteQL API caps at 100,000 rows per query with no
        way to paginate past that limit. This method splits the query
        into per-year chunks. For most tables, splits on
        ``lastmodifieddate``. For junction tables (TransactionAccountingLine,
        TransactionLine) that don't have their own date field, splits
        by joining to the parent Transaction table's ``lastmodifieddate``.
        """
        assert self._suiteql is not None
        all_rows: list[dict[str, Any]] = []

        is_junction = table_name.lower() in self._JUNCTION_TABLES

        # Determine the year range
        if is_junction:
            # Junction tables: get year range from parent Transaction table
            count_sql = (
                "SELECT MIN(EXTRACT(YEAR FROM lastmodifieddate)) AS min_yr, "
                "MAX(EXTRACT(YEAR FROM lastmodifieddate)) AS max_yr "
                "FROM Transaction"
            )
        else:
            count_sql = (
                f"SELECT MIN(EXTRACT(YEAR FROM lastmodifieddate)) AS min_yr, "
                f"MAX(EXTRACT(YEAR FROM lastmodifieddate)) AS max_yr "
                f"FROM {table_name}"
            )
            if base_where:
                count_sql += " WHERE " + " AND ".join(base_where)

        try:
            yr_result = self._suiteql.execute(count_sql, limit=1)
            if not yr_result.rows:
                return all_rows
            min_yr = int(yr_result.rows[0].get("min_yr") or 2015)
            max_yr = int(yr_result.rows[0].get("max_yr") or 2026)
        except Exception:
            min_yr, max_yr = 2015, 2026

        for year in range(min_yr, max_yr + 1):
            if is_junction:
                # JOIN to Transaction to filter by year
                year_where = list(base_where)
                year_where.append(
                    f"transaction IN (SELECT id FROM Transaction "
                    f"WHERE EXTRACT(YEAR FROM lastmodifieddate) = {year})"
                )
            else:
                year_where = list(base_where)
                year_where.append(
                    f"EXTRACT(YEAR FROM lastmodifieddate) = {year}"
                )
            sql = f"SELECT * FROM {table_name} WHERE " + " AND ".join(year_where)

            result = self._suiteql.execute(sql, limit=limit)
            all_rows.extend(result.rows)

            logger.info(
                "  %s year %d: %d rows (total so far: %d)",
                table_name, year, len(result.rows), len(all_rows),
            )

            # If a single year exceeds 100K, split by quarter
            if len(result.rows) >= 100_000:
                logger.info(
                    "  Year %d hit 100K cap. Splitting by quarter.", year
                )
                # Remove the year's rows (we'll re-fetch by quarter)
                all_rows = all_rows[: -len(result.rows)]
                for q_start, q_end in [(1, 3), (4, 6), (7, 9), (10, 12)]:
                    q_where = list(base_where)
                    q_where.append(
                        f"EXTRACT(YEAR FROM lastmodifieddate) = {year}"
                    )
                    q_where.append(
                        f"EXTRACT(MONTH FROM lastmodifieddate) BETWEEN {q_start} AND {q_end}"
                    )
                    q_sql = f"SELECT * FROM {table_name} WHERE " + " AND ".join(q_where)
                    q_result = self._suiteql.execute(q_sql, limit=limit)
                    all_rows.extend(q_result.rows)
                    logger.info(
                        "    Q%d (%d-%d): %d rows",
                        (q_start - 1) // 3 + 1, q_start, q_end,
                        len(q_result.rows),
                    )

        return all_rows

    # --- Internal helpers ---

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise ConnectorError(
                "Not connected. Call connect() first or use as context manager."
            )

    def _probe_record(self, record: RecordTypeInfo) -> ProbedRecord:
        """Probe a single record type via SuiteQL COUNT(*).

        Returns a ProbedRecord with access status, row count, and column names.
        """
        assert self._suiteql is not None
        try:
            result = self._suiteql.execute(
                f"SELECT COUNT(*) AS cnt FROM {record.suiteql_name}", limit=1
            )
            count = int(result.rows[0].get("cnt", 0)) if result.rows else 0
            return ProbedRecord(
                record=record,
                status=AccessStatus.ACCESSIBLE,
                row_count=count,
            )
        except ConnectorError as e:
            error_msg = str(e)
            if "not found" in error_msg.lower():
                status = AccessStatus.NOT_FOUND
            elif "permission" in error_msg.lower() or "access" in error_msg.lower():
                status = AccessStatus.RESTRICTED
            else:
                # Default to RESTRICTED — the record likely exists but the
                # role can't see it. "Record not found" in SuiteQL often
                # means the record type isn't exposed to this role, not that
                # it doesn't exist in the instance.
                status = AccessStatus.RESTRICTED
            return ProbedRecord(
                record=record,
                status=status,
                error_message=error_msg[:200],
            )

    def _discover_columns(self, table_name: str) -> list[ColumnInfo]:
        """Discover columns by fetching one row from the table."""
        assert self._suiteql is not None
        try:
            result = self._suiteql.execute(
                f"SELECT * FROM {table_name} WHERE ROWNUM <= 1", limit=1
            )
            if not result.rows:
                return []

            columns: list[ColumnInfo] = []
            for col_name in result.column_names:
                if col_name == "links":
                    continue
                value = result.rows[0].get(col_name)
                col_type = self._infer_type(col_name, value)
                is_custom = col_name.startswith("custbody") or col_name.startswith("custcol")
                columns.append(ColumnInfo(
                    name=col_name,
                    display_name=col_name.replace("_", " ").title(),
                    column_type=col_type,
                    is_custom=is_custom,
                    is_nullable=True,
                ))
            return columns
        except ConnectorError:
            return []

    @staticmethod
    def _infer_type(col_name: str, value: Any) -> ColumnType:
        """Infer the ColumnType from a column name and sample value.

        SuiteQL returns everything as strings, so we use naming conventions
        and value patterns to infer types.
        """
        name_lower = col_name.lower()

        # ID columns
        if name_lower == "id" or name_lower.endswith("id"):
            return ColumnType.INTEGER

        # Date columns
        if "date" in name_lower:
            return ColumnType.DATE

        # Boolean columns
        if value in ("T", "F"):
            return ColumnType.BOOLEAN

        # Amount/currency columns
        amount_keywords = ["amount", "balance", "rate", "price", "cost", "total", "debit", "credit"]
        if any(kw in name_lower for kw in amount_keywords):
            return ColumnType.DECIMAL

        # Count/quantity columns
        if any(kw in name_lower for kw in ["count", "quantity", "number", "num"]):
            return ColumnType.INTEGER

        # Foreign key references (common NS patterns)
        fk_names = [
            "account", "subsidiary", "department", "location", "class",
            "customer", "vendor", "employee", "item", "currency",
            "parent", "transaction", "transactionline",
        ]
        if name_lower in fk_names:
            return ColumnType.REFERENCE

        # Try to parse as number
        if value is not None and isinstance(value, str):
            try:
                float(value)
                if "." in value:
                    return ColumnType.DECIMAL
                return ColumnType.INTEGER
            except ValueError:
                pass

        return ColumnType.STRING

    @staticmethod
    def _build_tree(rows: list[dict[str, Any]]) -> list[HierarchyNode]:
        """Build a tree from flat rows with id, label, parent columns."""
        nodes_by_id: dict[str, dict[str, Any]] = {}
        children_map: dict[str, list[str]] = {}

        for row in rows:
            node_id = str(row.get("id", ""))
            parent_id = str(row.get("parent", "")) if row.get("parent") else None
            nodes_by_id[node_id] = {
                "id": node_id,
                "label": str(row.get("label", "")),
                "parent_id": parent_id,
            }
            if parent_id:
                children_map.setdefault(parent_id, []).append(node_id)

        def _build_node(node_id: str, depth: int = 0) -> HierarchyNode:
            info = nodes_by_id[node_id]
            child_ids = children_map.get(node_id, [])
            children = [_build_node(cid, depth + 1) for cid in child_ids]
            return HierarchyNode(
                id=info["id"],
                label=info["label"],
                parent_id=info["parent_id"],
                children=children,
                depth=depth,
            )

        # Roots are nodes with no parent or whose parent isn't in the dataset
        roots = [
            nid for nid, info in nodes_by_id.items()
            if info["parent_id"] is None or info["parent_id"] not in nodes_by_id
        ]

        return [_build_node(rid) for rid in roots]

    def _discover_custom_segments(self) -> list[dict[str, Any]]:
        """Discover Custom Segments defined in this NetSuite instance.

        Custom Segments are company-specific dimensions that appear as
        additional segment columns on transactions. They are backed by
        custom record types or custom lists.

        Returns:
            List of dicts with keys: name, display_name, table_name, script_id.
        """
        assert self._suiteql is not None
        segments: list[dict[str, Any]] = []

        try:
            # CustomSegment table lists all custom segments
            result = self._suiteql.execute(
                "SELECT scriptid, label, recordtype "
                "FROM CustomSegment ORDER BY label",
                limit=200,
            )
            for row in result.rows:
                script_id = row.get("scriptid", "")
                label = row.get("label", script_id)
                record_type = row.get("recordtype", "")
                segments.append({
                    "name": script_id,
                    "display_name": label,
                    "table_name": record_type if record_type else script_id,
                    "script_id": script_id,
                })
        except ConnectorError:
            # CustomSegment table not available — may not have permission
            # or instance may not use custom segments
            logger.debug("CustomSegment table not accessible — skipping")

        return segments

    def _has_column(self, table_name: str, column_name: str) -> bool:
        """Check if a table has a specific column via a probe query."""
        assert self._suiteql is not None
        try:
            self._suiteql.execute(
                f"SELECT {column_name} FROM {table_name} WHERE ROWNUM <= 1",
                limit=1,
            )
            return True
        except ConnectorError:
            return False
