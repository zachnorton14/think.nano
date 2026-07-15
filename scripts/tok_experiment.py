"""
Tokenizer ablation harness: compare how the document-sampling strategy used to
TRAIN the BPE tokenizer affects compactness and token quality.

Motivation: tok_train.py trains the vocab on doc[:doc_cap] -- the first `doc_cap`
characters of each document. For a corpus of very long documents (e.g. pre-1930s
books averaging ~700k chars) this only ever shows the tokenizer document
*openings* (title pages, prefaces, chapter 1), which may bias the learned merges
toward beginnings and miss vocabulary that only appears deeper in documents.

This script trains several tokenizer variants that differ in the "edge" variables
(sampling position, doc_cap, char budget) and evaluates each on a HELD-OUT set of
full documents (the val shard), reporting:

  - compactness      : bytes / token overall  (higher = better compression)
  - opening bytes/tok: measured on doc[:10k]   (what the baseline trains on)
  - body bytes/tok   : measured on doc[10k:]   (what the baseline never sees)
  - body gap         : opening - body bytes/tok. A large positive gap means the
                       vocab compresses openings better than bodies == beginning bias.
  - fertility        : tokens / whitespace-word (lower = better)
  - byte_fallback_%  : % of emitted tokens that are single raw bytes (lower = better)

All variants train on the SAME character budget and are scored on the SAME held-out
text, so the numbers are directly comparable.

Run on Colab (needs rustbpe + the downloaded shards), e.g.:
    python -m scripts.tok_experiment --data-dir "$NANOCHAT_DATA_DIR" \
        --output-json "$NANOCHAT_BASE_DIR/tok_experiment.json"
"""

import argparse
import json
import random
import time

from nanochat.tokenizer import RustBPETokenizer
from nanochat.dataset import parquets_iter_batched

OPENING_SPLIT = 10_000  # boundary (chars) between a document's "opening" and "body"


# -----------------------------------------------------------------------------
# Document -> training-text sampling strategies

def sample_head(doc, doc_cap, rng):
    """Baseline: the first doc_cap characters."""
    return doc[:doc_cap]


def sample_random(doc, doc_cap, rng):
    """A single random doc_cap-char window from anywhere in the document."""
    if len(doc) <= doc_cap:
        return doc
    start = rng.randint(0, len(doc) - doc_cap)
    return doc[start:start + doc_cap]


def sample_chunks(doc, doc_cap, rng, k=3):
    """k evenly-spaced chunks summing to ~doc_cap chars, spread across the doc."""
    if len(doc) <= doc_cap:
        return doc
    chunk = max(1, doc_cap // k)
    if len(doc) <= chunk:
        return doc[:chunk]
    span = len(doc) - chunk
    parts = [doc[round(i * span / (k - 1)):round(i * span / (k - 1)) + chunk] for i in range(k)]
    return "".join(parts)


SAMPLERS = {"head": sample_head, "random": sample_random, "chunks": sample_chunks}


# -----------------------------------------------------------------------------
# The variants to compare. Edit this list to sweep other edge variables.
# Keeping max_chars constant across variants makes compactness directly comparable.
DEFAULT_VARIANTS = [
    {"name": "head-10k",    "sampling": "head",   "doc_cap": 10_000},
    {"name": "random-10k",  "sampling": "random", "doc_cap": 10_000},
    {"name": "chunks-10k",  "sampling": "chunks", "doc_cap": 10_000},
    {"name": "head-2k",     "sampling": "head",   "doc_cap": 2_000},
    {"name": "head-50k",    "sampling": "head",   "doc_cap": 50_000},
    {"name": "random-50k",  "sampling": "random", "doc_cap": 50_000},
]


def build_train_text_iterator(sampler, doc_cap, max_chars, data_dir, seed):
    """Yield sampled document slices until max_chars characters have been produced."""
    rng = random.Random(seed)
    nchars = 0
    used_docs = 0
    for batch in parquets_iter_batched(split="train", data_dir=data_dir):
        for doc in batch:
            piece = sampler(doc, doc_cap, rng)
            if not piece:
                continue
            nchars += len(piece)
            used_docs += 1
            yield piece
            if nchars >= max_chars:
                yield {"__stats__": {"chars": nchars, "docs": used_docs}}
                return
    yield {"__stats__": {"chars": nchars, "docs": used_docs}}


def train_variant(variant, vocab_size, default_max_chars, data_dir, seed):
    sampler = SAMPLERS[variant["sampling"]]
    max_chars = int(variant.get("max_chars", default_max_chars))
    stats = {"requested_max_chars": max_chars}

    def text_only():
        for item in build_train_text_iterator(sampler, variant["doc_cap"], max_chars, data_dir, seed):
            if isinstance(item, dict):
                stats.update(item["__stats__"])
            else:
                yield item

    t0 = time.time()
    tok = RustBPETokenizer.train_from_iterator(text_only(), vocab_size)
    stats["train_time"] = time.time() - t0
    # Did we actually reach the requested budget, or did the local shards run out?
    stats["reached_budget"] = stats.get("chars", 0) >= 0.99 * max_chars
    return tok, stats


# -----------------------------------------------------------------------------
# Evaluation on held-out full documents (the val shard)

def load_eval_docs(data_dir, max_bytes):
    docs, total = [], 0
    for batch in parquets_iter_batched(split="val", data_dir=data_dir):
        for doc in batch:
            docs.append(doc)
            total += len(doc.encode("utf-8"))
            if total >= max_bytes:
                return docs
    return docs


def _single_byte_ids(tok):
    """Set of token ids that decode to exactly one raw byte (byte-fallback tokens)."""
    ids = set()
    for tid in range(tok.get_vocab_size()):
        try:
            if len(tok.enc.decode_single_token_bytes(tid)) == 1:
                ids.add(tid)
        except Exception:
            pass  # special tokens have no byte representation
    return ids


def evaluate(tok, docs):
    single_byte = _single_byte_ids(tok)
    openings = [d[:OPENING_SPLIT] for d in docs]
    bodies = [d[OPENING_SPLIT:] for d in docs if len(d) > OPENING_SPLIT]

    def encode_bucket(texts):
        texts = [t for t in texts if t]
        n_bytes = sum(len(t.encode("utf-8")) for t in texts)
        n_words = sum(len(t.split()) for t in texts)
        ids_lists = tok.enc.encode_ordinary_batch(texts, num_threads=8)
        n_tokens = sum(len(ids) for ids in ids_lists)
        n_single = sum(sum(1 for i in ids if i in single_byte) for ids in ids_lists)
        return n_bytes, n_tokens, n_words, n_single

    ob, ot, ow, os_ = encode_bucket(openings)
    bb, bt, bw, bs = encode_bucket(bodies)
    tot_bytes, tot_tokens = ob + bb, ot + bt
    tot_words, tot_single = ow + bw, os_ + bs
    bpt = lambda b, t: (b / t) if t else float("nan")
    return {
        "bytes_per_token": round(bpt(tot_bytes, tot_tokens), 4),
        "opening_bytes_per_token": round(bpt(ob, ot), 4),
        "body_bytes_per_token": round(bpt(bb, bt), 4),
        "body_gap": round(bpt(ob, ot) - bpt(bb, bt), 4),
        "fertility": round(tot_tokens / tot_words, 4) if tot_words else float("nan"),
        "byte_fallback_pct": round(100 * tot_single / tot_tokens, 3) if tot_tokens else float("nan"),
        "eval_docs": len(docs),
        "eval_bytes": tot_bytes,
    }


# -----------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Tokenizer sampling ablation")
    p.add_argument("--data-dir", type=str, default=None, help="parquet dir with train shards + val shard")
    p.add_argument("--config", type=str, default=None,
                   help="experiment config to resolve --data-dir from (alternative to --data-dir)")
    p.add_argument("--variants-json", type=str, default=None,
                   help="path to a JSON list of variant dicts (name, sampling, doc_cap, "
                        "optional max_chars) overriding the built-in DEFAULT_VARIANTS")
    p.add_argument("--vocab-size", type=int, default=32768)
    p.add_argument("--max-chars", type=int, default=12_000_000,
                   help="training char budget per variant (kept below the smallest "
                        "variant's available chars so budgets are equal)")
    p.add_argument("--eval-bytes", type=int, default=40_000_000,
                   help="how much held-out val text to score on")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output-json", type=str, default=None)
    args = p.parse_args()

    if args.data_dir is None and args.config is not None:
        from scripts.experiment import Experiment
        args.data_dir = str(Experiment(args.config).data_dir)
        print(f"Resolved data dir from config: {args.data_dir}", flush=True)
    if args.data_dir is None:
        p.error("provide --data-dir or --config")

    variants = DEFAULT_VARIANTS
    if args.variants_json:
        with open(args.variants_json) as f:
            variants = json.load(f)
        print(f"Loaded {len(variants)} variants from {args.variants_json}", flush=True)

    print(f"Loading held-out eval docs (~{args.eval_bytes/1e6:.0f} MB)...", flush=True)
    eval_docs = load_eval_docs(args.data_dir, args.eval_bytes)
    print(f"  {len(eval_docs)} eval documents", flush=True)

    results = []
    for variant in variants:
        print(f"\n=== {variant['name']} ({variant['sampling']}, doc_cap={variant['doc_cap']:,}) ===", flush=True)
        tok, stats = train_variant(variant, args.vocab_size, args.max_chars, args.data_dir, args.seed)
        budget_note = "" if stats.get("reached_budget", True) else "  [EXHAUSTED shards before budget]"
        print(f"  trained on {stats.get('chars', 0):,} chars from {stats.get('docs', 0):,} docs "
              f"in {stats.get('train_time', 0):.1f}s{budget_note}", flush=True)
        metrics = evaluate(tok, eval_docs)
        row = {**variant, **stats, **metrics}
        results.append(row)
        print(f"  bytes/token={metrics['bytes_per_token']}  body_gap={metrics['body_gap']}  "
              f"fertility={metrics['fertility']}  byte_fallback%={metrics['byte_fallback_pct']}", flush=True)

    # Markdown summary
    print("\n\n| Variant | Sampling | doc_cap | max_chars | chars used | docs used | reached? | "
          "bytes/tok | opening | body | body gap | fertility | bytefb% |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        print(f"| {r['name']} | {r['sampling']} | {r['doc_cap']:,} | "
              f"{r.get('requested_max_chars', 0):,} | {r.get('chars', 0):,} | {r.get('docs', 0):,} | "
              f"{'yes' if r.get('reached_budget', True) else 'NO'} | {r['bytes_per_token']} | "
              f"{r['opening_bytes_per_token']} | {r['body_bytes_per_token']} | {r['body_gap']} | "
              f"{r['fertility']} | {r['byte_fallback_pct']} |")

    if args.output_json:
        with open(args.output_json, "w") as f:
            json.dump({"config": vars(args), "results": results}, f, indent=2)
        print(f"\nWrote {args.output_json}")


if __name__ == "__main__":
    main()
