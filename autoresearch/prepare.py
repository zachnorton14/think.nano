"""
One-time data preparation for autoresearch experiments on jbduran/think-dataset-clean.

Downloads parquet shards, trains a BPE tokenizer, and pretokenizes everything into
flat uint16 token shards so the training loop never touches the tokenizer.

Usage:
    python autoresearch/prepare.py                 # full prep (~3.1 GB download)
    python autoresearch/prepare.py --num-shards 2  # tiny, for testing

Data, tokenizer and token cache are stored in ~/.cache/autoresearch/.

This file is FIXED. It holds the training constants and the evaluation metric, so
that every experiment is measured the same way. Do not modify it.
"""

import os
import sys
import json
import time
import math
import random
import shutil
import pickle
import hashlib
import argparse
from multiprocessing import Pool

import requests
import numpy as np
import pyarrow.parquet as pq
import rustbpe
import tiktoken
import torch

# ---------------------------------------------------------------------------
# Constants (fixed, do not modify)
# ---------------------------------------------------------------------------

MAX_SEQ_LEN = 2048       # context length used by the evaluation
TIME_BUDGET = 300        # training time budget in seconds (5 minutes)
EVAL_TOKENS = 40 * 524288  # number of tokens for val eval

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "autoresearch")
DATA_DIR = os.path.join(CACHE_DIR, "data")
TOKENIZER_DIR = os.path.join(CACHE_DIR, "tokenizer")
PRETOK_DIR = os.path.join(CACHE_DIR, "pretok")
BASE_URL = "https://huggingface.co/datasets/jbduran/think-dataset-clean/resolve/main"
MAX_SHARD = 472  # the last datashard is shard_00472.parquet
VAL_SHARD = MAX_SHARD  # pinned validation shard (shard_00472)
VAL_FILENAME = f"shard_{VAL_SHARD:05d}.parquet"
VOCAB_SIZE = 8192

# Pretokenization
SHARD_TOKENS = 100_000_000        # tokens per output .bin file
VAL_TOKENS = int(EVAL_TOKENS * 1.5)  # headroom so the eval never wraps the val stream

# Tokenizer training. This corpus stores whole books as single rows (median ~537K
# chars), so cropping each document to its head would train the vocab on title pages
# and OCR front matter. Take a random window per book instead, matching the
# --sampling random option in scripts/tok_train.py.
TOKENIZER_MAX_CHARS = 1_000_000_000
TOKENIZER_DOC_CAP = 200_000
TOKENIZER_SAMPLING_SEED = 42

# BPE split pattern (GPT-4 style, with \p{N}{1,2} instead of {1,3})
SPLIT_PATTERN = r"""'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}+|\p{N}{1,2}| ?[^\s\p{L}\p{N}]++[\r\n]*|\s*[\r\n]|\s+(?!\S)|\s+"""

SPECIAL_TOKENS = [f"<|reserved_{i}|>" for i in range(4)]
BOS_TOKEN = "<|reserved_0|>"

# ---------------------------------------------------------------------------
# Cache provenance
#
# CACHE_DIR, and the shard_NNNNN.parquet naming inside it, are exactly what upstream
# autoresearch uses for a different corpus. On a reused disk the download step would
# see those shards as "already present" and skip them, and every later stage would
# silently inherit the wrong data. Each stage therefore records what produced it and
# refuses to reuse anything that does not match.
# ---------------------------------------------------------------------------

DATA_PROVENANCE = {"base_url": BASE_URL}
TOKENIZER_PROVENANCE = {
    "base_url": BASE_URL,
    "vocab_size": VOCAB_SIZE,
    "split_pattern": SPLIT_PATTERN,
    "special_tokens": SPECIAL_TOKENS,
    "doc_cap": TOKENIZER_DOC_CAP,
    "max_chars": TOKENIZER_MAX_CHARS,
    "sampling_seed": TOKENIZER_SAMPLING_SEED,
}


def _read_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def _write_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)


def _tokenizer_fingerprint():
    """SHA-256 over the tokenizer directory. Any change invalidates the token cache."""
    if not os.path.isdir(TOKENIZER_DIR):
        return None
    digest = hashlib.sha256()
    for name in sorted(os.listdir(TOKENIZER_DIR)):
        path = os.path.join(TOKENIZER_DIR, name)
        if not os.path.isfile(path):
            continue
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _check_data_provenance():
    """Refuse to build on parquet shards that came from somewhere else."""
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "provenance.json")
    previous = _read_json(path)
    if previous is None:
        stale = [f for f in os.listdir(DATA_DIR) if f.endswith(".parquet")]
        if stale:
            raise SystemExit(
                f"{DATA_DIR} already holds {len(stale)} parquet shards of unknown origin.\n"
                f"Upstream autoresearch uses this exact path and shard naming for a different\n"
                f"corpus, so they cannot be trusted. Delete {CACHE_DIR} and re-run."
            )
    elif previous != DATA_PROVENANCE:
        raise SystemExit(
            f"{DATA_DIR} holds shards from {previous.get('base_url')},\n"
            f"not {BASE_URL}.\n"
            f"Delete {CACHE_DIR} and re-run."
        )
    _write_json(path, DATA_PROVENANCE)

# ---------------------------------------------------------------------------
# Data download
# ---------------------------------------------------------------------------

def download_single_shard(index):
    """Download one parquet shard with retries. Returns True on success."""
    filename = f"shard_{index:05d}.parquet"
    filepath = os.path.join(DATA_DIR, filename)
    if os.path.exists(filepath):
        return True

    url = f"{BASE_URL}/{filename}"
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()
            temp_path = filepath + ".tmp"
            with open(temp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
            os.rename(temp_path, filepath)
            print(f"  Downloaded {filename}")
            return True
        except (requests.RequestException, IOError) as e:
            print(f"  Attempt {attempt}/{max_attempts} failed for {filename}: {e}")
            for path in [filepath + ".tmp", filepath]:
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            if attempt < max_attempts:
                time.sleep(2 ** attempt)
    return False


def download_data(num_shards, download_workers=8):
    """Download training shards + pinned validation shard."""
    _check_data_provenance()
    num_train = min(num_shards, MAX_SHARD)
    ids = list(range(num_train))
    if VAL_SHARD not in ids:
        ids.append(VAL_SHARD)

    # Count what's already downloaded
    existing = sum(1 for i in ids if os.path.exists(os.path.join(DATA_DIR, f"shard_{i:05d}.parquet")))
    if existing == len(ids):
        print(f"Data: all {len(ids)} shards already downloaded at {DATA_DIR}")
        return

    needed = len(ids) - existing
    print(f"Data: downloading {needed} shards ({existing} already exist)...")

    workers = max(1, min(download_workers, needed))
    with Pool(processes=workers) as pool:
        results = pool.map(download_single_shard, ids)

    ok = sum(1 for r in results if r)
    print(f"Data: {ok}/{len(ids)} shards ready at {DATA_DIR}")
    assert ok == len(ids), f"Only {ok}/{len(ids)} shards downloaded. Re-run prepare.py."

# ---------------------------------------------------------------------------
# Tokenizer training
# ---------------------------------------------------------------------------

def list_parquet_files():
    """Return sorted list of parquet file paths in the data directory."""
    files = sorted(f for f in os.listdir(DATA_DIR) if f.endswith(".parquet") and not f.endswith(".tmp"))
    return [os.path.join(DATA_DIR, f) for f in files]


def _iter_documents(parquet_paths, batch_size=16):
    """Yield lists of document texts. Batched to bound peak Python memory: this corpus
    packs up to 64 whole books (~56 MB of text) into a single parquet row group."""
    for filepath in parquet_paths:
        pf = pq.ParquetFile(filepath)
        for batch in pf.iter_batches(batch_size=batch_size, columns=["text"]):
            yield batch.column("text").to_pylist()


def text_iterator(max_chars=TOKENIZER_MAX_CHARS, doc_cap=TOKENIZER_DOC_CAP):
    """Yield documents from the training split, each cropped to a random doc_cap window."""
    parquet_paths = [p for p in list_parquet_files() if not p.endswith(VAL_FILENAME)]
    rng = random.Random(TOKENIZER_SAMPLING_SEED)
    nchars = 0
    for docs in _iter_documents(parquet_paths):
        for text in docs:
            if len(text) > doc_cap:
                start = rng.randint(0, len(text) - doc_cap)
                doc = text[start:start + doc_cap]
            else:
                doc = text
            nchars += len(doc)
            yield doc
            if nchars >= max_chars:
                return


def train_tokenizer():
    """Train BPE tokenizer using rustbpe, save as tiktoken pickle."""
    tokenizer_pkl = os.path.join(TOKENIZER_DIR, "tokenizer.pkl")
    token_bytes_path = os.path.join(TOKENIZER_DIR, "token_bytes.pt")
    provenance_path = os.path.join(TOKENIZER_DIR, "provenance.json")

    if (os.path.exists(tokenizer_pkl) and os.path.exists(token_bytes_path)
            and _read_json(provenance_path) == TOKENIZER_PROVENANCE):
        print(f"Tokenizer: already trained at {TOKENIZER_DIR}")
        return

    # Missing, stale, or built from different settings: rebuild from scratch so a
    # partial directory can never be half-reused.
    if os.path.exists(TOKENIZER_DIR):
        shutil.rmtree(TOKENIZER_DIR)
    os.makedirs(TOKENIZER_DIR, exist_ok=True)

    parquet_files = list_parquet_files()
    if len(parquet_files) < 2:
        print("Tokenizer: need at least 2 data shards (1 train + 1 val). Download more data first.")
        sys.exit(1)

    # --- Train with rustbpe ---
    print("Tokenizer: training BPE tokenizer...")
    t0 = time.time()

    tokenizer = rustbpe.Tokenizer()
    vocab_size_no_special = VOCAB_SIZE - len(SPECIAL_TOKENS)
    tokenizer.train_from_iterator(text_iterator(), vocab_size_no_special, pattern=SPLIT_PATTERN)

    # Build tiktoken encoding from trained merges
    pattern = tokenizer.get_pattern()
    mergeable_ranks = {bytes(k): v for k, v in tokenizer.get_mergeable_ranks()}
    tokens_offset = len(mergeable_ranks)
    special_tokens = {name: tokens_offset + i for i, name in enumerate(SPECIAL_TOKENS)}
    enc = tiktoken.Encoding(
        name="rustbpe",
        pat_str=pattern,
        mergeable_ranks=mergeable_ranks,
        special_tokens=special_tokens,
    )

    # Save tokenizer
    with open(tokenizer_pkl, "wb") as f:
        pickle.dump(enc, f)

    t1 = time.time()
    print(f"Tokenizer: trained in {t1 - t0:.1f}s, saved to {tokenizer_pkl}")

    # --- Build token_bytes lookup for BPB evaluation ---
    print("Tokenizer: building token_bytes lookup...")
    special_set = set(SPECIAL_TOKENS)
    token_bytes_list = []
    for token_id in range(enc.n_vocab):
        token_str = enc.decode([token_id])
        if token_str in special_set:
            token_bytes_list.append(0)
        else:
            token_bytes_list.append(len(token_str.encode("utf-8")))
    token_bytes_tensor = torch.tensor(token_bytes_list, dtype=torch.int32)
    torch.save(token_bytes_tensor, token_bytes_path)
    print(f"Tokenizer: saved token_bytes to {token_bytes_path}")

    # Sanity check
    test = "Hello world! Numbers: 123. Unicode: 你好"
    encoded = enc.encode_ordinary(test)
    decoded = enc.decode(encoded)
    assert decoded == test, f"Tokenizer roundtrip failed: {test!r} -> {decoded!r}"

    _write_json(provenance_path, TOKENIZER_PROVENANCE)
    print(f"Tokenizer: sanity check passed (vocab_size={enc.n_vocab})")


class Tokenizer:
    """Minimal tokenizer wrapper. Training is handled above."""

    def __init__(self, enc):
        self.enc = enc
        self.bos_token_id = enc.encode_single_token(BOS_TOKEN)

    @classmethod
    def from_directory(cls, tokenizer_dir=TOKENIZER_DIR):
        with open(os.path.join(tokenizer_dir, "tokenizer.pkl"), "rb") as f:
            enc = pickle.load(f)
        return cls(enc)

    def get_vocab_size(self):
        return self.enc.n_vocab

    def get_bos_token_id(self):
        return self.bos_token_id

    def encode(self, text, prepend=None, num_threads=8):
        if prepend is not None:
            prepend_id = prepend if isinstance(prepend, int) else self.enc.encode_single_token(prepend)
        if isinstance(text, str):
            ids = self.enc.encode_ordinary(text)
            if prepend is not None:
                ids.insert(0, prepend_id)
        elif isinstance(text, list):
            ids = self.enc.encode_ordinary_batch(text, num_threads=num_threads)
            if prepend is not None:
                for row in ids:
                    row.insert(0, prepend_id)
        else:
            raise ValueError(f"Invalid input type: {type(text)}")
        return ids

    def decode(self, ids):
        return self.enc.decode(ids)


def get_token_bytes(device="cpu"):
    path = os.path.join(TOKENIZER_DIR, "token_bytes.pt")
    with open(path, "rb") as f:
        return torch.load(f, map_location=device)

# ---------------------------------------------------------------------------
# Pretokenization
#
# The training loop reads a flat uint16 token stream rather than tokenizing text on
# the fly. This corpus stores whole books as single rows (~180K tokens each), which
# no document-packing scheme handles sensibly at a 2048-token row length, and it also
# keeps tokenizer throughput from becoming a confound between experiments.
# ---------------------------------------------------------------------------

class TokenShardWriter:
    def __init__(self, output_dir, prefix, shard_tokens):
        self.output_dir = output_dir
        self.prefix = prefix
        self.shard_tokens = int(shard_tokens)
        self.files = []
        self.total_tokens = 0
        self.shard_index = 0
        self.current = None
        self.current_tokens = 0
        self.current_path = None

    def _open_next(self):
        filename = f"{self.prefix}_{self.shard_index:05d}.bin"
        self.current_path = os.path.join(self.output_dir, filename)
        self.current = open(self.current_path, "wb")
        self.current_tokens = 0
        self.shard_index += 1

    def _close_current(self):
        if self.current is None:
            return
        self.current.close()
        self.files.append({"filename": os.path.basename(self.current_path), "num_tokens": self.current_tokens})
        self.current = None
        self.current_path = None
        self.current_tokens = 0

    def write(self, tokens):
        if not tokens:
            return
        arr = np.asarray(tokens, dtype=np.uint16)
        offset = 0
        while offset < len(arr):
            if self.current is None:
                self._open_next()
            remaining = self.shard_tokens - self.current_tokens
            take = min(remaining, len(arr) - offset)
            arr[offset:offset + take].tofile(self.current)
            self.current_tokens += take
            self.total_tokens += take
            offset += take
            if self.current_tokens >= self.shard_tokens:
                self._close_current()

    def close(self):
        self._close_current()


def _write_split(split, parquet_paths, writer, tokenizer, max_tokens):
    bos_token = tokenizer.get_bos_token_id()
    started = time.time()
    for docs in _iter_documents(parquet_paths):
        for tokens in tokenizer.encode(docs, prepend=bos_token):
            if max_tokens > 0:
                remaining = max_tokens - writer.total_tokens
                if remaining <= 0:
                    writer.close()
                    return
                if len(tokens) > remaining:
                    tokens = tokens[:remaining]
            writer.write(tokens)
        elapsed = max(time.time() - started, 1e-6)
        print(f"\r  {split}: {writer.total_tokens:,} tokens | {writer.total_tokens / elapsed:,.0f} tok/s   ",
              end="", flush=True)
    writer.close()
    print()


def pretokenize():
    """Tokenize the local parquet shards into flat uint16 token shards."""
    meta_path = os.path.join(PRETOK_DIR, "meta.json")
    if _pretok_cache_exists():
        print(f"Pretok: cache already present at {PRETOK_DIR}")
        return

    parquet_paths = list_parquet_files()
    assert len(parquet_paths) >= 2, f"Need train shards plus validation in {DATA_DIR}."
    val_paths = [p for p in parquet_paths if p.endswith(VAL_FILENAME)]
    train_paths = [p for p in parquet_paths if not p.endswith(VAL_FILENAME)]
    assert val_paths, f"Missing validation shard {VAL_FILENAME} in {DATA_DIR}."
    assert train_paths, f"No training shards in {DATA_DIR}."

    tokenizer = Tokenizer.from_directory()
    vocab_size = tokenizer.get_vocab_size()
    assert vocab_size <= np.iinfo(np.uint16).max + 1, f"vocab_size={vocab_size} does not fit uint16"

    if os.path.exists(PRETOK_DIR):
        shutil.rmtree(PRETOK_DIR)
    os.makedirs(PRETOK_DIR, exist_ok=True)

    print(f"Pretok: writing token cache to {PRETOK_DIR}")
    train_writer = TokenShardWriter(PRETOK_DIR, "train", SHARD_TOKENS)
    val_writer = TokenShardWriter(PRETOK_DIR, "val", SHARD_TOKENS)
    _write_split("train", train_paths, train_writer, tokenizer, -1)
    _write_split("val", val_paths, val_writer, tokenizer, VAL_TOKENS)

    meta = {
        "dtype": "uint16",
        "base_url": BASE_URL,
        "tokenizer_fingerprint": _tokenizer_fingerprint(),
        "vocab_size": vocab_size,
        "shard_tokens": SHARD_TOKENS,
        "train_tokens": train_writer.total_tokens,
        "val_tokens": val_writer.total_tokens,
        "train_files": train_writer.files,
        "val_files": val_writer.files,
        "train_parquet_files": [os.path.basename(p) for p in train_paths],
        "val_parquet_files": [os.path.basename(p) for p in val_paths],
        "created_at_unix": math.floor(time.time()),
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Pretok: train {train_writer.total_tokens:,} tokens | val {val_writer.total_tokens:,} tokens")
    assert val_writer.total_tokens >= EVAL_TOKENS, (
        f"Val split has {val_writer.total_tokens:,} tokens but the eval needs {EVAL_TOKENS:,}."
    )

# ---------------------------------------------------------------------------
# Runtime utilities (imported by train.py)
# ---------------------------------------------------------------------------

def load_pretok_meta():
    meta_path = os.path.join(PRETOK_DIR, "meta.json")
    assert os.path.exists(meta_path), f"Missing token cache at {PRETOK_DIR}. Run prepare.py first."
    with open(meta_path, "r") as f:
        return json.load(f)


def _pretok_cache_exists():
    """True only if the cache on disk matches the corpus, tokenizer and shard set now
    present. Anything else (different dataset, retrained tokenizer, more shards
    downloaded, short val split) rebuilds rather than silently reusing."""
    meta = _read_json(os.path.join(PRETOK_DIR, "meta.json"))
    if meta is None:
        return False
    if meta.get("base_url") != BASE_URL:
        return False
    if meta.get("tokenizer_fingerprint") != _tokenizer_fingerprint():
        return False
    if meta.get("val_tokens", 0) < EVAL_TOKENS:
        return False
    if os.path.isdir(DATA_DIR):
        present = [os.path.basename(p) for p in list_parquet_files()]
        if sorted(meta.get("train_parquet_files", [])) != sorted(p for p in present if p != VAL_FILENAME):
            return False
        if sorted(meta.get("val_parquet_files", [])) != sorted(p for p in present if p == VAL_FILENAME):
            return False
    for split in ("train", "val"):
        entries = meta.get(f"{split}_files", [])
        if not entries:
            return False
        for entry in entries:
            if not os.path.exists(os.path.join(PRETOK_DIR, entry["filename"])):
                return False
    return True


def get_vocab_size():
    return load_pretok_meta()["vocab_size"]


def _load_split_arrays(split):
    assert split in ("train", "val"), "split must be 'train' or 'val'"
    meta = load_pretok_meta()
    dtype = np.dtype(meta.get("dtype", "uint16"))
    entries = meta.get(f"{split}_files", [])
    assert entries, f"No {split} token files listed in {PRETOK_DIR}/meta.json"
    arrays, sizes = [], []
    for entry in entries:
        path = os.path.join(PRETOK_DIR, entry["filename"])
        assert os.path.exists(path), f"Missing token shard: {path}"
        arr = np.memmap(path, mode="r", dtype=dtype)
        assert len(arr) > 0, f"Empty token shard: {path}"
        arrays.append(arr)
        sizes.append(len(arr))
    return arrays, sizes


class _TokenCursor:
    """Position in a concatenated, infinitely cycling token stream."""

    def __init__(self, arrays, sizes):
        self.arrays = arrays
        self.sizes = sizes
        self.file_idx = 0
        self.pos = 0
        self.epoch = 1

    def _advance_file(self):
        self.file_idx += 1
        self.pos = 0
        if self.file_idx >= len(self.arrays):
            self.file_idx = 0
            self.epoch += 1

    def read(self, n):
        out = np.empty(int(n), dtype=np.uint16)
        filled = 0
        while filled < n:
            arr = self.arrays[self.file_idx]
            available = self.sizes[self.file_idx] - self.pos
            take = min(available, n - filled)
            out[filled:filled + take] = arr[self.pos:self.pos + take]
            filled += take
            self.pos += take
            if self.pos >= self.sizes[self.file_idx]:
                self._advance_file()
        return out


def make_dataloader(B, T, split, device="cuda"):
    """Yield (inputs, targets, epoch) from the flat token stream.

    Rows are contiguous slices of the corpus. The yielded tensors are views into a
    persistent buffer and are invalidated by the next call, which matches how the
    training loop consumes them (forward and backward run before the next fetch).
    """
    arrays, sizes = _load_split_arrays(split)
    cursor = _TokenCursor(arrays, sizes)
    read_tokens = B * T + 1
    use_cuda = device == "cuda"
    cpu_buffer = torch.empty(read_tokens, dtype=torch.long, pin_memory=use_cuda)
    gpu_buffer = torch.empty(read_tokens, dtype=torch.long, device=device)
    while True:
        batch_np = cursor.read(read_tokens).astype(np.int64, copy=False)
        cpu_buffer.copy_(torch.from_numpy(batch_np))
        gpu_buffer.copy_(cpu_buffer, non_blocking=use_cuda)
        yield gpu_buffer[:-1].view(B, T), gpu_buffer[1:].view(B, T), cursor.epoch

# ---------------------------------------------------------------------------
# Evaluation (DO NOT CHANGE — this is the fixed metric)
# ---------------------------------------------------------------------------

@torch.no_grad()
def evaluate_bpb(model, batch_size):
    """
    Bits per byte (BPB): vocab size-independent evaluation metric.
    Sums per-token cross-entropy (in nats), sums target byte lengths,
    then converts nats/byte to bits/byte. Special tokens (byte length 0)
    are excluded from both sums.
    Uses fixed MAX_SEQ_LEN so results are comparable across configs.
    """
    token_bytes = get_token_bytes(device="cuda")
    val_loader = make_dataloader(batch_size, MAX_SEQ_LEN, "val")
    steps = EVAL_TOKENS // (batch_size * MAX_SEQ_LEN)
    total_nats = 0.0
    total_bytes = 0
    for _ in range(steps):
        x, y, _ = next(val_loader)
        loss_flat = model(x, y, reduction='none').view(-1)
        y_flat = y.reshape(-1)
        nbytes = token_bytes[y_flat]
        mask = nbytes > 0
        total_nats += (loss_flat * mask).sum().item()
        total_bytes += nbytes.sum().item()
    return total_nats / (math.log(2) * total_bytes)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepare data and tokenizer for autoresearch")
    parser.add_argument("--num-shards", type=int, default=40, help="Number of training shards to download (-1 = all). Val shard is always pinned.")
    parser.add_argument("--download-workers", type=int, default=8, help="Number of parallel download workers")
    args = parser.parse_args()

    num_shards = MAX_SHARD if args.num_shards == -1 else args.num_shards

    print(f"Cache directory: {CACHE_DIR}")
    print()

    # Step 1: Download data
    download_data(num_shards, download_workers=args.download_workers)
    print()

    # Step 2: Train tokenizer
    train_tokenizer()
    print()

    # Step 3: Pretokenize into a flat token stream
    pretokenize()
    print()
    print("Done! Ready to train.")
