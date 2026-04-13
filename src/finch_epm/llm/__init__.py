"""Provider-agnostic LLM integration for finch-epm.

Supports any LLM provider (Anthropic, OpenAI, Google, Ollama, or any
OpenAI-compatible endpoint) through a common Provider interface.
"""

from finch_epm.llm.base import LLMConfig, LLMResponse, Provider
from finch_epm.llm.registry import resolve_model

__all__ = ["LLMConfig", "LLMResponse", "Provider", "resolve_model"]
