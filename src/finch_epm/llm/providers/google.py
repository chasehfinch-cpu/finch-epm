"""Google Gemini LLM provider.

Uses the Google GenAI REST API via httpx. No google SDK dependency.
"""

from __future__ import annotations

from typing import Any

import httpx

from finch_epm.llm.base import LLMError, LLMResponse, Message, Provider
from finch_epm.llm.registry import resolve_model

_API_BASE = "https://generativelanguage.googleapis.com"


class GoogleProvider(Provider):
    """Google Gemini provider via the GenAI REST API."""

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        if not api_key:
            raise LLMError(
                "Google API key is required. "
                "Set GOOGLE_API_KEY or run: finch-epm llm configure"
            )
        self._api_key = api_key
        self._model = resolve_model("google", model)
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
        resolved_model = resolve_model("google", model) if model else self._model

        contents: list[dict[str, Any]] = []
        for m in messages:
            role = "user" if m.role == "user" else "model"
            contents.append({"role": role, "parts": [{"text": m.content}]})

        payload: dict[str, Any] = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        url = (
            f"{self._base_url}/v1beta/models/{resolved_model}"
            f":generateContent?key={self._api_key}"
        )

        try:
            resp = httpx.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=120.0,
            )
        except httpx.HTTPError as e:
            raise LLMError(f"Google GenAI API request failed: {e}") from e

        if resp.status_code != 200:
            raise LLMError(
                f"Google GenAI API returned {resp.status_code}: {resp.text}"
            )

        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise LLMError("Google GenAI returned no candidates")

        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)

        usage_meta = data.get("usageMetadata", {})

        return LLMResponse(
            content=text,
            model=resolved_model,
            stop_reason=candidates[0].get("finishReason", ""),
            usage={
                "input_tokens": usage_meta.get("promptTokenCount", 0),
                "output_tokens": usage_meta.get("candidatesTokenCount", 0),
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
            "provider": "google",
            "model": self._model,
            "base_url": self._base_url,
        }
