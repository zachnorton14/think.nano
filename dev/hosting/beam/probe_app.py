"""
The CPU-only dress rehearsal. Deploy this FIRST -- it costs cents, not dollars.

    beam deploy beam_app.py:probe_handler --name think-nano-probe   # from repo root
    python dev/hosting/beam/smoke_test.py <printed-url>

It serves the same ui.html and the same route shapes as app.py, but with a fake
generator instead of a model and no GPU attached. Everything it exercises is
something that can break independently of the weights:

  * `beam config` is set up and the deploy pipeline works;
  * .beamignore is correct -- the sync is seconds, not minutes;
  * the Volume mounts where app.py expects, and the checkpoint is actually in it
    (it lists what it finds, which catches a bad `beam cp` before a GPU does);
  * SSE passes through Beam's proxy unbuffered;
  * AUTHORIZED is what you meant it to be -- open the URL in a private window;
  * the UI's wake-up panel, streaming, error path and fallback all render.

Delete it once app.py is live:  beam deployment delete <id>
"""

import os
import sys

from beam import Image, Volume

# Only this folder is needed: the probe imports config.py but never nanochat.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# The same constants app.py deploys with, so this rehearses the real
# configuration rather than a lookalike. Importing app.py itself would also
# build its @asgi stub in this process, which is worth avoiding.
from config import AUTHORIZED, CONTAINER_ENV, MOUNT_PATH, VOLUME_NAME  # noqa: E402

FAKE_REPLY = (
    "The wireless telegraph transmits messages through the air by means of "
    "electrical waves, requiring neither post nor cable. Its chief service has "
    "been to ships at sea, which may now speak with the shore at great distance."
)


# The @asgi decorator lives in beam_app.py at the repo root (see app.py for
# why); it reads these two and delegates to build_app below.
image = Image(python_version="python3.11").add_python_packages(["fastapi>=0.117.1", "uvicorn>=0.36.0"])
volume = Volume(name=VOLUME_NAME, mount_path=MOUNT_PATH)


def build_app(context):
    import asyncio
    import json
    import pathlib
    import time

    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
    from pydantic import BaseModel
    from typing import List, Optional

    app = FastAPI(title="think.nano probe")
    UI_HTML = (pathlib.Path(__file__).parent / "ui.html").read_text(encoding="utf-8")

    SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}

    def inspect_volume():
        """Report what is actually on the volume, from inside a container.

        This is the check worth having: `beam ls` shows the volume, but only a
        container sees the mount path app.py will really read from.
        """
        checkpoint_dir = os.environ["NANOCHAT_CHECKPOINT_DIR"]
        tokenizer_dir = os.environ["NANOCHAT_TOKENIZER_DIR"]
        report = {"mount_path": MOUNT_PATH, "mounted": os.path.isdir(MOUNT_PATH)}
        for label, path in (("checkpoint", checkpoint_dir), ("tokenizer", tokenizer_dir)):
            if not os.path.isdir(path):
                report[label] = {"path": path, "exists": False}
                continue
            entries = sorted(os.listdir(path))
            report[label] = {
                "path": path,
                "exists": True,
                "files": [
                    {"name": n, "gib": round(os.path.getsize(os.path.join(path, n)) / 1024 ** 3, 3)}
                    for n in entries if os.path.isfile(os.path.join(path, n))
                ],
            }
        models = [f for f in report.get("checkpoint", {}).get("files", []) if f["name"].startswith("model_")]
        metas = [f for f in report.get("checkpoint", {}).get("files", []) if f["name"].startswith("meta_")]
        tokenizers = [f for f in report.get("tokenizer", {}).get("files", []) if f["name"] == "tokenizer.pkl"]
        report["ready_for_app"] = bool(models and metas and tokenizers)
        report["problems"] = [
            msg for msg, ok in (
                (f"no model_*.pt under {checkpoint_dir}", models),
                (f"no meta_*.json under {checkpoint_dir}", metas),
                (f"no tokenizer.pkl under {tokenizer_dir}", tokenizers),
            ) if not ok
        ]
        return report

    class ChatMessage(BaseModel):
        role: str
        content: str

    class ChatRequest(BaseModel):
        messages: List[ChatMessage]
        temperature: Optional[float] = None
        max_tokens: Optional[int] = None
        top_k: Optional[int] = None
        repetition_penalty: Optional[float] = None
        stream: bool = True

    @app.get("/", response_class=HTMLResponse)
    async def root():
        return HTMLResponse(UI_HTML)

    @app.get("/health")
    async def health():
        volume = inspect_volume()
        return {
            "status": "ok",
            "ready": True,
            "probe": True,  # nothing here is a real model
            "volume": volume,
            "model": {"step": 0, "config": {}, "val_bpb": None, "storage_dtype": "probe"},
            "runtime": {"gpu": "none (probe)", "device": "cpu", "compute_dtype": "n/a",
                        "vram_gib": 0, "boot_seconds": 0},
        }

    @app.get("/volume")
    async def volume():
        return JSONResponse(inspect_volume())

    @app.get("/stream-probe")
    async def stream_probe():
        async def gen():
            for i in range(6):
                yield f"data: {json.dumps({'i': i, 't': round(time.time(), 3)})}\n\n"
                await asyncio.sleep(0.5)
            yield f"data: {json.dumps({'done': True})}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)

    @app.post("/chat/completions")
    async def chat_completions(request: ChatRequest):
        # Word-at-a-time at a plausible decode rate, so the UI is exercised the
        # way the real model will exercise it.
        words = FAKE_REPLY.split(" ")

        if not request.stream:
            await asyncio.sleep(0.04 * len(words))
            return JSONResponse({"content": FAKE_REPLY})

        async def sse():
            for i, word in enumerate(words):
                yield f"data: {json.dumps({'token': ('' if i == 0 else ' ') + word})}\n\n"
                await asyncio.sleep(0.04)
            yield f"data: {json.dumps({'done': True})}\n\n"

        return StreamingResponse(sse(), media_type="text/event-stream", headers=SSE_HEADERS)

    return app
