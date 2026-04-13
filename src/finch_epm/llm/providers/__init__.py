"""LLM provider implementations.

Each module implements the Provider ABC for a specific LLM service.
All providers use httpx for HTTP calls -- no provider-specific SDKs required.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from finch_epm.llm.base import Provider

# Mapping of provider name -> module path for lazy import.
_PROVIDER_MODULES: dict[str, str] = {
    "anthropic": "finch_epm.llm.providers.anthropic",
    "openai": "finch_epm.llm.providers.openai",
    "google": "finch_epm.llm.providers.google",
    "ollama": "finch_epm.llm.providers.ollama",
    "openai_compatible": "finch_epm.llm.providers.openai_compatible",
    "noop": "finch_epm.llm.providers.noop",
}

# Provider name -> class name within the module.
_PROVIDER_CLASSES: dict[str, str] = {
    "anthropic": "AnthropicProvider",
    "openai": "OpenAIProvider",
    "google": "GoogleProvider",
    "ollama": "OllamaProvider",
    "openai_compatible": "OpenAICompatibleProvider",
    "noop": "NoopProvider",
}


def get_provider_class(provider_name: str) -> type[Provider]:
    """Lazily import and return the Provider class for a given name.

    Raises:
        ValueError: If the provider name is not recognized.
    """
    module_path = _PROVIDER_MODULES.get(provider_name)
    if module_path is None:
        available = ", ".join(sorted(_PROVIDER_MODULES.keys()))
        raise ValueError(
            f"Unknown LLM provider: '{provider_name}'. Available: {available}"
        )

    import importlib

    module = importlib.import_module(module_path)
    class_name = _PROVIDER_CLASSES[provider_name]
    return getattr(module, class_name)


def list_provider_names() -> list[str]:
    """Return all available provider names (excluding noop)."""
    return sorted(k for k in _PROVIDER_MODULES if k != "noop")
