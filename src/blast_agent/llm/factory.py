"""Select an LLM client from environment configuration."""

from __future__ import annotations

import os
from pathlib import Path

from .anthropic import AnthropicClient
from .gemini import GeminiClient, LLMUnavailable


def client_from_env() -> AnthropicClient | GeminiClient:
    """Return the configured provider, preferring Anthropic when unforced."""

    dotenv = GeminiClient._read_dotenv(Path(".env"))

    def configured(name: str) -> str | None:
        if name in os.environ:
            return os.environ[name]
        return dotenv.get(name)

    provider = os.environ.get("BLAST_LLM_PROVIDER", "").strip().lower()
    if provider and provider not in {"anthropic", "gemini"}:
        raise LLMUnavailable(
            "BLAST_LLM_PROVIDER must be 'anthropic' or 'gemini'"
        )

    if provider == "anthropic":
        if not configured("ANTHROPIC_API_KEY"):
            raise LLMUnavailable("ANTHROPIC_API_KEY is not configured")
        return AnthropicClient.from_env()
    if provider == "gemini":
        if not configured("GEMINI_API_KEY"):
            raise LLMUnavailable("GEMINI_API_KEY is not configured")
        return GeminiClient.from_env()

    if configured("ANTHROPIC_API_KEY"):
        return AnthropicClient.from_env()
    if configured("GEMINI_API_KEY"):
        return GeminiClient.from_env()
    raise LLMUnavailable("no LLM API key configured")


__all__ = ["client_from_env"]
