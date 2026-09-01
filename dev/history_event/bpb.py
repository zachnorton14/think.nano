"""Exact target-masked bits-per-byte scoring and aggregation."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class TargetTokens:
    input_ids: list[int]
    target_mask: list[bool]
    target_bytes: int
    boundary_crossing: list[dict]

    def __post_init__(self) -> None:
        if len(self.target_mask) != len(self.input_ids) - 1:
            raise ValueError("target_mask must align with next-token targets")
        if self.target_bytes <= 0:
            raise ValueError("semantic target must contain at least one UTF-8 byte")


def native_target_tokens(tokenizer, prefix: str, target: str) -> TargetTokens:
    """Tokenize with exact tiktoken byte spans, including boundary-merging tokens."""
    conditioning = prefix + " "
    full = conditioning + target
    token_ids = tokenizer.encode(full)
    if not hasattr(tokenizer, "enc") or not hasattr(tokenizer.enc, "decode_single_token_bytes"):
        raise TypeError("native tokenizer must expose enc.decode_single_token_bytes")
    pieces = [tokenizer.enc.decode_single_token_bytes(token_id) for token_id in token_ids]
    if b"".join(pieces) != full.encode("utf-8"):
        raise ValueError("native token bytes do not reconstruct the scored text")
    boundary = len(conditioning.encode("utf-8"))
    crossings: list[dict] = []
    mask: list[bool] = []
    position = 0
    for index, (token_id, piece) in enumerate(zip(token_ids, pieces)):
        start, end = position, position + len(piece)
        include = end > boundary
        mask.append(include)
        if start < boundary < end:
            crossings.append({
                "token_index": index + 1,  # +1 because BOS is prepended below
                "token_id": token_id,
                "start_byte": start,
                "end_byte": end,
            })
        position = end
    bos = tokenizer.get_bos_token_id()
    # The first next-token target is token_ids[0], not BOS.
    return TargetTokens(
        input_ids=[bos, *token_ids],
        target_mask=mask,
        target_bytes=len(target.encode("utf-8")),
        boundary_crossing=crossings,
    )


def tiktoken_target_tokens(
    tokenizer, prefix: str, target: str, bos_token_id: int
) -> TargetTokens:
    """Tokenize a raw-completion tiktoken model with its explicit BOS token."""
    conditioning = prefix + " "
    full = conditioning + target
    token_ids = tokenizer.encode(full)
    pieces = [tokenizer.decode_single_token_bytes(token_id) for token_id in token_ids]
    if b"".join(pieces) != full.encode("utf-8"):
        raise ValueError("tiktoken bytes do not reconstruct the scored text")
    boundary = len(conditioning.encode("utf-8"))
    crossings: list[dict] = []
    token_mask: list[bool] = []
    position = 0
    for index, (token_id, piece) in enumerate(zip(token_ids, pieces)):
        start, end = position, position + len(piece)
        token_mask.append(end > boundary)
        if start < boundary < end:
            crossings.append({
                "token_index": index + 1,
                "token_id": token_id,
                "start_byte": start,
                "end_byte": end,
            })
        position = end
    return TargetTokens(
        input_ids=[bos_token_id, *token_ids],
        target_mask=token_mask,
        target_bytes=len(target.encode("utf-8")),
        boundary_crossing=crossings,
    )


def hf_target_tokens(tokenizer, prefix: str, target: str) -> TargetTokens:
    """Tokenize a Hugging Face fast tokenizer using character offset mappings."""
    conditioning = prefix + " "
    full = conditioning + target
    encoded = tokenizer(full, add_special_tokens=False, return_offsets_mapping=True)
    token_ids = list(encoded["input_ids"])
    offsets = [tuple(pair) for pair in encoded["offset_mapping"]]
    if len(token_ids) != len(offsets):
        raise ValueError("token ids and offset mappings have different lengths")
    boundary = len(conditioning)
    crossings = []
    mask = []
    for index, (token_id, (start, end)) in enumerate(zip(token_ids, offsets)):
        mask.append(end > boundary)
        if start < boundary < end:
            crossings.append({
                "token_index": index + 1,
                "token_id": token_id,
                "start_character": start,
                "end_character": end,
            })
    bos = tokenizer.bos_token_id
    if bos is None:
        bos = tokenizer.eos_token_id
    if bos is None:
        raise ValueError("Hugging Face tokenizer has neither BOS nor EOS token")
    return TargetTokens(
        input_ids=[bos, *token_ids],
        target_mask=mask,
        target_bytes=len(target.encode("utf-8")),
        boundary_crossing=crossings,
    )


def metrics_from_losses(
    losses_nats: Sequence[float], target_mask: Sequence[bool], target_bytes: int
) -> dict:
    if len(losses_nats) != len(target_mask):
        raise ValueError("losses and target mask must have equal lengths")
    if target_bytes <= 0:
        raise ValueError("target_bytes must be positive")
    selected = [float(loss) for loss, include in zip(losses_nats, target_mask) if include]
    if not selected:
        raise ValueError("target mask selected no tokens")
    nll = math.fsum(selected)
    return {
        "nll_nats": nll,
        "target_bytes": target_bytes,
        "target_token_count": len(selected),
        "bpb": nll / (math.log(2) * target_bytes),
    }


def metrics_from_logits(logits, target_ids, target_mask: Sequence[bool], target_bytes: int) -> dict:
    """Compute the masked NLL; logits must predict every id in target_ids."""
    import torch

    if logits.ndim == 3:
        if logits.shape[0] != 1:
            raise ValueError("only batch size one is supported")
        logits = logits[0]
    targets = torch.as_tensor(target_ids, dtype=torch.long, device=logits.device)
    if logits.shape[0] != targets.numel():
        raise ValueError("logits and target ids have different sequence lengths")
    losses = torch.nn.functional.cross_entropy(logits.float(), targets, reduction="none")
    return metrics_from_losses(losses.detach().cpu().tolist(), target_mask, target_bytes)


def _aggregate_group(rows: list[dict]) -> dict:
    if not rows:
        return {
            "event_count": 0,
            "macro_mean_bpb": None,
            "micro_bpb": None,
            "standard_deviation": None,
            "standard_error": None,
            "total_nll_nats": 0.0,
            "target_bytes": 0,
        }
    bpbs = [float(row["bpb"]) for row in rows]
    total_nll = math.fsum(float(row["nll_nats"]) for row in rows)
    total_bytes = sum(int(row["target_bytes"]) for row in rows)
    std = statistics.pstdev(bpbs) if len(bpbs) > 1 else 0.0
    return {
        "event_count": len(rows),
        "macro_mean_bpb": statistics.fmean(bpbs),
        "micro_bpb": total_nll / (math.log(2) * total_bytes),
        "standard_deviation": std,
        "standard_error": std / math.sqrt(len(rows)),
        "total_nll_nats": total_nll,
        "target_bytes": total_bytes,
    }


def aggregate_scores(rows: list[dict], cutoff_year: int | None) -> dict:
    if not rows:
        raise ValueError("cannot aggregate an empty score set")
    by_decade: dict[int, list[dict]] = {}
    for row in rows:
        by_decade.setdefault(int(row["event_decade"]), []).append(row)
    result = {
        "overall": _aggregate_group(rows),
        "by_decade": {str(decade): _aggregate_group(by_decade[decade]) for decade in sorted(by_decade)},
    }
    if cutoff_year is None:
        result.update({"pre_cutoff": None, "post_cutoff": None})
    else:
        result.update({
            "pre_cutoff": _aggregate_group([
                row for row in rows if row["event_year"] <= cutoff_year
            ]),
            "post_cutoff": _aggregate_group([
                row for row in rows if row["event_year"] > cutoff_year
            ]),
        })
    return result
