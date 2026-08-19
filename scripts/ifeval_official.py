"""Fetch and run the pinned official Google Research IFEval scorer."""

import argparse
import hashlib
import importlib
import json
import os
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

from scripts.ifeval_common import merge_shards, read_inputs


GOOGLE_RESEARCH_REVISION = "1eb8bb0cbe5fd9072311ae3fd760e3644fee690b"
FILES = {
    "instructions.py": "60e086f5342a03ce8e18b64bbcccf86308f523c08aa826707a562150a52f3edf",
    "evaluation_lib.py": "35decc06000718487f44d7deafa6d3f48a8ec0886281edf40162c0265b7d248c",
    "instructions_registry.py": "ec92d72c264f6d906978613085db262356174300370a3fffe6fefd5969ce9cfc",
    "instructions_util.py": "a73797261eee5bf447e279d82a2b700b1bdd3cb1193412dbab1270a85832bc6b",
    "data/input_data.jsonl": "67ffeee0fcb87c317c5b08a2de85557b4a7e96ada6178aa645b4954fe4b53d49",
}


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare(destination):
    root = Path(destination)
    package = root / "instruction_following_eval"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").touch()
    base = (
        "https://raw.githubusercontent.com/google-research/google-research/"
        f"{GOOGLE_RESEARCH_REVISION}/instruction_following_eval"
    )
    for relative, expected in FILES.items():
        output = package / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        if not output.exists() or _sha256(output) != expected:
            temporary = output.with_suffix(output.suffix + ".tmp")
            urllib.request.urlretrieve(f"{base}/{relative}", temporary)
            if _sha256(temporary) != expected:
                temporary.unlink(missing_ok=True)
                raise RuntimeError(f"Checksum mismatch for official IFEval {relative}")
            os.replace(temporary, output)
    print(f"Official IFEval ready at {package}")
    print(f"Input rows: {len(read_inputs(package / 'data/input_data.jsonl'))}")
    return package


def _metrics(outputs):
    prompt_correct = sum(output.follow_all_instructions for output in outputs)
    instruction_total = sum(len(output.follow_instruction_list) for output in outputs)
    instruction_correct = sum(
        sum(output.follow_instruction_list) for output in outputs
    )
    tier0_total = defaultdict(int)
    tier0_correct = defaultdict(int)
    tier1_total = defaultdict(int)
    tier1_correct = defaultdict(int)
    for output in outputs:
        for instruction_id, followed in zip(
            output.instruction_id_list, output.follow_instruction_list
        ):
            tier0 = instruction_id.split(":")[0]
            tier0_total[tier0] += 1
            tier0_correct[tier0] += int(followed)
            tier1_total[instruction_id] += 1
            tier1_correct[instruction_id] += int(followed)
    return {
        "prompt_level_accuracy": prompt_correct / len(outputs),
        "instruction_level_accuracy": instruction_correct / instruction_total,
        "prompt_correct": prompt_correct,
        "prompt_total": len(outputs),
        "instruction_correct": instruction_correct,
        "instruction_total": instruction_total,
        "tier0": {
            key: tier0_correct[key] / tier0_total[key] for key in sorted(tier0_total)
        },
        "tier1": {
            key: tier1_correct[key] / tier1_total[key] for key in sorted(tier1_total)
        },
    }


def score(official_root, predictions, output_dir, model_id, allow_partial=False):
    package = prepare(official_root)
    sys.path.insert(0, str(package.parent))
    evaluation_lib = importlib.import_module(
        "instruction_following_eval.evaluation_lib"
    )
    all_inputs = evaluation_lib.read_prompt_list(package / "data/input_data.jsonl")
    rows = [json.loads(line) for line in Path(predictions).read_text().splitlines() if line]
    if not rows or len(rows) > 541:
        raise ValueError(f"Predictions must contain 1 to 541 rows, found {len(rows)}")
    if not allow_partial and len(rows) != 541:
        raise ValueError(f"Predictions must contain 541 rows, found {len(rows)}")
    if any(row.get("model_id") != model_id for row in rows):
        raise ValueError(f"Predictions contain a model other than {model_id!r}")
    prompt_to_response = {row["prompt"]: row["response"] for row in rows}
    if len(prompt_to_response) != len(rows):
        raise ValueError("Predictions contain duplicate prompts")
    expected_prompts = {row.prompt for row in all_inputs}
    if not set(prompt_to_response).issubset(expected_prompts):
        raise ValueError("Prediction prompts are not a subset of official IFEval")
    inputs = [row for row in all_inputs if row.prompt in prompt_to_response]
    if len(inputs) != len(rows):
        raise ValueError("Prediction prompts do not uniquely match official IFEval")
    generation_settings = {
        (
            int(row.get("max_tokens", -1)),
            float(row.get("temperature", -1)),
            row.get("system_prompt"),
        )
        for row in rows
    }
    if len(generation_settings) != 1:
        raise ValueError("Prediction rows do not share one generation configuration")
    max_tokens, temperature, system_prompt = generation_settings.pop()

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema_version": 1,
        "model_id": model_id,
        "official_repository": "google-research/google-research",
        "official_revision": GOOGLE_RESEARCH_REVISION,
        "input_rows": len(inputs),
        "complete": len(inputs) == 541,
        "generation": {
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system_prompt": system_prompt,
        },
    }
    for label, function in (
        ("strict", evaluation_lib.test_instruction_following_strict),
        ("loose", evaluation_lib.test_instruction_following_loose),
    ):
        outputs = [function(row, prompt_to_response) for row in inputs]
        evaluation_lib.write_outputs(destination / f"eval_results_{label}.jsonl", outputs)
        summary[label] = _metrics(outputs)
    temporary = destination / "summary.json.tmp"
    temporary.write_text(json.dumps(summary, indent=2) + "\n")
    os.replace(temporary, destination / "summary.json")
    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--destination", required=True)
    merge_parser = subparsers.add_parser("merge")
    merge_parser.add_argument("--input", required=True)
    merge_parser.add_argument("--shard", action="append", required=True)
    merge_parser.add_argument("--output", required=True)
    merge_parser.add_argument("--model-id", required=True)
    score_parser = subparsers.add_parser("score")
    score_parser.add_argument("--official-root", required=True)
    score_parser.add_argument("--predictions", required=True)
    score_parser.add_argument("--output-dir", required=True)
    score_parser.add_argument("--model-id", required=True)
    score_parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.destination)
    elif args.command == "merge":
        print(merge_shards(args.input, args.shard, args.output, args.model_id))
    else:
        score(
            args.official_root,
            args.predictions,
            args.output_dir,
            args.model_id,
            allow_partial=args.allow_partial,
        )


if __name__ == "__main__":
    main()
