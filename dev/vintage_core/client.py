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
    return (f"calls={USAGE['calls']} in={USAGE['prompt']} (cached={USAGE['cached']}) "
            f"out={USAGE['completion']} cost=${USAGE['cost_milli']/1000:.4f}")


def _api_key():
    key = os.environ.get(config.LLM_API_KEY_ENV)
    if not key:
        raise RuntimeError(f"{config.LLM_API_KEY_ENV} not set (in .env or environment)")
    return key


def _backoff(attempt):
    # exponential with jitter, capped at 30s — long enough to ride out throttle windows
    time.sleep(min(2 ** attempt + random.random(), 30))


def chat(messages, model, base_url, temperature=0.0, max_tokens=512, retries=7):
    """One chat completion → assistant text. Resilient to rate-limit/throttle (429s,
    and 200-responses carrying an error body) so transient throttling does not become a
    silent default-to-keep."""
    url = base_url.rstrip("/") + "/chat/completions"
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
                    last = str(data.get("error", data))[:200]
                    _backoff(attempt)
                    continue
                u = data.get("usage", {}) or {}
                USAGE["calls"] += 1
                USAGE["prompt"] += u.get("prompt_tokens", 0)
                USAGE["completion"] += u.get("completion_tokens", 0)
                USAGE["cached"] += (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
                try:
                    USAGE["cost_milli"] += int(round(float(data.get("cost", 0) or 0) * 1000))
                except (TypeError, ValueError):
                    pass
                return data["choices"][0]["message"]["content"]
            last = f"HTTP {r.status_code}: {r.text[:160]}"
            if r.status_code in (429, 500, 502, 503, 529):
                _backoff(attempt)
                continue
            raise RuntimeError(last)
        except requests.RequestException as e:
            last = str(e)
            _backoff(attempt)
    raise RuntimeError(f"chat failed after {retries} retries: {last}")


_OBJ = re.compile(r"(\[.*\]|\{.*\})", re.S)  # first JSON array or object


def chat_json(messages, model, base_url, **kw):
    """chat() but parse the assistant content as JSON (tolerates ``` fences and
    surrounding prose / reasoning by extracting the first {...} object)."""
    txt = _FENCE.sub("", chat(messages, model, base_url, **kw).strip()).strip()
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        m = _OBJ.search(txt)
        if m:
            return json.loads(m.group(1))
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
