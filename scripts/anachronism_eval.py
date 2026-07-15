"""
Anachronism separation test for a base (pretrain-only) vintage model.

Go/no-go check for loss-based synthetic-question filtering: can we tell authentic
pre-1930s questions apart from anachronistic ones by how surprised a vintage model is?

Two scorers are reported, both in bits-per-byte (vocab-independent, see evaluate_bpb):

  vintage_*  the vintage model's own bits/byte on the question.
             Defect: authentic period prose is full of rare archaic vocabulary, so it
             scores high, inflating the authentic tail and blunting any threshold.

  delta_*    vintage bits/byte MINUS a modern model's bits/byte on the same words
             (enable with --modern-hf-path). Text that is merely rare-and-hard is
             surprising to BOTH models and cancels to ~0; text that is anachronistic
             is surprising to the vintage model ONLY, and survives the subtraction.
             This is aimed squarely at the authentic-tail defect above.

For each scorer we report the mean (whole-question bits/byte) and the peak (mean of the
top-k word bits/byte). Peak exists because a single anachronistic word spikes a couple
of words and is otherwise washed out by the mean.

Reported per bucket and per probe kind (lexical / conceptual / register):
  - loss percentiles, and AUC = P(anachronistic > authentic): 0.5 = no signal,
    1.0 = perfect, <0.5 = INVERTED (model finds the probes *less* surprising than
    genuine period text, in which case no threshold can ever separate them)
  - recall at the authentic-p95 threshold (the ~5% false-positive operating point)

IMPORTANT: point --checkpoint-dir at a BASE (pretrain-only) checkpoint, never an SFT
checkpoint. An SFT model trained on the authentic pairs has memorized the reference and
will bias the test (the reference distribution collapses artificially tight).

Examples:

    # vintage only
    python -m scripts.anachronism_eval \
        --checkpoint-dir hf_download/experiments/think-d12-1ep-65sh-r30/base_checkpoints \
        --tokenizer-dir  hf_download/experiments/think-d12-1ep-65sh-r30/tokenizer

    # with the modern-model delta (needs transformers: uv sync --extra cpu --group dev)
    python -m scripts.anachronism_eval \
        --checkpoint-dir hf_download/experiments/think-d12-1ep-65sh-r30/base_checkpoints \
        --tokenizer-dir  hf_download/experiments/think-d12-1ep-65sh-r30/tokenizer \
        --modern-hf-path openai-community/gpt2 \
        --output-json    dev/anachronism_r30_delta.json
"""
import os
import json
import argparse

from nanochat.common import compute_init, compute_cleanup, print0, autodetect_device_type
from nanochat.checkpoint_manager import build_model, find_last_step, load_model
from nanochat.tokenizer import get_token_bytes
from nanochat.loss_eval import score_word_bits
from scripts.anachronism_probe import load_authentic_questions, load_anachronistic_questions


def _auc(pos, neg):
    """P(random pos > random neg), ties counted as 0.5. pos=anachronistic, neg=authentic."""
    if not pos or not neg:
        return float("nan")
    wins = 0.0
    for p in pos:
        for n in neg:
            wins += 1.0 if p > n else (0.5 if p == n else 0.0)
    return wins / (len(pos) * len(neg))


def _pct(values, q):
    if not values:
        return float("nan")
    s = sorted(values)
    return s[min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))]


def _topk_mean(values, k):
    if not values:
        return float("nan")
    k = min(k, len(values))
    return sum(sorted(values, reverse=True)[:k]) / k


def _vintage_metrics(wb, peak_k):
    """(mean, peak) bits/byte for one text from its per-word bits."""
    total_bytes = sum(wb["bytes"])
    if total_bytes == 0:
        return None
    per_word = [b / n for b, n in zip(wb["bits"], wb["bytes"]) if n > 0]
    return sum(wb["bits"]) / total_bytes, _topk_mean(per_word, peak_k)


def _delta_metrics(wv, wm, peak_k):
    """(mean, peak) of vintage-minus-modern bits/byte, aligned word by word."""
    total_bytes = sum(wv["bytes"])
    if total_bytes == 0 or not wm["bytes"]:
        return None
    # same text -> same word split; zip guards against differing truncation
    per_word = [
        (bv / nv) - (bm / nm)
        for bv, nv, bm, nm in zip(wv["bits"], wv["bytes"], wm["bits"], wm["bytes"])
        if nv > 0 and nm > 0
    ]
    if not per_word:
        return None
    paired = list(zip(wv["bits"], wm["bits"]))
    mean = sum(bv - bm for bv, bm in paired) / total_bytes
    return mean, _topk_mean(per_word, peak_k)


def _analyze(name, auth, anach, anachronistic, report):
    """Print + record percentiles / AUC / recall for one metric, overall and by kind."""
    auc = _auc(anach, auth)
    thr = _pct(auth, 0.95)  # authentic p95 = ~5% false-positive operating point
    caught = sum(1 for x in anach if x > thr)
    recall = caught / len(anach) if anach else float("nan")

    kind_scores = {}
    for a, score in zip(anachronistic, anach):
        kind_scores.setdefault(a["kind"], []).append(score)
    kind_recall = {k: sum(1 for x in v if x > thr) / len(v) for k, v in kind_scores.items()}
    kind_auc = {k: _auc(v, auth) for k, v in kind_scores.items()}

    print0("")
    print0("=" * 74)
    print0(f"metric: {name}  (bits per byte)")
    print0("=" * 74)
    print0(f"  separation AUC: {auc:.3f}   (0.5 = no signal, 1.0 = perfect, <0.5 = inverted)")
    print0(f"  @ authentic p95 threshold ({thr:.3f}): caught {caught}/{len(anach)} (recall {recall:.2f})")
    print0("")
    print0(f"  {'bucket':<16} {'n':>4}  {'p10':>7} {'p50':>7} {'p90':>7}  {'AUC':>6}  {'recall':>6}")
    print0(f"  {'-'*16} {'-'*4}  {'-'*7} {'-'*7} {'-'*7}  {'-'*6}  {'-'*6}")
    print0(f"  {'authentic':<16} {len(auth):>4}  {_pct(auth,0.1):>7.3f} {_pct(auth,0.5):>7.3f} {_pct(auth,0.9):>7.3f}  {'—':>6}  {'—':>6}")
    print0(f"  {'anachronistic':<16} {len(anach):>4}  {_pct(anach,0.1):>7.3f} {_pct(anach,0.5):>7.3f} {_pct(anach,0.9):>7.3f}  {auc:>6.3f}  {recall:>6.2f}")
    for k in sorted(kind_scores):
        v = kind_scores[k]
        print0(f"    {k:<14} {len(v):>4}  {_pct(v,0.1):>7.3f} {_pct(v,0.5):>7.3f} {_pct(v,0.9):>7.3f}  {kind_auc[k]:>6.3f}  {kind_recall[k]:>6.2f}")

    report["metrics"][name] = {
        "auc": auc,
        "threshold_p95_authentic": thr,
        "recall_at_p95": recall,
        "recall_by_kind": kind_recall,
        "auc_by_kind": kind_auc,
        "authentic_pcts": {"p10": _pct(auth, 0.1), "p50": _pct(auth, 0.5), "p90": _pct(auth, 0.9)},
        "anachronistic_pcts": {"p10": _pct(anach, 0.1), "p50": _pct(anach, 0.5), "p90": _pct(anach, 0.9)},
        "pcts_by_kind": {
            k: {"n": len(v), "p10": _pct(v, 0.1), "p50": _pct(v, 0.5), "p90": _pct(v, 0.9)}
            for k, v in kind_scores.items()
        },
    }
    return auc


def main():
    parser = argparse.ArgumentParser(description="Anachronism loss separation test")
    parser.add_argument("--checkpoint-dir", type=str, default=None, help="explicit base checkpoint directory")
    parser.add_argument("--tokenizer-dir", type=str, default=None, help="explicit tokenizer directory")
    parser.add_argument("--model-tag", type=str, default=None, help="nanochat base model tag (if not using --checkpoint-dir)")
    parser.add_argument("--step", type=int, default=None, help="model step to load (default = last)")
    parser.add_argument("--modern-hf-path", type=str, default=None, help="HF causal LM for the delta reference (e.g. openai-community/gpt2)")
    parser.add_argument("--num-authentic", type=int, default=256, help="number of authentic questions to sample")
    parser.add_argument("--peak-k", type=int, default=3, help="top-k words averaged for the peak metric")
    parser.add_argument("--max-tokens", type=int, default=512, help="truncate questions to this many tokens")
    parser.add_argument("--device-type", type=str, default="", help="cuda|cpu|mps (empty = autodetect)")
    parser.add_argument("--output-json", type=str, default=None, help="write structured results")
    args = parser.parse_args()

    device_type = autodetect_device_type() if args.device_type == "" else args.device_type
    _, ddp_rank, _, _, device = compute_init(device_type)

    # --- load vintage model (base / pretrain-only) ---
    if args.checkpoint_dir:
        step = args.step if args.step is not None else find_last_step(args.checkpoint_dir)
        model, tokenizer, meta = build_model(
            args.checkpoint_dir, step, device, phase="eval", tokenizer_dir=args.tokenizer_dir,
        )
    else:
        model, tokenizer, meta = load_model(
            "base", device, phase="eval", model_tag=args.model_tag, step=args.step,
            tokenizer_dir=args.tokenizer_dir,
        )
    token_bytes = get_token_bytes(device=device, tokenizer_dir=args.tokenizer_dir)
    print0(f"Loaded vintage base model at step {meta['step']} on {device}")

    # --- load probes ---
    authentic = load_authentic_questions(n=args.num_authentic)
    anachronistic = load_anachronistic_questions()
    anach_texts = [a["q"] for a in anachronistic]
    print0(f"Authentic questions: {len(authentic)}   Anachronistic probes: {len(anachronistic)}")

    # --- score under the vintage model (forward pass only) ---
    auth_v = score_word_bits(model, tokenizer, authentic, device, token_bytes, max_tokens=args.max_tokens)
    anach_v = score_word_bits(model, tokenizer, anach_texts, device, token_bytes, max_tokens=args.max_tokens)

    # --- optionally score under a modern model for the delta ---
    auth_m = anach_m = None
    if args.modern_hf_path:
        from scripts.base_eval import load_hf_model, get_hf_token_bytes
        modern, modern_tok = load_hf_model(args.modern_hf_path, device)
        modern_token_bytes = get_hf_token_bytes(modern_tok, device=device)
        auth_m = score_word_bits(modern, modern_tok, authentic, device, modern_token_bytes, max_tokens=args.max_tokens)
        anach_m = score_word_bits(modern, modern_tok, anach_texts, device, modern_token_bytes, max_tokens=args.max_tokens)

    if ddp_rank != 0:
        compute_cleanup()
        return

    # --- assemble metrics ---
    report = {
        "model_step": meta["step"],
        "peak_k": args.peak_k,
        "num_authentic": len(authentic),
        "modern_hf_path": args.modern_hf_path,
        "metrics": {},
    }

    v_auth = [m for m in (_vintage_metrics(w, args.peak_k) for w in auth_v) if m]
    v_anach = [m for m in (_vintage_metrics(w, args.peak_k) for w in anach_v) if m]
    _analyze("vintage_mean", [m[0] for m in v_auth], [m[0] for m in v_anach], anachronistic, report)
    vintage_peak_auc = _analyze("vintage_peak", [m[1] for m in v_auth], [m[1] for m in v_anach], anachronistic, report)

    delta_peak_auc = None
    if auth_m is not None:
        d_auth = [m for m in (_delta_metrics(wv, wm, args.peak_k) for wv, wm in zip(auth_v, auth_m)) if m]
        d_anach = [m for m in (_delta_metrics(wv, wm, args.peak_k) for wv, wm in zip(anach_v, anach_m)) if m]
        _analyze("delta_mean", [m[0] for m in d_auth], [m[0] for m in d_anach], anachronistic, report)
        delta_peak_auc = _analyze("delta_peak", [m[1] for m in d_auth], [m[1] for m in d_anach], anachronistic, report)

    # --- verdict ---
    headline = delta_peak_auc if delta_peak_auc is not None else vintage_peak_auc
    label = "delta_peak" if delta_peak_auc is not None else "vintage_peak"
    verdict = "SIGNAL" if headline >= 0.8 else ("WEAK" if headline >= 0.65 else "NO SIGNAL")
    print0("")
    print0(f"VERDICT ({label} AUC {headline:.3f}): {verdict}")
    if delta_peak_auc is not None:
        print0(f"  delta_peak {delta_peak_auc:.3f} vs vintage_peak {vintage_peak_auc:.3f}  "
               f"({delta_peak_auc - vintage_peak_auc:+.3f} from the modern-model delta)")
    report["verdict"] = verdict

    # --- log to nanochat report + optional structured json ---
    try:
        from nanochat.report import get_report
        get_report().log(section="Anachronism separation test", data=[{
            "model step": meta["step"],
            "modern reference": args.modern_hf_path or "none",
            "vintage_peak AUC": vintage_peak_auc,
            "delta_peak AUC": delta_peak_auc,
            "verdict": verdict,
        }])
    except Exception as e:
        print0(f"(report logging skipped: {e})")

    if args.output_json:
        os.makedirs(os.path.dirname(os.path.abspath(args.output_json)), exist_ok=True)
        tmp = args.output_json + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        os.replace(tmp, args.output_json)
        print0(f"Structured results written to: {args.output_json}")

    compute_cleanup()


if __name__ == "__main__":
    main()
