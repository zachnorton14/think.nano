#!/usr/bin/env python3
"""
Exercise a deployed (or `beam serve`-previewed) think.nano endpoint.

Run this immediately after the first deploy, before pointing anyone at the URL.
It answers the four questions you cannot answer from the Beam dashboard:

  1. does the container boot and load the checkpoint at all;
  2. does SSE actually stream, or is something buffering the whole response
     (Beam's docs do not commit either way -- see /stream-probe in app.py);
  3. what is the real cold-start time, so the UI copy can quote a true number;
  4. what is time-to-first-token and tokens/sec on the GPU you picked.

    python dev/hosting/smoke_test.py https://think-nano-xxxxxxx-v1.app.beam.cloud

Add --token <BEAM_TOKEN> if you deployed with AUTHORIZED = True.
Only stdlib, so it runs anywhere without installing anything.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

PROMPT = "Describe the wireless telegraph in two sentences."


def request(url, token=None, payload=None, timeout=600):
    headers = {"Accept": "text/event-stream"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.urlopen(
        urllib.request.Request(url, data=data, headers=headers), timeout=timeout
    )


def sse_frames(response):
    """Yield (arrival_time, parsed_json) per SSE frame, as they arrive."""
    buffer = b""
    while True:
        chunk = response.read1(4096) if hasattr(response, "read1") else response.read(1)
        if not chunk:
            return
        now = time.perf_counter()
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            line = line.strip()
            if line.startswith(b"data: "):
                yield now, json.loads(line[6:])


def check_health(base, token):
    print("[1/4] cold start + /health")
    t0 = time.perf_counter()
    try:
        with request(f"{base}/health", token) as res:
            info = json.loads(res.read())
    except urllib.error.HTTPError as exc:
        print(f"      FAIL  HTTP {exc.code}: {exc.read()[:300].decode(errors='replace')}")
        if exc.code in (401, 403):
            print("      hint: the app was deployed with AUTHORIZED = True; pass --token")
        return None
    except Exception as exc:
        print(f"      FAIL  {exc}")
        return None

    wall = time.perf_counter() - t0
    model, runtime = info.get("model", {}), info.get("runtime", {})
    config = model.get("config", {})
    print(f"      PASS  answered in {wall:.1f}s (container reported boot {runtime.get('boot_seconds')}s)")
    print(f"            {runtime.get('gpu')}  {runtime.get('compute_dtype')}  "
          f"{runtime.get('vram_gib')} GiB allocated")
    print(f"            d{config.get('n_layer')} n_embd={config.get('n_embd')} "
          f"ctx={config.get('sequence_len')} step={model.get('step')} "
          f"stored as {model.get('storage_dtype')}")
    if runtime.get("compute_dtype") != "torch.bfloat16":
        print("      WARN  compute dtype is not bfloat16 -- the GPU probably lacks bf16 "
              "tensor cores (T4/V100). Pick A10G, RTX4090, L40S, A100 or H100.")
    if wall < 3:
        print("      NOTE  that was a warm container; restart it to measure a true cold start")
    return info


def check_streaming(base, token):
    print("[2/4] /stream-probe (is SSE buffered?)")
    try:
        with request(f"{base}/stream-probe", token, timeout=60) as res:
            arrivals = [t for t, evt in sse_frames(res) if not evt.get("done")]
    except Exception as exc:
        print(f"      FAIL  {exc}")
        return False

    if len(arrivals) < 2:
        print(f"      FAIL  got {len(arrivals)} frames, expected 6")
        return False
    gaps = [b - a for a, b in zip(arrivals, arrivals[1:])]
    spread = max(arrivals) - min(arrivals)
    print(f"      frames={len(arrivals)} spread={spread:.2f}s "
          f"median gap={sorted(gaps)[len(gaps) // 2]:.2f}s (server sends every 0.50s)")
    if spread < 1.0:
        print("      FAIL  all frames landed at once -- something is buffering the response.")
        print("            Set stream:false in the UI, or ask Beam about SSE passthrough.")
        return False
    print("      PASS  frames arrive incrementally")
    return True


def check_generation(base, token, stream):
    label = "streaming" if stream else "non-streaming"
    print(f"[3/4] /chat/completions ({label})")
    payload = {"messages": [{"role": "user", "content": PROMPT}], "max_tokens": 96, "stream": stream}
    t0 = time.perf_counter()
    try:
        with request(f"{base}/chat/completions", token, payload) as res:
            if not stream:
                text = json.loads(res.read())["content"]
                elapsed = time.perf_counter() - t0
                print(f"      PASS  {len(text)} chars in {elapsed:.1f}s")
                print(f"      ---\n{text.strip()[:400]}\n      ---")
                return True
            first, last, parts = None, None, []
            for arrival, evt in sse_frames(res):
                if evt.get("error"):
                    print(f"      FAIL  server error: {evt['error']}")
                    return False
                if evt.get("done"):
                    break
                if "token" in evt:
                    first = first or arrival
                    last = arrival
                    parts.append(evt["token"])
    except Exception as exc:
        print(f"      FAIL  {exc}")
        return False

    if not parts:
        print("      FAIL  no tokens returned")
        return False
    text = "".join(parts)
    ttft = first - t0
    rate = (len(parts) - 1) / (last - first) if last > first else float("nan")
    print(f"      PASS  {len(parts)} chunks, TTFT {ttft:.2f}s, {rate:.1f} chunks/s")
    print(f"      ---\n{text.strip()[:400]}\n      ---")
    return True


def check_warm(base, token):
    print("[4/4] warm /health (container should still be up)")
    t0 = time.perf_counter()
    try:
        with request(f"{base}/health", token, timeout=60) as res:
            res.read()
    except Exception as exc:
        print(f"      FAIL  {exc}")
        return False
    elapsed = time.perf_counter() - t0
    verdict = "PASS" if elapsed < 3 else "WARN"
    print(f"      {verdict}  {elapsed * 1000:.0f}ms -- keep_warm_seconds is holding the container")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", help="Base URL of the deployment")
    parser.add_argument("--token", default=None, help="Beam auth token (only if AUTHORIZED = True)")
    args = parser.parse_args()
    base = args.url.rstrip("/")

    print(f"target: {base}\n")
    if check_health(base, args.token) is None:
        raise SystemExit(1)
    print()
    streams = check_streaming(base, args.token)
    print()
    ok = check_generation(base, args.token, stream=streams)
    print()
    check_warm(base, args.token)

    print()
    if ok and streams:
        print("All checks passed. Safe to hand out the URL.")
    elif ok:
        print("Generation works but streaming is buffered: ship with stream:false.")
    else:
        print("Generation failed -- check `beam logs` before sending anyone the link.")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
