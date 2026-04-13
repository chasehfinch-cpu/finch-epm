"""Tests for the ask pipeline: prompt building, YAML extraction, validation retry."""

from __future__ import annotations

import pytest

from finch_epm.llm.ask import AskResult, ask_llm, extract_yaml
from finch_epm.llm.base import Message
from finch_epm.llm.prompt import build_catalog_summary, build_system_prompt
from finch_epm.llm.providers.noop import NoopProvider


# ---------------------------------------------------------------------------
# YAML extraction
# ---------------------------------------------------------------------------


class TestExtractYaml:
    """Tests for extracting YAML from LLM responses."""

    def test_extract_from_yaml_fences(self) -> None:
        text = "Here's your dashboard:\n```yaml\nname: test\n```\nEnjoy!"
        assert extract_yaml(text) == "name: test"

    def test_extract_from_plain_fences(self) -> None:
        text = "```\nname: test\n```"
        assert extract_yaml(text) == "name: test"

    def test_extract_bare_yaml(self) -> None:
        text = "name: test\nqueries: []"
        assert extract_yaml(text) == "name: test\nqueries: []"

    def test_extract_with_leading_text(self) -> None:
        text = "Some explanation\n```yaml\nname: test\n```"
        assert extract_yaml(text) == "name: test"

    def test_extract_yml_fence(self) -> None:
        text = "```yml\nname: test\n```"
        assert extract_yaml(text) == "name: test"

    def test_extract_multiline(self) -> None:
        text = "```yaml\nname: test\ndescription: long\nqueries:\n  - name: q\n    sql: SELECT 1\n```"
        result = extract_yaml(text)
        assert "name: test" in result
        assert "queries:" in result

    def test_extract_empty_returns_empty(self) -> None:
        result = extract_yaml("")
        assert result == ""

    def test_extract_with_frontmatter(self) -> None:
        text = "---\nname: test\n---"
        result = extract_yaml(text)
        assert "name: test" in result


# ---------------------------------------------------------------------------
# Ask pipeline with noop provider
# ---------------------------------------------------------------------------

_VALID_FDASH = """\
name: Test Dashboard
description: A test dashboard
queries:
  - name: q1
    sql: SELECT 1 AS value
charts:
  - type: kpi
    title: Test KPI
    data: q1
    value: value
"""

_INVALID_FDASH_MISSING_CHART = """\
name: Bad Dashboard
queries:
  - name: q1
    sql: SELECT 1
"""

_INVALID_FDASH_BAD_REF = """\
name: Bad Ref
queries:
  - name: q1
    sql: SELECT 1
charts:
  - type: kpi
    title: Test
    data: nonexistent
    value: x
"""


class TestAskPipeline:
    """Tests for the full ask pipeline."""

    def test_happy_path(self) -> None:
        provider = NoopProvider(responses=[_VALID_FDASH])
        result = ask_llm(
            prompt="build me a dashboard",
            provider=provider,
            system_prompt="You are a dashboard generator.",
        )
        assert result.success
        assert result.fdash_content
        assert result.spec is not None
        assert result.spec.name == "Test Dashboard"
        assert result.attempts == 1
        assert not result.errors

    def test_retry_on_validation_error(self) -> None:
        # First response is invalid (no charts), second is valid
        provider = NoopProvider(responses=[
            _INVALID_FDASH_MISSING_CHART,
            _VALID_FDASH,
        ])
        result = ask_llm(
            prompt="build me a dashboard",
            provider=provider,
            system_prompt="test",
        )
        assert result.success
        assert result.attempts == 2

    def test_max_retries_exhausted(self) -> None:
        # All responses are invalid
        provider = NoopProvider(responses=[_INVALID_FDASH_MISSING_CHART])
        result = ask_llm(
            prompt="build me a dashboard",
            provider=provider,
            system_prompt="test",
            max_retries=1,
        )
        assert not result.success
        assert result.attempts == 2  # initial + 1 retry
        assert result.errors

    def test_bad_reference_triggers_retry(self) -> None:
        provider = NoopProvider(responses=[
            _INVALID_FDASH_BAD_REF,
            _VALID_FDASH,
        ])
        result = ask_llm(
            prompt="build me a dashboard",
            provider=provider,
            system_prompt="test",
        )
        assert result.success
        assert result.attempts == 2

    def test_zero_retries(self) -> None:
        provider = NoopProvider(responses=[_VALID_FDASH])
        result = ask_llm(
            prompt="test",
            provider=provider,
            system_prompt="test",
            max_retries=0,
        )
        assert result.success

    def test_zero_retries_with_invalid_fails(self) -> None:
        provider = NoopProvider(responses=[_INVALID_FDASH_MISSING_CHART])
        result = ask_llm(
            prompt="test",
            provider=provider,
            system_prompt="test",
            max_retries=0,
        )
        assert not result.success

    def test_responses_tracked(self) -> None:
        provider = NoopProvider(responses=[_VALID_FDASH])
        result = ask_llm(
            prompt="test",
            provider=provider,
            system_prompt="test",
        )
        assert len(result.responses) == 1
        assert result.responses[0].model == "noop"


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------


class TestPromptBuilder:
    """Tests for system prompt assembly."""

    def test_build_system_prompt_no_cache(self, catalog_store) -> None:
        prompt = build_system_prompt(catalog_store, None, [])
        assert "Dashboard Specification" in prompt
        assert "Available Data" in prompt
        assert "Additional Rules" in prompt

    def test_build_system_prompt_with_catalog(self, catalog_store, fake_connector) -> None:
        # Save some schema data into the catalog
        schema = fake_connector.introspect_schema()
        catalog_store.save_schema(schema)

        prompt = build_system_prompt(
            catalog_store, None,
            [(schema.source_name, schema.profile_name)],
        )
        assert "Available Data" in prompt
        # Should include table info from the fake connector
        assert "columns" in prompt

    def test_catalog_summary_empty(self, catalog_store) -> None:
        summary = build_catalog_summary(catalog_store, [])
        assert summary == []

    def test_catalog_summary_with_data(self, catalog_store, fake_connector) -> None:
        schema = fake_connector.introspect_schema()
        catalog_store.save_schema(schema)
        summary = build_catalog_summary(
            catalog_store,
            [(schema.source_name, schema.profile_name)],
        )
        assert len(summary) > 0
        assert "table" in summary[0]
        assert "columns" in summary[0]
