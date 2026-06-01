"""
Normalize an existing book-shard dataset to a UNIFORM shard size.

Reads shard_*.parquet (single `text` column) from a source — either a local
directory (--source-dir) or a HuggingFace dataset repo (--source-repo) — in
lexicographic order. The LAST shard is treated as the validation shard and is
copied through unchanged as the final output shard. All other (train) shards'
`text` rows are concatenated in order and re-chunked into uniform shards of
~--chars-per-shard characters each (default 250M chars ≈ ~100MB ZSTD-3, the
ClimbMix target). Output preserves nanochat conventions: single `text` column,
ZSTD-3, row_group_size, last-shard-is-val.

Re-chunking only redraws shard boundaries on the already-filtered / deduped /
shuffled text. It does NOT change which documents are present, their order, or
the validation set — so it cannot corrupt or bias the data. It only makes every
shard the same size.

Memory/disk: one input shard (~80MB) + one output buffer (~chars-per-shard) at
a time; with --upload-incremental each finished output shard is uploaded in
batches then deleted locally, so local disk stays small.

Examples:
    # Read uniform-ize a local dir in place-ish (writes to a new dir)
    python dev/repack_uniform_shards.py \
        --source-dir /content/base_data_books \
        --output-dir /content/base_data_books_uniform

    # Read from HF, write uniform shards to a NEW HF repo (safest)
    python dev/repack_uniform_shards.py \
        --source-repo jbduran/think-institutional-books \
        --output-dir /content/base_data_books_uniform \
        --upload-incremental --target-repo jbduran/think-institutional-books-uniform

Requires HF_TOKEN in .env when reading from / writing to HF.
"""

import argparse
import glob
import json
import os
import re
import tempfile
from datetime import datetime, timezone

import pyarrow.parquet as pq
from dotenv import find_dotenv, load_dotenv

# Reuse the battle-tested write + upload helpers from the main script.
from repackage_institutional_books import (
    write_shard, upload_batch_and_delete, _with_upload_retry,
)

SHARD_RE = re.compile(r"shard_(\d+)\.parquet$")


def resolve_source_shards(args, token):
    """Return (kind, sorted_list) where kind is 'local' or 'hf'.

    For 'local', list items are absolute paths. For 'hf', list items are
    repo-relative filenames (to be downloaded on demand).
    """
    if args.source_dir:
        paths = sorted(p for p in glob.glob(os.path.join(args.source_dir, "shard_*.parquet")))
        if not paths:
            raise SystemExit(f"No shard_*.parquet in {args.source_dir}")
        return "local", paths
    if args.source_repo:
        from huggingface_hub import HfApi
        api = HfApi(token=token)
        files = api.list_repo_files(repo_id=args.source_repo, repo_type="dataset")
        shards = sorted(f for f in files if SHARD_RE.search(f))
        if not shards:
            raise SystemExit(f"No shard_*.parquet in repo {args.source_repo}")
        return "hf", shards
    raise SystemExit("Provide --source-dir or --source-repo")


def open_source_table(kind, item, repo_id, token, tmpdir):
    """Read the `text` column of one source shard. Returns a pyarrow Array.

    For HF sources, download to a temp file (deleted by caller via tmpdir cleanup).
    """
    if kind == "local":
        return pq.read_table(item, columns=["text"]).column("text")
    from huggingface_hub import hf_hub_download
    local = hf_hub_download(
        repo_id=repo_id, repo_type="dataset", filename=item,
        local_dir=tmpdir, token=token,
    )
    arr = pq.read_table(local, columns=["text"]).column("text")
    try:
        os.remove(local)
    except OSError:
        pass
    return arr


def repack(args, token):
    os.makedirs(args.output_dir, exist_ok=True)
    kind, shards = resolve_source_shards(args, token)
    repo_id = args.source_repo  # None for local
    print(f"Source: {kind} | {len(shards)} shards "
          f"(train: {len(shards) - 1}, val: 1 -> {os.path.basename(str(shards[-1]))})")

    train_src = shards[:-1]
    val_src = shards[-1]

    # Upload target setup
    api = None
    pending = []
    if args.upload_incremental:
        from huggingface_hub import HfApi
        api = HfApi(token=token)
        api.create_repo(repo_id=args.target_repo, repo_type="dataset",
                        private=True, exist_ok=True)
        print(f"Uploading uniform shards -> {args.target_repo} (batches of {args.upload_batch})")

    out_index = 0
    out_docs = []
    out_chars = 0
    total_docs = 0
    total_chars = 0
    shard_records = []

    def flush_out(is_val=False):
        nonlocal out_index, out_docs, out_chars, total_docs, total_chars
        if not out_docs:
            return
        fname, _ = write_shard(args.output_dir, out_index, out_docs, args.row_group_size)
        shard_records.append({"index": out_index, "filename": fname,
                              "num_docs": len(out_docs), "num_chars": out_chars,
                              **({"is_val": True} if is_val else {})})
        total_docs += len(out_docs)
        total_chars += out_chars
        print(f"WROTE {fname} | docs={len(out_docs):,} chars={out_chars:,}"
              + ("  [VAL]" if is_val else ""))
        if api is not None:
            pending.append(fname)
            if len(pending) >= args.upload_batch:
                upload_batch_and_delete(api, args.target_repo, args.output_dir, list(pending))
                print(f"  uploaded batch of {len(pending)} (1 commit)")
                pending.clear()
        out_index += 1
        out_docs = []
        out_chars = 0

    # ---- Re-chunk train shards into uniform output shards ----
    with tempfile.TemporaryDirectory() as tmp:
        for i, item in enumerate(train_src):
            col = open_source_table(kind, item, repo_id, token, tmp)
            for s in col.to_pylist():
                if not s:
                    continue
                out_docs.append(s)
                out_chars += len(s)
                if out_chars >= args.chars_per_shard:
                    flush_out()
            if (i + 1) % 25 == 0 or i + 1 == len(train_src):
                print(f"  read {i + 1}/{len(train_src)} source train shards "
                      f"(out so far: {out_index} shards, {total_chars:,} chars, buf={out_chars:,})")
        # final partial train shard
        flush_out()

        # ---- Val shard: copy through unchanged as the final shard ----
        val_col = open_source_table(kind, val_src, repo_id, token, tmp)
        out_docs = [s for s in val_col.to_pylist() if s]
        out_chars = sum(len(s) for s in out_docs)
        flush_out(is_val=True)

    # ---- manifest + README ----
    manifest = {
        "operation": "repack_uniform_shards",
        "source": args.source_dir or args.source_repo,
        "chars_per_shard": args.chars_per_shard,
        "row_group_size": args.row_group_size,
        "compression": "zstd-3",
        "num_shards": len(shard_records),
        "total_docs": total_docs,
        "total_chars": total_chars,
        "shards": shard_records,
        "note": "Re-chunk of an existing dataset to uniform shard size; documents, "
                "order, and val set unchanged. Topic stats not recomputed (text-only).",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(os.path.join(args.output_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    readme = (
        f"# Uniform-shard repack\n\n"
        f"Re-chunked from `{args.source_dir or args.source_repo}` to uniform "
        f"~{args.chars_per_shard:,}-char shards (≈100MB ZSTD-3). "
        f"Single `text` column, last shard is validation. Documents, order, and "
        f"the val set are unchanged — only shard boundaries were redrawn.\n"
    )
    with open(os.path.join(args.output_dir, "README.md"), "w") as f:
        f.write(readme)

    # Upload remaining shards + metadata
    if api is not None:
        if pending:
            upload_batch_and_delete(api, args.target_repo, args.output_dir, list(pending))
            print(f"  uploaded final batch of {len(pending)} (1 commit)")
            pending.clear()
        present = [m for m in ("manifest.json", "README.md")
                   if os.path.exists(os.path.join(args.output_dir, m))]
        if present:
            _with_upload_retry(
                lambda: api.upload_folder(folder_path=args.output_dir, repo_id=args.target_repo,
                                          repo_type="dataset", allow_patterns=present,
                                          commit_message="Add README + manifest"),
                what="metadata")

    print("\n=== Repack done ===")
    print(f"Output: {args.output_dir}")
    print(f"Uniform shards: {len(shard_records)} (incl. 1 val) | total chars: {total_chars:,}")
    if api is not None:
        print(f"Uploaded to: https://huggingface.co/datasets/{args.target_repo}")
    sizes = [r["num_chars"] for r in shard_records[:-1]]  # exclude val
    if sizes:
        print(f"Train shard chars: min={min(sizes):,} max={max(sizes):,} "
              f"(target {args.chars_per_shard:,})")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--source-dir", type=str, help="Local dir of shard_*.parquet")
    src.add_argument("--source-repo", type=str, help="HF dataset repo id to read shards from")
    p.add_argument("--output-dir", type=str, required=True, help="Where to write uniform shards")
    p.add_argument("--chars-per-shard", type=int, default=250_000_000,
                   help="Target chars per output shard (default 250M ≈ 100MB)")
    p.add_argument("--row-group-size", type=int, default=64)
    p.add_argument("--upload-incremental", action="store_true",
                   help="Upload uniform shards to --target-repo in batches, deleting locally")
    p.add_argument("--upload-batch", type=int, default=50)
    p.add_argument("--target-repo", type=str, default=None,
                   help="HF repo to upload uniform shards to (required with --upload-incremental)")
    return p.parse_args()


def main():
    args = parse_args()
    if args.upload_incremental and not args.target_repo:
        raise SystemExit("--upload-incremental requires --target-repo")
    dp = find_dotenv(usecwd=True)
    if dp:
        load_dotenv(dp)
    token = os.getenv("HF_TOKEN")
    if (args.source_repo or args.upload_incremental) and not token:
        raise SystemExit("HF_TOKEN required for HF read/write. Put it in .env.")
    repack(args, token)


if __name__ == "__main__":
    main()
