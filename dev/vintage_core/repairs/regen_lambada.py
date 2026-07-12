"""LAMBADA sentence-array restyle: light per-sentence restyle, fail-closed per element.

The (tail-frozen) prefix is split into a lossless sentence array in code. Sentences that are
head-truncated, the penultimate cue, target-bearing, or pure dialogue are marked verbatim and
never sent. The rest go to the model as a JSON array; the model returns a same-length array. Each
returned sentence is validated independently (quotes, newlines, digits, no post-1930) and reverted
to its original if it fails - so one bad sentence never discards the passage, and sentence count is
guaranteed by structure. The reconstructed row must still pass the full release gate.

Staged rollout:
  python -m dev.vintage_core.repairs.regen_lambada --pilot 50   # blind review file, no bundle write
  python -m dev.vintage_core.repairs.regen_lambada --generate   # full, writes accepted rows
"""
from __future__ import annotations

import argparse
import collections
import difflib
import json
import math
import random
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dev.vintage_core import bundle_validation as bv
from dev.vintage_core import temporal
from dev.vintage_core.repairs import decompose_lambada as dl
from dev.vintage_core.repairs.regen_squad import _restore_boundary_whitespace

REL = Path("eval_data/language_understanding/lambada_openai.jsonl")
ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "artifacts" / "vintage-core-filtered"
CANDIDATE = ROOT / "artifacts" / "vintage-core-restyle"
REVIEW = ROOT / "dev" / "vintage_core" / "review" / "restyle_lambada_pilot.md"
FINAL_REVIEW = ROOT / "dev" / "vintage_core" / "review" / "restyle_lambada_final_sample.md"
REPORT = ROOT / "dev" / "vintage_core" / "review" / "restyle_lambada_report.md"
AUDIT_LOG = ROOT / "dev" / "vintage_core" / "review" / "restyle_lambada_semantic_audit.jsonl"
AGENT_INPUT = ROOT / "dev" / "vintage_core" / "review" / "lambada_agent_trial_input.jsonl"
AGENT_CANDIDATES = ROOT / "dev" / "vintage_core" / "review" / "lambada_agent_trial_candidates.jsonl"
AGENT_AUDIT_INPUT = ROOT / "dev" / "vintage_core" / "review" / "lambada_agent_trial_audit_input.jsonl"
AGENT_VERDICTS = ROOT / "dev" / "vintage_core" / "review" / "lambada_agent_trial_verdicts.jsonl"

_TERMINATORS = re.compile(r"[.!?]+")
_WORD = re.compile(r"\b[A-Za-z][A-Za-z'’.-]*\b")
_ATTRIBUTION = re.compile(
    r"\b(?:(?:said|asked|answered|replied|returned|cried|called|whispered|murmured|"
    r"shouted|yelled|observed|remarked|added|continued|agreed|insisted|explained|"
    r"suggested|muttered|groaned|laughed|chuckled|wailed)\s+(?:he|she|they|[A-Z][\w'’.-]*)|"
    r"(?:he|she|they|[A-Z][\w'’.-]*)\s+(?:said|asked|answered|replied|returned|cried|"
    r"called|whispered|murmured|shouted|yelled|observed|remarked|added|continued|agreed|"
    r"insisted|explained|suggested|muttered|groaned|laughed|chuckled|wailed))\b",
    re.IGNORECASE,
)
_COMMON_CAPITALIZED = {
    "A", "An", "And", "As", "At", "Before", "Both", "But", "By", "Even", "Eventually",
    "For", "From", "He", "Her", "His", "How", "I", "If", "In", "Instead", "It", "Its",
    "Later", "Like", "Meanwhile", "My", "No", "Now", "Oh", "On", "Once", "She", "So",
    "Some", "That", "The", "Then", "There", "Thereafter", "Thereupon", "They", "This", "Though", "To", "We", "Well",
    "What", "When", "Where", "While", "Who", "Why", "With", "Without", "Yes", "You",
}
_MODAL = re.compile(r"\b(?:can|could|may|might|must|shall|should|will|would)\b", re.IGNORECASE)
_EMPHATIC_DO = re.compile(r"\b(?:do|does|did)\s+(?!not\b)[a-z]+\b", re.IGNORECASE)
_ADVERB = re.compile(r"\b[a-z]+ly\b", re.IGNORECASE)
_HYPHENATED = re.compile(r"\b[A-Za-z]+(?:-[A-Za-z]+)+\b")
_UNAMBIGUOUS_CONTRACTION = re.compile(
    r"\b(?:I'm|you're|he's|she's|it's|we're|they're|I've|you've|we've|they've|I'll|you'll|"
    r"he'll|she'll|we'll|they'll|isn't|aren't|wasn't|weren't|don't|doesn't|didn't|can't|"
    r"couldn't|won't|wouldn't|shouldn't|hasn't|haven't|hadn't)\b",
    re.IGNORECASE,
)
_SAFE_LEXICAL_OPPORTUNITY = re.compile(
    r"\b(?:inside|begin|began|start|started|help|helped|kids|while)\b", re.IGNORECASE,
)
AUDITED_PILOT_REVERTS = frozenset({
    487, 672, 743, 1116, 1261, 1623, 1815, 1988, 2289, 2341, 2419, 2560, 2654,
    2707, 2835, 2850, 2881, 3079, 3123, 3172, 3196, 3220, 3307, 3327, 3342,
    3396, 3481, 3602, 3829, 4064, 4067,
})


def _read(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _write(path, rows):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def _proper_name_tokens(text: str) -> collections.Counter:
    tokens = []
    for match in _WORD.finditer(text):
        token = match.group(0).strip(".'’-")
        lowered = token.lower().replace("’", "'")
        if re.match(r"^(?:i|you|he|she|it|we|they|there|that|who|what)(?:'m|'re|'ve|'d|'ll|'s)$", lowered):
            continue
        if lowered in {
            "isn't", "aren't", "wasn't", "weren't", "don't", "doesn't", "didn't", "can't",
            "couldn't", "won't", "wouldn't", "shouldn't", "hasn't", "haven't", "hadn't",
        }:
            continue
        if token[:1].isupper() and token not in _COMMON_CAPITALIZED:
            tokens.append(token)
    return collections.Counter(tokens)


def _attribution_signature(text: str) -> list[str]:
    if not dl.QUOTED_SPAN_RE.search(text):
        return []
    return [" ".join(match.group(0).split()) for match in _ATTRIBUTION.finditer(text)]


def _modal_signature(text: str) -> list[str]:
    normalized = text.lower().replace("’", "'")
    normalized = re.sub(
        r"\b(i|you|he|she|it|we|they)'ll\b", r"\1 will", normalized,
    )
    replacements = {
        "can't": "can not", "couldn't": "could not", "mayn't": "may not",
        "mightn't": "might not", "mustn't": "must not", "shan't": "shall not",
        "shouldn't": "should not", "won't": "will not", "wouldn't": "would not",
    }
    for contraction, expanded in replacements.items():
        normalized = normalized.replace(contraction, expanded)
    normalized = normalized.replace("cannot", "can not")
    return _MODAL.findall(normalized)


def _element_ok(orig: str, new: str) -> bool:
    """Accept a restyled sentence only if it preserves quotes, newlines, digits and stays pre-1930."""
    if not isinstance(new, str) or not new.strip():
        return False
    if bv.quoted_spans(orig) != bv.quoted_spans(new):
        return False
    if orig.count("\n") != new.count("\n"):
        return False
    if bv.digit_tokens(orig) != bv.digit_tokens(new):
        return False
    if _TERMINATORS.findall(orig) != _TERMINATORS.findall(new):
        return False
    if _proper_name_tokens(orig) != _proper_name_tokens(new):
        return False
    if _attribution_signature(orig) != _attribution_signature(new):
        return False
    if _modal_signature(orig) != _modal_signature(new):
        return False
    if len(_EMPHATIC_DO.findall(new)) > len(_EMPHATIC_DO.findall(orig)):
        return False
    if collections.Counter(_ADVERB.findall(orig.lower())) != collections.Counter(_ADVERB.findall(new.lower())):
        return False
    if collections.Counter(_HYPHENATED.findall(orig.lower())) != collections.Counter(_HYPHENATED.findall(new.lower())):
        return False
    new_upon = len(re.findall(r"\bupon\b", new, re.IGNORECASE))
    old_upon = len(re.findall(r"\bupon\b", orig, re.IGNORECASE))
    if new_upon > old_upon:
        old_on = len(re.findall(r"\b(?:on|onto)\b", orig, re.IGNORECASE))
        new_on = len(re.findall(r"\b(?:on|onto)\b", new, re.IGNORECASE))
        if old_on - new_on < new_upon - old_upon:
            return False
        if re.search(r"\baccompan(?:y|ies|ied)\b.*\bupon\b", new, re.IGNORECASE):
            return False
    for phrase in ("pick up", "picked up", "picking up"):
        if phrase in orig.lower() and phrase not in new.lower():
            return False
    # LAMBADA is a light edit. This rejects wholesale rewrites while allowing contraction
    # expansion and several small diction changes in a longer sentence.
    if difflib.SequenceMatcher(None, orig, new).ratio() < 0.72:
        return False
    if set(temporal.post_cutoff_years({"context": new})) - set(temporal.post_cutoff_years({"context": orig})):
        return False
    if set(temporal.science_anachronisms({"context": new})) - set(temporal.science_anachronisms({"context": orig})):
        return False
    return True


def _restyle_prefix(filt_row, chat_fn):
    """Return a restyled prefix (or None if nothing safely changed)."""
    prefix, _frag = dl.split_context(filt_row["context"])
    marked = dl.mark_verbatim(dl.split_sentences(prefix), filt_row["continuation"])
    editable = [m["text"] for m in marked if not m["verbatim"]]
    if not editable:
        return None
    from dev.vintage_core import prompts
    try:
        out = chat_fn(prompts.lambada_sentence_messages(editable))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(out, list) or len(out) != len(editable):
        return None
    # restore each element's original boundary whitespace (preserves inter-sentence spaces and
    # newlines), then accept/revert per element and splice back in order
    def resolve(orig, new):
        if not isinstance(new, str):
            return orig
        restored = _restore_boundary_whitespace(orig, new)
        return restored if _element_ok(orig, restored) else orig
    validated = [resolve(orig, new) for orig, new in zip(editable, out)]
    it = iter(validated)
    pieces = [m["text"] if m["verbatim"] else next(it) for m in marked]
    restyled = "".join(pieces)
    return restyled if restyled != prefix else None


def _row_ok(filt_row, restyled_prefix, idx):
    _prefix, frag = dl.split_context(filt_row["context"])
    candidate = {"context": dl.rebuild_context(restyled_prefix, frag), "continuation": filt_row["continuation"]}
    issues = bv.validate_pair("lambada_openai", "language_modeling", idx, filt_row, candidate)
    return candidate if not issues else None


def _chat_json_fn():
    from dev.vintage_core.client import chat_json
    import os
    base = os.environ.get("VINTAGE_RESTYLE_BASE_URL", "https://opencode.ai/zen/go/v1")
    model = os.environ.get("VINTAGE_RESTYLE_MODEL", "mimo-v2.5")
    return lambda msgs: chat_json(msgs, model, base, temperature=0.4, max_tokens=4096)


def _generate(filt, idxs, workers=32):
    chat_fn = _chat_json_fn()

    def one(idx):
        pre = _restyle_prefix(filt[idx], chat_fn)
        return (idx, _row_ok(filt[idx], pre, idx)) if pre is not None else (idx, None)

    out = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for f in as_completed([ex.submit(one, i) for i in idxs]):
            idx, row = f.result()
            if row:
                out[idx] = row
    return out


def _spread(values, count, seed=0):
    """Deterministically sample across a stratum instead of taking a corpus prefix."""
    if count <= 0 or not values:
        return []
    if count >= len(values):
        return list(values)
    if seed:
        return sorted(random.Random(seed).sample(values, count))
    return [values[min(len(values) - 1, math.floor(i * len(values) / count))] for i in range(count)]


def _pilot_indices(filt, count, seed=0):
    narrative, mixed, frozen = [], [], []
    for idx, row in enumerate(filt):
        prefix, _frag = dl.split_context(row["context"])
        marked = dl.mark_verbatim(dl.split_sentences(prefix), row["continuation"])
        editable = [m["text"] for m in marked if not m["verbatim"]]
        if not editable:
            frozen.append(idx)
        elif any(dl.QUOTED_SPAN_RE.search(text) for text in editable):
            mixed.append(idx)
        else:
            narrative.append(idx)
    each = count // 3
    selected = (_spread(narrative, each, seed) + _spread(mixed, each, seed + 1)
                + _spread(frozen, count - 2 * each, seed + 2))
    return selected


def _changed_elements(original, candidate):
    oprefix, _ = dl.split_context(original["context"])
    cprefix, _ = dl.split_context(candidate["context"])
    old = dl.split_sentences(oprefix)
    new = dl.split_sentences(cprefix)
    if len(old) != len(new):
        return [(oprefix, cprefix)]
    return [(before, after) for before, after in zip(old, new) if before != after]


def _write_review(filt, accepted, idxs, path=REVIEW, title="LAMBADA pilot"):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {title} ({len(accepted)}/{len(idxs)} passages styled)\n"]
    for idx in idxs:
        row = accepted.get(idx)
        lines.append(f"\n## idx {idx} - {'STYLED' if row else 'unchanged (stays original)'}")
        lines.append(f"- target: `{filt[idx]['continuation']}`")
        _pre, frag = dl.split_context(filt[idx]["context"])
        if row:
            changes = _changed_elements(filt[idx], row)
            lines.append(f"- changed elements: {len(changes)}")
            for change_no, (before, after) in enumerate(changes, 1):
                lines.append(f"  - {change_no} ORIG: {before!r}")
                lines.append(f"  - {change_no} NEW:  {after!r}")
        lines.append(f"- frozen final: {frag!r}")
    path.write_text("\n".join(lines), encoding="utf-8")


def _coverage(filt, rest):
    eligible_rows = styled_rows = total_elements = eligible_elements = styled_elements = 0
    for source, candidate in zip(filt, rest):
        prefix, _ = dl.split_context(source["context"])
        marked = dl.mark_verbatim(dl.split_sentences(prefix), source["continuation"])
        eligible = sum(not item["verbatim"] for item in marked)
        total_elements += len(marked)
        eligible_elements += eligible
        eligible_rows += bool(eligible)
        changes = _changed_elements(source, candidate) if source != candidate else []
        styled_elements += len(changes)
        styled_rows += bool(changes)
    return {
        "rows": len(filt), "eligible_rows": eligible_rows, "styled_rows": styled_rows,
        "total_elements": total_elements, "eligible_elements": eligible_elements,
        "styled_elements": styled_elements,
    }


def _write_report(filt, rest):
    stats = _coverage(filt, rest)
    row_pct = 100 * stats["styled_rows"] / stats["rows"]
    eligible_row_pct = 100 * stats["styled_rows"] / max(1, stats["eligible_rows"])
    element_pct = 100 * stats["styled_elements"] / max(1, stats["eligible_elements"])
    REPORT.write_text(
        "# LAMBADA Restyle Report\n\n"
        f"- Rows: {stats['rows']:,}\n"
        f"- Rows with editable narration: {stats['eligible_rows']:,}\n"
        f"- Rows with at least one accepted edit: {stats['styled_rows']:,} "
        f"({row_pct:.1f}% of all; {eligible_row_pct:.1f}% of eligible)\n"
        f"- Eligible sentence/chunks: {stats['eligible_elements']:,}\n"
        f"- Accepted edited sentence/chunks: {stats['styled_elements']:,} ({element_pct:.1f}%)\n"
        "- Continuations and final sentence fragments: frozen byte-for-byte\n",
        encoding="utf-8",
    )
    return stats


def _collect_audit_records(filt, rest):
    records = []
    for idx, (source, candidate) in enumerate(zip(filt, rest)):
        if source == candidate:
            continue
        oprefix, frag = dl.split_context(source["context"])
        cprefix, _ = dl.split_context(candidate["context"])
        old, new = dl.split_sentences(oprefix), dl.split_sentences(cprefix)
        if len(old) != len(new):
            records.append({
                "id": f"{idx}:row", "idx": idx, "position": -1,
                "original": oprefix, "candidate": cprefix,
                "target": source["continuation"], "frozen_tail": frag,
            })
            continue
        for position, (before, after) in enumerate(zip(old, new)):
            if before != after:
                records.append({
                    "id": f"{idx}:{position}", "idx": idx, "position": position,
                    "original": before, "candidate": after,
                    "target": source["continuation"], "frozen_tail": frag,
                })
    return records


def _audit_batch(records, base, model):
    from dev.vintage_core import prompts
    from dev.vintage_core.client import chat_json

    public = [
        {key: record[key] for key in ("id", "original", "candidate", "target", "frozen_tail")}
        for record in records
    ]
    expected = {record["id"] for record in records}
    try:
        response = chat_json(
            prompts.lambada_audit_messages(public), model, base,
            temperature=0.0, max_tokens=4096,
        )
        if not isinstance(response, list):
            raise ValueError("audit response is not an array")
        by_id = {item.get("id"): item for item in response if isinstance(item, dict)}
        if set(by_id) != expected or len(response) != len(expected):
            raise ValueError("audit response ids differ")
        return [
            {
                **record,
                "accept": by_id[record["id"]].get("accept") is True,
                "reason": str(by_id[record["id"]].get("reason", ""))[:300],
            }
            for record in records
        ]
    except Exception as exc:  # noqa: BLE001 - semantic audit fails closed
        return [{**record, "accept": False, "reason": f"audit failure: {exc}"} for record in records]


def _run_semantic_audit(filt, rest, batch_size=12, workers=12, dry_run=False):
    import os

    records = _collect_audit_records(filt, rest)
    batches = [records[start:start + max(1, batch_size)]
               for start in range(0, len(records), max(1, batch_size))]
    base = os.environ.get("VINTAGE_RESTYLE_BASE_URL", "https://opencode.ai/zen/go/v1")
    model = os.environ.get("VINTAGE_RESTYLE_MODEL", "mimo-v2.5")
    verdicts = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(_audit_batch, batch, base, model) for batch in batches]
        for future in as_completed(futures):
            verdicts.extend(future.result())
    verdicts.sort(key=lambda item: (item["idx"], item["position"]))
    AUDIT_LOG.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in verdicts),
        encoding="utf-8",
    )
    rejected = [item for item in verdicts if not item["accept"]]
    if dry_run:
        return len(records), rejected

    rejected_by_row: dict[int, set[int]] = {}
    for item in rejected:
        rejected_by_row.setdefault(item["idx"], set()).add(item["position"])
    for idx, positions in rejected_by_row.items():
        source, candidate = filt[idx], rest[idx]
        if -1 in positions:
            rest[idx] = source
            continue
        oprefix, frag = dl.split_context(source["context"])
        cprefix, _ = dl.split_context(candidate["context"])
        old, new = dl.split_sentences(oprefix), dl.split_sentences(cprefix)
        if len(old) != len(new):
            rest[idx] = source
            continue
        for position in positions:
            new[position] = old[position]
        rebuilt = {"context": dl.rebuild_context("".join(new), frag),
                   "continuation": source["continuation"]}
        rest[idx] = (rebuilt if not bv.validate_pair(
            "lambada_openai", "language_modeling", idx, source, rebuilt) else source)
    _write(CANDIDATE / REL, rest)
    _write_report(filt, rest)
    return len(records), rejected


def _retry_audit_failures(filt, rest, batch_size=3, workers=12):
    previous = [json.loads(line) for line in AUDIT_LOG.read_text(encoding="utf-8").splitlines()]
    failures = [item for item in previous if str(item.get("reason", "")).startswith("audit failure:")]
    if not failures:
        return 0, 0
    import os

    batches = [failures[start:start + max(1, batch_size)]
               for start in range(0, len(failures), max(1, batch_size))]
    base = os.environ.get("VINTAGE_RESTYLE_BASE_URL", "https://opencode.ai/zen/go/v1")
    model = os.environ.get("VINTAGE_RESTYLE_MODEL", "mimo-v2.5")
    retried = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(_audit_batch, batch, base, model) for batch in batches]
        for future in as_completed(futures):
            retried.extend(future.result())
    updates = {item["id"]: item for item in retried}
    merged = [updates.get(item["id"], item) for item in previous]
    merged.sort(key=lambda item: (item["idx"], item["position"]))
    AUDIT_LOG.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in merged), encoding="utf-8"
    )

    accepted_by_row: dict[int, dict[int, str]] = {}
    for item in retried:
        if item["accept"] and item["position"] >= 0 and _element_ok(item["original"], item["candidate"]):
            accepted_by_row.setdefault(item["idx"], {})[item["position"]] = item["candidate"]
    applied = 0
    for idx, replacements in accepted_by_row.items():
        source, candidate = filt[idx], rest[idx]
        oprefix, frag = dl.split_context(source["context"])
        cprefix, _ = dl.split_context(candidate["context"])
        old, current = dl.split_sentences(oprefix), dl.split_sentences(cprefix)
        if len(old) != len(current):
            continue
        for position, replacement in replacements.items():
            current[position] = replacement
            applied += 1
        rebuilt = {"context": dl.rebuild_context("".join(current), frag),
                   "continuation": source["continuation"]}
        if not bv.validate_pair("lambada_openai", "language_modeling", idx, source, rebuilt):
            rest[idx] = rebuilt
    _write(CANDIDATE / REL, rest)
    _write_report(filt, rest)
    return len(failures), applied


def _export_agent_trial(filt, rest, count=200, seed=20260712, contractions_only=False,
                        safe_lexical_only=False):
    choices = []
    for idx, (source, candidate) in enumerate(zip(filt, rest)):
        if source != candidate:
            continue
        prefix, _ = dl.split_context(source["context"])
        marked = dl.mark_verbatim(dl.split_sentences(prefix), source["continuation"])
        editable = [(position, item["text"]) for position, item in enumerate(marked)
                    if not item["verbatim"]]
        if not editable:
            continue
        # Isolated generators receive useful narration only: no quotations/attributions and enough
        # context for a faithful edit. One changed chunk is sufficient to style the row.
        plain = [
            item for item in editable
            if not dl.QUOTED_SPAN_RE.search(item[1])
            and not _attribution_signature(item[1])
            and len(_WORD.findall(item[1])) >= 6
        ]
        if contractions_only:
            plain = [item for item in plain if _UNAMBIGUOUS_CONTRACTION.search(item[1])]
        if safe_lexical_only:
            plain = [item for item in plain if _SAFE_LEXICAL_OPPORTUNITY.search(item[1])]
        if not plain:
            continue
        position, text = min(plain, key=lambda item: len(item[1]))
        choices.append({"id": f"{idx}:{position}", "text": text})
    selected = sorted(random.Random(seed).sample(choices, min(count, len(choices))),
                      key=lambda item: tuple(map(int, item["id"].split(":"))))
    AGENT_INPUT.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in selected),
        encoding="utf-8",
    )
    return len(selected)


def _prepare_agent_audit(filt, candidates_path=AGENT_CANDIDATES):
    inputs = {item["id"]: item for item in _read(AGENT_INPUT)}
    candidates = {item["id"]: item for item in _read(candidates_path)}
    if set(candidates) != set(inputs):
        raise ValueError("agent candidate ids differ from trial input ids")
    records = []
    for item_id, source_item in inputs.items():
        idx, _position = map(int, item_id.split(":"))
        _prefix, frag = dl.split_context(filt[idx]["context"])
        generated = candidates[item_id].get("candidate")
        if generated == source_item["text"] or not _element_ok(source_item["text"], generated):
            continue
        records.append({
            "id": item_id,
            "original": source_item["text"],
            "candidate": generated,
            "target": filt[idx]["continuation"],
            "frozen_tail": frag,
        })
    AGENT_AUDIT_INPUT.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records), encoding="utf-8"
    )
    return len(records)


def _apply_agent_candidates(filt, rest, candidates_path=AGENT_CANDIDATES,
                            verdicts_path=AGENT_VERDICTS):
    inputs = {item["id"]: item for item in _read(AGENT_INPUT)}
    candidates = {item["id"]: item for item in _read(candidates_path)}
    verdicts = {item["id"]: item for item in _read(verdicts_path)}
    if set(inputs) != set(candidates) or not set(verdicts).issubset(inputs):
        raise ValueError("agent trial input/candidate/verdict ids are inconsistent")
    applied = rejected = 0
    for item_id, source_item in inputs.items():
        idx, position = map(int, item_id.split(":"))
        generated = candidates[item_id].get("candidate")
        if item_id not in verdicts or verdicts[item_id].get("accept") is not True or not _element_ok(source_item["text"], generated):
            rejected += 1
            continue
        source = filt[idx]
        prefix, frag = dl.split_context(source["context"])
        chunks = dl.split_sentences(prefix)
        if position >= len(chunks) or chunks[position] != source_item["text"]:
            rejected += 1
            continue
        chunks[position] = generated
        candidate = {"context": dl.rebuild_context("".join(chunks), frag),
                     "continuation": source["continuation"]}
        if bv.validate_pair("lambada_openai", "language_modeling", idx, source, candidate):
            rejected += 1
            continue
        rest[idx] = candidate
        applied += 1
    _write(CANDIDATE / REL, rest)
    _write_report(filt, rest)
    return applied, rejected


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", type=int, default=0)
    ap.add_argument("--apply-pilot", action="store_true",
                    help="write accepted pilot rows so the full run reuses them")
    ap.add_argument("--generate", action="store_true")
    ap.add_argument("--pilot-seed", type=int, default=0,
                    help="nonzero seed selects a different deterministic stratified pilot")
    ap.add_argument("--apply-audited-reverts", action="store_true")
    ap.add_argument("--audit", action="store_true", help="semantic-equivalence audit current edits")
    ap.add_argument("--audit-dry-run", action="store_true", help="report semantic rejects, do not apply")
    ap.add_argument("--audit-batch-size", type=int, default=12)
    ap.add_argument("--audit-workers", type=int, default=12)
    ap.add_argument("--retry-audit-failures", action="store_true")
    ap.add_argument("--review-sample", type=int, default=0,
                    help="write a deterministic sample of surviving edits; no network")
    ap.add_argument("--export-agent-trial", type=int, default=0)
    ap.add_argument("--agent-seed", type=int, default=20260712)
    ap.add_argument("--agent-contractions", action="store_true")
    ap.add_argument("--agent-safe-lexical", action="store_true")
    ap.add_argument("--prepare-agent-audit", action="store_true")
    ap.add_argument("--apply-agent-candidates", action="store_true")
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--batch-size", type=int, default=128,
                    help="write an atomic bundle checkpoint after each batch")
    ap.add_argument("--max-items", type=int, default=0,
                    help="process at most N remaining rows; 0 means all")
    args = ap.parse_args()
    filt = _read(SOURCE / REL)
    rest = _read(CANDIDATE / REL)

    if args.apply_audited_reverts:
        for idx in AUDITED_PILOT_REVERTS:
            rest[idx] = filt[idx]
        _write(CANDIDATE / REL, rest)
        _write_report(filt, rest)
        print(f"lambada: reverted {len(AUDITED_PILOT_REVERTS)} audited pilot rows")

    if args.audit or args.audit_dry_run:
        total, rejected = _run_semantic_audit(
            filt, rest, args.audit_batch_size, args.audit_workers, dry_run=args.audit_dry_run,
        )
        print(f"lambada audit: rejected={len(rejected)}/{total} changed elements "
              f"dry_run={args.audit_dry_run} -> {AUDIT_LOG}")
        return

    if args.retry_audit_failures:
        retried, applied = _retry_audit_failures(
            filt, rest, args.audit_batch_size, args.audit_workers,
        )
        print(f"lambada audit retry: retried={retried} applied={applied}")
        return

    if args.review_sample:
        changed = [idx for idx, (source, candidate) in enumerate(zip(filt, rest))
                   if source != candidate]
        count = min(args.review_sample, len(changed))
        idxs = sorted(random.Random(20260712).sample(changed, count))
        accepted = {idx: rest[idx] for idx in idxs}
        _write_review(filt, accepted, idxs, FINAL_REVIEW, "LAMBADA final blind sample")
        print(f"lambada: wrote {count}-row final sample -> {FINAL_REVIEW}")
        return

    if args.export_agent_trial:
        count = _export_agent_trial(
            filt, rest, args.export_agent_trial, args.agent_seed, args.agent_contractions,
            args.agent_safe_lexical,
        )
        print(f"lambada: exported {count} isolated agent inputs -> {AGENT_INPUT}")
        return

    if args.prepare_agent_audit:
        count = _prepare_agent_audit(filt)
        print(f"lambada: prepared {count} independent audit records -> {AGENT_AUDIT_INPUT}")
        return

    if args.apply_agent_candidates:
        applied, rejected = _apply_agent_candidates(filt, rest)
        print(f"lambada: agent trial applied={applied} rejected={rejected}")
        return

    if args.pilot:
        idxs = _pilot_indices(filt, min(args.pilot, len(filt)), args.pilot_seed)
        queued = [idx for idx in idxs if rest[idx] == filt[idx]]
        accepted = {idx: rest[idx] for idx in idxs if rest[idx] != filt[idx]}
        accepted.update(_generate(filt, queued, args.workers))
        _write_review(filt, accepted, idxs)
        if args.apply_pilot:
            for idx, row in accepted.items():
                rest[idx] = row
            _write(CANDIDATE / REL, rest)
            _write_report(filt, rest)
        print(f"lambada pilot: {len(accepted)}/{len(idxs)} passages styled -> review at {REVIEW}")
        return

    if args.generate:
        idxs = [i for i in range(len(filt)) if rest[i]["context"] == filt[i]["context"]]
        idxs = idxs[:args.max_items or None]
        accepted_total = 0
        for start in range(0, len(idxs), max(1, args.batch_size)):
            batch = idxs[start:start + max(1, args.batch_size)]
            accepted = _generate(filt, batch, args.workers)
            for idx, row in accepted.items():
                rest[idx] = row
            accepted_total += len(accepted)
            _write(CANDIDATE / REL, rest)
            print(f"lambada: checkpoint {min(start + len(batch), len(idxs))}/{len(idxs)} "
                  f"accepted_total={accepted_total}", flush=True)
        stats = _write_report(filt, rest)
        print(f"lambada: styled {stats['styled_rows']} of {stats['rows']} passages; wrote bundle")


if __name__ == "__main__":
    main()
