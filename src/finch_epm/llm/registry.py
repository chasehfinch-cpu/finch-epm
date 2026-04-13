"""Model alias registry.

Maps generic aliases (fast, balanced, best) to provider-specific model IDs.
Update this file when providers release new models -- no other code changes needed.
"""

from __future__ import annotations

# Provider -> alias -> model ID.
# Keep alphabetical by provider, then alias order: fast, balanced, best.
_MODEL_ALIASES: dict[str, dict[str, str]] = {
    "anthropic": {
        "fast": "claude-haiku-4-5-20251001",
        "balanced": "claude-sonnet-4-6-20250610",
        "best": "claude-opus-4-6-20250610",
    },
    "openai": {
        "fast": "gpt-4.1-mini",
        "balanced": "gpt-4.1",
        "best": "o3",
    },
    "google": {
        "fast": "gemini-2.0-flash",
        "balanced": "gemini-2.5-pro",
        "best": "gemini-2.5-pro",
    },
    "ollama": {
        "fast": "llama3.2",
        "balanced": "llama3.3",
        "best": "llama3.3:70b",
    },
    "openai_compatible": {
        "fast": "fast",
        "balanced": "balanced",
        "best": "best",
    },
}

# Default model per provider when none is specified.
_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-6-20250610",
    "openai": "gpt-4.1",
    "google": "gemini-2.5-pro",
    "ollama": "llama3.3",
    "openai_compatible": "default",
}


def resolve_model(provider_name: str, alias_or_model: str | None = None) -> str:
    """Resolve a model alias or return the literal model ID.

    Args:
        provider_name: Provider key (e.g. "anthropic", "openai").
        alias_or_model: An alias ("fast", "balanced", "best"), a literal
            model ID, or None (uses the provider default).

    Returns:
        A concrete model ID string.
    """
    if alias_or_model is None:
        return _DEFAULT_MODELS.get(provider_name, "default")

    aliases = _MODEL_ALIASES.get(provider_name, {})
    return aliases.get(alias_or_model, alias_or_model)


def list_aliases(provider_name: str) -> dict[str, str]:
    """Return the alias -> model mapping for a provider."""
    return dict(_MODEL_ALIASES.get(provider_name, {}))


def default_model(provider_name: str) -> str:
    """Return the default model for a provider."""
    return _DEFAULT_MODELS.get(provider_name, "default")
