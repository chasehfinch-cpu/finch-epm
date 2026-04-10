"""Connector type registry.

Connectors register themselves via the ``@register_connector`` decorator.
The rest of the system looks up connectors by their type string.
"""

from __future__ import annotations

from typing import Type

from finch_epm.connectors.base import ConnectorBase

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
