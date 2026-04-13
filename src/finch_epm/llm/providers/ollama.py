"""Ollama local LLM provider.

Uses Ollama's OpenAI-compatible endpoint via httpx.
"""

from __future__ import annotations

from typing import Any

import httpx

from finch_epm.llm.base import LLMError, LLMResponse, Message, Provider
from finch_epm.llm.registry import resolve_model

_DEFAULT_BASE = "http://localhost:11434"


class OllamaProvider(Provider):
    """Ollama local provider via the OpenAI-compatible API."""

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str = "",
    ) -> None:
        self._model = resolve_model("ollama", model)
        self._base_url = (base_url or _DEFAULT_BASE).rstrip("/")

    def generate(
        self,
        system: str,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 8192,
    ) -> LLMResponse:
        resolved_model = resolve_model("ollama", model) if model else self._model
        api_messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        api_messages.extend(
            {"role": m.role, "content": m.content} for m in messages
        )

        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": api_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        try:
            resp = httpx.post(
                f"{self._base_url}/v1/chat/completions",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=300.0,  # Local models can be slow
            )
        except httpx.ConnectError as e:
            raise LLMError(
                f"Cannot connect to Ollama at {self._base_url}. "
                "Is Ollama running? Start it with: ollama serve"
            ) from e
        except httpx.HTTPError as e:
            raise LLMError(f"Ollama API request failed: {e}") from e

        if resp.status_code != 200:
            raise LLMError(
                f"Ollama API returned {resp.status_code}: {resp.text}"
            )

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise LLMError("Ollama returned no choices in response")

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
            "provider": "ollama",
            "model": self._model,
            "base_url": self._base_url,
        }
