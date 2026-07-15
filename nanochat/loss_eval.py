"""
A number of functions that help with evaluating a base model.
"""
import re
import math
import torch
import torch.distributed as dist

_WORD_RE = re.compile(rb'\S+')

@torch.no_grad()
def evaluate_bpb(model, batches, steps, token_bytes):
    """
    Instead of the naive 'mean loss', this function returns the bits per byte (bpb),
    which is a tokenization vocab size-independent metric, meaning you are still comparing
    apples:apples if you change the vocab size. The way this works is that instead of just
    calculating the average loss as usual, you calculate the sum loss, and independently
    also the sum bytes (of all the target tokens), and divide. This normalizes the loss by
    the number of bytes that the target tokens represent.

    The added complexity is so that:
    1) All "normal" tokens are normalized by the length of the token in bytes
    2) No special tokens (e.g. <|bos|>) are included in the metric - they are masked out.
    3) No actively masked tokens (using ignore_index of e.g. -1) are included in the metric.

    In addition to evaluate_loss, we need the token_bytes tensor:
    It is a 1D tensor of shape (vocab_size,), indicating the number of bytes for
    each token id, or 0 if the token is to not be counted (e.g. special tokens).
    """
    # record the losses
    total_nats = torch.tensor(0.0, dtype=torch.float32, device=model.get_device())
    total_bytes = torch.tensor(0, dtype=torch.int64, device=model.get_device())
    batch_iter = iter(batches)
    for _ in range(steps):
        x, y = next(batch_iter)
        loss2d = model(x, y, loss_reduction='none') # (B, T)
        loss2d = loss2d.view(-1) # flatten
        y = y.view(-1) # flatten
        if (y.int() < 0).any(): # mps does not currently have kernel for < 0 for int64, only int32
            # slightly more complex code path if some target tokens are ignore_index (e.g. -1)
            # any target token < 0 is to be ignored: do NOT index token_bytes with negatives
            valid = y >= 0
            y_safe = torch.where(valid, y, torch.zeros_like(y))
            # map valid targets to their byte length; ignored targets contribute 0 bytes
            num_bytes2d = torch.where(
                valid,
                token_bytes[y_safe],
                torch.zeros_like(y, dtype=token_bytes.dtype)
            )
            total_nats += (loss2d * (num_bytes2d > 0)).sum()
            total_bytes += num_bytes2d.sum()
        else:
            # fast path: no ignored targets, safe to index directly
            num_bytes2d = token_bytes[y]
            total_nats += (loss2d * (num_bytes2d > 0)).sum()
            total_bytes += num_bytes2d.sum()
    # sum reduce across all ranks
    world_size = dist.get_world_size() if dist.is_initialized() else 1
    if world_size > 1:
        dist.all_reduce(total_nats, op=dist.ReduceOp.SUM)
        dist.all_reduce(total_bytes, op=dist.ReduceOp.SUM)
    # move both to cpu, calculate bpb and return
    total_nats = total_nats.item()
    total_bytes = total_bytes.item()
    if total_bytes == 0:
        return float('inf')
    bpb = total_nats / (math.log(2) * total_bytes)
    return bpb

@torch.no_grad()
def evaluate_bpb_per_position(model, batches, steps, token_bytes, bucket_size=256):
    """
    Same bpb metric as evaluate_bpb, but additionally bucketed by token position
    within the sequence. Useful for comparing models trained at different context
    lengths: loss at matched positions isolates model quality from the mechanical
    advantage of later positions having more context.

    Returns (overall_bpb, buckets) where buckets is a list of
    {"start": int, "end": int, "bpb": float} over position ranges [start, end).
    """
    device = model.get_device()
    nats_pos = None
    bytes_pos = None
    batch_iter = iter(batches)
    for _ in range(steps):
        x, y = next(batch_iter)
        B, T = x.shape
        # the model returns the unreduced loss flattened to (B*T,); restore (B, T)
        loss2d = model(x, y, loss_reduction='none').view(B, T)
        y2d = y.view(B, T)
        if nats_pos is None:
            nats_pos = torch.zeros(T, dtype=torch.float32, device=device)
            bytes_pos = torch.zeros(T, dtype=torch.int64, device=device)
        valid = y2d >= 0
        y_safe = torch.where(valid, y2d, torch.zeros_like(y2d))
        num_bytes2d = torch.where(
            valid,
            token_bytes[y_safe],
            torch.zeros_like(y2d, dtype=token_bytes.dtype)
        )
        nats_pos += (loss2d * (num_bytes2d > 0)).sum(dim=0)
        bytes_pos += num_bytes2d.sum(dim=0)
    world_size = dist.get_world_size() if dist.is_initialized() else 1
    if world_size > 1:
        dist.all_reduce(nats_pos, op=dist.ReduceOp.SUM)
        dist.all_reduce(bytes_pos, op=dist.ReduceOp.SUM)
    nats_pos = nats_pos.cpu()
    bytes_pos = bytes_pos.cpu()
    total_bytes = bytes_pos.sum().item()
    overall_bpb = nats_pos.sum().item() / (math.log(2) * total_bytes) if total_bytes > 0 else float('inf')
    buckets = []
    T = nats_pos.numel()
    for start in range(0, T, bucket_size):
        end = min(start + bucket_size, T)
        nb = bytes_pos[start:end].sum().item()
        bpb = nats_pos[start:end].sum().item() / (math.log(2) * nb) if nb > 0 else float('inf')
        buckets.append({"start": start, "end": end, "bpb": bpb})
    return overall_bpb, buckets

@torch.no_grad()
def score_sequence_losses(model, tokenizer, texts, device, peak_k=3, max_tokens=512):
    """
    Score a list of raw text strings by the model's per-token loss, one sequence at
    a time. Unlike evaluate_bpb (which aggregates a single corpus-level metric over a
    dataloader), this returns a *per-text* record, which is what anachronism filtering
    needs: one scalar per candidate question.

    For each text we prepend <|bos|> and measure the model's cross-entropy (in nats)
    on each subsequent token. We report two views of the same per-token losses:
      - mean: average loss over the text (overall surprise)
      - peak: mean of the top-k per-token losses (localized surprise) — a single
              anachronistic token spikes a few positions and is otherwise washed out
              by the mean, so peak is the more discriminative signal for filtering.

    Returns a list of dicts aligned to `texts`: {"mean", "peak", "n_tokens"}.
    Sequences too short to score (< 2 tokens) yield NaN scores and n_tokens=0.
    """
    bos = tokenizer.get_bos_token_id()
    results = []
    for text in texts:
        ids = tokenizer.encode(text, prepend=bos)[:max_tokens]
        if len(ids) < 2:
            results.append({"mean": float("nan"), "peak": float("nan"), "n_tokens": 0})
            continue
        x = torch.tensor(ids[:-1], dtype=torch.long, device=device).unsqueeze(0)
        y = torch.tensor(ids[1:], dtype=torch.long, device=device).unsqueeze(0)
        loss = model(x, y, loss_reduction='none').view(-1).float()  # (T,) nats per target token
        k = min(peak_k, loss.numel())
        results.append({
            "mean": loss.mean().item(),
            "peak": loss.topk(k).values.mean().item(),
            "n_tokens": int(loss.numel()),
        })
    return results

@torch.no_grad()
def score_word_bits(model, tokenizer, texts, device, token_bytes, max_tokens=512):
    """
    Score texts and return per-WORD bits, aligned to the raw text rather than to tokens.

    This is what makes two models with *different tokenizers* comparable. Per-token loss
    cannot be subtracted across vocabularies: the same word may be 1 token in one
    tokenizer and 3 in another, so "loss per token" measures different things on each
    side. Bits per byte is vocab-independent (the same reasoning behind evaluate_bpb),
    and words give an interpretable unit on top of it.

    For each text we:
      1) score every token with cross-entropy and convert nats -> bits,
      2) spread each token's bits uniformly across the bytes that token encodes,
      3) re-aggregate those bytes into whitespace-delimited words of the original text.

    Because step 3 keys off the raw text, two different models produce word arrays that
    line up 1:1, and their per-word bits can be differenced directly (the vintage-minus-
    modern "anachronism delta").

    `token_bytes` is the (vocab_size,) byte-length tensor for THIS model's tokenizer
    (nanochat.tokenizer.get_token_bytes, or base_eval.get_hf_token_bytes for HF models).

    Returns a list aligned to `texts` of dicts: {"words": [str], "bits": [float],
    "bytes": [int]}, where bits[i] is the total bits the model spent encoding words[i].
    """
    bos = tokenizer.get_bos_token_id()
    out = []
    for text in texts:
        ids = tokenizer.encode(text, prepend=bos)[:max_tokens]
        if len(ids) < 2:
            out.append({"words": [], "bits": [], "bytes": []})
            continue
        x = torch.tensor(ids[:-1], dtype=torch.long, device=device).unsqueeze(0)
        y = torch.tensor(ids[1:], dtype=torch.long, device=device).unsqueeze(0)
        loss = model(x, y, loss_reduction='none').view(-1).float()  # (T,) nats per target token
        bits = (loss / math.log(2)).tolist()
        nbytes = token_bytes[y.view(-1)].tolist()
        # spread each token's bits uniformly over the bytes it encodes
        byte_bits = []
        for b, nb in zip(bits, nbytes):
            nb = int(nb)
            if nb > 0:
                byte_bits.extend([b / nb] * nb)
        # re-aggregate bytes into the original text's words
        text_bytes = text.encode("utf-8")
        n = min(len(byte_bits), len(text_bytes))
        words, word_bits, word_bytes = [], [], []
        for m in _WORD_RE.finditer(text_bytes):
            start, end = m.start(), min(m.end(), n)
            if start >= n:
                break  # word lies beyond the truncated region
            words.append(text_bytes[m.start():m.end()].decode("utf-8", errors="replace"))
            word_bits.append(float(sum(byte_bits[start:end])))
            word_bytes.append(end - start)
        out.append({"words": words, "bits": word_bits, "bytes": word_bytes})
    return out
