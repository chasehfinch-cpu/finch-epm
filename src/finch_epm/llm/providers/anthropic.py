"""Anthropic (Claude) LLM provider.

Uses the Anthropic Messages API via httpx. No anthropic SDK dependency.
"""

from __future__ import annotations

from typing import Any

import httpx

from finch_epm.llm.base import LLMError, LLMResponse, Message, Provider
from finch_epm.llm.registry import resolve_model

_API_BASE = "https://api.anthropic.com"
_API_VERSION = "2023-06-01"


class AnthropicProvider(Provider):
    """Anthropic Claude provider via the Messages API."""

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        if not api_key:
            raise LLMError(
                "Anthropic API key is required. "
                "Set ANTHROPIC_API_KEY or run: finch-epm llm configure"
            )
        self._api_key = api_key
        self._model = resolve_model("anthropic", model)
        self._base_url = (base_url or _API_BASE).rstrip("/")

    def generate(
        self,
        system: str,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 8192,
    ) -> LLMResponse:
        resolved_model = resolve_model("anthropic", model) if model else self._model
        payload: dict[str, Any] = {
            "model": resolved_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }

        try:
            resp = httpx.post(
                f"{self._base_url}/v1/messages",
                json=payload,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": _API_VERSION,
                    "content-type": "application/json",
                },
                timeout=120.0,
            )
        except httpx.HTTPError as e:
            raise LLMError(f"Anthropic API request failed: {e}") from e

        if resp.status_code != 200:
            raise LLMError(
                f"Anthropic API returned {resp.status_code}: {resp.text}"
            )

        data = resp.json()
        content_blocks = data.get("content", [])
        text = "".join(
            block.get("text", "") for block in content_blocks if block.get("type") == "text"
        )
        usage = data.get("usage", {})

        return LLMResponse(
            content=text,
            model=data.get("model", resolved_model),
            stop_reason=data.get("stop_reason", ""),
            usage={
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            },
        )

    def test_connection(self) -> bool:
        try:
            self.generate(
                system="Respond with exactly: ok",
                messages=[Message(role="user", content="ping")],
                max_tokens=16,
            )
            return True
        except LLMError:
            raise

    def describe(self) -> dict[str, Any]:
        return {
            "provider": "anthropic",
            "model": self._model,
            "base_url": self._base_url,
        }
