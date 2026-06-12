"""Migrate the pre-lineage Hugging Face model repo into the canonical layout.

The default is a dry run. With --apply, the script copies objects server-side,
verifies destination sizes, and only then deletes superseded visible paths.
"""

import argparse
import json
import os
from pathlib import Path

from huggingface_hub import (
    CommitOperationAdd,
    CommitOperationCopy,
    CommitOperationDelete,
    HfApi,
)

DEFAULT_REPO = "jbduran/think.nano"
ARCHIVE_ROOT = "archive/pre-lineage-v1"
D12_FLOPS_PER_TOKEN = 887_097_900.0
BASE_BATCH_TOKENS = 524_288


def chunks(values, size=50):
    for index in range(0, len(values), size):
        yield values[index:index + size]


def file_inventory(api, repo_id):
    entries = api.list_repo_tree(
        repo_id,
        recursive=True,
        expand=True,
        repo_type="model",
    )
    return {
        entry.path: {
            "size": getattr(entry, "size", None),
            "oid": getattr(entry, "blob_id", None),
        }
        for entry in entries
        if (
            hasattr(entry, "path")
            and getattr(entry, "size", None) is not None
            and not entry.path.endswith("/")
        )
    }


def prefix_mapping(inventory, source, destination):
    source = source.rstrip("/")
    destination = destination.rstrip("/")
    return [
        (path, f"{destination}/{path[len(source) + 1:]}")
        for path in sorted(inventory)
        if path.startswith(source + "/")
    ]


def metadata_operations(repo_root, inventory):
    configs = repo_root / "configs"
    records = [
        (
            configs / "base" / "think-d12-r11.25.json",
            "experiments/think-d12-r11.25/config.json",
            {
                "stage": "base",
                "experiment_id": "think-d12-r11.25",
                "base_experiment_id": "think-d12-r11.25",
                "parent_experiment_id": None,
                "parent_checkpoint_step": None,
                "checkpoint_step": 2362,
                "training_tokens": 2362 * BASE_BATCH_TOKENS,
                "flops_per_token": D12_FLOPS_PER_TOKEN,
                "stage_training_flops": (
                    2362 * BASE_BATCH_TOKENS * D12_FLOPS_PER_TOKEN
                ),
                "inherited_parent_flops": 0.0,
                "cumulative_pipeline_training_flops": (
                    2362 * BASE_BATCH_TOKENS * D12_FLOPS_PER_TOKEN
                ),
            },
        ),
        (
            configs / "base" / "think-d12-r20.json",
            "experiments/think-d12-r20/config.json",
            {
                "stage": "base",
                "experiment_id": "think-d12-r20",
                "base_experiment_id": "think-d12-r20",
                "parent_experiment_id": None,
                "parent_checkpoint_step": None,
                "checkpoint_step": 4200,
                "training_tokens": 4200 * BASE_BATCH_TOKENS,
                "flops_per_token": D12_FLOPS_PER_TOKEN,
                "stage_training_flops": (
                    4200 * BASE_BATCH_TOKENS * D12_FLOPS_PER_TOKEN
                ),
                "inherited_parent_flops": 0.0,
                "cumulative_pipeline_training_flops": (
                    4200 * BASE_BATCH_TOKENS * D12_FLOPS_PER_TOKEN
                ),
            },
        ),
        (
            configs / "sft" / "smoltalk-mmlu3-gsm8k4-v1.json",
            (
                "experiments/think-d12-r11.25/sft/"
                "smoltalk-mmlu3-gsm8k4-v1/config.json"
            ),
            {
                "stage": "sft",
                "experiment_id": "smoltalk-mmlu3-gsm8k4-v1",
                "base_experiment_id": "think-d12-r11.25",
                "parent_experiment_id": "think-d12-r11.25",
                "parent_checkpoint_step": 2362,
                "checkpoint_step": 1065,
                "training_tokens": 1065 * BASE_BATCH_TOKENS,
                "flops_per_token": D12_FLOPS_PER_TOKEN,
                "stage_training_flops": (
                    1065 * BASE_BATCH_TOKENS * D12_FLOPS_PER_TOKEN
                ),
                "inherited_parent_flops": (
                    2362 * BASE_BATCH_TOKENS * D12_FLOPS_PER_TOKEN
                ),
                "cumulative_pipeline_training_flops": (
                    (2362 + 1065) * BASE_BATCH_TOKENS * D12_FLOPS_PER_TOKEN
                ),
                "lineage_inferred_from_checkpoint_metadata": True,
            },
        ),
    ]
    operations = []
    for config_path, remote_path, summary in records:
        if remote_path not in inventory:
            operations.append(
                CommitOperationAdd(
                    path_in_repo=remote_path,
                    path_or_fileobj=config_path.read_bytes(),
                )
            )
        base = remote_path.rsplit("/", 1)[0]
        run = {
            "experiment_id": summary["experiment_id"],
            "stage": summary["stage"],
            "wandb_run_id": None,
            "migration_note": "Migrated from the pre-lineage repository layout.",
        }
        run_path = f"{base}/run.json"
        summary_path = f"{base}/summary.json"
        if run_path not in inventory:
            operations.append(CommitOperationAdd(
                path_in_repo=run_path,
                path_or_fileobj=(json.dumps(run, indent=2) + "\n").encode(),
            ))
        if summary_path not in inventory:
            operations.append(CommitOperationAdd(
                path_in_repo=summary_path,
                path_or_fileobj=(json.dumps(summary, indent=2) + "\n").encode(),
            ))
    completed_climbmix = (
        configs / "base" / "climbmix-d12-1epoch-25shards.json"
    )
    operations.append(CommitOperationAdd(
        path_in_repo="experiments/climbmix-d12-1epoch-25shards/config.json",
        path_or_fileobj=completed_climbmix.read_bytes(),
    ))
    return operations


def build_plan(inventory):
    canonical = []
    archive = []
    removals = set()

    migrations = [
        (
            "base_checkpoints/d12",
            "experiments/think-d12-r11.25/base_checkpoints",
        ),
        (
            "base_checkpoints/d12-ratio20",
            "experiments/think-d12-r20/base_checkpoints",
        ),
        (
            "chatsft_checkpoints/d12",
            (
                "experiments/think-d12-r11.25/sft/"
                "smoltalk-mmlu3-gsm8k4-v1/checkpoints"
            ),
        ),
    ]
    for source, destination in migrations:
        pairs = prefix_mapping(inventory, source, destination)
        canonical.extend(pairs)
        archive.extend(prefix_mapping(inventory, source, f"{ARCHIVE_ROOT}/{source}"))
        removals.update(source_path for source_path, _ in pairs)

    tokenizer_pairs = prefix_mapping(
        inventory, "tokenizer", "experiments/think-d12-r11.25/tokenizer"
    )
    tokenizer_pairs += prefix_mapping(
        inventory, "tokenizer", "experiments/think-d12-r20/tokenizer"
    )
    canonical.extend(tokenizer_pairs)
    archive.extend(prefix_mapping(inventory, "tokenizer", f"{ARCHIVE_ROOT}/tokenizer"))
    removals.update(
        path for path in inventory if path.startswith("tokenizer/")
    )

    incomplete = "experiments/climbmix-d12-r12-baseline-v2"
    archive.extend(prefix_mapping(
        inventory,
        incomplete,
        f"{ARCHIVE_ROOT}/{incomplete}",
    ))
    removals.update(
        path for path in inventory if path.startswith(incomplete + "/")
    )
    return canonical, archive, sorted(removals)


def verify_pairs(inventory, pairs):
    errors = []
    for source, destination in pairs:
        source_info = inventory.get(source)
        destination_info = inventory.get(destination)
        if destination_info is None:
            errors.append(f"missing destination: {destination}")
            continue
        if (
            source_info.get("size") is not None
            and destination_info.get("size") != source_info.get("size")
        ):
            errors.append(
                f"size mismatch: {source} -> {destination} "
                f"({source_info.get('size')} != {destination_info.get('size')})"
            )
        if (
            source_info.get("oid")
            and destination_info.get("oid")
            and destination_info.get("oid") != source_info.get("oid")
        ):
            errors.append(
                f"object identity mismatch: {source} -> {destination}"
            )
    if errors:
        raise RuntimeError("\n".join(errors))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    api = HfApi(token=os.environ.get("HF_TOKEN"))
    inventory = file_inventory(api, args.repo)
    canonical, archive, removals = build_plan(inventory)
    copies = canonical + archive

    print(f"Repository: {args.repo}")
    print(f"Canonical copies: {len(canonical)}")
    print(f"Archive copies:   {len(archive)}")
    print(f"Visible deletes:  {len(removals)}")
    for source, destination in copies:
        print(f"COPY {source} -> {destination}")
    for path in removals:
        print(f"DELETE {path}")
    if not args.apply:
        print("Dry run only. Re-run with --apply to mutate the repository.")
        return

    copy_operations = [
        CommitOperationCopy(src_path_in_repo=source, path_in_repo=destination)
        for source, destination in copies
        if destination not in inventory
    ]
    for index, operations in enumerate(chunks(copy_operations), start=1):
        api.create_commit(
            repo_id=args.repo,
            repo_type="model",
            operations=operations,
            commit_message=f"Lineage migration copy batch {index}",
        )

    updated = file_inventory(api, args.repo)
    verify_pairs(updated, copies)

    repo_root = Path(__file__).resolve().parents[1]
    metadata = metadata_operations(repo_root, updated)
    readme = """---
library_name: pytorch
tags:
- nanochat
- language-model
---
# think.nano

Durable model artifacts for lineage-aware nanochat experiments.

Each base experiment owns its tokenizer and base checkpoints. SFT runs are
nested under their exact base parent, and post-training runs are nested under
their exact SFT parent. Legacy paths are retained under `archive/pre-lineage-v1`.
"""
    metadata.append(CommitOperationAdd(
        path_in_repo="README.md",
        path_or_fileobj=readme.encode(),
    ))
    for index, operations in enumerate(chunks(metadata), start=1):
        api.create_commit(
            repo_id=args.repo,
            repo_type="model",
            operations=operations,
            commit_message=f"Add lineage metadata batch {index}",
        )

    for index, paths in enumerate(chunks(removals), start=1):
        api.create_commit(
            repo_id=args.repo,
            repo_type="model",
            operations=[CommitOperationDelete(path_in_repo=path) for path in paths],
            commit_message=f"Archive superseded visible paths batch {index}",
        )
    print("Migration complete. Canonical and archive copies were verified before deletion.")


if __name__ == "__main__":
    main()
