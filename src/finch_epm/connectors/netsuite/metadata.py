"""NetSuite REST metadata-catalog API client for schema discovery.

Discovers record types, fields, and custom objects via:
    - GET /services/rest/record/v1/metadata-catalog (standard records)
    - SuiteQL against CustomRecordType / CustomField (custom objects)
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from finch_epm.connectors.base import ConnectorError
from finch_epm.connectors.netsuite.auth import NetSuiteAuthenticator
from finch_epm.connectors.netsuite.suiteql import SuiteQLClient

# Metadata-catalog endpoint template
_METADATA_URL = (
    "https://{account_id}.suitetalk.api.netsuite.com"
    "/services/rest/record/v1/metadata-catalog"
)

# Rate limit retry settings
_MAX_RETRIES = 3
_INITIAL_BACKOFF_SECONDS = 2.0


class MetadataClient:
    """Discovers NetSuite schema via REST metadata API and SuiteQL.

    Standard record types and their fields come from the metadata-catalog
    endpoint. Custom record types and custom fields come from SuiteQL
    queries against the CustomRecordType and CustomField tables.
    """

    def __init__(
        self,
        authenticator: NetSuiteAuthenticator,
        account_id: str,
        suiteql_client: SuiteQLClient,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._auth = authenticator
        self._account_id = account_id
        self._suiteql = suiteql_client
        self._http_client = http_client or httpx.Client(timeout=60.0)

    @property
    def _metadata_url(self) -> str:
        account_slug = self._account_id.replace("-", "_").lower()
        return _METADATA_URL.format(account_id=account_slug)

    def fetch_record_catalog(
        self,
        record_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Fetch the metadata catalog for record types.

        Args:
            record_types: Specific record types to fetch. None = all available.

        Returns:
            Raw JSON response from the metadata-catalog endpoint.
        """
        headers = self._auth.get_headers()
        headers["Accept"] = "application/json"

        url = self._metadata_url
        if record_types:
            select = ",".join(record_types)
            url = f"{url}?select={select}"

        for attempt in range(_MAX_RETRIES):
            try:
                response = self._http_client.get(url, headers=headers)
            except httpx.HTTPError as e:
                if attempt == _MAX_RETRIES - 1:
                    raise ConnectorError(
                        f"Metadata catalog request failed: {e}"
                    ) from e
                time.sleep(_INITIAL_BACKOFF_SECONDS * (2 ** attempt))
                continue

            if response.status_code == 200:
                return response.json()

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else _INITIAL_BACKOFF_SECONDS * (2 ** attempt)
                time.sleep(wait)
                continue

            if response.status_code == 401:
                self._auth._current_token = None
                headers = self._auth.get_headers()
                headers["Accept"] = "application/json"
                continue

            raise ConnectorError(
                f"Metadata catalog request failed (HTTP {response.status_code}): "
                f"{response.text[:500]}"
            )

        raise ConnectorError(f"Metadata catalog request failed after {_MAX_RETRIES} retries")

    def fetch_custom_record_types(self) -> list[dict[str, Any]]:
        """Discover custom record types via SuiteQL.

        Returns:
            List of dicts with keys: name, scriptid, internalid, description.
        """
        result = self._suiteql.execute(
            "SELECT name, scriptid, internalid, description "
            "FROM CustomRecordType "
            "ORDER BY name"
        )
        return result.rows

    def fetch_custom_fields(
        self, record_type_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Discover custom fields via SuiteQL.

        Args:
            record_type_id: Filter to fields on a specific record type.
                None = all custom fields.

        Returns:
            List of dicts with field metadata.
        """
        sql = (
            "SELECT scriptid, name, fieldtype, fieldvaluetype, "
            "ismandatory FROM CustomField"
        )
        if record_type_id:
            sql += f" WHERE appliesto = '{record_type_id}'"
        sql += " ORDER BY name"

        result = self._suiteql.execute(sql)
        return result.rows

    def fetch_record_fields(self, record_type: str) -> dict[str, Any]:
        """Fetch detailed field metadata for a specific record type.

        Uses the metadata-catalog endpoint with a single record type
        to get the full field list including types and constraints.

        Args:
            record_type: e.g. "customer", "invoice", "transaction"

        Returns:
            JSON schema-like dict describing the record's fields.
        """
        return self.fetch_record_catalog(record_types=[record_type])

    def close(self) -> None:
        """Release HTTP resources."""
        self._http_client.close()
