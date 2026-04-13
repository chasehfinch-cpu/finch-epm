"""Tests for the federated query router."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, ClassVar

from finch_epm.cache.federation import (
    ExecutionPlan,
    FederatedQueryRouter,
    FederationConfig,
    _strip_source_prefixes,
)
from finch_epm.cache.local import LocalCacheEngine
from finch_epm.cache.sync import SyncEngine
from finch_epm.connectors.fake import FakeConnector


class _DirectQueryFake(FakeConnector):
    """FakeConnector with direct query enabled."""

    connector_type: ClassVar[str] = "fake_dq"
    source_prefix: ClassVar[str] = "fdq"

    def __init__(self, profile_name: str = "test", **kwargs: Any) -> None:
        super().__init__(profile_name, config={"supports_direct_query": True}, **kwargs)


class TestPlanExecution:
    def test_cross_source_always_local(self, cache_engine: LocalCacheEngine) -> None:
        conn_a = _DirectQueryFake("a")
        conn_a.connect()
        router = FederatedQueryRouter(
            cache=cache_engine,
            connectors={"fdq": conn_a},
        )
        plan = router.plan_execution(
            "SELECT * FROM fdq__t1 JOIN other__t2 ON fdq__t1.id = other__t2.id"
        )
        assert plan.strategy == "local"
        assert "cross-source" in plan.reason
        conn_a.close()

    def test_single_source_fresh_cache_local(
        self, fake_connector: FakeConnector, cache_engine: LocalCacheEngine
    ) -> None:
        """Fresh cache → local even for a capable source."""
        SyncEngine(fake_connector, cache_engine).sync_tables(
            ["gl_detail"], mode="full"
        )

        conn = _DirectQueryFake("test")
        conn.connect()
        router = FederatedQueryRouter(
            cache=cache_engine,
            connectors={"fdq": conn},
        )
        # This table has prefix "fdq" but was synced under "fake"
        # Let's test with a real fdq-prefixed query
        plan = router.plan_execution("SELECT * FROM fdq__gl_detail")
        # No prefer_remote, cache should be fresh for this prefix
        assert plan.strategy == "local"
        conn.close()

    def test_prefer_remote_overrides(self, cache_engine: LocalCacheEngine) -> None:
        conn = _DirectQueryFake("test")
        conn.connect()
        router = FederatedQueryRouter(
            cache=cache_engine,
            connectors={"fdq": conn},
            config=FederationConfig(prefer_remote=["fdq"]),
        )
        plan = router.plan_execution("SELECT * FROM fdq__gl_detail")
        assert plan.strategy == "remote"
        assert "prefer_remote" in plan.reason
        conn.close()

    def test_prefer_local_overrides(self, cache_engine: LocalCacheEngine) -> None:
        conn = _DirectQueryFake("test")
        conn.connect()
        router = FederatedQueryRouter(
            cache=cache_engine,
            connectors={"fdq": conn},
            config=FederationConfig(prefer_local=["fdq"]),
        )
        plan = router.plan_execution("SELECT * FROM fdq__gl_detail")
        assert plan.strategy == "local"
        assert "prefer_local" in plan.reason
        conn.close()

    def test_no_direct_query_always_local(self, cache_engine: LocalCacheEngine) -> None:
        conn = FakeConnector("test")
        conn.connect()
        router = FederatedQueryRouter(
            cache=cache_engine,
            connectors={"fake": conn},
        )
        plan = router.plan_execution("SELECT * FROM fake__gl_detail")
        assert plan.strategy == "local"
        assert "no direct query" in plan.reason
        conn.close()


class TestExecuteRemote:
    def test_remote_execution_returns_data(
        self, cache_engine: LocalCacheEngine
    ) -> None:
        conn = _DirectQueryFake("test")
        conn.connect()
        router = FederatedQueryRouter(
            cache=cache_engine,
            connectors={"fdq": conn},
            config=FederationConfig(prefer_remote=["fdq"]),
        )

        result = router.execute("SELECT COUNT(*) AS cnt FROM fdq__gl_detail")
        assert result.row_count == 1
        assert result.served_from.startswith("remote:")
        conn.close()

    def test_local_fallback_when_no_router(
        self, fake_connector: FakeConnector, cache_engine: LocalCacheEngine
    ) -> None:
        """federation_router=None falls back to cache execution."""
        SyncEngine(fake_connector, cache_engine).sync_tables(
            ["gl_detail"], mode="full"
        )

        from finch_epm.dashboard.fdash import load_fdash_string
        from finch_epm.dashboard.resolver import resolve_queries

        yaml_str = """
name: Test
queries:
  - name: q1
    sql: SELECT COUNT(*) AS cnt FROM fake__gl_detail
charts:
  - type: kpi
    title: Count
    data: q1
    value: cnt
"""
        spec = load_fdash_string(yaml_str)
        results = resolve_queries(spec, cache_engine, federation_router=None)
        assert results["q1"].row_count == 1
        assert results["q1"].served_from == "local"


class TestStripSourcePrefixes:
    def test_simple(self) -> None:
        result = _strip_source_prefixes(
            "SELECT * FROM sf__PUBLIC__EVENTS", "sf"
        )
        assert "PUBLIC.EVENTS" in result
        assert "sf__" not in result

    def test_no_double_underscores(self) -> None:
        result = _strip_source_prefixes(
            "SELECT * FROM sf__tablename", "sf"
        )
        assert "tablename" in result

    def test_preserves_other_prefixes(self) -> None:
        result = _strip_source_prefixes(
            "SELECT * FROM ns__Account JOIN sf__EVENTS ON 1=1", "sf"
        )
        assert "ns__Account" in result
        assert "sf__" not in result


class TestConnectorDirectQuery:
    def test_default_supports_false(self) -> None:
        conn = FakeConnector("test")
        assert conn.supports_direct_query() is False

    def test_base_class_execute_raises(self) -> None:
        """ConnectorBase.execute_direct_query raises NotImplementedError."""
        from finch_epm.connectors.base import ConnectorBase

        # ConnectorBase is abstract, but we can call the method directly
        import pytest
        with pytest.raises(NotImplementedError):
            ConnectorBase.execute_direct_query(FakeConnector("test"), "SELECT 1")

    def test_fake_with_direct_query_enabled(self) -> None:
        conn = FakeConnector("test", config={"supports_direct_query": True})
        conn.connect()
        assert conn.supports_direct_query() is True
        result = conn.execute_direct_query(
            "SELECT COUNT(*) AS cnt FROM gl_detail"
        )
        assert len(result.rows) == 1
        conn.close()
