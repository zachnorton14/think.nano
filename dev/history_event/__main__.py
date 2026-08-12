"""Command-line entry point for the HISTORY-EVENT reconstruction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import DEFAULT_ARTIFACT_ROOT, PipelinePaths
from .source import prepare


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare", help="fetch and parse pinned Wikipedia revisions")
    prepare_parser.add_argument("--refresh", action="store_true", help="fetch snapshots even if cached")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = PipelinePaths(args.artifacts)
    if args.command == "prepare":
        result = prepare(paths, refresh=args.refresh)
    else:  # pragma: no cover - argparse enforces subcommands
        raise AssertionError(args.command)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
