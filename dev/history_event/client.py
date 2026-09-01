"""Minimal OpenAI-compatible client with complete per-call metadata."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .config import OPENCODE_ENDPOINT


class APIError(RuntimeError):
    error_kind = "api"


class RateLimitError(APIError):
    error_kind = "rate_limit"


class RegionOptInError(APIError):
    error_kind = "region"


class TransportError(APIError):
    error_kind = "transport"


def load_api_key() -> str:
    try:
        from dotenv import load_dotenv
    except ImportError as exc:  # pragma: no cover - dependency error
        raise RuntimeError("python-dotenv is required; run `uv sync --group dev`") from exc
    load_dotenv()
    key = os.getenv("OPENCODE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENCODE_API_KEY is missing from .env")
    return key


def parse_json_content(content: str) -> Any:
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"model response was not valid JSON: {exc}") from exc


class OpenCodeClient:
    def __init__(self, api_key: str | None = None, timeout: float = 180.0):
        self.api_key = api_key or load_api_key()
        self.timeout = timeout

    def chat_json(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_tokens: int,
        endpoint: str = OPENCODE_ENDPOINT,
    ) -> tuple[Any, dict]:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "OpenAI/Python history-event-reconstruction",
            },
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:2000]
            if exc.code == 429:
                raise RateLimitError(f"HTTP 429 from {endpoint}: {detail}") from exc
            if exc.code == 403:
                raise RegionOptInError(f"HTTP 403 from {endpoint}: {detail}") from exc
            raise APIError(f"HTTP {exc.code} from {endpoint}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportError(f"request to {endpoint} failed: {exc}") from exc
        latency = time.monotonic() - started
        try:
            decoded = json.loads(body)
            content = decoded["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise APIError(f"invalid chat response from {endpoint}: {body[:1000]}") from exc
        if not isinstance(content, str):
            raise APIError("chat response content was not a string")
        usage = decoded.get("usage") or {}
        prompt_details = usage.get("prompt_tokens_details") or {}
        metadata = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "endpoint": endpoint,
            "model": model,
            "latency_seconds": round(latency, 6),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "cached_tokens": prompt_details.get("cached_tokens"),
            "reported_cost": usage.get("cost", decoded.get("cost")),
            "usage": usage,
        }
        try:
            parsed = parse_json_content(content)
        except ValueError as exc:
            # Preserve billable usage and latency even when only the model's content is malformed.
            setattr(exc, "call_metadata", metadata)
            raise
        return parsed, metadata
