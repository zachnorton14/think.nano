"""Small OpenAI-compatible HTTP client with per-call audit metadata."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .config import CHAT_ENDPOINT, RESPONSES_ENDPOINT


class APIError(RuntimeError):
    pass


class FreeUsageLimitError(APIError):
    """OpenCode's free-model allowance is exhausted and should not be retried in a burst."""


class RateLimitError(APIError):
    """The active route is rate limited and should be resumed at lower concurrency."""


class RegionOptInError(APIError):
    """The requested Go model requires an explicit workspace region opt-in."""


def load_api_key() -> str:
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise RuntimeError("python-dotenv is required; run `uv sync --group dev`") from exc
    load_dotenv()
    api_key = os.getenv("OPENCODE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENCODE_API_KEY is missing from .env")
    return api_key


def parse_json_content(content: str) -> Any:
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"model response was not valid JSON: {exc}") from exc


def _usage_metadata(response: dict) -> dict:
    usage = response.get("usage") or {}
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    return {
        "usage": usage,
        "prompt_tokens": usage.get("prompt_tokens", usage.get("input_tokens")),
        "completion_tokens": usage.get("completion_tokens", usage.get("output_tokens")),
        "cached_tokens": details.get("cached_tokens"),
        "reported_cost": usage.get("cost", response.get("cost")),
    }


class OpenCodeClient:
    def __init__(self, api_key: str | None = None, timeout: float = 180.0):
        self.api_key = api_key or load_api_key()
        self.timeout = timeout

    def _post(self, endpoint: str, payload: dict) -> tuple[dict, dict]:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=raw,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                # Cloudflare rejects Python urllib's default signature on the Zen endpoint.
                # Match the conventional user agent used by OpenAI-compatible SDK clients.
                "User-Agent": "OpenAI/Python vintage-gsm8k",
            },
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            try:
                error_type = (json.loads(detail).get("error") or {}).get("type")
            except (AttributeError, json.JSONDecodeError):
                error_type = None
            if exc.code == 429 and error_type == "FreeUsageLimitError":
                raise FreeUsageLimitError(f"HTTP {exc.code} from {endpoint}: {detail}") from exc
            if exc.code == 429:
                raise RateLimitError(f"HTTP {exc.code} from {endpoint}: {detail}") from exc
            if exc.code == 403 and error_type == "RegionError":
                raise RegionOptInError(f"HTTP {exc.code} from {endpoint}: {detail}") from exc
            raise APIError(f"HTTP {exc.code} from {endpoint}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise APIError(f"request to {endpoint} failed: {exc}") from exc
        latency = time.monotonic() - started
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError as exc:
            raise APIError(f"non-JSON response from {endpoint}: {body[:500]}") from exc
        metadata = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "endpoint": endpoint,
            "model": payload.get("model"),
            "latency_seconds": round(latency, 6),
            **_usage_metadata(decoded),
        }
        return decoded, metadata

    def chat_json(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float = 0.0,
        endpoint: str = CHAT_ENDPOINT,
    ) -> tuple[Any, dict]:
        response, metadata = self._post(
            endpoint,
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise APIError(f"chat response lacked choices[0].message.content: {response!r}") from exc
        if not isinstance(content, str):
            raise APIError("chat response content was not a string")
        return parse_json_content(content), metadata

    def responses_json(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_output_tokens: int,
    ) -> tuple[Any, dict]:
        response, metadata = self._post(
            RESPONSES_ENDPOINT,
            {
                "model": model,
                "instructions": system,
                "input": user,
                "max_output_tokens": max_output_tokens,
            },
        )
        content = response.get("output_text")
        if not isinstance(content, str):
            chunks = []
            for item in response.get("output", []):
                for part in item.get("content", []):
                    text = part.get("text")
                    if isinstance(text, str):
                        chunks.append(text)
            content = "".join(chunks)
        if not content:
            raise APIError(f"responses result lacked output text: {response!r}")
        return parse_json_content(content), metadata
