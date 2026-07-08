"""Shared HF auth + repo/shard helpers for all pipeline stages.

Token resolution order: HF_TOKEN env var (set by the notebook from a Colab
secret) -> already-cached huggingface_hub login. Importing this module logs in
and constructs the HfApi client once.
"""
import os
import re
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download, login

import config


def get_token():
    tok = os.environ.get("HF_TOKEN")
    if not tok:
        # Fall back to any cached credential; raises later if a write is attempted
        # without one. The notebook is expected to export HF_TOKEN.
        tok = None
    return tok


HF_TOKEN = get_token()
if HF_TOKEN:
    login(token=HF_TOKEN, add_to_git_credential=False)
api = HfApi(token=HF_TOKEN)


def ensure_dst_repo():
    """Create the destination dataset repo if it does not exist yet (no-op after)."""
    api.create_repo(repo_id=config.DST_REPO, repo_type="dataset", exist_ok=True, private=False)


def list_repo_files_safe(repo_id):
    try:
        return api.list_repo_files(repo_id=repo_id, repo_type="dataset")
    except Exception as exc:
        print(f"Could not list {repo_id}: {exc}")
        return []


_SHARD_RE = re.compile(r"(^|.*/)shard_\d+\.parquet$")


def source_shards(repo_id=None, prefix="", root_only=False):
    """List shard paths in a repo.

    - prefix="foo": only shards under `foo/` (e.g. the stripped layer).
    - root_only=True: only shards at the repo root (no `/` in the path). Use this
      for the clean source so a stray subfolder (e.g. `stripped/`) is never
      mistaken for input.
    Defaults to the FILTER's input (config.SRC_REPO). Returns repo-relative paths.
    """
    repo_id = repo_id or config.SRC_REPO
    files = list_repo_files_safe(repo_id)
    shards = sorted(p for p in files if _SHARD_RE.match(p))
    if not shards:
        shards = sorted(p for p in files if p.endswith(".parquet"))
    if prefix:
        pref = prefix.rstrip("/") + "/"
        shards = [p for p in shards if p.startswith(pref)]
    elif root_only:
        shards = [p for p in shards if "/" not in p]
    return shards


def destination_shards(prefix="", root_only=False):
    """Set of shard paths already present in DST_REPO.

    - prefix="foo": only shards under `foo/` (e.g. the stripped layer).
    - root_only=True: only shards at the repo root (the final filter outputs), so
      the stripped layer is never counted as a completed final shard.
    """
    files = list_repo_files_safe(config.DST_REPO)
    shards = set(p for p in files if _SHARD_RE.match(p))
    if prefix:
        pref = prefix.rstrip("/") + "/"
        shards = {p for p in shards if p.startswith(pref)}
    elif root_only:
        shards = {p for p in shards if "/" not in p}
    return shards


def output_path_for_source(path_in_repo):
    """Basename of a shard, dropping any prefix -- final output shards are at root."""
    return Path(path_in_repo).name


def download_source_shard(path_in_repo, repo_id=None):
    return hf_hub_download(
        repo_id=repo_id or config.SRC_REPO,
        repo_type="dataset",
        filename=path_in_repo,
        token=HF_TOKEN,
        local_dir=config.SRC_CACHE,
    )
