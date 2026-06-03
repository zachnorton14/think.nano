"""
HuggingFace Hub sync helpers for the Gutenberg nanochat pipeline (gutenbergv3).

Storage layout
--------------
HF *dataset* repo  (raw Gutenberg book text, tokenizer-agnostic):
    data/shard_00000.parquet ...        # one 'text' column per row (a book)

HF *model* repo    (everything vocab-locked to the trained model):
    tokenizer/tokenizer.pkl
    tokenizer/token_bytes.pt
    base_checkpoints/d12/model_000500.pt , optim_000500_rank0.pt , meta_000500.json , ...
    chatsft_checkpoints/d12/model_*.pt , optim_*.pt , meta_*.json

The repo paths under the model repo deliberately MIRROR the on-disk layout
relative to NANOCHAT_BASE_DIR, so downloads with `local_dir=base_dir` land in
exactly the place nanochat expects (e.g. <base>/base_checkpoints/d12/...).

NOTE ON LOCATION: the source of truth for this file lives in the project root
(alongside the notebooks), NOT inside the cloned nanochat repo. The notebook's
install cell copies it into nanochat/nanochat/hf_sync.py at session start so
`from nanochat.hf_sync import ...` resolves inside `python -m scripts.*` runs.
Edit the copy at the project root.
"""

import os
import re

from huggingface_hub import (
    HfApi,
    login,
    snapshot_download,
    hf_hub_download,
    list_repo_files,
    create_repo,
)

DATASET_DATA_PREFIX = "data"          # parquet shards live under data/ in the dataset repo
TOKENIZER_PREFIX = "tokenizer"        # tokenizer files live under tokenizer/ in the model repo
TOKENIZER_FILES = ["tokenizer.pkl", "token_bytes.pt"]

_api = HfApi()


# -----------------------------------------------------------------------------
# Auth
def login_from_colab(token=None):
    """
    Log in to the Hub. Order of precedence:
      1) explicit `token` arg
      2) Colab secret named HF_TOKEN (google.colab.userdata)
      3) HF_TOKEN environment variable
      4) interactive notebook_login() prompt
    Also exports HF_TOKEN into os.environ so that `!python -m scripts.*`
    subprocesses inherit the credential.
    """
    if token is None:
        try:
            from google.colab import userdata
            token = userdata.get("HF_TOKEN")
        except Exception:
            token = os.environ.get("HF_TOKEN")
    if token:
        os.environ["HF_TOKEN"] = token
        login(token=token, add_to_git_credential=False)
        who = _api.whoami(token=token)
        print(f"Logged in to HuggingFace as: {who.get('name', '?')}")
        return token
    # last resort: interactive
    from huggingface_hub import notebook_login
    print("No HF_TOKEN found (arg / Colab secret / env). Falling back to interactive login.")
    notebook_login()
    return os.environ.get("HF_TOKEN")


# -----------------------------------------------------------------------------
# Small utilities
def _safe_list_repo_files(repo_id, repo_type):
    try:
        return list_repo_files(repo_id, repo_type=repo_type)
    except Exception:
        return []


def repo_has_parquet(dataset_repo):
    return any(f.endswith(".parquet") for f in _safe_list_repo_files(dataset_repo, "dataset"))


def tokenizer_on_hub(model_repo):
    files = _safe_list_repo_files(model_repo, "model")
    return f"{TOKENIZER_PREFIX}/{TOKENIZER_FILES[0]}" in files


# -----------------------------------------------------------------------------
# Dataset (raw text)  --  built ONCE
def build_and_push_dataset(dataset_repo, local_build_dir,
                           src_hf_id="sedthh/gutenberg_english",
                           num_shards=100, private=False, force=False):
    """
    One-time: download `src_hf_id`, reshard into `num_shards` parquet files with a
    single 'text' column (the format tok_train/pretok expect), and push them to
    `dataset_repo` under data/. Skips entirely if the repo already has parquet
    (unless force=True).
    """
    if not force and repo_has_parquet(dataset_repo):
        print(f"Dataset repo {dataset_repo} already has parquet shards — skipping build.")
        return

    import time
    import pyarrow as pa
    import pyarrow.parquet as pq
    from datasets import load_dataset

    create_repo(dataset_repo, repo_type="dataset", exist_ok=True, private=private)
    data_dir = os.path.join(local_build_dir, DATASET_DATA_PREFIX)
    os.makedirs(data_dir, exist_ok=True)

    print(f"Loading source dataset {src_hf_id} (may take a minute)...")
    ds = load_dataset(src_hf_id, split="train")
    total = len(ds)
    print(f"Books: {total:,}; resharding into {num_shards} parquet shards")
    rows_per_shard = total // num_shards
    t0 = time.time()

    for shard_idx in range(num_shards):
        shard_path = os.path.join(data_dir, f"shard_{shard_idx:05d}.parquet")
        if os.path.exists(shard_path):
            continue
        start = shard_idx * rows_per_shard
        end = total if shard_idx == num_shards - 1 else start + rows_per_shard
        shard_ds = ds.select(range(start, end))
        texts = []
        for row in shard_ds:
            text = (row.get("TEXT") or row.get("text") or "").strip()
            if text:
                texts.append(text)
        tmp = shard_path + ".tmp"
        pq.write_table(pa.table({"text": texts}), tmp, compression="snappy")
        os.replace(tmp, shard_path)
        print(f"  shard {shard_idx + 1}/{num_shards} ({len(texts):,} books) "
              f"elapsed={time.time() - t0:.0f}s")

    print(f"Uploading {num_shards} shards to dataset repo {dataset_repo} ...")
    _api.upload_folder(
        folder_path=data_dir,
        path_in_repo=DATASET_DATA_PREFIX,
        repo_id=dataset_repo,
        repo_type="dataset",
        allow_patterns=["*.parquet"],
        commit_message=f"raw Gutenberg text: {num_shards} shards",
    )
    print(f"Done. Dataset pushed to https://huggingface.co/datasets/{dataset_repo}")


def download_dataset(dataset_repo, dest_dir, max_shards=None):
    """
    Download the raw-text parquet shards and place them FLAT in `dest_dir`
    (no data/ subdir), which is what both tok_train (fixed DATA_DIR) and
    pretok_gutenberg expect. Returns `dest_dir`.

    `max_shards` limits how many shards (sorted by name) are fetched — handy to
    cap per-session download when you only need enough text for TARGET_TOKENS.
    Idempotent: snapshot_download skips shards already present.
    """
    os.makedirs(dest_dir, exist_ok=True)
    if max_shards is None:
        allow = [f"{DATASET_DATA_PREFIX}/*.parquet"]
    else:
        files = sorted(f for f in _safe_list_repo_files(dataset_repo, "dataset")
                       if f.endswith(".parquet"))
        allow = files[:max_shards]
        assert allow, f"No parquet shards found in dataset repo {dataset_repo}"
    snapshot_download(repo_id=dataset_repo, repo_type="dataset",
                      local_dir=dest_dir, allow_patterns=allow)
    # Flatten data/*.parquet up into dest_dir so default tool paths work.
    data_dir = os.path.join(dest_dir, DATASET_DATA_PREFIX)
    if os.path.isdir(data_dir):
        for f in os.listdir(data_dir):
            if f.endswith(".parquet"):
                os.replace(os.path.join(data_dir, f), os.path.join(dest_dir, f))
    return dest_dir


# -----------------------------------------------------------------------------
# Tokenizer  --  built ONCE, downloaded every session
def upload_tokenizer(model_repo, tokenizer_dir, private=False):
    create_repo(model_repo, repo_type="model", exist_ok=True, private=private)
    _api.upload_folder(
        folder_path=tokenizer_dir,
        path_in_repo=TOKENIZER_PREFIX,
        repo_id=model_repo,
        repo_type="model",
        allow_patterns=TOKENIZER_FILES,
        commit_message="tokenizer",
    )
    print(f"Tokenizer pushed to model repo {model_repo}/{TOKENIZER_PREFIX}")


def download_tokenizer(model_repo, base_dir):
    """Download tokenizer files into <base_dir>/tokenizer/ (where get_tokenizer looks)."""
    for name in TOKENIZER_FILES:
        hf_hub_download(repo_id=model_repo, repo_type="model",
                        filename=f"{TOKENIZER_PREFIX}/{name}", local_dir=base_dir)
    print(f"Tokenizer downloaded to {os.path.join(base_dir, TOKENIZER_PREFIX)}")


# -----------------------------------------------------------------------------
# Checkpoints
def _ckpt_filenames(step, with_optimizer=True, rank=0):
    names = [f"model_{step:06d}.pt", f"meta_{step:06d}.json"]
    if with_optimizer:
        names.append(f"optim_{step:06d}_rank{rank:d}.pt")
    return names


def latest_hf_step(model_repo, subdir):
    """Return the largest checkpoint step present under `subdir` in the model repo, or None."""
    files = _safe_list_repo_files(model_repo, "model")
    pat = re.compile(re.escape(subdir) + r"/model_(\d+)\.pt$")
    steps = [int(m.group(1)) for f in files for m in [pat.search(f)] if m]
    return max(steps) if steps else None


def upload_checkpoint(model_repo, base_dir, subdir, step, with_optimizer=True, private=False):
    """
    Push the files for a single checkpoint `step` (model + meta [+ optim]) from
    <base_dir>/<subdir>/ to the model repo under the same <subdir>/ path, in one commit.
    """
    create_repo(model_repo, repo_type="model", exist_ok=True, private=private)
    local_dir = os.path.join(base_dir, subdir)
    patterns = [f"model_{step:06d}.pt", f"meta_{step:06d}.json"]
    if with_optimizer:
        patterns.append(f"optim_{step:06d}_rank*.pt")
    _api.upload_folder(
        folder_path=local_dir,
        path_in_repo=subdir,
        repo_id=model_repo,
        repo_type="model",
        allow_patterns=patterns,
        commit_message=f"{subdir} checkpoint step {step}",
    )
    print(f"Uploaded {subdir} step {step} to {model_repo}")


def download_checkpoint(model_repo, base_dir, subdir, step, with_optimizer=True, rank=0):
    """Download one checkpoint step into <base_dir>/<subdir>/ (mirrors repo layout)."""
    for name in _ckpt_filenames(step, with_optimizer, rank):
        hf_hub_download(repo_id=model_repo, repo_type="model",
                        filename=f"{subdir}/{name}", local_dir=base_dir)
    print(f"Downloaded {subdir} step {step} from {model_repo}")


def download_latest_checkpoint(model_repo, base_dir, subdir, with_optimizer=True, rank=0):
    """
    Download the newest checkpoint under `subdir` into <base_dir>/<subdir>/.
    Returns the step (int) downloaded, or None if no checkpoint exists on the Hub.
    """
    step = latest_hf_step(model_repo, subdir)
    if step is None:
        return None
    download_checkpoint(model_repo, base_dir, subdir, step,
                        with_optimizer=with_optimizer, rank=rank)
    return step
