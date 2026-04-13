"""Tests for third-party connector plugin discovery via setuptools entry points."""

from __future__ import annotations

import logging
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import pytest

from finch_epm.connectors.base import ConnectorBase
from finch_epm.connectors.registry import (
    _REGISTRY,
    discover_plugins,
    register_connector,
)


class _StubConnector(ConnectorBase):
    """Minimal concrete ConnectorBase for testing plugin registration."""

    connector_type: ClassVar[str] = "stub_plugin"
    display_name: ClassVar[str] = "Stub Plugin"

    def connect(self) -> None:
        self._connected = True

    def close(self) -> None:
        self._connected = False

    def introspect_schema(self) -> Any:
        return None

    def list_dimensions(self) -> list:
        return []

    def get_hierarchy(self, dimension_name: str) -> list:
        return []

    def plan_scope(self, scope: Any) -> Any:
        return None

    def fetch_facts(self, plan: Any) -> Any:
        return None

    def validate_credentials(self) -> bool:
        return True


def _make_entry_point(name: str, load_result: Any, *, raises: Exception | None = None):
    """Create a mock entry point."""
    ep = MagicMock()
    ep.name = name
    if raises:
        ep.load.side_effect = raises
    else:
        ep.load.return_value = load_result
    return ep


@pytest.fixture(autouse=True)
def _clean_registry():
    """Ensure stub_plugin is removed from registry after each test."""
    yield
    _REGISTRY.pop("stub_plugin", None)


class TestDiscoverPlugins:
    """Tests for discover_plugins()."""

    @patch("finch_epm.connectors.registry.entry_points")
    def test_empty_entry_points(self, mock_eps: MagicMock) -> None:
        """No entry points registered — returns empty, no crash."""
        mock_eps.return_value = []
        result = discover_plugins()
        assert result == []

    @patch("finch_epm.connectors.registry.entry_points")
    def test_registers_valid_connector(self, mock_eps: MagicMock) -> None:
        """A valid ConnectorBase subclass is registered."""
        ep = _make_entry_point("stub", _StubConnector)
        mock_eps.return_value = [ep]

        result = discover_plugins()

        assert result == ["stub_plugin"]
        assert _REGISTRY["stub_plugin"] is _StubConnector

    @patch("finch_epm.connectors.registry.entry_points")
    def test_skips_non_connector_class(
        self, mock_eps: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A class that doesn't subclass ConnectorBase is skipped."""
        ep = _make_entry_point("bad", str)  # str is not a connector
        mock_eps.return_value = [ep]

        with caplog.at_level(logging.WARNING):
            result = discover_plugins()

        assert result == []
        assert "does not subclass ConnectorBase" in caplog.text

    @patch("finch_epm.connectors.registry.entry_points")
    def test_handles_import_error(
        self, mock_eps: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An entry point that fails to load is skipped gracefully."""
        ep = _make_entry_point("broken", None, raises=ImportError("missing dep"))
        mock_eps.return_value = [ep]

        with caplog.at_level(logging.WARNING):
            result = discover_plugins()

        assert result == []
        assert "import error" in caplog.text

    @patch("finch_epm.connectors.registry.entry_points")
    def test_collision_with_builtin_skips_plugin(
        self, mock_eps: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A plugin whose connector_type collides with a built-in is skipped."""
        # Pre-register under the same type
        _REGISTRY["stub_plugin"] = _StubConnector  # type: ignore[assignment]

        # Create a different class with the same connector_type
        class _DuplicateConnector(_StubConnector):
            connector_type: ClassVar[str] = "stub_plugin"

        ep = _make_entry_point("dup", _DuplicateConnector)
        mock_eps.return_value = [ep]

        with caplog.at_level(logging.WARNING):
            result = discover_plugins()

        assert result == []
        assert "collides" in caplog.text
        # Original stays
        assert _REGISTRY["stub_plugin"] is _StubConnector

    @patch("finch_epm.connectors.registry.entry_points")
    def test_skips_empty_connector_type(
        self, mock_eps: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A connector with an empty connector_type is skipped."""

        class _EmptyType(ConnectorBase):
            connector_type: ClassVar[str] = ""
            display_name: ClassVar[str] = "Empty"

            def connect(self) -> None: ...
            def close(self) -> None: ...
            def introspect_schema(self) -> Any: return None
            def list_dimensions(self) -> list: return []
            def get_hierarchy(self, dimension_name: str) -> list: return []
            def plan_scope(self, scope: Any) -> Any: return None
            def fetch_facts(self, plan: Any) -> Any: return None
            def validate_credentials(self) -> bool: return True

        ep = _make_entry_point("empty_type", _EmptyType)
        mock_eps.return_value = [ep]

        with caplog.at_level(logging.WARNING):
            result = discover_plugins()

        assert result == []
        assert "no connector_type" in caplog.text
