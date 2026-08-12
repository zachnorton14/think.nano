"""Command-line entry point for the HISTORY-EVENT reconstruction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import DEFAULT_ARTIFACT_ROOT, PipelinePaths
from .gold import generate_gold_report, gold_status, run_gold
from .io import read_json
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
    else:  # pragma: no cover - argparse enforces subcommands
        raise AssertionError(args.command)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
