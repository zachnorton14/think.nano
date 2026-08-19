"""Compare the unpunctuated-input fixes on one checkpoint, side by side.

The complaint is that the model degrades when a visitor types without
punctuation. This script makes that concrete: for each probe it generates the
same question five ways and prints them together.

    control  the well-formed question, no shaping        <- the ceiling
    raw      the unpunctuated question, no shaping       <- the floor
    period   unpunctuated + a bare "." appended
    repair   unpunctuated + "." or "?" per the question heuristic
    prime    unpunctuated + an invisible priming exchange
    both     repair + prime

`control` is what makes this a measurement instead of a vibe check: a fix is
working when its replies read like the control's, not merely better than raw.

`period` against `repair` is the other comparison worth having: the mark the
repair picks comes from a word-list heuristic (prompt_shaping.looks_like_question),
and if the two conditions read the same, drop the heuristic and always append ".".

Greedy by default (temperature 0) so a difference between conditions is the
condition and not the sampler.

    python -m scripts.punctuation_probe \
        --model-tag Think.Unbounded-d32-v2mix-cont-pre1930-curriculum-c3-robust-v2 \
        --system-prompt-file configs/system_prompts/pre1930-companion.txt \
        --priming-turns configs/priming_turns/pre1930-companion.json \
        --out dev/punctuation_probe.json
"""

import argparse
import json


from nanochat.checkpoint_manager import load_model, load_model_from_checkpoint_dir
from nanochat.common import autodetect_device_type, compute_init
from nanochat.engine import Engine
from nanochat.prompt_shaping import load_priming_turns, repair_user_text

# (unpunctuated as a visitor would type it, well-formed control).
# Deliberately spans the shapes that fail differently: bare nouns and
# declarations with no question in them at all, casual fragments, and ordinary
# questions missing only their mark.
PROBES = [
    ("texas", "Tell me about Texas."),
    ("i love you", "I love you."),
    ("whats the weather like", "What is the weather like?"),
    ("how do i read a sextant", "How do I read a sextant?"),
    ("tell me a joke", "Tell me a joke."),
    ("who was napoleon", "Who was Napoleon?"),
    ("my father died last week", "My father died last week."),
    ("whats the fastest way to get to chicago", "What is the fastest way to get to Chicago?"),
    ("do you like poetry", "Do you like poetry?"),
    ("explain the tides", "Explain the tides."),
    ("hello", "Hello."),
    ("k", "All right."),
]


def build_prompt(tokenizer, text, system_text, priming):
    """Render one single-turn conversation, primed for the assistant.

    Matches the convention in scripts/chat_web.py: no system special token, so
    the system prompt is merged into the first user turn -- which is the first
    priming turn when priming is on, exactly as the server renders it.
    """
    bos = tokenizer.get_bos_token_id()
    user_start = tokenizer.encode_special("<|user_start|>")
    user_end = tokenizer.encode_special("<|user_end|>")
    assistant_start = tokenizer.encode_special("<|assistant_start|>")
    assistant_end = tokenizer.encode_special("<|assistant_end|>")

    out = [bos]
    turns = [*priming, {"role": "user", "content": text}]
    for i, message in enumerate(turns):
        content = message["content"]
        if i == 0 and system_text and message["role"] == "user":
            content = f"{system_text}\n\n{content}"
        start, end = (user_start, user_end) if message["role"] == "user" else (assistant_start, assistant_end)
        out.append(start)
        out.extend(tokenizer.encode(content))
        out.append(end)
    out.append(assistant_start)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-i', '--source', type=str, default="sft", help="Source of the model: sft|rl")
    parser.add_argument('-g', '--model-tag', type=str, default=None, help='Model tag to load')
    parser.add_argument('-s', '--step', type=int, default=None, help='Step to load')
    parser.add_argument('--checkpoint-dir', type=str, default=None, help='Exact checkpoint directory (overrides model-tag lookup)')
    parser.add_argument('--tokenizer-dir', type=str, default=None, help='Tokenizer directory')
    parser.add_argument('--system-prompt-file', type=str, default='', help='Serve with this system prompt, as the deployment does')
    parser.add_argument('--priming-turns', type=str, default='default', help="Priming exchange for the prime/both conditions: 'default' or a path to JSON")
    parser.add_argument('-t', '--temperature', type=float, default=0.0, help='0.0 = greedy, so differences are the condition and not the sampler')
    parser.add_argument('-k', '--top-k', type=int, default=50, help='Top-k sampling parameter (ignored when greedy)')
    parser.add_argument('-m', '--max-tokens', type=int, default=200, help='Generation cap per reply')
    parser.add_argument('--conditions', type=str, default='control,raw,period,repair,prime,both', help='Comma-separated subset to run')
    parser.add_argument('--out', type=str, default='', help='Also write the raw results here as JSON')
    parser.add_argument('--device-type', type=str, default='', choices=['cuda', 'cpu', 'mps'], help='empty => autodetect')
    args = parser.parse_args()

    conditions = [c.strip() for c in args.conditions.split(',') if c.strip()]
    known = {"control", "raw", "period", "repair", "prime", "both"}
    unknown = set(conditions) - known
    if unknown:
        parser.error(f"unknown condition(s): {sorted(unknown)}; pick from {sorted(known)}")

    system_text = ""
    if args.system_prompt_file:
        with open(args.system_prompt_file, "r", encoding="utf-8") as f:
            system_text = f.read().strip()
    priming = load_priming_turns(args.priming_turns)
    if not priming and ({"prime", "both"} & set(conditions)):
        parser.error("--priming-turns resolved to nothing, so the prime/both conditions have no fix to test")

    device_type = autodetect_device_type() if args.device_type == "" else args.device_type
    _, _, _, _, device = compute_init(device_type)
    if args.checkpoint_dir:
        model, tokenizer, meta = load_model_from_checkpoint_dir(
            args.checkpoint_dir, device, phase="eval", step=args.step,
            tokenizer_dir=args.tokenizer_dir)
    else:
        model, tokenizer, meta = load_model(
            args.source, device, phase="eval", model_tag=args.model_tag, step=args.step)
    engine = Engine(model, tokenizer)

    # (text to send, priming turns to prepend) per condition.
    def variants(bad, good):
        return {
            "control": (good, []),
            "raw": (bad, []),
            "period": (repair_user_text(bad, question_mark=False), []),
            "repair": (repair_user_text(bad), []),
            "prime": (bad, priming),
            "both": (repair_user_text(bad), priming),
        }

    results = []
    for bad, good in PROBES:
        row = {"raw_input": bad, "control_input": good, "replies": {}}
        for condition in conditions:
            text, prefix = variants(bad, good)[condition]
            prompt = build_prompt(tokenizer, text, system_text, prefix)
            generated, _ = engine.generate_batch(
                prompt, num_samples=1, max_tokens=args.max_tokens,
                temperature=args.temperature, top_k=args.top_k,
            )
            # generate_batch already drops the terminal assistant_end/bos.
            completion = generated[0][len(prompt):]
            row["replies"][condition] = {
                "sent": text,
                "reply": tokenizer.decode(completion).strip(),
                "prompt_tokens": len(prompt),
            }
        results.append(row)
        print("=" * 78)
        print(f"typed: {bad!r}")
        for condition in conditions:
            entry = row["replies"][condition]
            print(f"--- {condition} ({entry['prompt_tokens']} prompt tokens) — sent {entry['sent']!r}")
            print(entry["reply"])
        print()

    if args.out:
        payload = {
            "model_tag": args.model_tag or args.checkpoint_dir,
            "step": args.step,
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "system_prompt_file": args.system_prompt_file,
            "priming_turns": priming,
            "conditions": conditions,
            "results": results,
        }
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"wrote {args.out}")

    # Reply length is the one thing worth reporting without a human in the loop:
    # the observed failure is short, clipped, off-register replies, so a
    # condition that does not move the mean length is unlikely to have fixed it.
    print("=" * 78)
    print("mean reply length in characters (a proxy, not a score):")
    for condition in conditions:
        lengths = [len(r["replies"][condition]["reply"]) for r in results]
        print(f"  {condition:<8} {sum(lengths) / len(lengths):6.1f}")


if __name__ == "__main__":
    main()
