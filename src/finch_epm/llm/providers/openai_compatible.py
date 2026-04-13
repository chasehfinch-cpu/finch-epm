"""Generic OpenAI-compatible LLM provider.

Works with any endpoint that implements the OpenAI Chat Completions API:
LM Studio, vLLM, Together, OpenRouter, Groq, Azure OpenAI, etc.
"""

from __future__ import annotations

from typing import Any

import httpx

from finch_epm.llm.base import LLMError, LLMResponse, Message, Provider
from finch_epm.llm.registry import resolve_model


class OpenAICompatibleProvider(Provider):
    """Generic OpenAI-compatible endpoint provider."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        model: str | None = None,
    ) -> None:
        if not base_url:
            raise LLMError(
                "Base URL is required for OpenAI-compatible provider. "
                "Example: http://localhost:1234/v1"
            )
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = resolve_model("openai_compatible", model)

    def generate(
        self,
        system: str,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 8192,
    ) -> LLMResponse:
        resolved_model = (
            resolve_model("openai_compatible", model) if model else self._model
        )
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

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        # Ensure the URL ends with the completions path
        url = self._base_url
        if not url.endswith("/chat/completions"):
            url = f"{url}/chat/completions"

        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=120.0)
        except httpx.ConnectError as e:
            raise LLMError(
                f"Cannot connect to {self._base_url}. "
                "Is the server running?"
            ) from e
        except httpx.HTTPError as e:
            raise LLMError(f"API request failed: {e}") from e

        if resp.status_code != 200:
            raise LLMError(
                f"API returned {resp.status_code}: {resp.text}"
            )

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise LLMError("API returned no choices in response")

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
            "provider": "openai_compatible",
            "model": self._model,
            "base_url": self._base_url,
        }
