"""Tests for multi-source table namespacing."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from finch_epm.cache.local import LocalCacheEngine
from finch_epm.cache.models import QueryRequest, SourceTableRef, StalenessLevel
from finch_epm.cache.sync import (
    SyncEngine,
    _make_cache_table_name,
    migrate_to_namespaced_tables,
)
from finch_epm.connectors.fake import FakeConnector


class TestMakeCacheTableName:
    def test_simple(self) -> None:
        assert _make_cache_table_name("ns", "Account") == "ns__Account"

    def test_dots_sanitized(self) -> None:
        assert _make_cache_table_name("ss", "dbo.Sites") == "ss__dbo__Sites"

    def test_multiple_dots(self) -> None:
        assert _make_cache_table_name("pg", "public.schema.table") == "pg__public__schema__table"

    def test_fake_prefix(self) -> None:
        assert _make_cache_table_name("fake", "gl_detail") == "fake__gl_detail"


class TestSourceTableRef:
    def test_cache_name(self) -> None:
        ref = SourceTableRef(source_prefix="ns", raw_table_name="Account")
        assert ref.cache_name == "ns__Account"

    def test_cache_name_with_dots(self) -> None:
        ref = SourceTableRef(source_prefix="ss", raw_table_name="dbo.Sites")
        assert ref.cache_name == "ss__dbo__Sites"

    def test_parse_roundtrip(self) -> None:
        ref = SourceTableRef(source_prefix="ns", raw_table_name="Account")
        parsed = SourceTableRef.parse(ref.cache_name)
        assert parsed.source_prefix == "ns"
        assert parsed.raw_table_name == "Account"

    def test_parse_with_underscores_in_name(self) -> None:
        parsed = SourceTableRef.parse("fake__gl_detail")
        assert parsed.source_prefix == "fake"
        assert parsed.raw_table_name == "gl_detail"

    def test_parse_no_prefix_raises(self) -> None:
        with pytest.raises(ValueError, match="no source prefix"):
            SourceTableRef.parse("just_a_table")


class TestSyncCreatesNamespacedTables:
    def test_tables_get_prefix(
        self, fake_connector: FakeConnector, cache_engine: LocalCacheEngine
    ) -> None:
        engine = SyncEngine(fake_connector, cache_engine)
        engine.sync_tables(["gl_detail", "subsidiary"], mode="full")

        assert cache_engine.has_table("fake__gl_detail")
        assert cache_engine.has_table("fake__subsidiary")
        assert not cache_engine.has_table("gl_detail")
        assert not cache_engine.has_table("subsidiary")


class TestCrossSourceJoin:
    def test_join_across_prefixes(self, cache_engine: LocalCacheEngine) -> None:
        """Two fake connectors with different prefixes can be joined."""

        class FakeA(FakeConnector):
            connector_type: ClassVar[str] = "fake_a"
            source_prefix: ClassVar[str] = "a"

        class FakeB(FakeConnector):
            connector_type: ClassVar[str] = "fake_b"
            source_prefix: ClassVar[str] = "b"

        conn_a = FakeA("test")
        conn_a.connect()
        conn_b = FakeB("test")
        conn_b.connect()

        SyncEngine(conn_a, cache_engine).sync_tables(["gl_detail"], mode="full")
        SyncEngine(conn_b, cache_engine).sync_tables(["subsidiary"], mode="full")

        assert cache_engine.has_table("a__gl_detail")
        assert cache_engine.has_table("b__subsidiary")

        # Cross-source JOIN should work in DuckDB
        result = cache_engine.execute_query(QueryRequest(
            sql="""
                SELECT g.subsidiary_id, s.name
                FROM a__gl_detail g
                JOIN b__subsidiary s
                    ON CAST(g.subsidiary_id AS VARCHAR) = CAST(s.id AS VARCHAR)
                LIMIT 5
            """
        ))
        assert result.row_count > 0

        conn_a.close()
        conn_b.close()


class TestValidateTablesExist:
    def test_all_found(self, cache_engine: LocalCacheEngine) -> None:
        cache_engine.ingest_facts("t1", ["a"], ["string"], [["x"]])
        cache_engine.ingest_facts("t2", ["a"], ["string"], [["y"]])
        found, missing = cache_engine.validate_tables_exist(["t1", "t2"])
        assert found == ["t1", "t2"]
        assert missing == []

    def test_some_missing(self, cache_engine: LocalCacheEngine) -> None:
        cache_engine.ingest_facts("t1", ["a"], ["string"], [["x"]])
        found, missing = cache_engine.validate_tables_exist(["t1", "t2"])
        assert found == ["t1"]
        assert missing == ["t2"]


class TestStalenessAggregation:
    def test_fresh_when_all_fresh(
        self, fake_connector: FakeConnector, cache_engine: LocalCacheEngine
    ) -> None:
        engine = SyncEngine(fake_connector, cache_engine)
        engine.sync_tables(["gl_detail", "subsidiary"], mode="full")

        staleness = cache_engine.get_staleness_multi_source(
            ["fake__gl_detail", "fake__subsidiary"]
        )
        # Just synced — should be fresh
        assert staleness.level == StalenessLevel.FRESH

    def test_missing_when_table_not_synced(
        self, cache_engine: LocalCacheEngine
    ) -> None:
        staleness = cache_engine.get_staleness_multi_source(
            ["fake__nonexistent"]
        )
        assert staleness.level == StalenessLevel.MISSING


class TestMigration:
    def test_renames_old_tables(self, cache_engine: LocalCacheEngine) -> None:
        """Old un-prefixed table is renamed to namespaced format."""
        # Simulate old-style table
        cache_engine.ingest_facts("gl_detail", ["a"], ["string"], [["x"]])

        # Create a watermark as if sync had been run before
        from datetime import datetime, timezone
        from finch_epm.cache.models import SyncWatermark

        cache_engine.update_watermark(SyncWatermark(
            source_name="fake",
            profile_name="test",
            table_name="gl_detail",
            last_synced_at=datetime.now(timezone.utc),
            row_count=1,
        ))

        connector = FakeConnector("test")
        renamed = migrate_to_namespaced_tables(cache_engine, connector)

        assert len(renamed) == 1
        assert renamed[0] == ("gl_detail", "fake__gl_detail")
        assert cache_engine.has_table("fake__gl_detail")
        assert not cache_engine.has_table("gl_detail")

    def test_skips_already_namespaced(
        self, fake_connector: FakeConnector, cache_engine: LocalCacheEngine
    ) -> None:
        """Tables that already have the prefix are not renamed."""
        engine = SyncEngine(fake_connector, cache_engine)
        engine.sync_tables(["gl_detail"], mode="full")

        renamed = migrate_to_namespaced_tables(cache_engine, fake_connector)
        assert len(renamed) == 0
