"""Minimal provider-agnostic OpenAI-compatible client (mirrors dev/gen_synthetic_data.py).

Clean direct API calls — NO agent harness — so our prompts fully determine behavior.
Endpoint/key/model come from config (default: OpenCode Zen). Key is read from the env
var named by config.LLM_API_KEY_ENV (loaded from .env).
"""
import os
import re
import json
import time

import requests
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config

load_dotenv()

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.S)


def _api_key():
    key = os.environ.get(config.LLM_API_KEY_ENV)
    if not key:
        raise RuntimeError(f"{config.LLM_API_KEY_ENV} not set (in .env or environment)")
    return key


def chat(messages, model, temperature=0.0, max_tokens=512, retries=4):
    """One chat completion → assistant text. Retries on transient errors."""
    url = config.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"}
    body = {"model": model, "messages": messages, "temperature": temperature,
            "max_tokens": max_tokens}
    last = None
    for attempt in range(retries):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=90)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            # 429/5xx are worth backing off (rate limits on OpenCode's 5-hour windows)
            if r.status_code in (429, 500, 502, 503, 529):
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(last)
        except requests.RequestException as e:
            last = str(e)
            time.sleep(2 ** attempt)
    raise RuntimeError(f"chat failed after {retries} retries: {last}")


def chat_json(messages, model, **kw):
    """chat() but parse the assistant content as JSON (tolerates ``` fences)."""
    txt = chat(messages, model, **kw).strip()
    txt = _FENCE.sub("", txt).strip()
    return json.loads(txt)


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
