"""Compare a checkpoint bare, system-prompted, and with inference-time shaping.

The default profiles isolate the three questions that matter before a run:

    bare       raw user text; no system prompt or shaping
    system     raw user text; system prompt only
    inference  punctuation repair + invisible priming turns; no system prompt

Additional profiles split the new inference behavior into its components, add
the system prompt to the complete serving stack, or compare the KV-cache Engine
against the model's slow native generator:

    repair, prime, full, native

Generation is greedy by default so differences come from the profile rather
than sampling. The model is loaded only once.
"""

import argparse
import json
import time
from pathlib import Path

import torch

from nanochat.checkpoint_manager import load_model, load_model_from_checkpoint_dir
from nanochat.common import autodetect_device_type, compute_init
from nanochat.engine import Engine
from nanochat.prompt_shaping import load_priming_turns, repair_user_text
from scripts.experiment import Experiment, resolve_system_prompt


DEFAULT_PROMPTS = [
    "whats the weather like",
    "tell me who you are",
]

PROFILE_SETTINGS = {
    "bare": {"backend": "engine", "system": False, "repair": False, "prime": False},
    "system": {"backend": "engine", "system": True, "repair": False, "prime": False},
    "repair": {"backend": "engine", "system": False, "repair": True, "prime": False},
    "prime": {"backend": "engine", "system": False, "repair": False, "prime": True},
    "inference": {"backend": "engine", "system": False, "repair": True, "prime": True},
    "full": {"backend": "engine", "system": True, "repair": True, "prime": True},
    "native": {"backend": "native", "system": False, "repair": False, "prime": False},
}


def parse_profiles(spec):
    profiles = [value.strip() for value in spec.split(",") if value.strip()]
    unknown = sorted(set(profiles) - set(PROFILE_SETTINGS))
    if unknown:
        raise ValueError(
            f"unknown profiles {unknown}; choose from {sorted(PROFILE_SETTINGS)}"
        )
    if not profiles or len(profiles) != len(set(profiles)):
        raise ValueError("profiles must be a non-empty list without duplicates")
    return profiles


def prepare_profile(profile, user_text, system_text, priming_turns):
    settings = PROFILE_SETTINGS[profile]
    sent = repair_user_text(user_text) if settings["repair"] else user_text
    return {
        "backend": settings["backend"],
        "sent": sent,
        "system_text": system_text if settings["system"] else "",
        "priming_turns": list(priming_turns) if settings["prime"] else [],
        "repaired": settings["repair"],
    }


def build_prompt(tokenizer, user_text, system_text="", priming_turns=()):
    """Render one turn exactly like chat_web/Beam, primed for the assistant."""
    bos = tokenizer.get_bos_token_id()
    user_start = tokenizer.encode_special("<|user_start|>")
    user_end = tokenizer.encode_special("<|user_end|>")
    assistant_start = tokenizer.encode_special("<|assistant_start|>")
    assistant_end = tokenizer.encode_special("<|assistant_end|>")
    turns = [*priming_turns, {"role": "user", "content": user_text}]
    out = [bos]
    for index, message in enumerate(turns):
        content = message["content"]
        if index == 0 and system_text and message["role"] == "user":
            content = f"{system_text}\n\n{content}"
        if message["role"] == "user":
            start, end = user_start, user_end
        else:
            start, end = assistant_start, assistant_end
        out.append(start)
        out.extend(tokenizer.encode(content))
        out.append(end)
    out.append(assistant_start)
    return out


def prepare_experiment_checkpoint(
    config_path,
    requested_step=None,
    parent_experiment_id=None,
    parent_step=None,
):
    experiment = Experiment(
        config_path,
        nproc_per_node=1,
        parent_experiment_id=parent_experiment_id,
        parent_step=parent_step,
    )
    experiment.initialize_for_inference()
    experiment._ensure_tokenizer()
    local = experiment.complete_local_steps()
    remote = experiment.complete_remote_steps(strict=True)
    available = sorted(set(local) | set(remote))
    if not available:
        raise RuntimeError(f"No complete checkpoint found for {experiment.experiment_id}")
    step = requested_step if requested_step is not None else available[-1]
    if step not in available:
        raise RuntimeError(
            f"Checkpoint step {step} is unavailable; complete steps: {available}"
        )
    if step not in local:
        experiment.download_step(step, include_optimizer=False)
    return experiment.checkpoint_dir, experiment.tokenizer_dir, step, experiment.experiment_id


def load_probe_model(args, device):
    if args.config:
        checkpoint_dir, tokenizer_dir, step, label = prepare_experiment_checkpoint(
            args.config,
            args.step,
            args.parent_experiment_id,
            args.parent_step,
        )
        model, tokenizer, meta = load_model_from_checkpoint_dir(
            checkpoint_dir,
            device,
            phase="eval",
            step=step,
            tokenizer_dir=tokenizer_dir,
        )
        return model, tokenizer, meta, label
    if args.checkpoint_dir:
        model, tokenizer, meta = load_model_from_checkpoint_dir(
            args.checkpoint_dir,
            device,
            phase="eval",
            step=args.step,
            tokenizer_dir=args.tokenizer_dir,
        )
        return model, tokenizer, meta, str(args.checkpoint_dir)
    model, tokenizer, meta = load_model(
        args.source,
        device,
        phase="eval",
        model_tag=args.model_tag,
        step=args.step,
    )
    return model, tokenizer, meta, args.model_tag


def synchronize(device):
    if device.type == "cuda":
        torch.cuda.synchronize(device)


def generate_engine(engine, prompt, args):
    generated, _ = engine.generate_batch(
        prompt,
        num_samples=1,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        top_k=args.top_k,
        repetition_penalty=args.repetition_penalty,
        repetition_window=args.repetition_window,
    )
    return generated[0][len(prompt):]


def generate_native(model, tokenizer, prompt, args):
    assistant_end = tokenizer.encode_special("<|assistant_end|>")
    bos = tokenizer.get_bos_token_id()
    completion = []
    for token in model.generate(
        prompt,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        top_k=args.top_k,
    ):
        if token in {assistant_end, bos}:
            break
        completion.append(token)
    return completion


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    locator = parser.add_mutually_exclusive_group()
    locator.add_argument("--config", help="Experiment config; downloads its latest checkpoint")
    locator.add_argument("--checkpoint-dir", help="Exact local checkpoint directory")
    locator.add_argument("--model-tag", help="Model tag resolved by checkpoint_manager")
    parser.add_argument("--tokenizer-dir", help="Tokenizer for --checkpoint-dir")
    parser.add_argument("--source", default="sft", help="Source for --model-tag")
    parser.add_argument("--step", type=int, default=None)
    parser.add_argument(
        "--parent-experiment-id",
        default=None,
        help="Parent base ID when an SFT config does not embed parent metadata",
    )
    parser.add_argument(
        "--parent-step",
        type=int,
        default=None,
        help="Parent base checkpoint step for --config",
    )
    parser.add_argument(
        "--profiles",
        default="bare,system,inference",
        help="Comma-separated profiles: bare, system, repair, prime, inference, full, native",
    )
    parser.add_argument(
        "--system-prompt",
        default="pre1930-companion",
        help="Name, path, literal text, or 'none' (used only by system/full)",
    )
    parser.add_argument(
        "--priming-turns",
        default="configs/priming_turns/pre1930-companion.json",
        help="'default' or JSON path (used only by prime/inference/full)",
    )
    parser.add_argument("--prompt", action="append", default=[], help="Probe prompt; repeatable")
    parser.add_argument("--prompt-file", default="", help="One probe prompt per non-empty line")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--max-tokens", type=int, default=160)
    parser.add_argument("--repetition-penalty", type=float, default=1.0)
    parser.add_argument("--repetition-window", type=int, default=64)
    parser.add_argument("--out", default="", help="Optional JSON output path")
    parser.add_argument(
        "--device-type",
        default="",
        choices=["cuda", "cpu", "mps"],
        help="Empty means autodetect",
    )
    args = parser.parse_args()
    if not (args.config or args.checkpoint_dir or args.model_tag):
        parser.error("pass one of --config, --checkpoint-dir, or --model-tag")
    if args.tokenizer_dir and not args.checkpoint_dir:
        parser.error("--tokenizer-dir is only valid with --checkpoint-dir")
    if (args.parent_experiment_id or args.parent_step is not None) and not args.config:
        parser.error("--parent-experiment-id/--parent-step are only valid with --config")
    try:
        profiles = parse_profiles(args.profiles)
    except ValueError as exc:
        parser.error(str(exc))

    prompts = list(args.prompt)
    if args.prompt_file:
        prompts.extend(
            line.strip()
            for line in Path(args.prompt_file).read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    if not prompts:
        prompts = list(DEFAULT_PROMPTS)

    system_text, system_label = resolve_system_prompt(args.system_prompt)
    priming_turns = load_priming_turns(args.priming_turns)
    if any(PROFILE_SETTINGS[name]["system"] for name in profiles) and not system_text:
        parser.error("system/full requested but --system-prompt resolves to none")
    if any(PROFILE_SETTINGS[name]["prime"] for name in profiles) and not priming_turns:
        parser.error("prime/inference/full requested but --priming-turns resolves to nothing")

    device_type = autodetect_device_type() if not args.device_type else args.device_type
    _, _, _, _, device = compute_init(device_type)
    model, tokenizer, meta, model_label = load_probe_model(args, device)
    engine = Engine(model, tokenizer)
    results = []

    print(f"Model: {model_label}; step={meta.get('step', args.step)}")
    print(f"System prompt: {system_label}; priming turns: {len(priming_turns)}")
    print(f"Profiles: {', '.join(profiles)}; temperature={args.temperature}")
    for user_text in prompts:
        row = {"input": user_text, "profiles": {}}
        print("=" * 78)
        print(f"INPUT: {user_text!r}")
        for profile in profiles:
            prepared = prepare_profile(profile, user_text, system_text, priming_turns)
            prompt = build_prompt(
                tokenizer,
                prepared["sent"],
                prepared["system_text"],
                prepared["priming_turns"],
            )
            synchronize(device)
            started = time.perf_counter()
            if prepared["backend"] == "native":
                completion = generate_native(model, tokenizer, prompt, args)
            else:
                completion = generate_engine(engine, prompt, args)
            synchronize(device)
            elapsed = time.perf_counter() - started
            reply = tokenizer.decode(completion).strip()
            entry = {
                **prepared,
                "system_text": bool(prepared["system_text"]),
                "priming_turns": len(prepared["priming_turns"]),
                "prompt_tokens": len(prompt),
                "reply": reply,
                "elapsed_seconds": elapsed,
            }
            row["profiles"][profile] = entry
            print(
                f"--- {profile} | sent={prepared['sent']!r} | "
                f"prompt={len(prompt)} tok | {elapsed:.2f}s"
            )
            print(reply)
        results.append(row)
        print()

    if args.out:
        payload = {
            "model": model_label,
            "checkpoint_step": meta.get("step", args.step),
            "profiles": profiles,
            "system_prompt": system_label,
            "priming_turns": args.priming_turns,
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "results": results,
        }
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        temporary.replace(output)
        print(f"Wrote {output}")


if __name__ == "__main__":
    main()
