"""SuiteQL query execution with automatic pagination and rate-limit handling.

All queries go through the NetSuite REST API:
    POST https://{account_id}.suitetalk.api.netsuite.com/services/rest/query/v1/suiteql
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from finch_epm.connectors.base import ConnectorError
from finch_epm.connectors.netsuite.auth import NetSuiteAuthenticator

# SuiteQL endpoint template
_SUITEQL_URL = (
    "https://{account_id}.suitetalk.api.netsuite.com"
    "/services/rest/query/v1/suiteql"
)

# Default page size (NetSuite max is 1000 per request)
_DEFAULT_PAGE_SIZE = 1000

# Safety limit to prevent runaway queries. Set high enough that
# real datasets complete. A typical GL table is 500K-2M rows.
# Override per-query via the limit parameter.
_MAX_TOTAL_ROWS = 10_000_000

# Rate limit retry settings
_MAX_RETRIES = 5
_INITIAL_BACKOFF_SECONDS = 2.0


@dataclass
class SuiteQLResult:
    """Result of a SuiteQL query, possibly spanning multiple pages."""

    rows: list[dict[str, Any]]
    total_results: int
    has_more: bool
    column_names: list[str] = field(default_factory=list)


class SuiteQLClient:
    """Executes SuiteQL queries against the NetSuite REST API.

    Handles pagination, rate limiting (HTTP 429), and error reporting.
    """

    def __init__(
        self,
        authenticator: NetSuiteAuthenticator,
        account_id: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._auth = authenticator
        self._account_id = account_id
        self._http_client = http_client or httpx.Client(timeout=60.0)

    @property
    def _suiteql_url(self) -> str:
        account_slug = self._account_id.replace("-", "_").lower()
        return _SUITEQL_URL.format(account_id=account_slug)

    def execute(
        self,
        sql: str,
        *,
        limit: int | None = None,
        page_size: int = _DEFAULT_PAGE_SIZE,
        progress_callback: Any = None,
    ) -> SuiteQLResult:
        """Execute a SuiteQL query with automatic pagination.

        Paginates through the full result set until the API reports
        no more rows (``hasMore=false``). There is no artificial row cap
        — large tables (500K+ rows) are fully fetched.

        Args:
            sql: The SuiteQL query string.
            limit: Maximum total rows to fetch. None = fetch all rows.
            page_size: Rows per API request (max 1000).
            progress_callback: Optional ``fn(rows_so_far, total_estimated)``
                called after each page for progress reporting.

        Returns:
            SuiteQLResult with all fetched rows.

        Raises:
            ConnectorError: If the query fails after retries.
        """
        if page_size > _DEFAULT_PAGE_SIZE:
            page_size = _DEFAULT_PAGE_SIZE

        max_rows = min(limit or _MAX_TOTAL_ROWS, _MAX_TOTAL_ROWS)
        all_rows: list[dict[str, Any]] = []
        column_names: list[str] = []
        offset = 0
        total_results = 0
        has_more = True

        while has_more and len(all_rows) < max_rows:
            fetch_limit = min(page_size, max_rows - len(all_rows))
            page = self._execute_page(sql, offset=offset, limit=fetch_limit)

            if page["items"]:
                if not column_names:
                    column_names = list(page["items"][0].keys())
                all_rows.extend(page["items"])

            total_results = page.get("totalResults", len(all_rows))
            has_more = page.get("hasMore", False)
            offset += len(page["items"])

            # Report progress
            if progress_callback and callable(progress_callback):
                progress_callback(len(all_rows), total_results)

            if not page["items"]:
                break

        return SuiteQLResult(
            rows=all_rows,
            total_results=total_results,
            has_more=has_more and len(all_rows) >= max_rows,
            column_names=column_names,
        )

    def _execute_page(
        self,
        sql: str,
        offset: int,
        limit: int,
    ) -> dict[str, Any]:
        """Execute a single page of a SuiteQL query with retry logic."""
        headers = self._auth.get_headers()
        url = f"{self._suiteql_url}?limit={limit}&offset={offset}"
        body = {"q": sql}

        for attempt in range(_MAX_RETRIES):
            try:
                response = self._http_client.post(
                    url, json=body, headers=headers
                )
            except httpx.HTTPError as e:
                if attempt == _MAX_RETRIES - 1:
                    raise ConnectorError(
                        f"SuiteQL request failed after {_MAX_RETRIES} retries: {e}"
                    ) from e
                self._backoff(attempt)
                continue

            if response.status_code == 200:
                return response.json()

            if response.status_code == 429:
                # Rate limited — back off and retry
                retry_after = response.headers.get("Retry-After")
                wait = (
                    float(retry_after)
                    if retry_after
                    else _INITIAL_BACKOFF_SECONDS * (2 ** attempt)
                )
                time.sleep(wait)
                continue

            if response.status_code == 401:
                # Token expired mid-pagination — force refresh
                self._auth._current_token = None
                headers = self._auth.get_headers()
                continue

            # Non-retryable error
            try:
                error_body = response.json()
                detail = error_body.get("title", error_body.get("detail", ""))
            except Exception:
                detail = response.text[:500]

            raise ConnectorError(
                f"SuiteQL query failed (HTTP {response.status_code}): {detail}\n"
                f"Query: {sql[:200]}"
            )

        raise ConnectorError(f"SuiteQL request failed after {_MAX_RETRIES} retries")

    @staticmethod
    def _backoff(attempt: int) -> None:
        """Exponential backoff with jitter."""
        import random
        wait = _INITIAL_BACKOFF_SECONDS * (2 ** attempt) + random.uniform(0, 1)
        time.sleep(wait)

    def close(self) -> None:
        """Release HTTP resources."""
        self._http_client.close()
