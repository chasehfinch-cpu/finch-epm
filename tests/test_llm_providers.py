"""Tests for the LLM provider layer.

All tests use the noop provider or test the provider registry.
No real API calls are made.
"""

from __future__ import annotations

import pytest

from finch_epm.llm.base import LLMError, LLMResponse, Message, Provider
from finch_epm.llm.providers import get_provider_class, list_provider_names
from finch_epm.llm.providers.noop import NoopProvider
from finch_epm.llm.registry import default_model, list_aliases, resolve_model


class TestProviderRegistry:
    """Tests for provider discovery and loading."""

    def test_list_providers_excludes_noop(self) -> None:
        names = list_provider_names()
        assert "noop" not in names
        assert "anthropic" in names
        assert "openai" in names
        assert "google" in names
        assert "ollama" in names
        assert "openai_compatible" in names

    def test_get_provider_class_anthropic(self) -> None:
        cls = get_provider_class("anthropic")
        assert issubclass(cls, Provider)

    def test_get_provider_class_openai(self) -> None:
        cls = get_provider_class("openai")
        assert issubclass(cls, Provider)

    def test_get_provider_class_google(self) -> None:
        cls = get_provider_class("google")
        assert issubclass(cls, Provider)

    def test_get_provider_class_ollama(self) -> None:
        cls = get_provider_class("ollama")
        assert issubclass(cls, Provider)

    def test_get_provider_class_noop(self) -> None:
        cls = get_provider_class("noop")
        assert cls is NoopProvider

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_provider_class("nonexistent")


class TestModelRegistry:
    """Tests for model alias resolution."""

    def test_resolve_alias_fast(self) -> None:
        model = resolve_model("anthropic", "fast")
        assert "haiku" in model

    def test_resolve_alias_balanced(self) -> None:
        model = resolve_model("anthropic", "balanced")
        assert "sonnet" in model

    def test_resolve_alias_best(self) -> None:
        model = resolve_model("anthropic", "best")
        assert "opus" in model

    def test_resolve_literal_model_id(self) -> None:
        model = resolve_model("anthropic", "claude-sonnet-4-6-20250610")
        assert model == "claude-sonnet-4-6-20250610"

    def test_resolve_none_returns_default(self) -> None:
        model = resolve_model("anthropic", None)
        assert model == default_model("anthropic")

    def test_resolve_unknown_provider_returns_literal(self) -> None:
        model = resolve_model("unknown_provider", "some-model")
        assert model == "some-model"

    def test_list_aliases(self) -> None:
        aliases = list_aliases("openai")
        assert "fast" in aliases
        assert "balanced" in aliases
        assert "best" in aliases

    def test_default_model_known_provider(self) -> None:
        model = default_model("openai")
        assert model  # Non-empty string

    def test_default_model_unknown_provider(self) -> None:
        model = default_model("unknown")
        assert model == "default"


class TestNoopProvider:
    """Tests for the noop test provider."""

    def test_generate_returns_response(self) -> None:
        provider = NoopProvider(responses=["name: test\nqueries:\n  - name: q\n    sql: SELECT 1\ncharts:\n  - type: kpi\n    title: T\n    data: q\n    value: '1'"])
        result = provider.generate(
            system="test", messages=[Message(role="user", content="hi")]
        )
        assert isinstance(result, LLMResponse)
        assert "test" in result.content
        assert result.model == "noop"

    def test_generate_wraps_in_yaml_fences(self) -> None:
        provider = NoopProvider(responses=["name: test"])
        result = provider.generate(
            system="", messages=[Message(role="user", content="")]
        )
        assert "```yaml" in result.content

    def test_generate_does_not_double_wrap(self) -> None:
        provider = NoopProvider(responses=["```yaml\nname: test\n```"])
        result = provider.generate(
            system="", messages=[Message(role="user", content="")]
        )
        # Should not have ```yaml twice
        assert result.content.count("```yaml") == 1

    def test_multiple_responses_consumed_in_order(self) -> None:
        provider = NoopProvider(responses=["first", "second", "third"])
        r1 = provider.generate(system="", messages=[Message(role="user", content="")])
        r2 = provider.generate(system="", messages=[Message(role="user", content="")])
        r3 = provider.generate(system="", messages=[Message(role="user", content="")])
        assert "first" in r1.content
        assert "second" in r2.content
        assert "third" in r3.content

    def test_exhausted_responses_repeat_last(self) -> None:
        provider = NoopProvider(responses=["only"])
        provider.generate(system="", messages=[Message(role="user", content="")])
        r2 = provider.generate(system="", messages=[Message(role="user", content="")])
        assert "only" in r2.content

    def test_test_connection(self) -> None:
        provider = NoopProvider()
        assert provider.test_connection() is True

    def test_describe(self) -> None:
        provider = NoopProvider()
        info = provider.describe()
        assert info["provider"] == "noop"

    def test_default_response_when_no_args(self) -> None:
        provider = NoopProvider()
        result = provider.generate(
            system="", messages=[Message(role="user", content="")]
        )
        assert result.content  # Should have a default response


class TestProviderConstructorValidation:
    """Test that providers validate their required configuration."""

    def test_anthropic_requires_api_key(self) -> None:
        from finch_epm.llm.providers.anthropic import AnthropicProvider
        with pytest.raises(LLMError, match="API key is required"):
            AnthropicProvider(api_key="")

    def test_openai_requires_api_key(self) -> None:
        from finch_epm.llm.providers.openai import OpenAIProvider
        with pytest.raises(LLMError, match="API key is required"):
            OpenAIProvider(api_key="")

    def test_google_requires_api_key(self) -> None:
        from finch_epm.llm.providers.google import GoogleProvider
        with pytest.raises(LLMError, match="API key is required"):
            GoogleProvider(api_key="")

    def test_openai_compatible_requires_base_url(self) -> None:
        from finch_epm.llm.providers.openai_compatible import OpenAICompatibleProvider
        with pytest.raises(LLMError, match="Base URL is required"):
            OpenAICompatibleProvider(base_url="")

    def test_ollama_no_key_required(self) -> None:
        from finch_epm.llm.providers.ollama import OllamaProvider
        provider = OllamaProvider()
        assert provider.describe()["provider"] == "ollama"
