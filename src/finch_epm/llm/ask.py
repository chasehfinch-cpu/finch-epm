"""Core ask pipeline: generate, extract, validate, retry.

This module implements the main ``finch-epm ask`` logic:
    1. Build a system prompt from the catalog and cache
    2. Send the user prompt to the configured LLM provider
    3. Extract .fdash YAML from the response
    4. Validate via the existing parser
    5. If validation fails, feed errors back and retry (up to max_retries)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from finch_epm.dashboard.fdash import FdashError, load_fdash_string, validate_fdash
from finch_epm.dashboard.models import DashboardSpec
from finch_epm.llm.base import LLMError, LLMResponse, Message, Provider

logger = logging.getLogger(__name__)


@dataclass
class AskResult:
    """Result of an ask invocation."""

    success: bool
    fdash_content: str = ""
    spec: DashboardSpec | None = None
    errors: list[str] = field(default_factory=list)
    attempts: int = 0
    responses: list[LLMResponse] = field(default_factory=list)


def extract_yaml(response_text: str) -> str:
    """Extract YAML content from LLM response.

    Looks for ```yaml ... ``` fences first, then plain ``` fences,
    then falls back to the entire response text.
    """
    # Try ```yaml ... ``` first
    pattern = r"```ya?ml\s*\n(.*?)```"
    matches = re.findall(pattern, response_text, re.DOTALL)
    if matches:
        return matches[0].strip()

    # Try plain ``` ... ```
    pattern = r"```\s*\n(.*?)```"
    matches = re.findall(pattern, response_text, re.DOTALL)
    if matches:
        return matches[0].strip()

    # Fallback: try the raw text (it might be bare YAML)
    stripped = response_text.strip()
    if stripped.startswith("name:") or stripped.startswith("---"):
        return stripped

    return stripped


def ask_llm(
    prompt: str,
    provider: Provider,
    system_prompt: str,
    *,
    model: str | None = None,
    max_retries: int = 2,
    temperature: float = 0.0,
) -> AskResult:
    """Run the ask pipeline: generate, extract, validate, retry.

    Args:
        prompt: The user's dashboard request (e.g. "build me a site P&L").
        provider: The configured LLM provider.
        system_prompt: Pre-built system prompt with spec + catalog.
        model: Optional model override.
        max_retries: Maximum correction attempts on validation failure.
        temperature: Sampling temperature.

    Returns:
        AskResult with the validated .fdash content on success,
        or errors on failure.
    """
    result = AskResult(success=False)
    messages: list[Message] = [Message(role="user", content=prompt)]

    for attempt in range(1, max_retries + 2):  # +2 because first attempt is not a retry
        result.attempts = attempt

        try:
            response = provider.generate(
                system=system_prompt,
                messages=messages,
                model=model,
                temperature=temperature,
            )
        except LLMError as e:
            result.errors.append(f"LLM generation failed: {e}")
            return result

        result.responses.append(response)

        # Extract YAML
        yaml_content = extract_yaml(response.content)
        if not yaml_content:
            error_msg = "LLM response did not contain any YAML content."
            result.errors.append(error_msg)
            if attempt <= max_retries:
                messages.append(Message(role="assistant", content=response.content))
                messages.append(Message(role="user", content=(
                    f"Error: {error_msg}\n"
                    "Please output a valid .fdash YAML file wrapped in ```yaml fences."
                )))
                continue
            return result

        # Parse
        try:
            spec = load_fdash_string(yaml_content, source="<llm-generated>")
        except FdashError as e:
            error_msg = f"YAML parse error: {e}"
            result.errors.append(error_msg)
            if attempt <= max_retries:
                messages.append(Message(role="assistant", content=response.content))
                messages.append(Message(role="user", content=(
                    f"The generated dashboard has errors:\n{error_msg}\n\n"
                    "Please fix these errors and output the corrected .fdash YAML."
                )))
                continue
            return result

        # Validate
        validation_errors = validate_fdash(spec)
        if validation_errors:
            error_text = "\n".join(f"- {e}" for e in validation_errors)
            result.errors = validation_errors
            if attempt <= max_retries:
                messages.append(Message(role="assistant", content=response.content))
                messages.append(Message(role="user", content=(
                    f"The generated dashboard has validation errors:\n{error_text}\n\n"
                    "Please fix these errors and output the corrected .fdash YAML."
                )))
                logger.info(
                    "Attempt %d/%d: %d validation errors, retrying",
                    attempt, max_retries + 1, len(validation_errors),
                )
                continue
            return result

        # Success
        result.success = True
        result.fdash_content = yaml_content
        result.spec = spec
        result.errors = []
        logger.info("Dashboard generated successfully on attempt %d", attempt)
        return result

    return result
