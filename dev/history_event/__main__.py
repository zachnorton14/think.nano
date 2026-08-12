"""Command-line entry point for the HISTORY-EVENT reconstruction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import DEFAULT_ARTIFACT_ROOT, DEFAULT_DATASET_REPO, PipelinePaths
from .gold import generate_gold_report, gold_status, run_gold
from .io import read_json
from .publication import package_dataset, publish_dataset
from .models import MODEL_SPECS
from .scoring import score_events
from .source import prepare


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare", help="fetch and parse pinned Wikipedia revisions")
    prepare_parser.add_argument("--refresh", action="store_true", help="fetch snapshots even if cached")
    gold_parser = commands.add_parser("gold", help="generate and validate DeepSeek reference answers")
    gold_parser.add_argument("--probe", action="store_true", help="run only a two-row paid-route probe")
    gold_parser.add_argument("--batch-size", type=int, default=8)
    gold_parser.add_argument("--workers", type=int, default=64)
    commands.add_parser("status", help="show source and gold progress")
    commands.add_parser("report", help="regenerate the gold audit report")
    commands.add_parser("package", help="build and validate the Hugging Face package")
    publish_parser = commands.add_parser("publish", help="upload the package to Hugging Face")
    publish_parser.add_argument("--repo-id", default=DEFAULT_DATASET_REPO)
    publish_parser.add_argument("--private", action="store_true")
    score_parser = commands.add_parser("score", help="score semantic targets in bits per UTF-8 byte")
    score_parser.add_argument("--model", required=True, choices=sorted(MODEL_SPECS))
    score_parser.add_argument("--events", type=Path)
    score_parser.add_argument("--output-dir", type=Path)
    score_parser.add_argument("--cache-dir", type=Path, default=Path("/tmp/history-event-model-cache"))
    score_parser.add_argument("--device", default="cuda")
    score_parser.add_argument("--limit", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = PipelinePaths(args.artifacts)
    if args.command == "prepare":
        result = prepare(paths, refresh=args.refresh)
    elif args.command == "gold":
        result = run_gold(
            paths, batch_size=args.batch_size, workers=args.workers, probe_only=args.probe
        )
    elif args.command == "status":
        result = {
            "source": read_json(paths.manifest)["counts"] if paths.manifest.exists() else None,
            "gold": gold_status(paths) if paths.recall_candidates.exists() else None,
        }
    elif args.command == "report":
        result = generate_gold_report(paths)
    elif args.command == "package":
        result = package_dataset(paths)
    elif args.command == "publish":
        result = publish_dataset(paths, repo_id=args.repo_id, private=args.private)
    elif args.command == "score":
        events_path = args.events or paths.events
        output_dir = args.output_dir or (paths.results_dir / args.model)
        result = score_events(
            model_id=args.model,
            events_path=events_path,
            output_dir=output_dir,
            cache_dir=args.cache_dir,
            device=args.device,
            limit=args.limit,
        )
    else:  # pragma: no cover - argparse enforces subcommands
        raise AssertionError(args.command)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
