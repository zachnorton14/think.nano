"""Restyle the filtered Vintage CORE bundle into an eval-ready period-register bundle.

Workflow:
  python -m dev.vintage_core.restyle preview --preview-size 10
  python -m dev.vintage_core.restyle stage --workers 4
  python -m dev.vintage_core.restyle audit
  python -m dev.vintage_core.restyle reject arc_challenge 12 --reason "..."
  python -m dev.vintage_core.restyle apply
  python -m dev.vintage_core.restyle package

Generation writes isolated candidates. Apply and package are offline and make no model calls.
"""
import argparse
import collections
import copy
import csv
import hashlib
import json
import os
import random
import re
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from difflib import SequenceMatcher

import yaml

from . import config, prompts
from .bundle_validation import digit_tokens, marker_signature, quoted_spans
from .client import RateLimited, Truncated, chat_json, cooldown_wait, usage_snapshot, usage_summary
from .temporal import annotate, science_anachronisms


OUT = config.OUT_RESTYLE
SOURCE = config.OUT_FILTERED
STAGE_DIR = os.path.join(OUT, "restyle", "staging")
APPROVED_DIR = os.path.join(OUT, "restyle", "approved")
REJECT_DIR = os.path.join(OUT, "restyle", "rejects")
AUDIT_REPORT = os.path.join(config.REVIEW_DIR, "restyle_audit.md")
PACKAGE_REPORT = os.path.join(OUT, "RESTYLE_REPORT.md")
RUN_LOG_DIR = os.path.join(OUT, "restyle", "run_logs")
PROMPT_VERSION = "restyle-v3"

STYLE_HINTS = ["schoolbook", "examination", "encyclopaedia", "miscellany"]
STYLE_WEIGHTS = [0.35, 0.30, 0.20, 0.15]
TEMP_SCHEDULE = [0.0, 0.6, 0.9, 1.1]
DEFAULT_MAX_TOKENS = 2048
MAX_GENERATION_TOKENS = 8192
DEFAULT_BATCH_SIZE = 1
# A 429 with a long cooldown (e.g. a free-tier usage-limit reset measured in hours)
# means retrying is futile: fail the item fast so the run reports it instead of the
# whole thread pool silently spinning on 60s sleeps forever.
MAX_RATE_LIMIT_WAIT = 300      # seconds; cooldown beyond this => give up on the item
MAX_RATE_LIMIT_RETRIES = 8     # bounded 429 retries so a persistent limit can't hang the run
MIMO_GO_INPUT_PER_M = 0.14
MIMO_GO_OUTPUT_PER_M = 0.28
MIMO_GO_CACHED_PER_M = 0.0028

COPY_UNCHANGED = {
    "bigbench_operators",
    "bigbench_language_identification",
    "agi_eval_lsat_ar",
    "bigbench_qa_wikidata",
}
MANUAL_REWRITE = {"bigbench_repeat_copy_logic"}
LAMBADA = "lambada_openai"

EMBEDDED_CHOICES_RE = re.compile(r"\nChoices:\n.*?\nAnswer:\s*$", re.S)
SENTENCE_MARK_RE = re.compile(r"[.!?]")
PREFIX_RE = re.compile(r"^(Question:|Q:)(\s*)")
SUFFIX_RE = re.compile(r"(\s*(?:Answer:|A:)\s*)$")
PROTECTED_SUFFIX_RE = re.compile(r"(\nChoices:\n.*?\nAnswer:\s*)$", re.S)
TOO_LIGHT_THRESHOLD = 0.92

# MiMo occasionally emits full-width / CJK punctuation (；，：！？（）) in place of ASCII.
# It is a cosmetic corruption, not a semantic one, so we normalise it losslessly rather
# than paying to regenerate. Curly quotes are intentionally left alone (quoted_spans handles them).
_FULLWIDTH_PUNCT = {
    "；": ";", "，": ",", "：": ":", "！": "!", "？": "?", "（": "(", "）": ")",
    "．": ".", "、": ",", "。": ".", "　": " ", "；": ";",
}
_FULLWIDTH_RE = re.compile("[" + "".join(_FULLWIDTH_PUNCT) + "]")


def _normalize_punctuation(text):
    if not isinstance(text, str):
        return text
    return _FULLWIDTH_RE.sub(lambda m: _FULLWIDTH_PUNCT[m.group(0)], text)


# A causal fragment completed by its choices ("...therefore"/"...consequently") that opens
# with a participial absolute ("X having ...", "X, being ...") has no finite main verb and
# dangles when a choice is appended (copa:39/40 class). Reject so it regenerates finitely.
_CAUSAL_TAIL_RE = re.compile(r"(?:^|[;,]\s*|\s)(?:therefore|consequently|so|thus|hence)\s*$", re.I)
_PARTICIPIAL_OPENING_RE = re.compile(r"^\W*(?:the\s+|a\s+|an\s+)?[A-Za-z]+(?:\s+[A-Za-z]+){0,2}\s*,?\s+(?:having|being)\b", re.I)


class ValidationError(ValueError):
    """Restyled item failed a deterministic invariant."""


RUN_STATS = collections.Counter()
RUN_STATS_LOCK = threading.Lock()


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
            stream.flush()

    def flush(self):
        for stream in self.streams:
            stream.flush()


def _default_log_path(command):
    return os.path.join(RUN_LOG_DIR, f"{command}.log")


def _install_run_log(command, path=None):
    path = os.path.expanduser(path or _default_log_path(command))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    f = open(path, "a", encoding="utf-8")
    sys.stdout = Tee(sys.stdout, f)
    sys.stderr = Tee(sys.stderr, f)
    print(f"run_log={path}", flush=True)
    print(f"run_started={datetime.now().isoformat(timespec='seconds')} append=true", flush=True)
    return f


def _usage_delta(before):
    after = usage_snapshot()
    return collections.Counter({key: after.get(key, 0) - before.get(key, 0) for key in set(after) | set(before)})


def _paid_equivalent(delta):
    prompt = delta.get("prompt", 0)
    cached = delta.get("cached", 0)
    uncached = max(0, prompt - cached)
    return (
        uncached * MIMO_GO_INPUT_PER_M / 1_000_000
        + cached * MIMO_GO_CACHED_PER_M / 1_000_000
        + delta.get("completion", 0) * MIMO_GO_OUTPUT_PER_M / 1_000_000
    )


def _record_usage(delta, latency, items, failover=False):
    with RUN_STATS_LOCK:
        RUN_STATS["items"] += items
        RUN_STATS["batches"] += 1
        RUN_STATS["latency_ms"] += int(latency * 1000)
        RUN_STATS["prompt"] += delta.get("prompt", 0)
        RUN_STATS["cached"] += delta.get("cached", 0)
        RUN_STATS["completion"] += delta.get("completion", 0)
        RUN_STATS["paid_equiv_micro"] += int(round(_paid_equivalent(delta) * 1_000_000))
        if failover:
            RUN_STATS["failovers"] += 1


def _run_summary():
    with RUN_STATS_LOCK:
        stats = collections.Counter(RUN_STATS)
    items = stats.get("items", 0)
    batches = stats.get("batches", 0)
    seconds = stats.get("latency_ms", 0) / 1000
    avg = (stats["prompt"] + stats["completion"]) / items if items else 0
    ipm = items / (seconds / 60) if seconds else 0
    return (
        f"paid_equiv_mimo_go=${stats['paid_equiv_micro']/1_000_000:.4f} "
        f"prompt={stats['prompt']} cached={stats['cached']} "
        f"completion={stats['completion']} avg_tokens_per_item={avg:.1f} "
        f"items_per_min={ipm:.1f} batches={batches} failovers={stats['failovers']}"
    )


def _atomic_text(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(value)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _atomic_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _read_jsonl(path, description):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValidationError(f"{description} line {line_no} invalid JSON: {e}") from e
    return rows


def _candidate_path(label):
    return os.path.join(STAGE_DIR, f"{label}.jsonl")


def _approved_path(label):
    return os.path.join(APPROVED_DIR, f"{label}.jsonl")


def _reject_path(label):
    return os.path.join(REJECT_DIR, f"{label}.rejects.jsonl")


def _review_path(label):
    return os.path.join(config.REVIEW_DIR, f"restyle_{label}.md")


def _load_filtered_tasks():
    with open(os.path.join(SOURCE, "core.yaml"), encoding="utf-8") as f:
        core = yaml.safe_load(f)
    tasks = []
    for task in core["icl_tasks"]:
        label = task["label"]
        path = os.path.join(SOURCE, "eval_data", task["dataset_uri"])
        with open(path, encoding="utf-8") as f:
            data = [json.loads(line) for line in f]
        tasks.append({
            "label": label,
            "task_type": task["icl_task_type"],
            "num_fewshot": task["num_fewshot"][0],
            "dataset_uri": task["dataset_uri"],
            "continuation_delimiter": task.get("continuation_delimiter", " "),
            "data": data,
            "yaml": task,
        })
    return tasks


def _metadata_rows():
    path = os.path.join(SOURCE, "eval_meta_data.csv")
    with open(path, encoding="utf-8") as f:
        return {row["Eval Task"]: row for row in csv.DictReader(f)}


def _benchmark_context(task, meta_rows):
    row = meta_rows.get(task["label"], {})
    return {
        "label": task["label"],
        "task_type": row.get("Task Type", task["task_type"]),
        "fewshot": row.get("#shots", str(task["num_fewshot"])),
        "random_baseline": row.get("Random baseline", ""),
        "description": row.get("Description", "").strip(),
    }


def _style_hint(idx):
    return random.Random(idx).choices(STYLE_HINTS, weights=STYLE_WEIGHTS, k=1)[0]


def _fingerprint(label, idx, original):
    raw = json.dumps(
        {"prompt": PROMPT_VERSION, "label": label, "idx": idx, "item": original},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _expected_keys(task_type):
    if task_type == "multiple_choice":
        return {"query", "choices", "gold"}
    if task_type == "schema":
        return {"context_options", "continuation", "gold"}
    if task_type == "language_modeling":
        return {"context", "continuation"}
    raise ValidationError(f"unsupported task type: {task_type}")


def _content_item(row):
    return row.get("candidate", row)


def _require_str(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string")


def _embedded_choices_block(query):
    m = EMBEDDED_CHOICES_RE.search(query or "")
    return m.group(0) if m else None


def _split_query_scaffold(query):
    """Return editable stem plus protected prefix/suffix for any scaffolded MC query."""
    prefix = ""
    body = query
    m = PREFIX_RE.match(body)
    if m:
        prefix = m.group(0)
        body = body[m.end():]
    suffix = ""
    m = PROTECTED_SUFFIX_RE.search(body)
    if m:
        suffix = m.group(1)
        body = body[:m.start()]
    else:
        m = SUFFIX_RE.search(body)
        if m:
            suffix = m.group(1)
            body = body[:m.start()]
    return prefix, body, suffix


def _with_query_scaffold(original, generated):
    if "query" not in original or "query" not in generated:
        return generated
    prefix, _body, suffix = _split_query_scaffold(original["query"])
    if not (prefix or suffix):
        return generated
    _gp, generated_body, _gs = _split_query_scaffold(generated["query"])
    out = copy.deepcopy(generated)
    out["query"] = f"{prefix}{generated_body.rstrip()}{suffix}"
    return out


def _speech_act(text):
    _prefix, body, _suffix = _split_query_scaffold(text)
    stripped = body.strip()
    lowered = stripped.lower()
    if not stripped:
        return "empty"
    if stripped.endswith("?"):
        return "question"
    if lowered.startswith(("to ", "make ", "create ", "assemble ", "remove ", "repeat ", "say ", "output ", "print ")):
        return "goal"
    if len(stripped.split()) <= 4 and not SENTENCE_MARK_RE.search(stripped):
        return "fragment"
    if stripped.endswith((",", ";", ":")):
        return "continuation"
    return "statement"


def _style_too_light(original_text, restyled_text):
    _prefix, original_body, _suffix = _split_query_scaffold(original_text)
    _rprefix, restyled_body, _rsuffix = _split_query_scaffold(restyled_text)
    if len(original_body.split()) < 8:
        return False
    if not SENTENCE_MARK_RE.search(original_body):
        return False
    return SequenceMatcher(None, original_body, restyled_body).ratio() > TOO_LIGHT_THRESHOLD


def _literals(text):
    return {
        "numbers": digit_tokens(text or ""),
        "quotes": quoted_spans(text or ""),
    }


def _text_fields(item, task_type):
    if task_type == "multiple_choice":
        return [item["query"]] + list(item["choices"])
    if task_type == "schema":
        return list(item["context_options"]) + [item["continuation"]]
    return [item["context"], item["continuation"]]


def _editable_text(item, task_type):
    if task_type == "multiple_choice":
        return item["query"]
    if task_type == "schema":
        return "\n".join(item["context_options"])
    return item["context"]


def _validate_literals(original, restyled, task_type):
    before = _literals("\n".join(_text_fields(original, task_type)))
    after = _literals("\n".join(_text_fields(restyled, task_type)))
    if before["numbers"] != after["numbers"]:
        raise ValidationError("numbers changed")
    if before["quotes"] != after["quotes"]:
        raise ValidationError("quoted text changed")


def _diff_span_pair(options):
    if len(options) != 2:
        return None
    a, b = options
    prefix = 0
    while prefix < min(len(a), len(b)) and a[prefix] == b[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < min(len(a), len(b)) - prefix
        and a[len(a) - 1 - suffix] == b[len(b) - 1 - suffix]
    ):
        suffix += 1
    a_mid = a[prefix: len(a) - suffix if suffix else len(a)]
    b_mid = b[prefix: len(b) - suffix if suffix else len(b)]
    return a_mid, b_mid


def _final_sentence_fragment(context):
    matches = list(SENTENCE_MARK_RE.finditer(context))
    if not matches:
        return context
    return context[matches[-1].end():]


def _sentence_count(context):
    return len(SENTENCE_MARK_RE.findall(context))


def _quote_count(context):
    return len(quoted_spans(context))


def _normalized_phrase(value):
    return " ".join(re.findall(r"[a-z0-9]+(?:'[a-z]+)?", value.lower()))


def _new_choice_leaks(original, item):
    before = _normalized_phrase(original["query"])
    after = _normalized_phrase(item["query"])
    leaks = []
    for choice in original["choices"]:
        phrase = _normalized_phrase(choice)
        if len(phrase) >= 4 and after.count(phrase) > before.count(phrase):
            leaks.append(choice)
    return leaks


def _new_joint_collision(original, item):
    continuation = original["continuation"]
    if not re.match(r"\s*[.!?,;:]", continuation):
        return False
    for old, new in zip(original["context_options"], item["context_options"]):
        if re.search(r"[.!?,;:]\s*$", new) and not re.search(r"[.!?,;:]\s*$", old):
            return True
    return False


def _validate_task_scaffold(original, item, label):
    markers = {
        "boolq": ("Passage:", "Question:"),
        "coqa": ("Story:", "Preceding questions:", "Final question:", "Question:", "Answer:"),
        "squad": ("Context:", "Question:", "Answer:"),
    }.get(label)
    if markers:
        source_text = original.get("context", original.get("query", ""))
        candidate_text = item.get("context", item.get("query", ""))
        if marker_signature(source_text, markers) != marker_signature(candidate_text, markers):
            raise ValidationError("protected scaffold marker sequence/placement changed")
        if label in {"coqa", "squad"} and not candidate_text.rstrip().endswith("Answer:"):
            raise ValidationError("context no longer ends in a blank Answer: cue")
    if label == "jeopardy":
        prefix = original["context"].split(":", 1)[0] + ":"
        if not item["context"].startswith(prefix):
            raise ValidationError("Jeopardy category prefix changed")


def validate_item(generated, original, task_type, label=""):
    if isinstance(generated, str):
        try:
            generated = json.loads(generated)
        except json.JSONDecodeError:
            pass
    if not isinstance(generated, dict):
        raise ValidationError("response is not a JSON object")
    generated = _with_query_scaffold(original, generated)
    keys = _expected_keys(task_type)
    missing = keys - generated.keys()
    if missing:
        raise ValidationError(f"missing keys: {sorted(missing)}")
    if "style_hint" in generated:
        raise ValidationError("style_hint leaked into output")
    unexpected = set(generated) - set(original)
    if unexpected:
        raise ValidationError(f"unexpected keys: {sorted(unexpected)}")
    # Only scoring content may be restyled. Preserve task-specific metadata and backfill
    # provenance from the filtered row even if the model omitted or altered those fields.
    item = {key: copy.deepcopy(generated[key]) for key in keys}
    item.update({key: copy.deepcopy(value) for key, value in original.items() if key not in keys})
    for key in keys:
        if isinstance(item[key], str):
            item[key] = _normalize_punctuation(item[key])
        elif isinstance(item[key], list):
            item[key] = [_normalize_punctuation(v) if isinstance(v, str) else v for v in item[key]]

    if task_type == "multiple_choice":
        _require_str(item["query"], "query")
        if item["choices"] != original["choices"]:
            raise ValidationError("choices changed")
        if item["gold"] != original["gold"]:
            raise ValidationError("gold changed")
        original_prefix, _original_body, original_suffix = _split_query_scaffold(original["query"])
        restyled_prefix, _restyled_body, restyled_suffix = _split_query_scaffold(item["query"])
        if original_prefix != restyled_prefix:
            raise ValidationError("scaffold prefix changed")
        if original_suffix != restyled_suffix:
            raise ValidationError("scaffold suffix changed")
        block = _embedded_choices_block(original["query"])
        if block and _embedded_choices_block(item["query"]) != block:
            raise ValidationError("embedded Choices block changed")
        if item["query"].count("\nChoices:\n") != original["query"].count("\nChoices:\n"):
            raise ValidationError("embedded Choices block count changed")
        if _speech_act(original["query"]) != _speech_act(item["query"]):
            raise ValidationError("speech act changed")
        if _style_too_light(original["query"], item["query"]):
            raise ValidationError("style too light")
        stem_body = _split_query_scaffold(item["query"])[1].strip()
        if _CAUSAL_TAIL_RE.search(stem_body) and _PARTICIPIAL_OPENING_RE.search(stem_body):
            raise ValidationError("dangling participial causal joint")
        leaks = _new_choice_leaks(original, item)
        if leaks:
            raise ValidationError(f"choice text newly appears in query: {leaks[:2]}")

    elif task_type == "schema":
        options = item["context_options"]
        if not isinstance(options, list) or len(options) != len(original["context_options"]):
            raise ValidationError("context option count changed")
        for i, option in enumerate(options):
            _require_str(option, f"context_options[{i}]")
        if item["continuation"] != original["continuation"]:
            raise ValidationError("continuation changed")
        if item["gold"] != original["gold"]:
            raise ValidationError("gold changed")
        original_diff = _diff_span_pair(original["context_options"])
        restyled_diff = _diff_span_pair(item["context_options"])
        if original_diff and restyled_diff and original_diff != restyled_diff:
            raise ValidationError("schema minimal-pair difference changed")
        if _new_joint_collision(original, item):
            raise ValidationError("new punctuation collision at continuation joint")

    elif task_type == "language_modeling":
        _require_str(item["context"], "context")
        if item["continuation"] != original["continuation"]:
            raise ValidationError("continuation changed")
        target = original["continuation"]
        if target and item["context"].count(target) != original["context"].count(target):
            raise ValidationError("target occurrence count changed")

    _validate_literals(original, item, task_type)
    _validate_task_scaffold(original, item, label)
    if label == LAMBADA:
        _validate_lambada(item, original)

    ann = annotate(item)
    if ann["regex_remove"] or ann["modern_terms"]:
        raise ValidationError(
            f"temporal regex hit: years={ann['years_found']} modern_terms={ann['modern_terms']}"
        )
    sci = science_anachronisms(item)
    if sci:
        raise ValidationError(f"post-1930 science concept: {sci}")
    return item


def _validate_lambada(item, original):
    fragment = _final_sentence_fragment(original["context"])
    if fragment and not item["context"].endswith(fragment):
        raise ValidationError("LAMBADA final sentence fragment changed")
    target = original["continuation"].strip()
    if target and item["context"].count(target) != original["context"].count(target):
        raise ValidationError("LAMBADA target occurrence count changed")
    if _sentence_count(item["context"]) != _sentence_count(original["context"]):
        raise ValidationError("LAMBADA sentence count changed")
    if _quote_count(item["context"]) != _quote_count(original["context"]):
        raise ValidationError("LAMBADA quote count changed")


def _chat_json_with_fallback(messages, temperature, max_tokens):
    before = usage_snapshot()
    start = time.time()
    failover = False
    try:
        result = chat_json(
            messages, config.RESTYLE_MODEL, config.RESTYLE_BASE_URL,
            temperature=temperature, max_tokens=max_tokens,
        )
    except RateLimited:
        failover = True
        result = chat_json(
            messages, config.RESTYLE_FALLBACK_MODEL, config.RESTYLE_FALLBACK_BASE_URL,
            temperature=temperature, max_tokens=max_tokens,
        )
    delta = _usage_delta(before)
    _record_usage(delta, time.time() - start, 1, failover=failover)
    return result


def _parse_batch_response(response, expected_ids):
    if isinstance(response, dict):
        for key in ("items", "results", "outputs"):
            if isinstance(response.get(key), list):
                response = response[key]
                break
    if not isinstance(response, list):
        raise ValidationError("batch response is not a JSON array")
    out = {}
    for row in response:
        if not isinstance(row, dict):
            raise ValidationError("batch row is not an object")
        bid = row.get("id")
        if not isinstance(bid, int) or isinstance(bid, bool):
            raise ValidationError("batch row has invalid id")
        if bid in out:
            raise ValidationError(f"batch response duplicate id={bid}")
        if bid not in expected_ids:
            raise ValidationError(f"batch response unexpected id={bid}")
        item = row.get("item", row.get("output", row.get("result")))
        if not isinstance(item, dict):
            raise ValidationError(f"batch row id={bid} missing item object")
        out[bid] = item
    missing = set(expected_ids) - set(out)
    if missing:
        raise ValidationError(f"batch response missing ids={sorted(missing)}")
    return out


def _chat_batch_json_with_fallback(messages, temperature, max_tokens, item_count):
    before = usage_snapshot()
    start = time.time()
    failover = False
    try:
        result = chat_json(
            messages, config.RESTYLE_MODEL, config.RESTYLE_BASE_URL,
            temperature=temperature, max_tokens=max_tokens,
        )
    except RateLimited:
        failover = True
        result = chat_json(
            messages, config.RESTYLE_FALLBACK_MODEL, config.RESTYLE_FALLBACK_BASE_URL,
            temperature=temperature, max_tokens=max_tokens,
        )
    delta = _usage_delta(before)
    _record_usage(delta, time.time() - start, item_count, failover=failover)
    return result


def _chunked(values, size):
    size = max(1, int(size))
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _generate_valid(task, idx, benchmark, rejection_feedback="", start_temperature_index=0,
                    retries=4, max_tokens=DEFAULT_MAX_TOKENS):
    original = task["data"][idx]
    attempts = 0
    rl_attempts = 0
    temperature_index = start_temperature_index
    token_budget = max_tokens
    feedback = rejection_feedback
    last = None
    while attempts < retries:
        temperature = TEMP_SCHEDULE[min(temperature_index, len(TEMP_SCHEDULE) - 1)]
        messages = prompts.restyle_messages(
            original, task["task_type"], benchmark, _style_hint(idx),
            rejection_feedback=feedback, lambada=(task["label"] == LAMBADA),
        )
        generated = None
        try:
            generated = _chat_json_with_fallback(messages, temperature, token_budget)
            item = validate_item(generated, original, task["task_type"], task["label"])
            return item
        except Truncated as e:
            last = e
            if token_budget >= MAX_GENERATION_TOKENS:
                break
            token_budget = min(token_budget * 2, MAX_GENERATION_TOKENS)
        except RateLimited as e:
            last = e
            wait = cooldown_wait()
            rl_attempts += 1
            if wait > MAX_RATE_LIMIT_WAIT or rl_attempts > MAX_RATE_LIMIT_RETRIES:
                break
            time.sleep(min(max(wait, 1.0), 60.0))
        except Exception as e:  # noqa: BLE001
            last = e
            attempts += 1
            temperature_index += 1
            token_budget = max_tokens
            if generated is not None:
                feedback = f"{rejection_feedback} Latest validation failure: {e}".strip()
            if attempts < retries:
                time.sleep(min(2 ** attempts, 8))
    raise RuntimeError(f"{task['label']} idx={idx} failed after {retries} attempts: {last}")


def _generate_batch_valid(task, idxs, benchmark, rejections, candidates, retries=4,
                          max_tokens=DEFAULT_MAX_TOKENS):
    if len(idxs) == 1:
        idx = idxs[0]
        old = candidates.get(idx)
        old_revision = int(old.get("revision", 0)) if old else 0
        item = _generate_valid(
            task, idx, benchmark,
            rejection_feedback=rejections.get(idx, ""),
            start_temperature_index=1 if idx in rejections else 0,
            retries=retries, max_tokens=max_tokens,
        )
        return {idx: _wrapper(task, idx, item, old_revision + 1)}

    # Mixed rejection feedback makes a single batch prompt ambiguous; split those into singles.
    if any(idx in rejections for idx in idxs):
        merged = {}
        for idx in idxs:
            merged.update(_generate_batch_valid(task, [idx], benchmark, rejections, candidates, retries, max_tokens))
        return merged

    attempts = 0
    rl_attempts = 0
    temperature_index = 0
    token_budget = max_tokens
    last = None
    while attempts < retries:
        temperature = TEMP_SCHEDULE[min(temperature_index, len(TEMP_SCHEDULE) - 1)]
        batch = [(idx, task["data"][idx], _style_hint(idx)) for idx in idxs]
        messages = prompts.restyle_batch_messages(
            batch, task["task_type"], benchmark, lambada=(task["label"] == LAMBADA),
        )
        generated = None
        try:
            generated = _chat_batch_json_with_fallback(messages, temperature, token_budget, len(idxs))
            by_id = _parse_batch_response(generated, set(idxs))
            wrappers = {}
            for idx in idxs:
                item = validate_item(by_id[idx], task["data"][idx], task["task_type"], task["label"])
                old = candidates.get(idx)
                old_revision = int(old.get("revision", 0)) if old else 0
                wrappers[idx] = _wrapper(task, idx, item, old_revision + 1)
            return wrappers
        except Truncated as e:
            last = e
            if token_budget >= MAX_GENERATION_TOKENS:
                break
            token_budget = min(token_budget * 2, MAX_GENERATION_TOKENS)
        except RateLimited as e:
            last = e
            wait = cooldown_wait()
            rl_attempts += 1
            if wait > MAX_RATE_LIMIT_WAIT or rl_attempts > MAX_RATE_LIMIT_RETRIES:
                break
            time.sleep(min(max(wait, 1.0), 60.0))
        except Exception as e:  # noqa: BLE001
            last = e
            attempts += 1
            temperature_index += 1
            token_budget = max_tokens
            if attempts < retries:
                time.sleep(min(2 ** attempts, 8))

    # Preserve work granularity: a bad batch falls back to per-item retries.
    merged = {}
    errors = []
    for idx in idxs:
        try:
            merged.update(_generate_batch_valid(task, [idx], benchmark, rejections, candidates, retries, max_tokens))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{idx}: {e}")
    if errors:
        raise RuntimeError(
            f"{task['label']} batch {idxs[0]}..{idxs[-1]} failed after split; "
            f"batch_error={last}; item_errors={errors}"
        )
    return merged


def _wrapper(task, idx, candidate, revision):
    original = task["data"][idx]
    return {
        "label": task["label"],
        "idx": idx,
        "dataset_uri": task["dataset_uri"],
        "prompt_version": PROMPT_VERSION,
        "fingerprint": _fingerprint(task["label"], idx, original),
        "revision": revision,
        "style_hint": _style_hint(idx),
        "candidate": candidate,
    }


def _load_wrappers(path):
    out = {}
    for line_no, row in enumerate(_read_jsonl(path, path), 1):
        idx = row.get("idx") if isinstance(row, dict) else None
        if not isinstance(idx, int) or isinstance(idx, bool):
            raise ValidationError(f"{path} line {line_no} invalid idx")
        if idx in out:
            raise ValidationError(f"{path} duplicate idx={idx}")
        out[idx] = row
    return out


def _load_rejections(label):
    out = {}
    for line_no, row in enumerate(_read_jsonl(_reject_path(label), f"{label} rejects"), 1):
        idx = row.get("idx") if isinstance(row, dict) else None
        reason = row.get("reason") if isinstance(row, dict) else None
        if not isinstance(idx, int) or isinstance(idx, bool):
            raise ValidationError(f"{label} reject line {line_no} invalid idx")
        if not isinstance(reason, str) or not reason.strip():
            raise ValidationError(f"{label} reject line {line_no} empty reason")
        out[idx] = reason.strip()
    return out


def _write_rejections(label, rejections):
    _atomic_jsonl(_reject_path(label), [{"idx": idx, "reason": reason} for idx, reason in sorted(rejections.items())])


def _validate_wrapper(task, wrapper):
    idx = wrapper.get("idx")
    if not isinstance(idx, int) or isinstance(idx, bool) or not 0 <= idx < len(task["data"]):
        raise ValidationError("invalid idx")
    if wrapper.get("label") != task["label"] or wrapper.get("dataset_uri") != task["dataset_uri"]:
        raise ValidationError("stale task identity")
    if wrapper.get("prompt_version") != PROMPT_VERSION:
        raise ValidationError("stale prompt version")
    if wrapper.get("fingerprint") != _fingerprint(task["label"], idx, task["data"][idx]):
        raise ValidationError("stale source fingerprint")
    item = validate_item(wrapper.get("candidate"), task["data"][idx], task["task_type"], task["label"])
    return item


def _eligible_tasks(tasks_filter=None, include_lambada=False):
    tasks_filter = tasks_filter or set()
    out = []
    for task in _load_filtered_tasks():
        label = task["label"]
        if tasks_filter and label not in tasks_filter:
            continue
        if label in COPY_UNCHANGED or label in MANUAL_REWRITE:
            continue
        if label == LAMBADA and not include_lambada:
            continue
        out.append(task)
    return out


def _selected_indices(task, limit=-1):
    total = len(task["data"])
    if limit <= 0 or limit >= total:
        return list(range(total))
    if limit == 1:
        return [0]
    return sorted({round(i * (total - 1) / (limit - 1)) for i in range(limit)})


def _write_review(label, task, wrappers, errors=None):
    errors = errors or {}
    lines = [
        f"# Restyle review: `{label}`",
        "",
        f"Staged candidates: {len(wrappers)}",
        "",
    ]
    for idx in sorted(set(wrappers) | set(errors)):
        wrapper = wrappers.get(idx)
        original = task["data"][idx]
        lines += [
            f"## idx={idx}",
            "",
            f"- Style hint: `{wrapper.get('style_hint', '') if wrapper else _style_hint(idx)}`",
            f"- Revision: `{wrapper.get('revision', 0) if wrapper else 0}`",
        ]
        if idx in errors:
            lines.append(f"- Error: {errors[idx]}")
        lines += [
            "",
            "**Original**",
            "",
            prompts.render_item(original, task["task_type"]).replace("\n", " "),
            "",
            "**Restyled**",
            "",
            prompts.render_item(_content_item(wrapper), task["task_type"]).replace("\n", " ") if wrapper else "Not staged.",
            "",
        ]
    _atomic_text(_review_path(label), "\n".join(lines).rstrip() + "\n")


def stage(tasks_filter=None, workers=2, max_items=-1, per_task_limit=-1, include_lambada=False,
          retries=4, max_tokens=DEFAULT_MAX_TOKENS, batch_size=DEFAULT_BATCH_SIZE):
    with RUN_STATS_LOCK:
        RUN_STATS.clear()
    meta = _metadata_rows()
    failures = []
    remaining = max_items
    for task in _eligible_tasks(tasks_filter, include_lambada):
        label = task["label"]
        benchmark = _benchmark_context(task, meta)
        candidates = _load_wrappers(_candidate_path(label))
        rejections = _load_rejections(label)
        indices = _selected_indices(task, per_task_limit)
        todo = []
        for idx in indices:
            wrapper = candidates.get(idx)
            if idx in rejections:
                todo.append(idx)
                continue
            if wrapper:
                try:
                    _validate_wrapper(task, wrapper)
                    continue
                except ValidationError:
                    pass
            todo.append(idx)
        if remaining == 0:
            todo = []
        elif remaining > 0:
            todo = todo[:remaining]
            remaining -= len(todo)
        print(f"{label}: selected={len(indices)} staged={len(indices)-len(todo)} generating={len(todo)}", flush=True)

        errors = {}

        batches = list(_chunked(todo, batch_size))

        if workers <= 1:
            for batch in batches:
                try:
                    wrappers = _generate_batch_valid(
                        task, batch, benchmark, rejections, candidates,
                        retries=retries, max_tokens=max_tokens,
                    )
                    for idx, wrapper in wrappers.items():
                        candidates[idx] = wrapper
                        rejections.pop(idx, None)
                    _atomic_jsonl(_candidate_path(label), [candidates[i] for i in sorted(candidates)])
                    _write_rejections(label, rejections)
                    print(
                        f"  {label}: batch={batch[0]}..{batch[-1]} items={len(batch)} | "
                        f"{usage_summary()} | {_run_summary()}",
                        flush=True,
                    )
                except Exception as e:  # noqa: BLE001
                    for idx in batch:
                        errors[idx] = str(e)
                    failures.append((label, batch[0], e))
        else:
            ex = ThreadPoolExecutor(max_workers=workers)
            try:
                futs = {
                    ex.submit(
                        _generate_batch_valid,
                        task, batch, benchmark, rejections, candidates,
                        retries, max_tokens,
                    ): batch
                    for batch in batches
                }
                for fut in as_completed(futs):
                    batch = futs[fut]
                    try:
                        wrappers = fut.result()
                        for idx, wrapper in wrappers.items():
                            candidates[idx] = wrapper
                            rejections.pop(idx, None)
                        _atomic_jsonl(_candidate_path(label), [candidates[i] for i in sorted(candidates)])
                        _write_rejections(label, rejections)
                        print(
                            f"  {label}: batch={batch[0]}..{batch[-1]} items={len(batch)} | "
                            f"{usage_summary()} | {_run_summary()}",
                            flush=True,
                        )
                    except Exception as e:  # noqa: BLE001
                        for idx in batch:
                            errors[idx] = str(e)
                        failures.append((label, batch[0], e))
            except KeyboardInterrupt:
                ex.shutdown(wait=False, cancel_futures=True)
                raise
            else:
                ex.shutdown(wait=True)
        _write_review(label, task, {idx: candidates[idx] for idx in sorted(candidates) if idx in indices}, errors)
        print(f"  {label}: summary | {_run_summary()}", flush=True)
    if failures:
        raise SystemExit("RESTYLE STAGING FAILED: " + ", ".join(f"{label}:{idx}" for label, idx, _ in failures))
    print(f"RUN SUMMARY | {_run_summary()}")


def preview(preview_size=10, tasks_filter=None, workers=2, batch_size=DEFAULT_BATCH_SIZE):
    stage(tasks_filter, workers=workers, per_task_limit=preview_size, batch_size=batch_size)


def status(tasks_filter=None):
    totals = collections.Counter()
    for task in _eligible_tasks(tasks_filter, include_lambada=True):
        candidates = _load_wrappers(_candidate_path(task["label"]))
        rejects = _load_rejections(task["label"])
        counts = collections.Counter()
        for idx, wrapper in candidates.items():
            if idx in rejects:
                counts["rejected"] += 1
                continue
            try:
                _validate_wrapper(task, wrapper)
                counts["valid"] += 1
            except ValidationError:
                counts["invalid"] += 1
        counts["rejects"] = len(rejects)
        totals.update(counts)
        print(
            f"{task['label']}: valid={counts['valid']} invalid={counts['invalid']} "
            f"rejects={counts['rejects']} staged={len(candidates)}"
        )
    print(f"TOTAL: valid={totals['valid']} invalid={totals['invalid']} rejects={totals['rejects']}")


def reject(label, idx, reason):
    if not reason.strip():
        raise SystemExit("--reason must be non-empty")
    tasks = {task["label"]: task for task in _load_filtered_tasks()}
    if label not in tasks:
        raise SystemExit(f"unknown task: {label}")
    candidates = _load_wrappers(_candidate_path(label))
    if idx not in candidates:
        raise SystemExit(f"no staged candidate: {label} idx={idx}")
    _validate_wrapper(tasks[label], candidates[idx])
    rejections = _load_rejections(label)
    rejections[idx] = reason.strip()
    _write_rejections(label, rejections)
    print(f"{label}: idx={idx} rejected; rerun stage")


def _audit_flags(task, wrapper):
    idx = wrapper["idx"]
    original = task["data"][idx]
    candidate = _content_item(wrapper)
    flags = []
    try:
        validate_item(candidate, original, task["task_type"], task["label"])
    except Exception as e:  # noqa: BLE001
        flags.append(f"validator: {e}")
    original_text = _editable_text(original, task["task_type"])
    candidate_text = _editable_text(candidate, task["task_type"])
    if len(candidate_text) > 1.5 * max(1, len(original_text)):
        flags.append("length > 1.5x")
    if task["task_type"] == "multiple_choice" and _embedded_choices_block(original.get("query", "")):
        if _embedded_choices_block(candidate.get("query", "")) != _embedded_choices_block(original["query"]):
            flags.append("embedded choices changed")
    return flags


def audit(tasks_filter=None):
    lines = ["# Restyle audit", "", "| Task | idx | Flags |", "| --- | ---: | --- |"]
    total = 0
    flagged = 0
    for task in _eligible_tasks(tasks_filter, include_lambada=True):
        for idx, wrapper in sorted(_load_wrappers(_candidate_path(task["label"])).items()):
            total += 1
            flags = _audit_flags(task, wrapper)
            if flags:
                flagged += 1
                lines.append(f"| {task['label']} | {idx} | {'; '.join(flags)} |")
    lines.insert(2, f"Staged: {total}; flagged: {flagged}")
    lines.insert(3, "")
    _atomic_text(AUDIT_REPORT, "\n".join(lines).rstrip() + "\n")
    print(f"wrote {AUDIT_REPORT} ({flagged}/{total} flagged)")


def apply(tasks_filter=None):
    tasks = {task["label"]: task for task in _eligible_tasks(tasks_filter, include_lambada=True)}
    for label, task in sorted(tasks.items()):
        rejects = _load_rejections(label)
        if rejects:
            raise SystemExit(f"RESTYLE APPLY REFUSED: {label} has pending rejects {sorted(rejects)}")
        candidates = _load_wrappers(_candidate_path(label))
        approved = {}
        errors = []
        for idx, wrapper in sorted(candidates.items()):
            try:
                item = _validate_wrapper(task, wrapper)
                approved[idx] = {**wrapper, "candidate": item}
            except Exception as e:  # noqa: BLE001
                errors.append(f"{label} idx={idx}: {e}")
        if errors:
            raise SystemExit("RESTYLE APPLY REFUSED:\n  " + "\n  ".join(errors))
        _atomic_jsonl(_approved_path(label), [approved[i] for i in sorted(approved)])
        print(f"{label}: applied {len(approved)} approved candidates offline")


def _manual_repeat_copy_items():
    return [
        {"context": "repeat with logic:\n\nQ: A melon has seven seeds. Repeat it is ripe once for every seed\nA:", "continuation": "it is ripe it is ripe it is ripe it is ripe it is ripe it is ripe it is ripe"},
        {"context": "repeat with logic:\n\nQ: say sparrow twice and wren once, and then repeat all of this three times.\nA:", "continuation": "sparrow sparrow wren sparrow sparrow wren sparrow sparrow wren"},
        {"context": "repeat with logic:\n\nQ: output if you teach a man to fish you will three times\nA:", "continuation": "if you teach a man to fish you will if you teach a man to fish you will if you teach a man to fish you will"},
        {"context": "repeat with logic:\n\nQ: repeat election to the council three times, but after every other word say indeed\nA:", "continuation": "election to indeed the council indeed election to indeed the council indeed election to indeed the council indeed"},
        {"context": "repeat with logic:\n\nQ: say purchase a pound of green beans twice, replacing a pound with a bunch for even times and a handful for odd\nA:", "continuation": "purchase a handful of green beans purchase a bunch of green beans"},
        {"context": "repeat with logic:\n\nQ: Output steam power is a four times, but in the middle also say notable invention\nA:", "continuation": "steam power is a steam power is a notable invention steam power is a steam power is a"},
        {"context": "repeat with logic:\n\nQ: say good day five times, but don't say day every even time\nA:", "continuation": "good day good good day good good day"},
        {"context": "repeat with logic:\n\nQ: Print logic eleven times, but after the 3rd and 8th also say true\nA:", "continuation": "logic logic logic true logic logic logic logic logic true logic logic logic"},
        {"context": "repeat with logic:\n\nQ: say fish are wholesome twice\nA:", "continuation": "fish are wholesome fish are wholesome"},
        {"context": "repeat with logic:\n\nQ: Seven times please repeat The School of Music\nA:", "continuation": "The School of Music The School of Music The School of Music The School of Music The School of Music The School of Music The School of Music"},
        {"context": "repeat with logic:\n\nQ: repeat the phrase the administrative district three times, and say the phrase good day after the second time\nA:", "continuation": "the administrative district the administrative district good day the administrative district"},
        {"context": "repeat with logic:\n\nQ: repeat whole note quarter note quarter note quarter note twice\nA:", "continuation": "whole note quarter note quarter note quarter note whole note quarter note quarter note quarter note"},
        {"context": "repeat with logic:\n\nQ: Say the letters of the alphabet in capital letters, but only the odd ones\nA:", "continuation": "A C E G I K M O Q S U W Y"},
        {"context": "repeat with logic:\n\nQ: Repeat historic church building twice, but after every word also say well\nA:", "continuation": "historic well church well building well historic well church well building well"},
        {"context": "repeat with logic:\n\nQ: repeat a woodchuck chucks lots of wood two times, but replace lots with five pounds the first time and two tons the second time\nA:", "continuation": "a woodchuck chucks five pounds of wood a woodchuck chucks two tons of wood"},
        {"context": "repeat with logic:\n\nQ: Three times please repeat The School of Music, and before the first time say Who plays the bass loudly?\nA:", "continuation": "Who plays the bass loudly? The School of Music The School of Music The School of Music"},
        {"context": "repeat with logic:\n\nQ: Say the days of the week but only the weekend days, two times\nA:", "continuation": "Saturday Sunday Saturday Sunday"},
        {"context": "repeat with logic:\n\nQ: repeat the word cat four times. After the second time, also say the word meow.\nA:", "continuation": "cat cat meow cat cat"},
        {"context": "repeat with logic:\n\nQ: Twice repeat inhabitants in the town and then three times live within walking distance\nA:", "continuation": "inhabitants in the town inhabitants in the town live within walking distance live within walking distance live within walking distance"},
        {"context": "repeat with logic:\n\nQ: ask a genus of plants in what family? four times. after the fourth time say The happy family\nA:", "continuation": "a genus of plants in what family? a genus of plants in what family? a genus of plants in what family? a genus of plants in what family? The happy family"},
        {"context": "repeat with logic:\n\nQ: Repeat the word dog four times, but halfway through also say woof\nA:", "continuation": "dog dog woof dog dog"},
        {"context": "repeat with logic:\n\nQ: say the village has a population five times, and after odd times add larger than California\nA:", "continuation": "the village has a population larger than California the village has a population the village has a population larger than California the village has a population the village has a population larger than California"},
        {"context": "repeat with logic:\n\nQ: Repeat cheese seven times; every third say whiz\nA:", "continuation": "cheese cheese cheese whiz cheese cheese cheese whiz cheese"},
        {"context": "repeat with logic:\n\nQ: Repeat all the world seven times, and after every second time add is a stage.\nA:", "continuation": "all the world all the world is a stage all the world all the world is a stage all the world all the world is a stage all the world"},
        {"context": "repeat with logic:\n\nQ: Repeat the phrase all horses eat oats four times. On the odd times, drop words that start with vowels\nA:", "continuation": "horses oats all horses eat oats horses oats all horses eat oats"},
        {"context": "repeat with logic:\n\nQ: Say hungry three times, then hippo two times, then feed me four times\nA:", "continuation": "hungry hungry hungry hippo hippo feed me feed me feed me feed me"},
        {"context": "repeat with logic:\n\nQ: A strawberry has three leaves. Say wish I had some cream for every odd leaf\nA:", "continuation": "wish I had some cream wish I had some cream"},
        {"context": "repeat with logic:\n\nQ: Say the botanical gardens are five times. If the time divides evenly by two add beautiful, or by three add wonderful. Otherwise say great.\nA:", "continuation": "the botanical gardens are great the botanical gardens are beautiful the botanical gardens are wonderful the botanical gardens are beautiful the botanical gardens are great"},
        {"context": "repeat with logic:\n\nQ: Repeat cat five times. After each time, also say mouse\nA:", "continuation": "cat mouse cat mouse cat mouse cat mouse cat mouse"},
        {"context": "repeat with logic:\n\nQ: say all work and no play makes three times, but every even time add Jack and odd time add Jill\nA:", "continuation": "all work and no play makes Jill all work and no play makes Jack all work and no play makes Jill"},
        {"context": "repeat with logic:\n\nQ: Repeat 5 times good day\nA:", "continuation": "good day good day good day good day good day"},
        {"context": "repeat with logic:\n\nQ: Repeat wavy line twice after the phrase can you draw\nA:", "continuation": "can you draw wavy line wavy line"},
    ]


def _approved_items(label):
    return {row["idx"]: _content_item(row) for row in _load_wrappers(_approved_path(label)).values()}


def package():
    tasks = _load_filtered_tasks()
    meta_rows = _metadata_rows()
    os.makedirs(os.path.join(OUT, "eval_data"), exist_ok=True)
    yaml_tasks = []
    csv_rows = []
    written = set()
    counts = {}
    for task in tasks:
        label = task["label"]
        original_data = list(task["data"])
        data = list(original_data)
        selected = 0
        if label in MANUAL_REWRITE:
            data = _manual_repeat_copy_items()
            selected = len(data)
        elif label not in COPY_UNCHANGED:
            approved = _approved_items(label)
            for idx, item in approved.items():
                data[idx] = item
            selected = len(approved)

        if task["dataset_uri"] not in written:
            path = os.path.join(OUT, "eval_data", task["dataset_uri"])
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                for item in data:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
            written.add(task["dataset_uri"])

        yaml_tasks.append(dict(task["yaml"]))
        row = dict(meta_rows[label])
        row["#datapoints"] = str(len(data))
        csv_rows.append(row)
        actual_changed = sum(before != after for before, after in zip(original_data, data))
        counts[label] = (len(data), selected, actual_changed, len(data) - actual_changed)

    with open(os.path.join(OUT, "core.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump({"icl_tasks": yaml_tasks}, f, sort_keys=False)
    cols = ["Eval Task", "Task Category", "Task Type", "#shots", "#datapoints",
            "Random baseline", "Centered Metric?", "Description"]
    with open(os.path.join(OUT, "eval_meta_data.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(csv_rows)

    lines = [
        "# Vintage CORE Restyle Report",
        "",
        "| Task | N | Approved/manual | Actual text changes | Filtered originals |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for label, (n, selected, actual_changed, originals) in counts.items():
        lines.append(f"| `{label}` | {n} | {selected} | {actual_changed} | {originals} |")
    _atomic_text(PACKAGE_REPORT, "\n".join(lines).rstrip() + "\n")
    print(f"packaged {len(yaml_tasks)} tasks -> {OUT}")


def lambada_preview(count=50, workers=2, batch_size=DEFAULT_BATCH_SIZE):
    stage({LAMBADA}, workers=workers, per_task_limit=count, include_lambada=True,
          batch_size=batch_size)
    task = next(task for task in _load_filtered_tasks() if task["label"] == LAMBADA)
    wrappers = _load_wrappers(_candidate_path(LAMBADA))
    lines = ["# LAMBADA blind review", "", "Guess the hidden continuation before opening the JSONL.", ""]
    for idx in _selected_indices(task, count):
        if idx not in wrappers:
            continue
        item = _content_item(wrappers[idx])
        lines += [f"## idx={idx}", "", item["context"] + " ____", ""]
    _atomic_text(os.path.join(config.REVIEW_DIR, "restyle_lambada_blind.md"), "\n".join(lines).rstrip() + "\n")


def _task_filter(raw):
    return {part for part in raw.split(",") if part}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    preview_parser = sub.add_parser("preview")
    preview_parser.add_argument("--preview-size", type=int, default=10)
    preview_parser.add_argument("--tasks", default="")
    preview_parser.add_argument("--workers", type=int, default=2)
    preview_parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    preview_parser.add_argument("--log-file", default="", help="write stdout/stderr to this log file")
    preview_parser.add_argument("--no-log", action="store_true", help="disable automatic run log")

    stage_parser = sub.add_parser("stage")
    stage_parser.add_argument("--tasks", default="")
    stage_parser.add_argument("--workers", type=int, default=2)
    stage_parser.add_argument("--max-items", type=int, default=-1)
    stage_parser.add_argument("--per-task-limit", type=int, default=-1)
    stage_parser.add_argument("--retries", type=int, default=4)
    stage_parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    stage_parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    stage_parser.add_argument("--include-lambada", action="store_true")
    stage_parser.add_argument("--log-file", default="", help="write stdout/stderr to this log file")
    stage_parser.add_argument("--no-log", action="store_true", help="disable automatic run log")

    status_parser = sub.add_parser("status")
    status_parser.add_argument("--tasks", default="")

    reject_parser = sub.add_parser("reject")
    reject_parser.add_argument("label")
    reject_parser.add_argument("idx", type=int)
    reject_parser.add_argument("--reason", required=True)

    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--tasks", default="")

    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--tasks", default="")

    lambada_parser = sub.add_parser("lambada-preview")
    lambada_parser.add_argument("--count", type=int, default=50)
    lambada_parser.add_argument("--workers", type=int, default=2)
    lambada_parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    lambada_parser.add_argument("--log-file", default="", help="write stdout/stderr to this log file")
    lambada_parser.add_argument("--no-log", action="store_true", help="disable automatic run log")

    sub.add_parser("package")

    args = parser.parse_args()
    log_handle = None
    if args.command in {"preview", "stage", "lambada-preview"} and not args.no_log:
        log_handle = _install_run_log(args.command, args.log_file or None)
    if args.command == "preview":
        preview(args.preview_size, _task_filter(args.tasks), args.workers, args.batch_size)
    elif args.command == "stage":
        stage(_task_filter(args.tasks), args.workers, args.max_items, args.per_task_limit,
              args.include_lambada, args.retries, args.max_tokens, args.batch_size)
    elif args.command == "status":
        status(_task_filter(args.tasks))
    elif args.command == "reject":
        reject(args.label, args.idx, args.reason)
    elif args.command == "audit":
        audit(_task_filter(args.tasks))
    elif args.command == "apply":
        apply(_task_filter(args.tasks))
    elif args.command == "lambada-preview":
        lambada_preview(args.count, args.workers, args.batch_size)
    elif args.command == "package":
        package()
    if log_handle is not None:
        log_handle.close()


if __name__ == "__main__":
    main()
