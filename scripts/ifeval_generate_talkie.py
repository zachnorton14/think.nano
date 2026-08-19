"""Generate one resumable IFEval shard with Talkie's official package."""

import argparse
import time

import torch

from scripts.ifeval_common import append_result, read_completed, read_inputs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model-id", default="talkie-1930-13b-it")
    parser.add_argument("--max-tokens", type=int, default=1280)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--cache-dir", default=None)
    args = parser.parse_args()
    if not 0 <= args.shard_index < args.shard_count:
        raise ValueError("shard-index must be in [0, shard-count)")

    from talkie import Talkie
    from talkie.chat import format_prompt, truncate_at_stop

    rows = read_inputs(args.input)
    completed = read_completed(args.output, args.model_id)
    if any(
        row.get("backend") != "talkie-official"
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

    talkie = Talkie(
        "talkie-1930-13b-it",
        device="cuda",
        cache_dir=args.cache_dir,
    )
    for position, row in enumerate(assigned, 1):
        key = int(row["key"])
        if key in completed:
            continue
        formatted = format_prompt(row["prompt"])
        token_ids = talkie.tokenizer.encode(formatted, allowed_special="all")
        context_limit = int(talkie.model.cos.size(1))
        generation_limit = min(args.max_tokens, max(context_limit - len(token_ids), 0))
        generated = []
        started = time.time()
        with torch.no_grad(), talkie._autocast:
            tokens = torch.tensor(token_ids, dtype=torch.long, device=talkie.device)[None]
            for _ in range(generation_limit):
                next_token = int(torch.argmax(talkie.model(tokens)[0]).item())
                if next_token in talkie._stop_ids:
                    break
                generated.append(next_token)
                tokens = torch.cat(
                    [tokens, torch.tensor([[next_token]], device=talkie.device)], dim=1
                )
        response, _ = truncate_at_stop(talkie.tokenizer.decode(generated))
        result = {
            "key": key,
            "prompt": row["prompt"],
            "response": response,
            "model_id": args.model_id,
            "backend": "talkie-official",
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
