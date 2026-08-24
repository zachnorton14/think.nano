#!/usr/bin/env python3
"""
A/B the prompt-side hot fixes against a live endpoint, without deploying.

The model drops to base-model behaviour on inputs the SFT never covered: a bare
"Hello", or any prompt with no closing punctuation. Two candidate fixes exist,
and both are *client*-side reproducible -- the API already accepts an assistant
turn in the history, so the priming exchange can be sent as ordinary messages.
That means this script measures both fixes against whatever is deployed right
now, before committing a deploy to either.

    python dev/hosting/beam/prompt_ab.py https://bartholomew-iii-<id>.app.beam.cloud

Variants per prompt:
  bare      what the UI sends today -- the failing baseline
  primed    DEFAULT_PRIMING_TURNS prepended, i.e. NANOCHAT_PRIMING_TURNS=default
  repaired  a period appended,               i.e. NANOCHAT_FIX_PUNCTUATION=1
  both      both at once

The primer and the punctuation rule are imported from nanochat/prompt_shaping.py,
so what this rehearses is exactly what the server would render, not a lookalike.

Add --token <BEAM_TOKEN> if you deployed with AUTHORIZED = True.
Only stdlib plus nanochat/prompt_shaping.py, so it runs anywhere without installing.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
from nanochat.prompt_shaping import DEFAULT_PRIMING_TURNS, repair_user_text

# The inputs that reportedly collapse: a greeting, an unpunctuated question, the
# same question punctuated (the control -- this one is expected to work), and a
# conversational opener with no question at all.
PROMPTS = [
    "Hello",
    "How are you doing",
    "How are you doing?",
    "tell me about the wireless telegraph",
]

VARIANTS = ("bare", "primed", "repaired", "both")


def build_messages(prompt, variant):
    content = repair_user_text(prompt) if variant in ("repaired", "both") else prompt
    prelude = list(DEFAULT_PRIMING_TURNS) if variant in ("primed", "both") else []
    return prelude + [{"role": "user", "content": content}]


def complete(base, messages, token, temperature, max_tokens, seed_note=""):
    """One non-streaming completion. Returns (text, seconds)."""
    payload = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {token}"} if token else {})},
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(request, timeout=600) as response:
        body = json.loads(response.read())
    return body.get("content", ""), time.perf_counter() - t0


def verdict(text, max_tokens):
    """A crude but honest signal, so runs are comparable without reading each one.

    Collapse looks like: long, and running out of tokens mid-sentence. An
    SFT-shaped answer stops on its own, which means it ends in punctuation well
    inside the cap. Roughly 4 characters per token.
    """
    stripped = text.strip()
    if not stripped:
        return "EMPTY"
    ran_out = len(stripped) > 3.5 * max_tokens
    stopped_cleanly = stripped[-1] in '.?!\u2026"\''
    if ran_out and not stopped_cleanly:
        return "RAN ON"      # hit the cap mid-sentence: base-model behaviour
    if not stopped_cleanly:
        return "NO STOP"     # ended without punctuation
    return "clean"


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", help="Base URL of the deployment")
    parser.add_argument("--token", default=None, help="Beam auth token (only if AUTHORIZED = True)")
    parser.add_argument("--variants", default=",".join(VARIANTS),
                        help=f"Comma-separated subset of: {', '.join(VARIANTS)}")
    parser.add_argument("--prompt", action="append", dest="prompts",
                        help="Override the built-in prompts (repeatable)")
    parser.add_argument("--repeats", type=int, default=1,
                        help="Samples per prompt/variant. Sampling is stochastic; "
                             "one draw of one prompt proves very little")
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--max-tokens", type=int, default=200,
                        help="Collapse is visible well inside 200 tokens, and short "
                             "generations keep the sweep to a few minutes")
    parser.add_argument("--full", action="store_true", help="Print whole responses, not the first line")
    args = parser.parse_args()

    base = args.url.rstrip("/")
    prompts = args.prompts or PROMPTS
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    unknown = set(variants) - set(VARIANTS)
    if unknown:
        parser.error(f"unknown variant(s): {', '.join(sorted(unknown))}")

    try:
        with urllib.request.urlopen(f"{base}/health", timeout=600) as response:
            health = json.loads(response.read())
    except urllib.error.URLError as exc:
        print(f"cannot reach {base}/health: {exc}")
        return 1
    print(f"model step {health['model']['step']} on {health['runtime']['gpu']}")
    print(f"server-side fixes already live: {health.get('prompt_fixes', 'unreported (pre-hotfix deploy)')}")
    print("Those apply on top of whatever this script sends, so A/B against a "
          "deploy with both switched off.\n")

    tally = {v: {} for v in variants}
    for prompt in prompts:
        print("=" * 78)
        print(f"PROMPT: {prompt!r}")
        print("=" * 78)
        for variant in variants:
            messages = build_messages(prompt, variant)
            for run in range(args.repeats):
                text, seconds = complete(base, messages, args.token, args.temperature, args.max_tokens)
                mark = verdict(text, args.max_tokens)
                tally[variant][mark] = tally[variant].get(mark, 0) + 1
                shown = text.strip() if args.full else text.strip().split("\n")[0][:160]
                print(f"\n  [{variant:<10}] {mark:<7} {len(text):>4} chars  {seconds:5.1f}s")
                print(f"    {shown}")
        print()

    print("=" * 78)
    print("SUMMARY  (clean = stopped on its own; RAN ON = base-model collapse)")
    print("=" * 78)
    for variant in variants:
        counts = ", ".join(f"{k}={v}" for k, v in sorted(tally[variant].items()))
        print(f"  {variant:<10} {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
