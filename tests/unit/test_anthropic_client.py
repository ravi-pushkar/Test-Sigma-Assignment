"""Unit tests for Anthropic structured JSON generation and provider selection."""

from typing import Any

import pytest

from blast_agent.llm import (
    AnthropicClient,
    GeminiClient,
    LLMError,
    LLMUnavailable,
    client_from_env,
)
from blast_agent.llm.anthropic import _convert_schema


POLICY_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "index": {"type": "INTEGER"},
        "rationale": {"type": "STRING"},
        "metadata": {
            "type": "OBJECT",
            "properties": {"safe": {"type": "BOOLEAN"}},
        },
    },
    "required": ["index", "rationale", "metadata"],
}


def anthropic_response(value: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": value}],
        "stop_reason": "end_turn",
    }


def test_generate_json_sends_anthropic_request_and_converts_schema() -> None:
    captured: dict[str, Any] = {}

    def transport(url: str, body: dict, headers: dict) -> tuple[int, dict]:
        captured.update(url=url, body=body, headers=headers)
        return 200, anthropic_response('{"index":1,"rationale":"ok"}')

    client = AnthropicClient("secret", transport=transport)

    assert client.generate_json("choose", POLICY_SCHEMA, temperature=0.7) == {
        "index": 1,
        "rationale": "ok",
    }
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "secret"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert captured["body"]["model"] == "claude-haiku-4-5"
    assert captured["body"]["max_tokens"] == 8192
    assert "temperature" not in captured["body"]
    schema = captured["body"]["output_config"]["format"]["schema"]
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["index"]["type"] == "integer"
    assert schema["properties"]["metadata"]["additionalProperties"] is False
    assert schema["properties"]["metadata"]["required"] == ["safe"]


def test_generate_json_retries_twice_then_succeeds() -> None:
    statuses = iter([429, 429, 200])
    delays: list[float] = []

    def transport(url: str, body: dict, headers: dict) -> tuple[int, dict]:
        status = next(statuses)
        payload = anthropic_response('{"ok":true}') if status == 200 else {}
        return status, payload

    client = AnthropicClient(
        "secret",
        transport=transport,
        sleep=delays.append,
        min_interval_seconds=0,
    )

    assert client.generate_json("prompt", {}) == {"ok": True}
    assert delays == [5, 10]


def test_generate_json_raises_after_five_retryable_failures() -> None:
    attempts = 0

    def transport(url: str, body: dict, headers: dict) -> tuple[int, dict]:
        nonlocal attempts
        attempts += 1
        return 429, {"error": {"message": "rate limited"}}

    client = AnthropicClient(
        "secret",
        transport=transport,
        sleep=lambda delay: None,
        min_interval_seconds=0,
    )

    with pytest.raises(LLMUnavailable):
        client.generate_json("prompt", {})
    assert attempts == 5


def test_generate_json_raises_on_refusal() -> None:
    def transport(url: str, body: dict, headers: dict) -> tuple[int, dict]:
        return 200, {"content": [], "stop_reason": "refusal"}

    client = AnthropicClient("secret", transport=transport)

    with pytest.raises(LLMError, match="Anthropic refusal"):
        client.generate_json("prompt", {})


def test_convert_schema_adds_closed_objects_recursively() -> None:
    source = {
        "type": "OBJECT",
        "properties": {
            "requirements": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {"statement": {"type": "STRING"}},
                    "required": ["statement"],
                },
            }
        },
        "required": ["requirements"],
    }

    assert _convert_schema(source) == {
        "type": "object",
        "properties": {
            "requirements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"statement": {"type": "string"}},
                    "required": ["statement"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["requirements"],
        "additionalProperties": False,
    }


def test_factory_selects_configured_or_forced_provider(monkeypatch) -> None:
    monkeypatch.delenv("BLAST_LLM_PROVIDER", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-secret")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    assert isinstance(client_from_env(), AnthropicClient)

    monkeypatch.setenv("BLAST_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secret")
    assert isinstance(client_from_env(), GeminiClient)
