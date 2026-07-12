"""Small, dependency-free client for Anthropic structured generation."""

from __future__ import annotations

from collections.abc import Callable
import json
import os
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .gemini import LLMError, LLMUnavailable


Transport = Callable[[str, dict[str, Any], dict[str, str]], tuple[int, dict[str, Any]]]
Sleep = Callable[[float], None]
Clock = Callable[[], float]


def _convert_schema(gemini_schema: dict[str, Any]) -> dict[str, Any]:
    """Convert the Gemini schema subset used by blast-agent to JSON Schema."""

    converted: dict[str, Any] = {}
    schema_type = gemini_schema.get("type")
    if isinstance(schema_type, str):
        converted["type"] = schema_type.lower()

    properties = gemini_schema.get("properties")
    if isinstance(properties, dict):
        converted["properties"] = {
            name: _convert_schema(value)
            for name, value in properties.items()
            if isinstance(value, dict)
        }

    if "required" in gemini_schema:
        converted["required"] = gemini_schema["required"]

    items = gemini_schema.get("items")
    if isinstance(items, dict):
        converted["items"] = _convert_schema(items)

    if "enum" in gemini_schema:
        converted["enum"] = gemini_schema["enum"]

    if converted.get("type") == "object":
        object_properties = converted.get("properties", {})
        if "required" not in converted:
            converted["required"] = list(object_properties)
        converted["additionalProperties"] = False

    return converted


class AnthropicClient:
    """Call Anthropic's Messages endpoint using only the standard library."""

    endpoint = "https://api.anthropic.com/v1/messages"

    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-4-5",
        max_tokens: int = 8192,
        transport: Transport | None = None,
        sleep: Sleep | None = None,
        min_interval_seconds: float = 1.0,
        clock: Clock | None = None,
    ) -> None:
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds must be non-negative")
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.transport = transport or self._urllib_transport
        self.sleep = sleep or time.sleep
        self.min_interval_seconds = min_interval_seconds
        self.clock = clock or time.monotonic
        self._last_transport_call: float | None = None

    def generate_json(
        self,
        prompt: str,
        response_schema: dict[str, Any],
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Generate and parse one JSON object matching ``response_schema``."""

        del temperature
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {
                "format": {
                    "type": "json_schema",
                    "schema": _convert_schema(response_schema),
                }
            },
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        retry_delays = (5.0, 10.0, 20.0, 40.0)

        for attempt in range(5):
            self._throttle()
            try:
                status, payload = self.transport(self.endpoint, body, headers)
            except LLMError:
                raise
            except Exception as exc:
                raise LLMUnavailable(f"Anthropic transport failed: {exc}") from exc

            if status in {429, 503, 529}:
                if attempt == 4:
                    raise LLMUnavailable(
                        f"Anthropic unavailable after 5 attempts (HTTP {status})"
                    )
                self.sleep(retry_delays[attempt])
                continue

            if status in {401, 403}:
                raise LLMError(
                    f"Anthropic authentication failed (HTTP {status}): "
                    f"{self._error_message(payload)}"
                )
            if status != 200:
                raise LLMError(
                    f"Anthropic HTTP {status}: {self._error_message(payload)}"
                )

            stop_reason = payload.get("stop_reason")
            if stop_reason == "refusal":
                raise LLMError("Anthropic refusal")
            if stop_reason == "max_tokens":
                raise LLMError("Anthropic response contained truncated JSON")

            try:
                content = payload["content"]
                text = next(
                    block["text"]
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
                parsed = json.loads(text)
            except (
                KeyError,
                StopIteration,
                TypeError,
                json.JSONDecodeError,
            ) as exc:
                raise LLMError("Malformed Anthropic response") from exc
            if not isinstance(parsed, dict):
                raise LLMError(
                    "Malformed Anthropic response: expected a JSON object"
                )
            return parsed

        raise AssertionError("retry loop exhausted unexpectedly")

    def _throttle(self) -> None:
        """Space every transport attempt relative to this client's prior call."""

        now = self.clock()
        if self._last_transport_call is not None:
            remaining = self.min_interval_seconds - (
                now - self._last_transport_call
            )
            if remaining > 0:
                self.sleep(remaining)
                now = self.clock()
        self._last_transport_call = now

    @classmethod
    def from_env(cls) -> AnthropicClient:
        """Build a client from the process environment or a local ``.env`` file."""

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        model = os.environ.get("ANTHROPIC_MODEL")
        min_interval = os.environ.get("ANTHROPIC_MIN_INTERVAL")
        dotenv: dict[str, str] = {}
        if not api_key or not model or min_interval is None:
            dotenv = cls._read_dotenv(Path(".env"))
        if not api_key:
            api_key = dotenv.get("ANTHROPIC_API_KEY")
        if not model:
            model = dotenv.get("ANTHROPIC_MODEL")
        if min_interval is None:
            min_interval = dotenv.get("ANTHROPIC_MIN_INTERVAL")
        if not api_key:
            raise LLMUnavailable("ANTHROPIC_API_KEY is not configured")
        try:
            min_interval_seconds = (
                1.0 if min_interval is None else float(min_interval)
            )
        except ValueError as exc:
            raise LLMUnavailable("ANTHROPIC_MIN_INTERVAL must be a number") from exc
        return cls(
            api_key=api_key,
            model=model or "claude-haiku-4-5",
            min_interval_seconds=min_interval_seconds,
        )

    @staticmethod
    def _read_dotenv(path: Path) -> dict[str, str]:
        if not path.is_file():
            return {}
        values: dict[str, str] = {}
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            if key:
                values[key] = value
        return values

    @staticmethod
    def _error_message(payload: dict[str, Any]) -> str:
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
        return "unknown error"

    @staticmethod
    def _urllib_transport(
        url: str, body: dict[str, Any], headers: dict[str, str]
    ) -> tuple[int, dict[str, Any]]:
        request = Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request) as response:
                status = response.status
                raw_payload = response.read()
        except HTTPError as exc:
            status = exc.code
            raw_payload = exc.read()

        try:
            payload = json.loads(raw_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if status != 200:
                return status, {}
            raise LLMError(
                f"Anthropic HTTP {status}: response was not valid JSON"
            ) from exc
        if not isinstance(payload, dict) and status != 200:
            return status, {}
        if not isinstance(payload, dict):
            raise LLMError(
                f"Anthropic HTTP {status}: response was not a JSON object"
            )
        return status, payload


__all__ = ["AnthropicClient", "_convert_schema"]
