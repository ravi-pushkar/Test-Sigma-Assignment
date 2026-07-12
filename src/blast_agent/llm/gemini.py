"""Small, dependency-free client for Gemini structured generation."""

from __future__ import annotations

from collections.abc import Callable
import json
import os
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


Transport = Callable[[str, dict[str, Any], dict[str, str]], tuple[int, dict[str, Any]]]
Sleep = Callable[[float], None]
Clock = Callable[[], float]


class LLMError(RuntimeError):
    """The language-model service returned an invalid or unsuccessful response."""


class LLMUnavailable(LLMError):
    """The language-model service cannot currently serve the request."""


class GeminiClient:
    """Call Gemini's JSON generation endpoint using only the standard library."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-flash-latest",
        transport: Transport | None = None,
        sleep: Sleep | None = None,
        min_interval_seconds: float = 10.0,
        clock: Clock | None = None,
    ) -> None:
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds must be non-negative")
        self.api_key = api_key
        self.model = model
        self.transport = transport or self._urllib_transport
        self.sleep = sleep or time.sleep
        self.min_interval_seconds = min_interval_seconds
        self.clock = clock or time.monotonic
        self._last_transport_call: float | None = None

    @property
    def endpoint(self) -> str:
        return (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )

    def generate_json(
        self,
        prompt: str,
        response_schema: dict[str, Any],
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Generate and parse one JSON object matching ``response_schema``."""

        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": response_schema,
                "temperature": temperature,
            },
        }
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        for attempt in range(5):
            self._throttle()
            try:
                status, payload = self.transport(self.endpoint, body, headers)
            except LLMError:
                raise
            except Exception as exc:
                raise LLMUnavailable(f"Gemini transport failed: {exc}") from exc

            if status in {429, 503}:
                if attempt == 4:
                    raise LLMUnavailable(
                        f"Gemini unavailable after 5 attempts (HTTP {status})"
                    )
                self.sleep(float(15 * (attempt + 1)))
                continue

            if status != 200:
                raise LLMError(f"Gemini HTTP {status}: {self._error_message(payload)}")

            try:
                text = payload["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(text)
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raise LLMError("Malformed Gemini response") from exc
            if not isinstance(parsed, dict):
                raise LLMError("Malformed Gemini response: expected a JSON object")
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
    def from_env(cls) -> GeminiClient:
        """Build a client from the process environment or a local ``.env`` file."""

        api_key = os.environ.get("GEMINI_API_KEY")
        model = os.environ.get("GEMINI_MODEL")
        min_interval = os.environ.get("GEMINI_MIN_INTERVAL")
        dotenv: dict[str, str] = {}
        if not api_key or not model or min_interval is None:
            dotenv = cls._read_dotenv(Path(".env"))
        if not api_key:
            api_key = dotenv.get("GEMINI_API_KEY")
        if not model:
            model = dotenv.get("GEMINI_MODEL")
        if min_interval is None:
            min_interval = dotenv.get("GEMINI_MIN_INTERVAL")
        if not api_key:
            raise LLMUnavailable("GEMINI_API_KEY is not configured")
        try:
            min_interval_seconds = (
                10.0 if min_interval is None else float(min_interval)
            )
        except ValueError as exc:
            raise LLMUnavailable("GEMINI_MIN_INTERVAL must be a number") from exc
        return cls(
            api_key=api_key,
            model=model or "gemini-flash-latest",
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
        if isinstance(payload, dict) and isinstance(payload.get("message"), str):
            return payload["message"]
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
            raise LLMError(f"Gemini HTTP {status}: response was not valid JSON") from exc
        if not isinstance(payload, dict) and status != 200:
            return status, {}
        if not isinstance(payload, dict):
            raise LLMError(f"Gemini HTTP {status}: response was not a JSON object")
        return status, payload


__all__ = ["GeminiClient", "LLMError", "LLMUnavailable"]
