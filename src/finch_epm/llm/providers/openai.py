"""OpenAI (GPT) LLM provider.

Uses the OpenAI Chat Completions API via httpx. No openai SDK dependency.
"""

from __future__ import annotations

from typing import Any

import httpx

from finch_epm.llm.base import LLMError, LLMResponse, Message, Provider
from finch_epm.llm.registry import resolve_model

_API_BASE = "https://api.openai.com"


class OpenAIProvider(Provider):
    """OpenAI GPT provider via the Chat Completions API."""

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        if not api_key:
            raise LLMError(
                "OpenAI API key is required. "
                "Set OPENAI_API_KEY or run: finch-epm llm configure"
            )
        self._api_key = api_key
        self._model = resolve_model("openai", model)
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
        resolved_model = resolve_model("openai", model) if model else self._model
        api_messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        api_messages.extend(
            {"role": m.role, "content": m.content} for m in messages
        )

        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": api_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            resp = httpx.post(
                f"{self._base_url}/v1/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            )
        except httpx.HTTPError as e:
            raise LLMError(f"OpenAI API request failed: {e}") from e

        if resp.status_code != 200:
            raise LLMError(
                f"OpenAI API returned {resp.status_code}: {resp.text}"
            )

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise LLMError("OpenAI returned no choices in response")

        choice = choices[0]
        text = choice.get("message", {}).get("content", "")
        usage = data.get("usage", {})

        return LLMResponse(
            content=text,
            model=data.get("model", resolved_model),
            stop_reason=choice.get("finish_reason", ""),
            usage={
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
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
            "provider": "openai",
            "model": self._model,
            "base_url": self._base_url,
        }
