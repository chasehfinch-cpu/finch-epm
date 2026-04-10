"""Tests for the LocalCacheEngine."""

from __future__ import annotations

from datetime import datetime, timezone

from finch_epm.cache.local import LocalCacheEngine
from finch_epm.cache.models import (
    QueryRequest,
    StalenessLevel,
    SyncWatermark,
)
from finch_epm.connectors.fake import FakeConnector
from finch_epm.connectors.types import ScopeDescription


class TestIngestAndQuery:
    def test_ingest_and_query(self, cache_engine: LocalCacheEngine) -> None:
        rows_inserted = cache_engine.ingest_facts(
            "test_table",
            ["id", "name", "value"],
            ["integer", "string", "decimal"],
            [[1, "a", 10.5], [2, "b", 20.0]],
        )
        assert rows_inserted == 2

        result = cache_engine.execute_query(
            QueryRequest(sql="SELECT * FROM test_table ORDER BY id")
        )
        assert result.row_count == 2
        assert result.column_names == ["id", "name", "value"]
        assert result.rows[0][1] == "a"

    def test_replace_mode(self, cache_engine: LocalCacheEngine) -> None:
        cache_engine.ingest_facts(
            "t", ["id"], ["integer"], [[1], [2]]
        )
        cache_engine.ingest_facts(
            "t", ["id"], ["integer"], [[3]], mode="replace"
        )
        result = cache_engine.execute_query(QueryRequest(sql="SELECT * FROM t"))
        assert result.row_count == 1

    def test_append_mode(self, cache_engine: LocalCacheEngine) -> None:
        cache_engine.ingest_facts(
            "t", ["id"], ["integer"], [[1]]
        )
        cache_engine.ingest_facts(
            "t", ["id"], ["integer"], [[2]], mode="append"
        )
        result = cache_engine.execute_query(QueryRequest(sql="SELECT * FROM t"))
        assert result.row_count == 2

    def test_has_table(self, cache_engine: LocalCacheEngine) -> None:
        assert not cache_engine.has_table("nope")
        cache_engine.ingest_facts("yes", ["id"], ["integer"], [[1]])
        assert cache_engine.has_table("yes")

    def test_empty_ingest(self, cache_engine: LocalCacheEngine) -> None:
        assert cache_engine.ingest_facts("t", ["id"], ["integer"], []) == 0

    def test_missing_table_query(self, cache_engine: LocalCacheEngine) -> None:
        result = cache_engine.execute_query(
            QueryRequest(sql="SELECT * FROM nonexistent")
        )
        assert result.row_count == 0
        assert result.staleness.level == StalenessLevel.MISSING


class TestWatermarks:
    def test_no_watermark_initially(self, cache_engine: LocalCacheEngine) -> None:
        assert cache_engine.get_watermark("src", "prof", "tbl") is None

    def test_set_and_get_watermark(self, cache_engine: LocalCacheEngine) -> None:
        now = datetime.now(timezone.utc)
        wm = SyncWatermark(
            source_name="fake",
            profile_name="test",
            table_name="gl_detail",
            last_synced_at=now,
            row_count=100,
        )
        cache_engine.update_watermark(wm)
        retrieved = cache_engine.get_watermark("fake", "test", "gl_detail")
        assert retrieved is not None
        assert retrieved.row_count == 100
        assert retrieved.table_name == "gl_detail"

    def test_update_watermark_overwrites(self, cache_engine: LocalCacheEngine) -> None:
        now = datetime.now(timezone.utc)
        cache_engine.update_watermark(
            SyncWatermark("s", "p", "t", now, row_count=10)
        )
        cache_engine.update_watermark(
            SyncWatermark("s", "p", "t", now, row_count=20)
        )
        wm = cache_engine.get_watermark("s", "p", "t")
        assert wm is not None
        assert wm.row_count == 20


class TestStaleness:
    def test_missing_when_no_watermark(self, cache_engine: LocalCacheEngine) -> None:
        info = cache_engine.get_staleness(["t1"], "src")
        assert info.level == StalenessLevel.MISSING

    def test_fresh_after_sync(self, cache_engine: LocalCacheEngine) -> None:
        now = datetime.now(timezone.utc)
        cache_engine.update_watermark(
            SyncWatermark("src", "p", "t1", now)
        )
        info = cache_engine.get_staleness(["t1"], "src")
        assert info.level == StalenessLevel.FRESH


class TestEndToEnd:
    def test_fake_connector_to_cache(
        self,
        fake_connector: FakeConnector,
        cache_engine: LocalCacheEngine,
    ) -> None:
        """Full data path: FakeConnector -> Cache -> Query."""
        scope = ScopeDescription(tables=["gl_detail"])
        plan = fake_connector.plan_scope(scope)
        result = fake_connector.fetch_facts(plan)

        col_type_strings = [ct.value for ct in result.column_types]
        cache_engine.ingest_facts(
            "gl_detail",
            list(result.column_names),
            col_type_strings,
            [list(row) for row in result.rows],
        )

        query_result = cache_engine.execute_query(
            QueryRequest(sql="SELECT SUM(amount) as total FROM gl_detail WHERE account_type = 'Income'")
        )
        assert query_result.row_count == 1
        total = query_result.rows[0][0]
        assert total > 0
