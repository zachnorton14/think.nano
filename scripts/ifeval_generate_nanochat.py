"""Generate one resumable IFEval shard with a nanochat checkpoint."""

import argparse
import time

import torch

from nanochat.checkpoint_manager import load_model_from_checkpoint_dir
from nanochat.engine import Engine
from scripts.ifeval_common import append_result, read_completed, read_inputs


def render_ifeval_prompt(tokenizer, prompt):
    """Wrap one IFEval instruction in the conversation shape the tokenizer expects."""
    return tokenizer.render_for_completion({
        "messages": [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": ""},
        ]
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--checkpoint-dir", required=True)
    parser.add_argument("--tokenizer-dir", required=True)
    parser.add_argument("--step", type=int, default=None)
    parser.add_argument("--max-tokens", type=int, default=1280)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    args = parser.parse_args()
    if not 0 <= args.shard_index < args.shard_count:
        raise ValueError("shard-index must be in [0, shard-count)")

    rows = read_inputs(args.input)
    completed = read_completed(args.output, args.model_id)
    if any(
        row.get("backend") != "nanochat"
        or int(row.get("max_tokens", -1)) != args.max_tokens
        or float(row.get("temperature", -1)) != 0.0
        or row.get("system_prompt") is not None
        for row in completed.values()
    ):
        raise ValueError("Existing shard uses different generation settings")
    assigned = [
        row for index, row in enumerate(rows)
        if index % args.shard_count == args.shard_index
    ]
    if all(int(row["key"]) in completed for row in assigned):
        print(f"Shard {args.shard_index} already complete; skipping model load")
        return

    device = torch.device("cuda")
    model, tokenizer, meta = load_model_from_checkpoint_dir(
        args.checkpoint_dir,
        device,
        phase="eval",
        step=args.step,
        tokenizer_dir=args.tokenizer_dir,
    )
    engine = Engine(model, tokenizer)
    architecture = meta.get("model_architecture", "auto-detected")
    for position, row in enumerate(assigned, 1):
        key = int(row["key"])
        if key in completed:
            continue
        prompt_tokens = render_ifeval_prompt(tokenizer, row["prompt"])
        room = model.config.sequence_len - len(prompt_tokens)
        generation_limit = min(args.max_tokens, max(room, 0))
        started = time.time()
        if generation_limit:
            generated, _ = engine.generate_batch(
                prompt_tokens,
                num_samples=1,
                max_tokens=generation_limit,
                temperature=0.0,
            )
            response = tokenizer.decode(generated[0][len(prompt_tokens):])
        else:
            response = ""
        result = {
            "key": key,
            "prompt": row["prompt"],
            "response": response,
            "model_id": args.model_id,
            "backend": "nanochat",
            "architecture": architecture,
            "checkpoint_step": int(meta.get("step", args.step or -1)),
            "max_tokens": args.max_tokens,
            "temperature": 0.0,
            "system_prompt": None,
            "elapsed_seconds": time.time() - started,
        }
        append_result(args.output, result)
        print(
            f"[{position}/{len(assigned)}] key={key} "
            f"chars={len(response)} elapsed={result['elapsed_seconds']:.1f}s",
            flush=True,
        )


if __name__ == "__main__":
    main()
