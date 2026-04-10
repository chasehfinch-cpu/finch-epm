"""Google BigQuery connector.

Implements ConnectorBase for BigQuery. Uses INFORMATION_SCHEMA for
introspection and standard SQL for queries.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, ClassVar

from finch_epm.connectors.base import ConnectorAuthError, ConnectorBase, ConnectorError
from finch_epm.connectors.registry import register_connector
from finch_epm.connectors.types import (
    ColumnInfo, ColumnType, DimensionInfo, FactResult, FetchPlan,
    HierarchyNode, SchemaInfo, ScopeDescription, TableInfo,
)

logger = logging.getLogger(__name__)

_BQ_TYPE_MAP: dict[str, ColumnType] = {
    "STRING": ColumnType.STRING,
    "BYTES": ColumnType.UNKNOWN,
    "INTEGER": ColumnType.INTEGER,
    "INT64": ColumnType.INTEGER,
    "FLOAT": ColumnType.FLOAT,
    "FLOAT64": ColumnType.FLOAT,
    "NUMERIC": ColumnType.DECIMAL,
    "BIGNUMERIC": ColumnType.DECIMAL,
    "BOOLEAN": ColumnType.BOOLEAN,
    "BOOL": ColumnType.BOOLEAN,
    "TIMESTAMP": ColumnType.DATETIME,
    "DATE": ColumnType.DATE,
    "TIME": ColumnType.STRING,
    "DATETIME": ColumnType.DATETIME,
    "GEOGRAPHY": ColumnType.STRING,
    "RECORD": ColumnType.TEXT,
    "STRUCT": ColumnType.TEXT,
    "JSON": ColumnType.TEXT,
}


@register_connector
class BigQueryConnector(ConnectorBase):
    """Google BigQuery connector.

    Config fields:
        project: GCP project ID
        dataset: BigQuery dataset name
        credentials_json: Path to service account JSON key file
            (the key file content is stored in keychain after import)

    The service account JSON key is stored in the OS keychain, not on disk.
    """

    connector_type: ClassVar[str] = "bigquery"
    display_name: ClassVar[str] = "BigQuery"

    def __init__(self, profile_name: str = "default", config: dict[str, Any] | None = None) -> None:
        super().__init__(profile_name, config or {})
        self._client: Any = None

    def connect(self) -> None:
        try:
            from google.cloud import bigquery
            from google.oauth2 import service_account
        except ImportError:
            raise ConnectorError(
                "google-cloud-bigquery is not installed. "
                "Install with: pip install finch-epm[bigquery]"
            )

        import json
        from finch_epm.profiles.manager import ProfileManager

        if not self.config:
            pm = ProfileManager()
            if not pm.profile_exists("bigquery", self.profile_name):
                raise ConnectorAuthError(f"No BigQuery profile '{self.profile_name}' found.")
            self.config = pm.get_config("bigquery", self.profile_name)

        pm = ProfileManager()
        creds_json = pm.get_secret("bigquery", self.profile_name, "credentials_json")
        if not creds_json:
            raise ConnectorAuthError("Service account credentials not found in OS keychain.")

        try:
            creds_dict = json.loads(creds_json)
            credentials = service_account.Credentials.from_service_account_info(creds_dict)
            self._client = bigquery.Client(
                project=self.config.get("project", ""),
                credentials=credentials,
            )
            self._connected = True
        except Exception as e:
            raise ConnectorAuthError(f"BigQuery connection failed: {e}") from e

    def close(self) -> None:
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
        self._connected = False

    def validate_credentials(self) -> bool:
        if self._client:
            try:
                list(self._client.list_datasets(max_results=1))
                return True
            except Exception:
                return False
        try:
            self.connect()
            r = self.validate_credentials()
            self.close()
            return r
        except ConnectorAuthError:
            return False

    def introspect_schema(self) -> SchemaInfo:
        self._ensure_connected()
        tables: list[TableInfo] = []
        dataset = self.config.get("dataset", "")
        project = self.config.get("project", "")

        query = f"""
            SELECT table_name, table_type,
                   COALESCE(CAST(row_count AS INT64), 0) AS row_count
            FROM `{project}.{dataset}.INFORMATION_SCHEMA.TABLES`
            ORDER BY table_name
        """
        result = self._client.query(query).result()

        for row in result:
            table_name = row.table_name
            full_name = f"{dataset}.{table_name}"

            # Get columns
            col_query = f"""
                SELECT column_name, data_type, is_nullable, ordinal_position
                FROM `{project}.{dataset}.INFORMATION_SCHEMA.COLUMNS`
                WHERE table_name = '{table_name}'
                ORDER BY ordinal_position
            """
            col_result = self._client.query(col_query).result()
            columns = [
                ColumnInfo(
                    name=cr.column_name, display_name=cr.column_name,
                    column_type=_BQ_TYPE_MAP.get(cr.data_type, ColumnType.UNKNOWN),
                    is_nullable=(cr.is_nullable == "YES"),
                )
                for cr in col_result
            ]

            tables.append(TableInfo(
                name=full_name, display_name=table_name, columns=columns,
                row_count_estimate=row.row_count,
                metadata={"access_status": "accessible", "category": row.table_type.lower()},
            ))

        return SchemaInfo(
            tables=tables, source_name="bigquery", profile_name=self.profile_name,
            introspected_at=datetime.now(),
            metadata={"total_records": len(tables), "accessible": len(tables), "restricted": 0, "not_found": 0},
        )

    def list_dimensions(self) -> list[DimensionInfo]:
        return []

    def get_hierarchy(self, dimension_name: str) -> list[HierarchyNode]:
        raise ValueError("Hierarchy not supported for BigQuery connector.")

    def plan_scope(self, scope: ScopeDescription) -> FetchPlan:
        return FetchPlan(scope=scope, estimated_rows=0, estimated_api_calls=len(scope.tables), native_plan={"method": "bigquery"})

    def fetch_facts(self, plan: FetchPlan) -> FactResult:
        self._ensure_connected()
        if not plan.scope.tables:
            return FactResult(column_names=[], column_types=[], rows=[])

        cols: list[str] = []
        types: list[ColumnType] = []
        rows: list[list[Any]] = []
        dataset = self.config.get("dataset", "")
        project = self.config.get("project", "")

        for table_name in plan.scope.tables:
            sql = f"SELECT * FROM `{project}.{dataset}.{table_name}`"
            if plan.scope.limit:
                sql += f" LIMIT {plan.scope.limit}"
            try:
                result = self._client.query(sql).result()
                if not cols:
                    cols = [f.name for f in result.schema]
                    types = [ColumnType.STRING] * len(cols)
                for row in result:
                    rows.append([str(v) if v is not None else None for v in row])
            except Exception as e:
                logger.warning("BigQuery fetch failed for %s: %s", table_name, e)

        return FactResult(column_names=cols, column_types=types, rows=rows, total_rows_available=len(rows), watermark=datetime.now())

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise ConnectorError("Not connected.")
