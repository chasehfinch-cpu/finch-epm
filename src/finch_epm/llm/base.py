"""Provider abstract base class and shared data models.

Every LLM provider (Anthropic, OpenAI, Google, Ollama, generic) implements
the Provider ABC. The rest of the system only depends on this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LLMConfig:
    """Configuration for an LLM provider instance.

    Stored via ProfileManager with connector_type="llm".
    """

    provider: str
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMResponse:
    """Response from an LLM provider."""

    content: str
    model: str = ""
    stop_reason: str = ""
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Message:
    """A single message in the conversation."""

    role: str  # "user" or "assistant"
    content: str


class Provider(ABC):
    """Abstract base class for LLM providers.

    Subclasses must implement generate(), test_connection(), and describe().
    All providers use httpx for HTTP calls (already a core dependency).
    """

    @abstractmethod
    def generate(
        self,
        system: str,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 8192,
    ) -> LLMResponse:
        """Generate a response from the LLM.

        Args:
            system: System prompt text.
            messages: Conversation messages.
            model: Model override (uses provider default if None).
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in the response.

        Returns:
            LLMResponse with the generated content.

        Raises:
            LLMError: If the API call fails.
        """

    @abstractmethod
    def test_connection(self) -> bool:
        """Make a cheap round-trip to verify credentials work.

        Returns:
            True if the connection succeeds.

        Raises:
            LLMError: With a readable error message if it fails.
        """

    @abstractmethod
    def describe(self) -> dict[str, Any]:
        """Describe this provider instance.

        Returns:
            Dict with at least: provider, model, base_url (if custom).
        """


class LLMError(Exception):
    """Raised when an LLM operation fails."""
