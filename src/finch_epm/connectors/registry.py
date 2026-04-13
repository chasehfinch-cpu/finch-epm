"""Connector type registry.

Connectors register themselves via the ``@register_connector`` decorator.
The rest of the system looks up connectors by their type string.

Third-party packages can also register connectors via setuptools entry
points in the ``finch_epm.connectors`` group. Call :func:`discover_plugins`
at startup to load them.
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points
from typing import Type

from finch_epm.connectors.base import ConnectorBase

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, Type[ConnectorBase]] = {}


def register_connector(cls: Type[ConnectorBase]) -> Type[ConnectorBase]:
    """Class decorator that registers a connector type.

    Usage::

        @register_connector
        class MyConnector(ConnectorBase):
            connector_type = "mydb"
            ...
    """
    _REGISTRY[cls.connector_type] = cls
    return cls


def get_connector_class(connector_type: str) -> Type[ConnectorBase]:
    """Look up a connector class by its type string.

    Raises:
        KeyError: If no connector is registered for that type.
    """
    if connector_type not in _REGISTRY:
        available = sorted(_REGISTRY.keys())
        raise KeyError(
            f"Unknown connector type: {connector_type!r}. Available: {available}"
        )
    return _REGISTRY[connector_type]


def list_connector_types() -> list[str]:
    """Return all registered connector type names, sorted."""
    return sorted(_REGISTRY.keys())


def discover_plugins() -> list[str]:
    """Discover and register third-party connector plugins.

    Scans the ``finch_epm.connectors`` entry point group for classes
    that subclass :class:`ConnectorBase`. Each valid entry point is
    loaded, validated, and registered.

    Built-in connectors take precedence: if a plugin's ``connector_type``
    collides with an already-registered type, the plugin is skipped.

    Returns:
        List of newly registered connector type names.
    """
    registered: list[str] = []
    eps = entry_points(group="finch_epm.connectors")

    for ep in eps:
        try:
            cls = ep.load()
        except Exception:
            logger.warning("Failed to load connector plugin %r: import error", ep.name)
            continue

        if not isinstance(cls, type) or not issubclass(cls, ConnectorBase):
            logger.warning(
                "Plugin %r does not subclass ConnectorBase, skipping", ep.name
            )
            continue

        ct = getattr(cls, "connector_type", "")
        if not ct:
            logger.warning(
                "Plugin %r has no connector_type, skipping", ep.name
            )
            continue

        if ct in _REGISTRY:
            logger.warning(
                "Plugin %r connector_type %r collides with existing, skipping",
                ep.name, ct,
            )
            continue

        _REGISTRY[ct] = cls
        registered.append(ct)
        logger.debug("Registered plugin connector %r from %r", ct, ep.name)

    return registered
