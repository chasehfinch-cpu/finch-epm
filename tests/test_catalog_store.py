"""Tests for the CatalogStore."""

from __future__ import annotations

from finch_epm.catalog.catalog import CatalogStore
from finch_epm.connectors.fake import FakeConnector


class TestSaveAndListTables:
    def test_save_schema_stores_tables(
        self, catalog_store: CatalogStore, fake_connector: FakeConnector
    ) -> None:
        schema = fake_connector.introspect_schema()
        catalog_store.save_schema(schema)

        tables = catalog_store.list_tables("fake", "test")
        assert len(tables) == 3
        names = {t["table_name"] for t in tables}
        assert names == {"gl_detail", "subsidiary", "account"}

    def test_tables_have_expected_fields(
        self, catalog_store: CatalogStore, fake_connector: FakeConnector
    ) -> None:
        schema = fake_connector.introspect_schema()
        catalog_store.save_schema(schema)

        tables = catalog_store.list_tables("fake", "test")
        for t in tables:
            assert "table_name" in t
            assert "display_name" in t
            assert "access_status" in t

    def test_access_status_filter(
        self, catalog_store: CatalogStore, fake_connector: FakeConnector
    ) -> None:
        schema = fake_connector.introspect_schema()
        catalog_store.save_schema(schema)

        # FakeConnector doesn't set access_status in metadata, so filter
        # for "unknown" should return all, "accessible" should return none
        unknown = catalog_store.list_tables("fake", "test", access_status="unknown")
        assert len(unknown) == 3

    def test_get_accessible_table_names(
        self, catalog_store: CatalogStore, fake_connector: FakeConnector
    ) -> None:
        schema = fake_connector.introspect_schema()
        catalog_store.save_schema(schema)

        # FakeConnector metadata doesn't have access_status="accessible"
        accessible = catalog_store.get_accessible_table_names("fake", "test")
        assert len(accessible) == 0  # None have "accessible" status


class TestSaveAndListColumns:
    def test_columns_for_gl_detail(
        self, catalog_store: CatalogStore, fake_connector: FakeConnector
    ) -> None:
        schema = fake_connector.introspect_schema()
        catalog_store.save_schema(schema)

        cols = catalog_store.list_columns("fake", "test", "gl_detail")
        assert len(cols) == 6
        col_names = [c["column_name"] for c in cols]
        assert "period" in col_names
        assert "amount" in col_names

    def test_columns_have_types(
        self, catalog_store: CatalogStore, fake_connector: FakeConnector
    ) -> None:
        schema = fake_connector.introspect_schema()
        catalog_store.save_schema(schema)

        cols = catalog_store.list_columns("fake", "test", "gl_detail")
        for c in cols:
            assert c["column_type"] is not None
            assert isinstance(c["column_type"], str)


class TestSaveAndListDimensions:
    def test_save_dimensions(
        self, catalog_store: CatalogStore, fake_connector: FakeConnector
    ) -> None:
        dims = fake_connector.list_dimensions()
        catalog_store.save_dimensions("fake", "test", dims)

        stored = catalog_store.list_dimensions("fake", "test")
        assert len(stored) == 2
        names = {d["dimension_name"] for d in stored}
        assert names == {"subsidiary", "account"}

    def test_dimension_hierarchy_flag(
        self, catalog_store: CatalogStore, fake_connector: FakeConnector
    ) -> None:
        dims = fake_connector.list_dimensions()
        catalog_store.save_dimensions("fake", "test", dims)

        stored = catalog_store.list_dimensions("fake", "test")
        for d in stored:
            assert d["supports_hierarchy"] is True


class TestReIntrospect:
    def test_re_introspect_replaces_data(
        self, catalog_store: CatalogStore, fake_connector: FakeConnector
    ) -> None:
        schema = fake_connector.introspect_schema()
        catalog_store.save_schema(schema)
        assert len(catalog_store.list_tables("fake", "test")) == 3

        # Re-save — should still be 3, not 6
        catalog_store.save_schema(schema)
        assert len(catalog_store.list_tables("fake", "test")) == 3


class TestSourceTracking:
    def test_source_timestamp(
        self, catalog_store: CatalogStore, fake_connector: FakeConnector
    ) -> None:
        schema = fake_connector.introspect_schema()
        catalog_store.save_schema(schema)

        source = catalog_store.get_source("fake", "test")
        assert source is not None
        assert source["last_introspected_at"] is not None

    def test_no_source_initially(self, catalog_store: CatalogStore) -> None:
        assert catalog_store.get_source("fake", "test") is None


class TestEmptyCatalog:
    def test_empty_tables(self, catalog_store: CatalogStore) -> None:
        assert catalog_store.list_tables("fake", "test") == []

    def test_empty_columns(self, catalog_store: CatalogStore) -> None:
        assert catalog_store.list_columns("fake", "test", "anything") == []

    def test_empty_dimensions(self, catalog_store: CatalogStore) -> None:
        assert catalog_store.list_dimensions("fake", "test") == []
