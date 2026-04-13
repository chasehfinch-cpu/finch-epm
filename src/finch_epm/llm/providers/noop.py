"""No-op LLM provider for tests and offline demos.

Returns canned responses from a list or from fixture files on disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from finch_epm.llm.base import LLMError, LLMResponse, Message, Provider


class NoopProvider(Provider):
    """Test provider that returns pre-configured responses.

    Responses are consumed in order. If the list is exhausted, the last
    response is repeated. This lets tests supply exactly the responses
    they need for the retry loop.
    """

    def __init__(
        self,
        responses: list[str] | None = None,
        fixture_dir: str | Path | None = None,
        api_key: str = "",
        model: str | None = None,
        base_url: str = "",
    ) -> None:
        self._responses: list[str] = []
        self._index = 0

        if responses:
            self._responses = list(responses)
        elif fixture_dir:
            fdir = Path(fixture_dir)
            if fdir.is_dir():
                for f in sorted(fdir.glob("*.yaml")) + sorted(fdir.glob("*.fdash")):
                    self._responses.append(f.read_text(encoding="utf-8"))

        if not self._responses:
            self._responses = ["name: empty\nqueries:\n  - name: q\n    sql: SELECT 1\n"
                               "charts:\n  - type: kpi\n    title: Test\n    data: q\n"
                               "    value: '1'"]

    def generate(
        self,
        system: str,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 8192,
    ) -> LLMResponse:
        if self._index < len(self._responses):
            content = self._responses[self._index]
            self._index += 1
        else:
            content = self._responses[-1]

        # Wrap in yaml fences if not already wrapped
        if "```yaml" not in content and "```" not in content:
            content = f"```yaml\n{content}\n```"

        return LLMResponse(
            content=content,
            model="noop",
            stop_reason="end_turn",
            usage={"input_tokens": 0, "output_tokens": 0},
        )

    def test_connection(self) -> bool:
        return True

    def describe(self) -> dict[str, Any]:
        return {
            "provider": "noop",
            "model": "noop",
            "responses_remaining": max(0, len(self._responses) - self._index),
        }
