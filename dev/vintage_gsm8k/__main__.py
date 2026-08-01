"""Command-line interface for `python -m dev.vintage_gsm8k`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import DEFAULT_ARTIFACT_ROOT, PipelinePaths
from .pipeline import judge, package, prepare, report, rewrite, status, verify
from .prefilter import prefilter
from .publication import publish_publications, stage_publications


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Adapt official GSM8K for the Vintage model")
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=DEFAULT_ARTIFACT_ROOT,
        help="pipeline state directory (default: artifacts/vintage-gsm8k)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="snapshot and normalize official GSM8K")
    prepare_parser.add_argument("--revision", default="main")

    prefilter_parser = subparsers.add_parser("prefilter", help="run the tiered regex/date prefilter")
    prefilter_parser.add_argument("--revision", default="main", help="official GSM8K revision")
    prefilter_parser.add_argument("--policy-revision", default="main", help="banned-list dataset revision")

    judge_parser = subparsers.add_parser("judge", help="run or resume temporal judging")
    judge_parser.add_argument("--revision", default="main")
    judge_parser.add_argument("--sample-per-split", type=int)
    judge_parser.add_argument("--batch-size", type=int, default=32)
    judge_parser.add_argument("--workers", type=int, default=8)
    judge_parser.add_argument("--max-tokens", type=int, default=8192)
    judge_parser.add_argument("--max-items", type=int, help="limit unresolved rows for a probe")

    subparsers.add_parser("status", help="show resumable stage counts")
    subparsers.add_parser("report", help="regenerate review artifacts without model calls")

    rewrite_parser = subparsers.add_parser("rewrite", help="rewrite reviewer-approved rows")
    rewrite_parser.add_argument("--workers", type=int, default=16)
    rewrite_parser.add_argument("--max-attempts", type=int, default=3)
    rewrite_parser.add_argument("--max-items", type=int)

    verify_parser = subparsers.add_parser("verify", help="run deterministic and independent checks")
    verify_parser.add_argument("--workers", type=int, default=8)
    verify_parser.add_argument("--max-items", type=int)

    subparsers.add_parser("package", help="write final train/test JSONL after every gate passes")

    subparsers.add_parser("stage-publication", help="build filtered and rewritten upload directories")
    publish_parser = subparsers.add_parser("publish", help="publish two public Hugging Face datasets")
    publish_parser.add_argument("--namespace")
    publish_parser.add_argument("--filtered-name", default="vintage-gsm8k-filtered")
    publish_parser.add_argument("--rewritten-name", default="vintage-gsm8k")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = PipelinePaths(args.artifact_root)
    if args.command == "prepare":
        result = prepare(paths, revision=args.revision)
    elif args.command == "prefilter":
        prepare(paths, revision=args.revision)
        result = prefilter(paths, policy_revision=args.policy_revision)
    elif args.command == "judge":
        result = judge(
            paths,
            revision=args.revision,
            sample_per_split=args.sample_per_split,
            batch_size=args.batch_size,
            workers=args.workers,
            max_tokens=args.max_tokens,
            max_items=args.max_items,
        )
    elif args.command == "status":
        result = status(paths)
    elif args.command == "report":
        result = report(paths)
    elif args.command == "rewrite":
        result = rewrite(
            paths,
            workers=args.workers,
            max_attempts=args.max_attempts,
            max_items=args.max_items,
        )
    elif args.command == "verify":
        result = verify(paths, workers=args.workers, max_items=args.max_items)
    elif args.command == "package":
        result = package(paths)
    elif args.command == "stage-publication":
        result = stage_publications(paths)
    elif args.command == "publish":
        result = publish_publications(
            paths,
            namespace=args.namespace,
            filtered_name=args.filtered_name,
            rewritten_name=args.rewritten_name,
        )
    else:  # argparse makes this unreachable
        raise AssertionError(args.command)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
