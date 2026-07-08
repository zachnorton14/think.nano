"""Minimal provider-agnostic OpenAI-compatible client (mirrors dev/gen_synthetic_data.py).

Clean direct API calls — NO agent harness — so our prompts fully determine behavior.
Endpoint/key/model come from config (default: OpenCode Zen). Key is read from the env
var named by config.LLM_API_KEY_ENV (loaded from .env).
"""
import os
import re
import json
import time
import random
from collections import Counter

import requests
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config

load_dotenv()

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.S)

# Process-wide token accounting (for cost estimation + monitoring).
USAGE = Counter()


def usage_summary():
    fb = f" fallback={USAGE['fallback']}" if USAGE.get("fallback") else ""
    return (f"calls={USAGE['calls']}{fb} in={USAGE['prompt']} (cached={USAGE['cached']}) "
            f"out={USAGE['completion']} cost=${USAGE['cost_milli']/1000:.4f}")


def usage_snapshot():
    """Return a copy of cumulative provider usage counters."""
    return Counter(USAGE)


def _api_key():
    key = os.environ.get(config.LLM_API_KEY_ENV)
    if not key:
        raise RuntimeError(f"{config.LLM_API_KEY_ENV} not set (in .env or environment)")
    return key


# --- per-endpoint circuit breaker: once an endpoint is rate-limited, skip it for a
# cooldown instead of paying a multi-retry backoff tax on every subsequent call. This is
# the fix for the 30h run: ~4700 fallback calls each wasted ~90s retrying a dead free tier.
_COOLDOWN = {}   # base_url -> epoch until which to skip the endpoint


def _cooling(base_url):
    return time.time() < _COOLDOWN.get(base_url, 0)


def _trip(base_url, seconds):
    _COOLDOWN[base_url] = max(_COOLDOWN.get(base_url, 0), time.time() + seconds)
    USAGE["tripped"] += 1


def cooldown_wait():
    """Seconds until the soonest cooling endpoint frees up (0 if none)."""
    if not _COOLDOWN:
        return 0.0
    return max(0.0, min(_COOLDOWN.values()) - time.time())


class RateLimited(RuntimeError):
    """Endpoint is throttled/cooling — caller should fall back immediately."""


class Truncated(RuntimeError):
    """The provider stopped generation because the completion token limit was reached."""

    def __init__(self, partial_content, max_tokens):
        self.partial_content = partial_content or ""
        self.max_tokens = max_tokens
        super().__init__(f"completion truncated at max_tokens={max_tokens}")


def chat(messages, model, base_url, temperature=0.0, max_tokens=512, retries=3):
    """One chat completion → assistant text.

    Rate-limit handling: on a 429 (or 200-with-error-body), trip a per-endpoint cooldown
    (honoring Retry-After) and raise RateLimited IMMEDIATELY so the caller's fallback
    engages with no wasted backoff. While an endpoint is cooling, calls to it fail fast.
    Only genuine transient errors (5xx / network) get a short bounded backoff+retry.
    """
    if _cooling(base_url):
        raise RateLimited(f"{base_url} cooling down")
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    headers = {"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"}
    body = {"model": model, "messages": messages, "temperature": temperature,
            "max_tokens": max_tokens}
    last = None
    for attempt in range(retries):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=120)
            if r.status_code == 200:
                data = r.json()
                if "choices" not in data:                 # 200 with an error body (rate/credits)
                    _trip(base_url, 60)
                    raise RateLimited(str(data.get("error", data))[:160])
                choice = data["choices"][0]
                u = data.get("usage", {}) or {}
                USAGE["calls"] += 1
                USAGE["prompt"] += u.get("prompt_tokens", 0)
                USAGE["completion"] += u.get("completion_tokens", 0)
                USAGE["cached"] += (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
                try:
                    USAGE["cost_milli"] += int(round(float(data.get("cost", 0) or 0) * 1000))
                except (TypeError, ValueError):
                    pass
                content = (choice.get("message") or {}).get("content") or ""
                if choice.get("finish_reason") == "length":
                    raise Truncated(content, max_tokens)
                return content
            if r.status_code == 429:                       # throttled: cool down + fail fast
                ra = r.headers.get("Retry-After")
                _trip(base_url, int(ra) if (ra and ra.isdigit()) else 60)
                raise RateLimited(f"429 {base_url}")
            last = f"HTTP {r.status_code}: {r.text[:160]}"
            if r.status_code in (500, 502, 503, 529):      # transient: short bounded retry
                time.sleep(min(2 ** attempt + random.random(), 8))
                continue
            raise RuntimeError(last)
        except requests.RequestException as e:
            last = str(e)
            time.sleep(min(2 ** attempt + random.random(), 8))
    raise RuntimeError(f"chat failed after {retries} retries: {last}")


_OBJ_START = re.compile(r"[\[{]")


def chat_json(messages, model, base_url, **kw):
    """chat() but parse the assistant content as JSON (tolerates ``` fences and
    surrounding prose / reasoning by extracting the first {...} object)."""
    txt = _FENCE.sub("", chat(messages, model, base_url, **kw).strip()).strip()
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for m in _OBJ_START.finditer(txt):
            try:
                obj, _ = decoder.raw_decode(txt[m.start():])
                return obj
            except json.JSONDecodeError:
                continue
        raise ValueError(f"no JSON in response: {txt[:120]!r}")


def map_concurrent(fn, items, workers=8, on_error=None):
    """Run fn(item)->result over items concurrently, preserving input order."""
    results = [None] * len(items)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        fut = {ex.submit(fn, it): i for i, it in enumerate(items)}
        for f in as_completed(fut):
            i = fut[f]
            try:
                results[i] = f.result()
            except Exception as e:  # noqa: BLE001
                results[i] = on_error(items[i], e) if on_error else {"error": str(e)}
    return results
