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

To chat, open the URL printed in the console. (If on cloud box, make sure to use public IP)

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

import argparse
import json
import os
import torch
import asyncio
import logging
import random
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import List, Optional, AsyncGenerator
from dataclasses import dataclass
from nanochat.common import compute_init, autodetect_device_type
from nanochat.checkpoint_manager import load_model
from nanochat.engine import Engine
from nanochat.prompt_shaping import load_priming_turns, repair_messages

# Abuse prevention limits
MAX_MESSAGES_PER_REQUEST = 500
MAX_MESSAGE_LENGTH = 8000
MAX_TOTAL_CONVERSATION_LENGTH = 32000
MIN_TEMPERATURE = 0.0
MAX_TEMPERATURE = 2.0
MIN_TOP_K = 0 # 0 disables top-k filtering, using full vocabulary
MAX_TOP_K = 200
MIN_MAX_TOKENS = 1
MAX_MAX_TOKENS = 4096
MIN_REPETITION_PENALTY = 1.0 # 1.0 disables the penalty
MAX_REPETITION_PENALTY = 2.0
# Headroom left over after the prompt + the tokens we are about to generate, so
# rounding in the budget math can never push us past the trained context.
CONTEXT_SAFETY_MARGIN = 16

parser = argparse.ArgumentParser(description='NanoChat Web Server')
parser.add_argument('-n', '--num-gpus', type=int, default=1, help='Number of GPUs to use (default: 1)')
parser.add_argument('-i', '--source', type=str, default="sft", help="Source of the model: sft|rl")
parser.add_argument('-t', '--temperature', type=float, default=0.8, help='Default temperature for generation')
parser.add_argument('-k', '--top-k', type=int, default=50, help='Default top-k sampling parameter')
parser.add_argument('-m', '--max-tokens', type=int, default=512, help='Default max tokens for generation')
parser.add_argument('-g', '--model-tag', type=str, default=None, help='Model tag to load')
parser.add_argument('-s', '--step', type=int, default=None, help='Step to load')
parser.add_argument('--checkpoint-dir', type=str, default=None, help='Exact checkpoint directory (overrides model-tag lookup)')
parser.add_argument('--tokenizer-dir', type=str, default=None, help='Tokenizer directory')
parser.add_argument('-p', '--port', type=int, default=8000, help='Port to run the server on')
parser.add_argument('--device-type', type=str, default='', choices=['cuda', 'cpu', 'mps'], help='Device type for evaluation: cuda|cpu|mps. empty => autodetect')
parser.add_argument('--host', type=str, default='0.0.0.0', help='Host to bind the server to')
parser.add_argument('--repetition-penalty', type=float, default=1.0,
                    help='CTRL-style repetition penalty over recent generated tokens (1.0 disables). '
                         'Off by default: it cannot tell a degenerate loop from requested repetition '
                         '(verse refrains, spelling, "write AAAA"), so enable it per-request instead.')
parser.add_argument('--repetition-window', type=int, default=64,
                    help='How many recent generated tokens the penalty considers (0 = the whole response)')
parser.add_argument('--system-prompt', type=str, default='', help='System prompt applied when the request does not carry its own')
parser.add_argument('--system-prompt-file', type=str, default='', help='Read the default system prompt from this file')
parser.add_argument('--fix-punctuation', action='store_true',
                    help='Append the missing sentence-final mark to each user turn before tokenizing '
                         'it. Unpunctuated turns are thin in SFT (end_punct_rate 0.05), so this moves '
                         'them back onto the trained distribution. Casing is left as the visitor typed it')
parser.add_argument('--priming-turns', type=str, default='',
                    help="Splice an invisible user/assistant exchange in front of every conversation: "
                         "'default' for the built-in one, or a path to a JSON file (see "
                         "configs/priming_turns/). The fake user turn is itself unpunctuated, so the "
                         "model sees an in-context example of answering that shape well -- which a "
                         "system prompt cannot demonstrate. Empty disables it")
args = parser.parse_args()

# Server-side default system prompt. A request that sends its own system message
# overrides this. The browser UI keeps a flat user/assistant array and has no
# place to type one, so this flag is how a persona gets attached when serving.
if args.system_prompt and args.system_prompt_file:
    parser.error("pass only one of --system-prompt / --system-prompt-file")
DEFAULT_SYSTEM_PROMPT = args.system_prompt.strip()
if args.system_prompt_file:
    with open(args.system_prompt_file, "r", encoding="utf-8") as f:
        DEFAULT_SYSTEM_PROMPT = f.read().strip()

# Standing conversational prefix, resolved once at boot so a malformed file fails
# the launch rather than every request. Empty list => feature off.
PRIMING_TURNS = load_priming_turns(args.priming_turns)

# Configure logging for conversation traffic
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

device_type = autodetect_device_type() if args.device_type == "" else args.device_type
ddp, ddp_rank, ddp_local_rank, ddp_world_size, device = compute_init(device_type)

@dataclass
class Worker:
    """A worker with a model loaded on a specific GPU."""
    gpu_id: int
    device: torch.device
    engine: Engine
    tokenizer: object

class WorkerPool:
    """Pool of workers, each with a model replica on a different GPU."""

    def __init__(self, num_gpus: Optional[int] = None):
        if num_gpus is None:
            if device_type == "cuda":
                num_gpus = torch.cuda.device_count()
            else:
                num_gpus = 1 # e.g. cpu|mps
        self.num_gpus = num_gpus
        self.workers: List[Worker] = []
        self.available_workers: asyncio.Queue = asyncio.Queue()

    async def initialize(self, source: str, model_tag: Optional[str] = None, step: Optional[int] = None):
        """Load model on each GPU."""
        print(f"Initializing worker pool with {self.num_gpus} GPUs...")
        if self.num_gpus > 1:
            assert device_type == "cuda", "Only CUDA supports multiple workers/GPUs. cpu|mps does not."

        for gpu_id in range(self.num_gpus):

            if device_type == "cuda":
                device = torch.device(f"cuda:{gpu_id}")
                print(f"Loading model on GPU {gpu_id}...")
            else:
                device = torch.device(device_type) # e.g. cpu|mps
                print(f"Loading model on {device_type}...")

            if args.checkpoint_dir:
                from nanochat.checkpoint_manager import load_model_from_checkpoint_dir
                model, tokenizer, _ = load_model_from_checkpoint_dir(
                    args.checkpoint_dir, device, phase="eval", step=step, tokenizer_dir=args.tokenizer_dir
                )
            else:
                model, tokenizer, _ = load_model(source, device, phase="eval", model_tag=model_tag, step=step)
            engine = Engine(model, tokenizer)
            worker = Worker(
                gpu_id=gpu_id,
                device=device,
                engine=engine,
                tokenizer=tokenizer,
            )
            self.workers.append(worker)
            await self.available_workers.put(worker)

        print(f"All {self.num_gpus} workers initialized!")

    async def acquire_worker(self) -> Worker:
        """Get an available worker from the pool."""
        return await self.available_workers.get()

    async def release_worker(self, worker: Worker):
        """Return a worker to the pool."""
        await self.available_workers.put(worker)

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_k: Optional[int] = None
    repetition_penalty: Optional[float] = None

def validate_chat_request(request: ChatRequest):
    """Validate chat request to prevent abuse."""
    # Check number of messages
    if len(request.messages) == 0:
        raise HTTPException(status_code=400, detail="At least one message is required")
    if len(request.messages) > MAX_MESSAGES_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"Too many messages. Maximum {MAX_MESSAGES_PER_REQUEST} messages allowed per request"
        )

    # Check individual message lengths and total conversation length
    total_length = 0
    for i, message in enumerate(request.messages):
        if not message.content:
            raise HTTPException(status_code=400, detail=f"Message {i} has empty content")

        msg_length = len(message.content)
        if msg_length > MAX_MESSAGE_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"Message {i} is too long. Maximum {MAX_MESSAGE_LENGTH} characters allowed per message"
            )
        total_length += msg_length

    if total_length > MAX_TOTAL_CONVERSATION_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Total conversation is too long. Maximum {MAX_TOTAL_CONVERSATION_LENGTH} characters allowed"
        )

    # Validate role values. A system message is allowed, but only as the very
    # first message: the tokenizer has no system special token and renders one
    # by merging it into the first user turn, which only makes sense up front.
    for i, message in enumerate(request.messages):
        if message.role == "system":
            if i != 0:
                raise HTTPException(
                    status_code=400,
                    detail="Only the first message may have role 'system'"
                )
            continue
        if message.role not in ["user", "assistant"]:
            raise HTTPException(
                status_code=400,
                detail=f"Message {i} has invalid role. Must be 'user', 'assistant', or 'system'"
            )
    if request.messages[0].role == "system" and len(request.messages) < 2:
        raise HTTPException(
            status_code=400,
            detail="A system message must be followed by a user message"
        )

    # Validate temperature
    if request.temperature is not None:
        if not (MIN_TEMPERATURE <= request.temperature <= MAX_TEMPERATURE):
            raise HTTPException(
                status_code=400,
                detail=f"Temperature must be between {MIN_TEMPERATURE} and {MAX_TEMPERATURE}"
            )

    # Validate top_k
    if request.top_k is not None:
        if not (MIN_TOP_K <= request.top_k <= MAX_TOP_K):
            raise HTTPException(
                status_code=400,
                detail=f"top_k must be between {MIN_TOP_K} and {MAX_TOP_K}"
            )

    # Validate max_tokens
    if request.max_tokens is not None:
        if not (MIN_MAX_TOKENS <= request.max_tokens <= MAX_MAX_TOKENS):
            raise HTTPException(
                status_code=400,
                detail=f"max_tokens must be between {MIN_MAX_TOKENS} and {MAX_MAX_TOKENS}"
            )

    # Validate repetition_penalty
    if request.repetition_penalty is not None:
        if not (MIN_REPETITION_PENALTY <= request.repetition_penalty <= MAX_REPETITION_PENALTY):
            raise HTTPException(
                status_code=400,
                detail=f"repetition_penalty must be between {MIN_REPETITION_PENALTY} and {MAX_REPETITION_PENALTY}"
            )

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load models on all GPUs on startup."""
    print("Loading nanochat models across GPUs...")
    app.state.worker_pool = WorkerPool(num_gpus=args.num_gpus)
    await app.state.worker_pool.initialize(args.source, model_tag=args.model_tag, step=args.step)
    print(f"Server ready at http://localhost:{args.port}")
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
    """Serve the chat UI."""
    ui_html_path = os.path.join("nanochat", "ui.html")
    with open(ui_html_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    # Replace the API_URL to use the same origin
    html_content = html_content.replace(
        "const API_URL = `http://${window.location.hostname}:8000`;",
        "const API_URL = '';"
    )
    return HTMLResponse(content=html_content)


@app.get("/logo.svg")
async def logo():
    """Serve the NanoChat logo for favicon and header."""
    logo_path = os.path.join("nanochat", "logo.svg")
    return FileResponse(logo_path, media_type="image/svg+xml")

async def generate_stream(
    worker: Worker,
    tokens,
    temperature=None,
    max_new_tokens=None,
    top_k=None,
    repetition_penalty=None
) -> AsyncGenerator[str, None]:
    """Generate assistant response with streaming."""
    temperature = temperature if temperature is not None else args.temperature
    max_new_tokens = max_new_tokens if max_new_tokens is not None else args.max_tokens
    top_k = top_k if top_k is not None else args.top_k
    repetition_penalty = repetition_penalty if repetition_penalty is not None else args.repetition_penalty

    assistant_end = worker.tokenizer.encode_special("<|assistant_end|>")
    bos = worker.tokenizer.get_bos_token_id()

    # Accumulate tokens to properly handle multi-byte UTF-8 characters (like emojis)
    accumulated_tokens = []
    # Track the last complete UTF-8 string (without replacement characters)
    last_clean_text = ""

    for token_column, token_masks in worker.engine.generate(
        tokens,
        num_samples=1,
        max_tokens=max_new_tokens,
        temperature=temperature,
        top_k=top_k,
        seed=random.randint(0, 2**31 - 1),
        repetition_penalty=repetition_penalty,
        repetition_window=args.repetition_window or None,
    ):
        token = token_column[0]

        # Stopping criteria
        if token == assistant_end or token == bos:
            break

        # Append the token to sequence
        accumulated_tokens.append(token)
        # Decode all accumulated tokens to get proper UTF-8 handling
        # Note that decode is a quite efficient operation, basically table lookup and string concat
        current_text = worker.tokenizer.decode(accumulated_tokens)
        # Only emit text if it doesn't end with a replacement character
        # This ensures we don't emit incomplete UTF-8 sequences
        if not current_text.endswith('�'):
            # Extract only the new text since last clean decode
            new_text = current_text[len(last_clean_text):]
            if new_text:  # Only yield if there's new content
                yield f"data: {json.dumps({'token': new_text, 'gpu': worker.gpu_id}, ensure_ascii=False)}\n\n"
                last_clean_text = current_text

    yield f"data: {json.dumps({'done': True})}\n\n"

def build_conversation_tokens(worker, messages, max_new_tokens):
    """Render the chat history into prompt tokens, primed for the assistant.

    Mirrors Tokenizer.render_conversation's convention: this tokenizer has no
    system special token (the vocab slots went to BPE merges), so a leading
    system message is merged into the first user turn with a blank line between.
    Training does exactly this, so serving must too.

    When the history outgrows the model's context we drop whole user/assistant
    exchanges from the front. The system prompt and the priming turns are
    standing context, not history, so they survive eviction; the system prompt is
    re-merged into whichever user turn ends up first.
    """
    tokenizer = worker.tokenizer
    bos = tokenizer.get_bos_token_id()
    user_start = tokenizer.encode_special("<|user_start|>")
    user_end = tokenizer.encode_special("<|user_end|>")
    assistant_start = tokenizer.encode_special("<|assistant_start|>")
    assistant_end = tokenizer.encode_special("<|assistant_end|>")

    # Normalize to plain dicts so the request's pydantic messages and the
    # configured priming turns are the same kind of thing from here down.
    turns = [{"role": m.role, "content": m.content} for m in messages]
    system_text = DEFAULT_SYSTEM_PROMPT
    if turns and turns[0]["role"] == "system":
        system_text = turns[0]["content"].strip() # per-request prompt wins
        turns = turns[1:]
    if args.fix_punctuation:
        turns = repair_messages(turns)
    # Never repaired: the priming user turn is unpunctuated on purpose.
    priming = PRIMING_TURNS

    # Overrunning the trained context does not raise: the rotary cache is built
    # 10x oversized (gpt.py) and the KV cache is sized per request, so the model
    # would just generate from positions it never saw in training and quietly
    # produce mush. The character-based limits above don't protect us either
    # (32K chars is roughly 2x a 4096-token context), so budget it explicitly.
    budget = worker.engine.model.config.sequence_len - max_new_tokens - CONTEXT_SAFETY_MARGIN

    def render(turns):
        out = [bos]
        for i, message in enumerate([*priming, *turns]):
            content = message["content"]
            if i == 0 and system_text and message["role"] == "user":
                content = f"{system_text}\n\n{content}"
            start, end = (user_start, user_end) if message["role"] == "user" else (assistant_start, assistant_end)
            out.append(start)
            out.extend(tokenizer.encode(content))
            out.append(end)
        out.append(assistant_start) # prime the assistant for completion
        return out

    dropped = 0
    while len(turns) > 1:
        tokens = render(turns)
        if len(tokens) <= budget:
            if dropped:
                logger.info(f"Context budget: dropped {dropped} oldest message(s), kept system prompt")
            return tokens
        turns = turns[2:] # drop an exchange, keeping user/assistant alternation
        dropped += 2

    # A single turn that still overflows: keep the system prompt intact and clip
    # the visitor's own text, since that is the part we can afford to lose.
    tokens = render(turns)
    if len(tokens) <= budget:
        return tokens
    # Drop the priming turns before clipping the visitor's own words: an example
    # of good style is worth less than the question the visitor actually asked.
    message = turns[0]
    prefix = f"{system_text}\n\n" if system_text and message["role"] == "user" else ""
    prefix_ids = tokenizer.encode(prefix) if prefix else []
    room = max(budget - len(prefix_ids) - 4, 0) # bos + start + end + assistant_start
    body = tokenizer.encode(message["content"])[:room]
    logger.info(f"Context budget: single message clipped to {len(body)} tokens")
    return [bos, user_start, *prefix_ids, *body, user_end, assistant_start]

@app.post("/chat/completions")
async def chat_completions(request: ChatRequest):
    """Chat completion endpoint (streaming only) - uses worker pool for multi-GPU."""

    # Basic validation to prevent abuse
    validate_chat_request(request)

    # Log incoming conversation to console
    logger.info("="*20)
    for i, message in enumerate(request.messages):
        logger.info(f"[{message.role.upper()}]: {message.content}")
    logger.info("-"*20)

    # Acquire a worker from the pool (will wait if all are busy)
    worker_pool = app.state.worker_pool
    worker = await worker_pool.acquire_worker()

    try:
        # Build conversation tokens (merges the system prompt, enforces context budget)
        max_new_tokens = request.max_tokens if request.max_tokens is not None else args.max_tokens
        conversation_tokens = build_conversation_tokens(worker, request.messages, max_new_tokens)

        # Streaming response with worker release after completion
        response_tokens = []
        async def stream_and_release():
            try:
                async for chunk in generate_stream(
                    worker,
                    conversation_tokens,
                    temperature=request.temperature,
                    max_new_tokens=request.max_tokens,
                    top_k=request.top_k,
                    repetition_penalty=request.repetition_penalty
                ):
                    # Accumulate response for logging
                    chunk_data = json.loads(chunk.replace("data: ", "").strip())
                    if "token" in chunk_data:
                        response_tokens.append(chunk_data["token"])
                    yield chunk
            finally:
                # Log the assistant response to console
                full_response = "".join(response_tokens)
                logger.info(f"[ASSISTANT] (GPU {worker.gpu_id}): {full_response}")
                logger.info("="*20)
                # Release worker back to pool after streaming is done
                await worker_pool.release_worker(worker)

        return StreamingResponse(
            stream_and_release(),
            media_type="text/event-stream"
        )
    except Exception as e:
        # Make sure to release worker even on error
        await worker_pool.release_worker(worker)
        raise e

@app.get("/health")
async def health():
    """Health check endpoint."""
    worker_pool = getattr(app.state, 'worker_pool', None)
    return {
        "status": "ok",
        "ready": worker_pool is not None and len(worker_pool.workers) > 0,
        "num_gpus": worker_pool.num_gpus if worker_pool else 0,
        "available_workers": worker_pool.available_workers.qsize() if worker_pool else 0
    }

@app.get("/stats")
async def stats():
    """Get worker pool statistics."""
    worker_pool = app.state.worker_pool
    return {
        "total_workers": len(worker_pool.workers),
        "available_workers": worker_pool.available_workers.qsize(),
        "busy_workers": len(worker_pool.workers) - worker_pool.available_workers.qsize(),
        "workers": [
            {
                "gpu_id": w.gpu_id,
                "device": str(w.device)
            } for w in worker_pool.workers
        ]
    }

if __name__ == "__main__":
    import uvicorn
    print(f"Starting NanoChat Web Server")
    print(f"Temperature: {args.temperature}, Top-k: {args.top_k}, Max tokens: {args.max_tokens}")
    print(f"User-turn repair: {'on' if args.fix_punctuation else 'off'}, "
          f"priming turns: {len(PRIMING_TURNS) or 'off'}")
    uvicorn.run(app, host=args.host, port=args.port)
