#!/usr/bin/env python3
"""
Preview a chat UI locally, with no GPU, no weights and no deployment.

Serves the HTML file at / and fakes the two endpoints it talks to, so the whole
page can be reviewed -- wake panel, streaming, the details panel, the sampling
controls, error states -- before anything is deployed.

    python dev/hosting/beam/preview_ui.py                 # ui_updated.html on :8080
    python dev/hosting/beam/preview_ui.py --wake 8        # fake an 8s cold start
    python dev/hosting/beam/preview_ui.py --file ui.html  # compare against the old UI
    python dev/hosting/beam/preview_ui.py --fail-stream   # rehearse buffered SSE

The /health payload mirrors what app.py really returns for the d32, so the
details panel renders the same fields it will in production. Stdlib only.
"""

import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPLY = (
    "The wireless telegraph is an apparatus for the sending of messages through "
    "the air by means of electrical waves, requiring neither post nor cable nor "
    "any wire whatever between the two stations. Its chief service has been to "
    "ships at sea, which may now speak with the shore across great distances, "
    "and summon help in an hour of peril; the loss of the Titanic, and the "
    "saving of those who were saved, turned upon it entirely."
)

HEALTH = {
    "status": "ok",
    "ready": True,
    "busy": False,
    "model": {
        "step": 9600,
        "config": {
            "sequence_len": 4096, "vocab_size": 32768, "n_layer": 32,
            "n_head": 16, "n_kv_head": 16, "n_embd": 2048,
            "window_pattern": "SSSL",
        },
        "val_bpb": 0.8543,
        "storage_dtype": "bfloat16",
    },
    "runtime": {
        "gpu": "NVIDIA A10G", "device": "cuda",
        "compute_dtype": "torch.bfloat16", "vram_gib": 5.25,
        "boot_seconds": 24.3,
    },
    "defaults": {"temperature": 0.8, "top_k": 50, "max_tokens": 512,
                 "repetition_penalty": 1.0},
    "preview": True,
}

ARGS = None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):
        print(f"  {self.command} {self.path} -> {fmt % a}")

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send(self, code, body, ctype):
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self._cors()
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            with open(ARGS.file, "r", encoding="utf-8") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif path == "/health":
            # The wake delay lives here because the real cold start is exactly
            # this: /health does not answer until the container is up.
            if ARGS.wake:
                time.sleep(ARGS.wake)
            payload = dict(HEALTH)
            payload["runtime"] = dict(HEALTH["runtime"],
                                      boot_seconds=ARGS.wake or HEALTH["runtime"]["boot_seconds"])
            self._send(200, json.dumps(payload), "application/json")
        elif path == "/stream-probe":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self._cors()
            self.end_headers()
            for i in range(6):
                self.wfile.write(f"data: {json.dumps({'i': i, 't': time.time()})}\n\n".encode())
                self.wfile.flush()
                time.sleep(0.5)
            self.wfile.write(b'data: {"done": true}\n\n')
            self.wfile.flush()
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        if self.path.split("?")[0] != "/chat/completions":
            self._send(404, "not found", "text/plain")
            return

        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length) or b"{}")
        sampling = {k: request.get(k) for k in ("temperature", "top_k", "max_tokens")}
        print(f"    sampling: {sampling}")

        if not request.get("stream", True):
            time.sleep(1.0)
            self._send(200, json.dumps({"content": REPLY}), "application/json")
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self._cors()
        self.end_headers()

        if ARGS.fail_stream:
            # What a buffering proxy looks like: zero token frames, then done.
            # The UI should notice and silently retry with stream:false.
            time.sleep(1.5)
            self.wfile.write(b'data: {"done": true}\n\n')
            self.wfile.flush()
            return

        # ~28 tokens/sec, which is roughly what a d32 does on an A10G.
        for i, word in enumerate(REPLY.split(" ")):
            chunk = ("" if i == 0 else " ") + word
            self.wfile.write(f"data: {json.dumps({'token': chunk})}\n\n".encode())
            self.wfile.flush()
            time.sleep(0.036)
        self.wfile.write(b'data: {"done": true}\n\n')
        self.wfile.flush()


def main():
    global ARGS
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", default=os.path.join(here, "ui_updated.html"),
                        help="HTML file to serve at /")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--wake", type=float, default=0,
                        help="Seconds to stall /health, to see the wake panel")
    parser.add_argument("--fail-stream", action="store_true",
                        help="Send no token frames, to rehearse the buffered-SSE fallback")
    ARGS = parser.parse_args()

    if not os.path.exists(ARGS.file):
        raise SystemExit(f"No such file: {ARGS.file}")

    print(f"serving {os.path.basename(ARGS.file)} at http://localhost:{ARGS.port}")
    if ARGS.wake:
        print(f"  /health will stall {ARGS.wake}s, so the wake panel shows")
    if ARGS.fail_stream:
        print("  streaming returns no tokens, so the non-streaming fallback fires")
    print("  Ctrl-C to stop\n")
    try:
        ThreadingHTTPServer(("127.0.0.1", ARGS.port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
