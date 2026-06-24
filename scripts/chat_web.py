#!/usr/bin/env python3
"""
Unified web chat server - serves both UI and API from a single FastAPI instance.

Uses data parallelism to distribute requests across multiple GPUs. Each GPU loads
a full copy of the model, and incoming requests are distributed to available workers.

Launch examples:

- single available GPU (default)
python -m scripts.chat_web

- 4 GPUs
python -m scripts.chat_web --num-gpus 4

- in-process from a notebook or script:
from scripts.chat_web import start_in_thread
start_in_thread(checkpoint_dir="...", tokenizer_dir="...", source="sft")

Endpoints:
  GET  /           - Chat UI
  POST /chat/completions - Chat API (streaming only)
  GET  /health     - Health check with worker pool status
  GET  /stats      - Worker pool statistics and GPU utilization

Abuse Prevention:
  - Maximum 500 messages per request
  - Maximum 8000 characters per message
  - Maximum 32000 characters total conversation length
  - Temperature clamped to 0.0-2.0
  - Top-k clamped to 0-200 (0 disables top-k filtering, using full vocabulary)
  - Max tokens clamped to 1-4096
"""

import json
import os
import torch
import asyncio
import logging
import random
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import List, Optional, AsyncGenerator

# Abuse prevention limits
MAX_MESSAGES_PER_REQUEST = 500
MAX_MESSAGE_LENGTH = 8000
MAX_TOTAL_CONVERSATION_LENGTH = 32000
MIN_TEMPERATURE = 0.0
MAX_TEMPERATURE = 2.0
MIN_TOP_K = 0
MAX_TOP_K = 200
MIN_MAX_TOKENS = 1
MAX_MAX_TOKENS = 4096

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


@dataclass
class ServerConfig:
    source: str = "sft"
    checkpoint_dir: Optional[str] = None
    tokenizer_dir: Optional[str] = None
    step: Optional[int] = None
    model_tag: Optional[str] = None
    num_gpus: int = 1
    temperature: float = 0.8
    top_k: int = 50
    max_tokens: int = 512
    host: str = "0.0.0.0"
    port: int = 8000
    device_type: str = ""


@dataclass
class Worker:
    gpu_id: int
    device: torch.device
    engine: Engine
    tokenizer: object


class WorkerPool:
    def __init__(self, num_gpus: Optional[int], device_type: str):
        if num_gpus is None:
            num_gpus = torch.cuda.device_count() if device_type == "cuda" else 1
        self.num_gpus = num_gpus
        self.device_type = device_type
        self.workers: List[Worker] = []
        self.available_workers: asyncio.Queue = asyncio.Queue()

    async def initialize(self, cfg: ServerConfig):
        print(f"Initializing worker pool with {self.num_gpus} GPU(s)...")
        if self.num_gpus > 1:
            assert self.device_type == "cuda", "Multiple workers require CUDA."

        for gpu_id in range(self.num_gpus):
            if self.device_type == "cuda":
                device = torch.device(f"cuda:{gpu_id}")
                print(f"Loading model on GPU {gpu_id}...")
            else:
                device = torch.device(self.device_type)
                print(f"Loading model on {self.device_type}...")

            if cfg.checkpoint_dir:
                from nanochat.checkpoint_manager import load_model_from_checkpoint_dir
                model, tokenizer, _ = load_model_from_checkpoint_dir(
                    cfg.checkpoint_dir, device, phase="eval",
                    step=cfg.step, tokenizer_dir=cfg.tokenizer_dir,
                )
            else:
                from nanochat.checkpoint_manager import load_model
                model, tokenizer, _ = load_model(
                    cfg.source, device, phase="eval",
                    model_tag=cfg.model_tag, step=cfg.step,
                )
            from nanochat.engine import Engine
            engine = Engine(model, tokenizer)
            worker = Worker(gpu_id=gpu_id, device=device, engine=engine, tokenizer=tokenizer)
            self.workers.append(worker)
            await self.available_workers.put(worker)

        print(f"All {self.num_gpus} worker(s) initialized!")

    async def acquire_worker(self) -> Worker:
        return await self.available_workers.get()

    async def release_worker(self, worker: Worker):
        await self.available_workers.put(worker)


class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_k: Optional[int] = None


def validate_chat_request(request: ChatRequest):
    if len(request.messages) == 0:
        raise HTTPException(status_code=400, detail="At least one message is required")
    if len(request.messages) > MAX_MESSAGES_PER_REQUEST:
        raise HTTPException(status_code=400, detail=f"Too many messages (max {MAX_MESSAGES_PER_REQUEST})")
    total_length = 0
    for i, message in enumerate(request.messages):
        if not message.content:
            raise HTTPException(status_code=400, detail=f"Message {i} has empty content")
        if len(message.content) > MAX_MESSAGE_LENGTH:
            raise HTTPException(status_code=400, detail=f"Message {i} too long (max {MAX_MESSAGE_LENGTH} chars)")
        total_length += len(message.content)
    if total_length > MAX_TOTAL_CONVERSATION_LENGTH:
        raise HTTPException(status_code=400, detail=f"Conversation too long (max {MAX_TOTAL_CONVERSATION_LENGTH} chars)")
    for i, message in enumerate(request.messages):
        if message.role not in ["user", "assistant"]:
            raise HTTPException(status_code=400, detail=f"Message {i} has invalid role '{message.role}'")
    if request.temperature is not None and not (MIN_TEMPERATURE <= request.temperature <= MAX_TEMPERATURE):
        raise HTTPException(status_code=400, detail=f"Temperature must be {MIN_TEMPERATURE}–{MAX_TEMPERATURE}")
    if request.top_k is not None and not (MIN_TOP_K <= request.top_k <= MAX_TOP_K):
        raise HTTPException(status_code=400, detail=f"top_k must be {MIN_TOP_K}–{MAX_TOP_K}")
    if request.max_tokens is not None and not (MIN_MAX_TOKENS <= request.max_tokens <= MAX_MAX_TOKENS):
        raise HTTPException(status_code=400, detail=f"max_tokens must be {MIN_MAX_TOKENS}–{MAX_MAX_TOKENS}")


def create_app(cfg: ServerConfig) -> FastAPI:
    """Build and return a configured FastAPI app. Safe to call from a notebook."""
    from nanochat.common import compute_init, autodetect_device_type
    device_type = autodetect_device_type() if cfg.device_type == "" else cfg.device_type
    compute_init(device_type)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.worker_pool = WorkerPool(num_gpus=cfg.num_gpus, device_type=device_type)
        await app.state.worker_pool.initialize(cfg)
        print(f"Server ready at http://localhost:{cfg.port}", flush=True)
        yield

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    async def root():
        ui_html_path = os.path.join("nanochat", "ui.html")
        with open(ui_html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        html_content = html_content.replace(
            "const API_URL = `http://${window.location.hostname}:8000`;",
            "const API_URL = '';",
        )
        return HTMLResponse(content=html_content)

    @app.get("/logo.svg")
    async def logo():
        return FileResponse(os.path.join("nanochat", "logo.svg"), media_type="image/svg+xml")

    async def generate_stream(worker: Worker, tokens, temperature=None, max_new_tokens=None, top_k=None) -> AsyncGenerator[str, None]:
        temperature = temperature if temperature is not None else cfg.temperature
        max_new_tokens = max_new_tokens if max_new_tokens is not None else cfg.max_tokens
        top_k = top_k if top_k is not None else cfg.top_k

        assistant_end = worker.tokenizer.encode_special("<|assistant_end|>")
        bos = worker.tokenizer.get_bos_token_id()
        accumulated_tokens = []
        last_clean_text = ""

        for token_column, token_masks in worker.engine.generate(
            tokens, num_samples=1, max_tokens=max_new_tokens,
            temperature=temperature, top_k=top_k, seed=random.randint(0, 2**31 - 1),
        ):
            token = token_column[0]
            if token == assistant_end or token == bos:
                break
            accumulated_tokens.append(token)
            current_text = worker.tokenizer.decode(accumulated_tokens)
            if not current_text.endswith('â€'):
                new_text = current_text[len(last_clean_text):]
                if new_text:
                    yield f"data: {json.dumps({'token': new_text, 'gpu': worker.gpu_id}, ensure_ascii=False)}\n\n"
                    last_clean_text = current_text

        yield f"data: {json.dumps({'done': True})}\n\n"

    @app.post("/chat/completions")
    async def chat_completions(request: ChatRequest):
        validate_chat_request(request)
        logger.info("="*20)
        for message in request.messages:
            logger.info(f"[{message.role.upper()}]: {message.content}")
        logger.info("-"*20)

        worker_pool = app.state.worker_pool
        worker = await worker_pool.acquire_worker()

        try:
            bos = worker.tokenizer.get_bos_token_id()
            user_start = worker.tokenizer.encode_special("<|user_start|>")
            user_end = worker.tokenizer.encode_special("<|user_end|>")
            assistant_start = worker.tokenizer.encode_special("<|assistant_start|>")
            assistant_end = worker.tokenizer.encode_special("<|assistant_end|>")

            conversation_tokens = [bos]
            for message in request.messages:
                if message.role == "user":
                    conversation_tokens += [user_start] + worker.tokenizer.encode(message.content) + [user_end]
                elif message.role == "assistant":
                    conversation_tokens += [assistant_start] + worker.tokenizer.encode(message.content) + [assistant_end]
            conversation_tokens.append(assistant_start)

            response_tokens = []
            async def stream_and_release():
                try:
                    async for chunk in generate_stream(worker, conversation_tokens,
                                                       temperature=request.temperature,
                                                       max_new_tokens=request.max_tokens,
                                                       top_k=request.top_k):
                        chunk_data = json.loads(chunk.replace("data: ", "").strip())
                        if "token" in chunk_data:
                            response_tokens.append(chunk_data["token"])
                        yield chunk
                finally:
                    logger.info(f"[ASSISTANT] (GPU {worker.gpu_id}): {''.join(response_tokens)}")
                    logger.info("="*20)
                    await worker_pool.release_worker(worker)

            return StreamingResponse(stream_and_release(), media_type="text/event-stream")
        except Exception as e:
            await worker_pool.release_worker(worker)
            raise e

    @app.get("/health")
    async def health():
        worker_pool = getattr(app.state, 'worker_pool', None)
        return {
            "status": "ok",
            "ready": worker_pool is not None and len(worker_pool.workers) > 0,
            "num_gpus": worker_pool.num_gpus if worker_pool else 0,
            "available_workers": worker_pool.available_workers.qsize() if worker_pool else 0,
        }

    @app.get("/stats")
    async def stats():
        worker_pool = app.state.worker_pool
        return {
            "total_workers": len(worker_pool.workers),
            "available_workers": worker_pool.available_workers.qsize(),
            "busy_workers": len(worker_pool.workers) - worker_pool.available_workers.qsize(),
            "workers": [{"gpu_id": w.gpu_id, "device": str(w.device)} for w in worker_pool.workers],
        }

    return app


def start_in_thread(
    checkpoint_dir: str,
    tokenizer_dir: str,
    source: str = "sft",
    step: Optional[int] = None,
    port: int = 8000,
    **kwargs,
) -> None:
    """Start the chat server in a background thread (for notebooks / in-process use)."""
    import threading
    import uvicorn

    cfg = ServerConfig(
        source=source,
        checkpoint_dir=checkpoint_dir,
        tokenizer_dir=tokenizer_dir,
        step=step,
        port=port,
        **kwargs,
    )
    app = create_app(cfg)
    thread = threading.Thread(
        target=uvicorn.run,
        args=(app,),
        kwargs={"host": cfg.host, "port": cfg.port, "log_level": "warning"},
        daemon=True,
    )
    thread.start()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='NanoChat Web Server')
    parser.add_argument('-n', '--num-gpus', type=int, default=1)
    parser.add_argument('-i', '--source', type=str, default="sft")
    parser.add_argument('-t', '--temperature', type=float, default=0.8)
    parser.add_argument('-k', '--top-k', type=int, default=50)
    parser.add_argument('-m', '--max-tokens', type=int, default=512)
    parser.add_argument('-g', '--model-tag', type=str, default=None)
    parser.add_argument('-s', '--step', type=int, default=None)
    parser.add_argument('--checkpoint-dir', type=str, default=None)
    parser.add_argument('--tokenizer-dir', type=str, default=None)
    parser.add_argument('-p', '--port', type=int, default=8000)
    parser.add_argument('--device-type', type=str, default='', choices=['cuda', 'cpu', 'mps', ''])
    parser.add_argument('--host', type=str, default='0.0.0.0')
    args = parser.parse_args()

    import uvicorn
    cfg = ServerConfig(
        source=args.source,
        checkpoint_dir=args.checkpoint_dir,
        tokenizer_dir=args.tokenizer_dir,
        step=args.step,
        model_tag=args.model_tag,
        num_gpus=args.num_gpus,
        temperature=args.temperature,
        top_k=args.top_k,
        max_tokens=args.max_tokens,
        host=args.host,
        port=args.port,
        device_type=args.device_type,
    )
    print(f"Starting NanoChat Web Server on port {cfg.port}")
    app = create_app(cfg)
    uvicorn.run(app, host=cfg.host, port=cfg.port)


if __name__ == "__main__":
    main()
