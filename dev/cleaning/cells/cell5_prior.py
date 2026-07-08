tokenizer = GPT2TokenizerFast.from_pretrained("gpt2")


def try_download_prior():
    try:
        prior_path = hf_hub_download(DST_REPO, "_prior/log_priors.npy", repo_type="dataset", token=HF_TOKEN)
        thresh_path = hf_hub_download(DST_REPO, "_prior/thresholds.json", repo_type="dataset", token=HF_TOKEN)
        log_priors = np.load(prior_path)
        with open(thresh_path, "r", encoding="utf-8") as f:
            thresholds = json.load(f)
        print("Loaded cached prior table and thresholds from destination repo.")
        return log_priors, thresholds
    except Exception:
        return None, None


def doc_mean_log_prior(text, log_priors):
    ids = tokenizer.encode(text[:TOKENIZE_CHARS], add_special_tokens=False)
    if not ids:
        return None
    ids = [i for i in ids if i < len(log_priors)]
    if not ids:
        return None
    return float(log_priors[ids].mean())


def build_prior_from_sample():
    rng = random.Random(RANDOM_SEED)
    sample_shards = SOURCE_SHARDS[:]
    rng.shuffle(sample_shards)
    sample_shards = sample_shards[:min(SAMPLE_SHARDS, len(sample_shards))]

    docs = []
    stage_estimates = Counter()
    raw_seen = 0

    print(f"Sampling up to {SAMPLE_DOCS:,} docs from {len(sample_shards):,} shards for priors...")
    for shard in tqdm(sample_shards, desc="sample shards"):
        local = download_source_shard(shard)
        pf = pq.ParquetFile(local)
        for rg_idx in range(pf.num_row_groups):
            table = pf.read_row_group(rg_idx, columns=["text"])
            for text in table.column("text").to_pylist():
                raw_seen += 1
                cleaned, reason = structural_clean(text)
                if cleaned is None:
                    stage_estimates[reason] += 1
                    continue
                docs.append(cleaned)
                if len(docs) >= SAMPLE_DOCS:
                    break
            if len(docs) >= SAMPLE_DOCS:
                break
        if len(docs) >= SAMPLE_DOCS:
            break

    if not docs:
        raise RuntimeError("No documents survived the structural sample; loosen thresholds or inspect source data.")

    counts = Counter()
    doc_token_ids = []
    total_tokens = 0
    for text in tqdm(docs, desc="tokenizing sample"):
        ids = tokenizer.encode(text[:TOKENIZE_CHARS], add_special_tokens=False)
        if not ids:
            continue
        counts.update(ids)
        doc_token_ids.append(ids)
        total_tokens += len(ids)

    if total_tokens == 0:
        raise RuntimeError("Tokenization sample produced zero tokens.")

    vocab_size = tokenizer.vocab_size
    log_priors = np.full(vocab_size, np.log2(1.0 / total_tokens), dtype=np.float32)
    for tok_id, count in counts.items():
        if tok_id < vocab_size:
            log_priors[tok_id] = np.log2(count / total_tokens)

    means = np.array([float(log_priors[[i for i in ids if i < vocab_size]].mean()) for ids in doc_token_ids])
    lo, hi = np.percentile(means, PRIOR_BAND)
    thresholds = {
        "prior_band": list(PRIOR_BAND),
        "low": float(lo),
        "high": float(hi),
        "sample_raw_docs_seen": int(raw_seen),
        "sample_structural_kept": int(len(docs)),
        "sample_structural_removed": dict(stage_estimates),
        "sample_prior_docs": int(len(means)),
        "estimated_prior_removed_pct": float(100.0 * ((means < lo) | (means > hi)).mean()),
        "mean_log_prior_percentiles": {
            str(p): float(np.percentile(means, p))
            for p in [1, 2.5, 5, 10, 25, 50, 75, 90, 95, 97.5, 99]
        },
    }

    PRIOR_DIR.mkdir(parents=True, exist_ok=True)
    local_prior = PRIOR_DIR / "log_priors.npy"
    local_thresh = PRIOR_DIR / "thresholds.json"
    local_sample = PRIOR_DIR / "sample_stats.json"
    np.save(local_prior, log_priors)
    for path, payload in [(local_thresh, thresholds), (local_sample, thresholds)]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)

    api.create_commit(
        repo_id=DST_REPO,
        repo_type="dataset",
        operations=[
            CommitOperationAdd(path_in_repo="_prior/log_priors.npy", path_or_fileobj=str(local_prior)),
            CommitOperationAdd(path_in_repo="_prior/thresholds.json", path_or_fileobj=str(local_thresh)),
            CommitOperationAdd(path_in_repo="_prior/sample_stats.json", path_or_fileobj=str(local_sample)),
        ],
        commit_message="add cleaning prior table and thresholds",
    )

    print("Sample-based prior estimates:")
    print(json.dumps(thresholds, indent=2))
    return log_priors, thresholds


if not FORCE_RECOMPUTE_PRIOR:
    LOG_PRIORS, PRIOR_THRESHOLDS = try_download_prior()
else:
    LOG_PRIORS, PRIOR_THRESHOLDS = None, None

if LOG_PRIORS is None:
    LOG_PRIORS, PRIOR_THRESHOLDS = build_prior_from_sample()

PRIOR_LOW = PRIOR_THRESHOLDS["low"]
PRIOR_HIGH = PRIOR_THRESHOLDS["high"]
print(f"Using mean log-prior band [{PRIOR_LOW:.4f}, {PRIOR_HIGH:.4f}]")
