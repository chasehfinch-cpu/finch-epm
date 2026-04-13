"""Tests for the SyncEngine."""

from __future__ import annotations

from finch_epm.cache.local import LocalCacheEngine
from finch_epm.cache.models import QueryRequest
from finch_epm.cache.sync import SyncEngine
from finch_epm.connectors.fake import FakeConnector


class TestFullSync:
    def test_sync_single_table(
        self, fake_connector: FakeConnector, cache_engine: LocalCacheEngine
    ) -> None:
        engine = SyncEngine(fake_connector, cache_engine)
        report = engine.sync_tables(["gl_detail"], mode="full")

        assert report.tables_synced == 1
        assert report.tables_failed == 0
        assert report.total_rows == 10

        result = cache_engine.execute_query(
            QueryRequest(sql="SELECT COUNT(*) AS cnt FROM fake__gl_detail")
        )
        assert result.rows[0][0] == 10

    def test_sync_multiple_tables(
        self, fake_connector: FakeConnector, cache_engine: LocalCacheEngine
    ) -> None:
        engine = SyncEngine(fake_connector, cache_engine)
        report = engine.sync_tables(
            ["gl_detail", "subsidiary"], mode="full"
        )

        assert report.tables_synced == 2
        assert report.total_rows == 15  # 10 gl + 5 subsidiary
        assert cache_engine.has_table("fake__gl_detail")
        assert cache_engine.has_table("fake__subsidiary")

    def test_full_replaces_data(
        self, fake_connector: FakeConnector, cache_engine: LocalCacheEngine
    ) -> None:
        engine = SyncEngine(fake_connector, cache_engine)

        # Sync twice in full mode
        engine.sync_tables(["gl_detail"], mode="full")
        engine.sync_tables(["gl_detail"], mode="full")

        result = cache_engine.execute_query(
            QueryRequest(sql="SELECT COUNT(*) AS cnt FROM fake__gl_detail")
        )
        # Should be 10, not 20 (full mode replaces)
        assert result.rows[0][0] == 10


class TestIncrementalSync:
    def test_incremental_appends(
        self, fake_connector: FakeConnector, cache_engine: LocalCacheEngine
    ) -> None:
        engine = SyncEngine(fake_connector, cache_engine)

        # First sync
        engine.sync_tables(["gl_detail"], mode="full")
        # Second sync (incremental)
        engine.sync_tables(["gl_detail"], mode="incremental")

        result = cache_engine.execute_query(
            QueryRequest(sql="SELECT COUNT(*) AS cnt FROM fake__gl_detail")
        )
        # Incremental appends — FakeConnector returns all rows regardless of since
        # so this will be 20 (10 + 10)
        assert result.rows[0][0] == 20

    def test_watermark_created(
        self, fake_connector: FakeConnector, cache_engine: LocalCacheEngine
    ) -> None:
        engine = SyncEngine(fake_connector, cache_engine)
        engine.sync_tables(["gl_detail"], mode="full")

        wm = cache_engine.get_watermark("fake", "test", "gl_detail")
        assert wm is not None
        assert wm.row_count == 10


class TestErrorHandling:
    def test_partial_failure_continues(
        self, fake_connector: FakeConnector, cache_engine: LocalCacheEngine
    ) -> None:
        engine = SyncEngine(fake_connector, cache_engine)

        # "nonexistent" will fail, but "subsidiary" should succeed
        report = engine.sync_tables(
            ["nonexistent", "subsidiary"], mode="full"
        )

        assert report.tables_synced == 1
        assert report.tables_failed == 1
        assert len(report.errors) == 1
        assert cache_engine.has_table("fake__subsidiary")

    def test_sync_report_accuracy(
        self, fake_connector: FakeConnector, cache_engine: LocalCacheEngine
    ) -> None:
        engine = SyncEngine(fake_connector, cache_engine)
        report = engine.sync_tables(["gl_detail", "account"], mode="full")

        assert report.tables_synced == 2
        assert report.elapsed_seconds > 0
        assert len(report.per_table) == 2
        for r in report.per_table:
            assert r.success
            assert r.elapsed_seconds >= 0


class TestProgressCallback:
    def test_callback_called(
        self, fake_connector: FakeConnector, cache_engine: LocalCacheEngine
    ) -> None:
        engine = SyncEngine(fake_connector, cache_engine)
        calls: list[tuple[str, int]] = []

        def on_progress(table: str, rows: int) -> None:
            calls.append((table, rows))

        engine.sync_tables(
            ["gl_detail", "subsidiary"],
            mode="full",
            progress_callback=on_progress,
        )

        assert len(calls) == 2
        table_names = [c[0] for c in calls]
        assert "gl_detail" in table_names
        assert "subsidiary" in table_names


class TestEmptySync:
    def test_no_tables(
        self, fake_connector: FakeConnector, cache_engine: LocalCacheEngine
    ) -> None:
        engine = SyncEngine(fake_connector, cache_engine)
        report = engine.sync_tables([], mode="full")
        assert report.tables_synced == 0
        assert report.total_rows == 0
