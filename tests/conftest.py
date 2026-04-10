"""Shared test fixtures."""

from __future__ import annotations

import pytest

from finch_epm.connectors.fake import FakeConnector
from finch_epm.cache.local import LocalCacheEngine
from finch_epm.catalog.catalog import CatalogStore


@pytest.fixture
def fake_connector() -> FakeConnector:
    """A FakeConnector with default built-in data."""
    conn = FakeConnector()
    conn.connect()
    yield conn
    conn.close()


@pytest.fixture
def cache_engine() -> LocalCacheEngine:
    """An in-memory LocalCacheEngine for testing."""
    engine = LocalCacheEngine(":memory:")
    yield engine
    engine.close()


@pytest.fixture
def catalog_store() -> CatalogStore:
    """An in-memory CatalogStore for testing."""
    store = CatalogStore(":memory:")
    yield store
    store.close()
