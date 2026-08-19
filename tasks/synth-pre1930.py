"""
Synthetic pre-1930 SFT dataset, one Task per route.
https://huggingface.co/datasets/zachnorton03/synthetic-pre1930-sft

The dataset is organized into ten task "routes" plus a mixed-route calibration_qa set,
each a folder of part-*.jsonl shards. This module reads the **graded/** copy of each
route (rows carry a holistic 0-100 ``score`` in addition to the Q/A payload), so the SFT
recipe can filter by grade threshold and sample exact row counts per route.

Two ways to consume the data:

  - ``Pre1930Route(route=...)`` -- one whole route as a Task (per-route-epochs recipe).
  - ``build_curriculum(spec)``  -- assemble a graded, count-capped mixture of many routes
                                   (the "curriculum" recipe; see the spec format below).

Row shapes (graded/<route>/):
  - single-turn routes: {"doc_index","category","book_category","year","prose_score",
                         "question","answer","score"}
  - multiturn_qa:       {"doc_index","category","year","prose_score",
                         "conversations":[{"role","content"},...],"score"}
Both normalize to the nanochat {"messages": [...]} conversation format.

Curriculum spec (a plain dict, embedded in the experiment config under data.curriculum):

  {
    "name": "C0",
    "mode": "flat" | "staged" | "domain_rebalanced",
    "epochs": 3,                         # flat/domain_rebalanced only
    "threshold_default": 90,             # grade floor unless a route overrides it
    "routes": {                          # flat/domain_rebalanced
      "knowledge_qa": {"count": 18000},
      "stem_reasoning": {"count": 6318, "threshold": 80}   # per-route override
    },
    "calibration_qa": {"count": 2400},   # optional; included on top of routes
    "authentic": {"count": 12257},       # optional; the separate authentic repo
    "stages": [                          # staged mode only (C3); cumulative, 1 pass/stage
      {"routes": ["knowledge_qa"], "authentic": "single"},
      {"routes": ["reasoning_qa","stem_reasoning","how_to_qa","opinion_qa",
                  "composition_qa","verse_qa"], "calibration_qa": true},
      {"routes": ["multiturn_qa","narrative_grounded","narrative_fiction"],
       "authentic": "multi"}
    ]
  }

The route folders are read directly from the Hub (huggingface_hub), not via
datasets.load_dataset, to sidestep Hub feature-inference. Set HF_TOKEN in the training
environment (the repo is not readable anonymously here).
"""

import json
import random
from collections import defaultdict, deque
from functools import lru_cache
from importlib import import_module

from huggingface_hub import HfApi, hf_hub_download
from tasks.common import Task, TaskMixture, TaskSequence

DATASET = "zachnorton03/synthetic-pre1930-sft"

# The ten route subsets, plus the mixed-route calibration anchor. All live under graded/.
ROUTES = (
    "knowledge_qa",
    "multiturn_qa",
    "reasoning_qa",
    "stem_reasoning",
    "narrative_grounded",
    "narrative_fiction",
    "opinion_qa",
    "how_to_qa",
    "verse_qa",
    "composition_qa",
)
CALIBRATION_ROUTE = "calibration_qa"
GRADED_ROUTES = ROUTES + (CALIBRATION_ROUTE,)

# Robustness rows live in their own repo. They are constructed rather than lifted
# from period prose and carry no judge grade, so keeping them out of the graded
# dataset preserves its provenance guarantee. They cover what the graded routes
# never show the model: a bare greeting, gibberish, an unfinished sentence, and
# what year it is.
ROBUSTNESS_DATASET = "zachnorton03/vintage-sft-robustness"
ROBUSTNESS_ROUTES = ("conversation_qa", "conversation_multiturn",
                     "unparseable_qa", "typo_qa", "era_qa")

# -----------------------------------------------------------------------------
# Eval holdout: a fixed, curriculum-independent stratified slice so every run in a
# sweep is scored on the *same* rows. Carved once per route from the >=80 pool by
# doc_index, seeded. Train pools always exclude these rows regardless of their own
# grade threshold.
_HOLDOUT_SEED = 1930
_HOLDOUT_FRAC = 0.015
_HOLDOUT_REF_THRESHOLD = 80
_HOLDOUT_MIN, _HOLDOUT_MAX = 16, 512

# Default seed for curriculum sampling/shuffles (shared across all curriculums).
_CURRICULUM_SEED = 1930


@lru_cache(maxsize=None)
def _load_robustness_rows(route):
    """Download + parse rows/<route>/part-*.jsonl from the robustness repo."""
    api = HfApi()
    prefix = f"rows/{route}/"
    shards = sorted(f for f in api.list_repo_files(ROBUSTNESS_DATASET, repo_type="dataset")
                    if f.startswith(prefix) and f.endswith(".jsonl"))
    if not shards:
        raise FileNotFoundError(f"no robustness shards for {route!r} under {prefix}")
    rows = []
    for f in shards:
        path = hf_hub_download(ROBUSTNESS_DATASET, f, repo_type="dataset")
        with open(path, encoding="utf-8") as fh:
            rows.extend(json.loads(line) for line in fh if line.strip())
    return rows


@lru_cache(maxsize=None)
def _load_graded_rows(route):
    """Download + parse every graded/<route>/part-*.jsonl shard. Cached per route so
    the many Task copies (one per epoch) share a single parse."""
    api = HfApi()
    prefix = f"graded/{route}/"
    shards = sorted(f for f in api.list_repo_files(DATASET, repo_type="dataset")
                    if f.startswith(prefix) and f.endswith(".jsonl"))
    if not shards:
        raise FileNotFoundError(f"no graded shards for route {route!r} under {prefix}")
    rows = []
    for f in shards:
        path = hf_hub_download(DATASET, f, repo_type="dataset")
        with open(path, encoding="utf-8") as fh:
            rows.extend(json.loads(line) for line in fh if line.strip())
    return rows


def _doc_id(row):
    # doc_index is a str for routes ("24561-w3") and an int for calibration_qa; normalize.
    return str(row["doc_index"])


def _score(row):
    return int(row.get("score", 0))


def _domain(row):
    # LC book class; multiturn rows lack book_category, so fall back to category.
    return row.get("book_category") or row.get("category") or "UNKNOWN"


def _row_to_messages(row):
    """Normalize a graded row to {"messages": [...]}, validating role alternation."""
    convs = row.get("conversations")
    if convs:                                     # multiturn_qa
        messages = [{"role": m["role"], "content": m["content"]} for m in convs]
    else:                                         # single-turn Q/A
        messages = [
            {"role": "user", "content": row["question"]},
            {"role": "assistant", "content": row["answer"]},
        ]
    assert len(messages) >= 2 and messages[0]["role"] == "user"
    for i, m in enumerate(messages):
        expected = "user" if i % 2 == 0 else "assistant"
        assert m["role"] == expected and isinstance(m["content"], str)
    return {"messages": messages}


@lru_cache(maxsize=None)
def _route_holdout(route):
    """Frozenset of held-out doc_index for a route. Deterministic, curriculum-independent."""
    rows = _load_graded_rows(route)
    ids = sorted(_doc_id(r) for r in rows if _score(r) >= _HOLDOUT_REF_THRESHOLD)
    if not ids:
        return frozenset()
    rng = random.Random(f"{_HOLDOUT_SEED}:{route}")
    rng.shuffle(ids)
    n = min(_HOLDOUT_MAX, max(_HOLDOUT_MIN, round(_HOLDOUT_FRAC * len(ids))))
    return frozenset(ids[:min(n, len(ids))])


def _domain_flatten_order(rows):
    """Reorder rows so any prefix is domain-balanced: round-robin across book_category
    groups (each group already shuffled by the caller). Taking the first N thus caps
    over-represented domains and draws thin ones up to availability."""
    groups = defaultdict(list)
    for r in rows:
        groups[_domain(r)].append(r)
    queues = [deque(v) for v in groups.values()]
    out = []
    while any(queues):
        for q in queues:
            if q:
                out.append(q.popleft())
    return out


def select_route_rows(route, threshold, count, seed=_CURRICULUM_SEED, domain_flatten=False):
    """Grade-filtered, holdout-excluded, deterministically sampled rows for one route.
    count=None takes the entire eligible pool. Returns the raw row dicts."""
    rows = _load_graded_rows(route)
    hold = _route_holdout(route)
    pool = [r for r in rows if _score(r) >= threshold and _doc_id(r) not in hold]
    rng = random.Random(f"{seed}:{route}:{threshold}")
    rng.shuffle(pool)
    if domain_flatten:
        pool = _domain_flatten_order(pool)
    if count is not None and count < len(pool):
        pool = pool[:count]
    return pool


def route_holdout_rows(route):
    """The held-out eval rows for a route (same across all curriculums)."""
    hold = _route_holdout(route)
    return [r for r in _load_graded_rows(route) if _doc_id(r) in hold]


# -----------------------------------------------------------------------------
# Task wrappers


# -----------------------------------------------------------------------------
# Input noise.
#
# Every graded question is clean, well-formed and punctuated, so a visitor who drops
# the question mark or types in lower case lands off the finetuned distribution --
# where the model falls back on base-corpus behaviour and rambles. Battering a share
# of the questions teaches it that the register survives sloppy input.
#
# Noise touches the USER side only, never the assistant's. ocr_corruption.py puts the
# reason well: "a corrupted question is context the model reads, a corrupted answer is
# a target it learns to reproduce." Answers are what the OCR cleaning was for.
#
# The seed carries the epoch, so a row can arrive clean in epoch 1 and battered in
# epoch 2 -- more surface variety from the same rows, and still fully deterministic
# for a given curriculum seed.

# QWERTY neighbours, for substitutions that look like a slipped finger rather than
# a random character.
_KEY_NEIGHBOURS = {
    "a": "qwsz", "b": "vghn", "c": "xdfv", "d": "serfcx", "e": "wsdr", "f": "drtgvc",
    "g": "ftyhbv", "h": "gyujnb", "i": "ujko", "j": "huikmn", "k": "jiolm", "l": "kop",
    "m": "njk", "n": "bhjm", "o": "iklp", "p": "ol", "q": "wa", "r": "edft",
    "s": "awedxz", "t": "rfgy", "u": "yhji", "v": "cfgb", "w": "qase", "x": "zsdc",
    "y": "tghu", "z": "asx",
}


def _pick_word(words, rng, min_len=1):
    idx = [i for i, w in enumerate(words) if len(w) >= min_len and w.isalpha()]
    return rng.choice(idx) if idx else None


# --- punctuation ---------------------------------------------------------------
# Terminal marks worth peeling, and the closers that hide them from a naive rstrip.
_END_MARKS = ".?!,;:\u2026"
_CLOSERS = "\"'\u2019\u201d)]"


def _drop_end_punct(text, rng):
    """"Is this real?" -> "Is this real" -- the commonest deviation a visitor makes.

    Whitespace is rstripped first, or a single trailing space silently blocks the
    peel; a closing quote or bracket is lifted off and put back, so `He said "yes."`
    is reached too instead of being skipped.
    """
    out = text.rstrip()
    tail = ""
    while out and out[-1] in _CLOSERS:
        tail = out[-1] + tail
        out = out[:-1]
    out = out.rstrip(_END_MARKS).rstrip()
    return (out + tail) or text


def _double_punct(text, rng):
    """"Hello!" -> "Hello!!!" — the visitor leaning on the key."""
    stripped = text.rstrip()
    if stripped and stripped[-1] in "?!":
        return stripped + stripped[-1] * rng.randint(1, 3)
    return stripped + rng.choice(("?", "!", "??", "!!", "?!"))


def _strip_punct(text, rng):
    return "".join(c for c in text if c.isalnum() or c.isspace()).strip() or text


# --- case ----------------------------------------------------------------------
def _lowercase(text, rng):
    return text.lower()


def _shout(text, rng):
    return text.upper()


def _caps_slip(text, rng):
    """"Hello" -> "HEllo" — caps lock released a beat late."""
    words = text.split()
    i = _pick_word(words, rng, 2)
    if i is None:
        return text
    w = words[i]
    n = min(rng.randint(2, 3), len(w))
    words[i] = w[:n].upper() + w[n:]
    return " ".join(words)


def _leading_lower(text, rng):
    return text[:1].lower() + text[1:] if text else text


# --- spacing -------------------------------------------------------------------
def _missing_space(text, rng):
    words = text.split()
    if len(words) < 2:
        return text
    i = rng.randrange(len(words) - 1)
    words[i:i + 2] = [words[i] + words[i + 1]]
    return " ".join(words)


def _extra_space(text, rng):
    words = text.split()
    if len(words) < 2:
        return text
    i = rng.randrange(len(words) - 1)
    return " ".join(words[:i + 1]) + "   " + " ".join(words[i + 1:])


# --- characters ----------------------------------------------------------------
def _transpose(text, rng):
    words = text.split()
    i = _pick_word(words, rng, 4)
    if i is None:
        return text
    w = list(words[i])
    j = rng.randrange(len(w) - 1)
    w[j], w[j + 1] = w[j + 1], w[j]
    words[i] = "".join(w)
    return " ".join(words)


def _drop_letter(text, rng):
    """"needle" -> "nedle" — the single commonest real typo."""
    words = text.split()
    i = _pick_word(words, rng, 4)
    if i is None:
        return text
    w = words[i]
    j = rng.randrange(1, len(w))
    words[i] = w[:j] + w[j + 1:]
    return " ".join(words)


def _double_letter(text, rng):
    words = text.split()
    i = _pick_word(words, rng, 3)
    if i is None:
        return text
    w = words[i]
    j = rng.randrange(len(w))
    words[i] = w[:j] + w[j] * 2 + w[j:]
    return " ".join(words)


def _keyboard_sub(text, rng):
    words = text.split()
    i = _pick_word(words, rng, 3)
    if i is None:
        return text
    w = list(words[i])
    spots = [k for k, c in enumerate(w) if c.lower() in _KEY_NEIGHBOURS]
    if not spots:
        return text
    k = rng.choice(spots)
    sub = rng.choice(_KEY_NEIGHBOURS[w[k].lower()])
    w[k] = sub.upper() if w[k].isupper() else sub
    words[i] = "".join(w)
    return " ".join(words)


# --- words ---------------------------------------------------------------------
def _drop_word(text, rng):
    words = text.split()
    if len(words) < 4:
        return text
    del words[rng.randrange(len(words))]
    return " ".join(words)


def _repeat_word(text, rng):
    words = text.split()
    if len(words) < 2:
        return text
    i = rng.randrange(len(words))
    words.insert(i, words[i])
    return " ".join(words)


def _drop_apostrophe(text, rng):
    return text.replace("'", "").replace("’", "")


# Grouped so a multi-op mangle draws from different families -- two character-level
# ops on one word is unreadable mush, one case slip plus one typo is realistic.
_NOISE_FAMILIES = {
    "punctuation": (_drop_end_punct, _double_punct, _strip_punct),
    "case": (_lowercase, _shout, _caps_slip, _leading_lower),
    "spacing": (_missing_space, _extra_space),
    "character": (_transpose, _drop_letter, _double_letter, _keyboard_sub),
    "word": (_drop_word, _repeat_word, _drop_apostrophe),
}


def noise_text(text, seed, rate, end_punct_rate=0.0):
    """Deterministically batter `text`. Returns it unchanged most of the time.

    Most damaged rows take one op; a tail take two or three from *different*
    families, so the heavy end reaches things like "HELO   wat is tihs" without
    the light end becoming unreadable.

    `end_punct_rate` is drawn *independently* of `rate`. Sharing the family draw
    caps terminal-mark removal at `rate * P(punctuation family)`, and it only ever
    arrives bundled with other damage -- but the observed failure is a clean, short,
    unpunctuated turn ("Texas", "I love you"). The separate draw is what puts that
    exact shape in the training data, and it makes the dose a directly settable
    number rather than a product of three other weights.
    """
    rng = random.Random(seed)
    out = text
    if rng.random() < rate:
        families = list(_NOISE_FAMILIES)
        rng.shuffle(families)
        n = rng.choices((1, 2, 3), weights=(60, 30, 10))[0]
        for family in families[:n]:
            out = rng.choice(_NOISE_FAMILIES[family])(out, rng)
    if rng.random() < end_punct_rate:
        out = _drop_end_punct(out, rng)
    return out.strip() or text


def _noised_conversation(conv, seed, rate, end_punct_rate=0.0):
    """Apply noise to user turns only, leaving assistant targets untouched."""
    out = []
    for i, m in enumerate(conv["messages"]):
        if m["role"] == "user":
            m = {**m, "content": noise_text(m["content"], f"{seed}:{i}", rate,
                                            end_punct_rate)}
        out.append(m)
    return {"messages": out}


class _RowListTask(Task):
    """A Task over an explicit list of already-selected graded rows.

    `noise_seed` differs per epoch, so the same row is battered differently (or not
    at all) on each pass over the data.
    """

    def __init__(self, rows, noise_seed=None, noise_rate=0.0,
                 noise_end_punct_rate=0.0, **kwargs):
        super().__init__(**kwargs)
        self.rows = rows
        self.noise_seed = noise_seed
        self.noise_rate = noise_rate
        self.noise_end_punct_rate = noise_end_punct_rate

    def num_examples(self):
        return len(self.rows)

    def get_example(self, index):
        conv = _row_to_messages(self.rows[index])
        if (self.noise_rate or self.noise_end_punct_rate) and self.noise_seed is not None:
            conv = _noised_conversation(conv, f"{self.noise_seed}:{index}",
                                        self.noise_rate, self.noise_end_punct_rate)
        return conv


class Pre1930Route(Task):
    """ One whole route of the graded synthetic pre-1930 SFT dataset as a Task.
    (Used by the legacy per-route-epochs recipe; unfiltered by grade.) """

    def __init__(self, route, split="train", val_size=256, **kwargs):
        super().__init__(**kwargs)
        assert route in GRADED_ROUTES, f"unknown route {route!r}; choose from {GRADED_ROUTES}"
        self.route = route
        rows = list(_load_graded_rows(route))
        random.Random(42).shuffle(rows)
        val_size = min(val_size, len(rows) // 2)
        self.rows = rows[val_size:] if split == "train" else rows[:val_size]

    def num_examples(self):
        return len(self.rows)

    def get_example(self, index):
        return _row_to_messages(self.rows[index])


# -----------------------------------------------------------------------------
# Authentic (separate repo) with single-/multi-turn filtering for staged curricula.


def _authentic_rounds(messages):
    rest = messages[1:] if messages and messages[0]["role"] == "system" else messages
    return len(rest) // 2


def _authentic_task(split, turns="all", count=None, seed=_CURRICULUM_SEED):
    """Authentic conversations as a Task, optionally filtered to single-/multi-turn
    and capped to `count` rows (deterministic)."""
    AuthenticPre1930 = import_module("tasks.authentic-pre1930").AuthenticPre1930
    base = AuthenticPre1930(split=split)
    indices = list(range(len(base)))
    if turns != "all":
        want_multi = turns == "multi"
        indices = [i for i in indices
                   if (_authentic_rounds(base[i]["messages"]) > 1) == want_multi]
    if count is not None and count < len(indices):
        rng = random.Random(f"{seed}:authentic:{turns}:{split}")
        rng.shuffle(indices)
        indices = indices[:count]
    return _AuthenticView(base, indices)


class _AuthenticView(Task):
    def __init__(self, base, indices, **kwargs):
        super().__init__(**kwargs)
        self.base = base
        self.indices = indices

    def num_examples(self):
        return len(self.indices)

    def get_example(self, index):
        return self.base[self.indices[index]]


# -----------------------------------------------------------------------------
# Curriculum builder


class CurriculumBundle:
    """Resolved curriculum: train dataset, aggregate val dataset, and per-route /
    per-domain val Tasks for stratified eval logging."""

    def __init__(self, train, val, val_by_route, val_by_domain, summary):
        self.train = train
        self.val = val
        self.val_by_route = val_by_route
        self.val_by_domain = val_by_domain
        self.summary = summary


def _route_threshold(spec, route, override):
    return int(override.get("threshold", spec.get("threshold_default", 90)))


def build_curriculum(spec, seed=_CURRICULUM_SEED):
    """Turn a curriculum spec dict into a CurriculumBundle."""
    mode = spec.get("mode", "flat")
    val_by_route = {}
    summary = {"mode": mode, "routes": {}}

    def register_val(name):
        if name not in val_by_route:
            val_by_route[name] = _RowListTask(route_holdout_rows(name))

    if mode == "staged":
        train = _build_staged(spec, seed, register_val, summary)
    else:
        train = _build_flat(spec, seed, mode, register_val, summary)

    # authentic val (shared; single test slice)
    if spec.get("authentic") is not None or any(
        st.get("authentic") for st in spec.get("stages", [])
    ):
        val_by_route["authentic"] = _authentic_task(split="test", turns="all")

    val = TaskMixture(list(val_by_route.values()))

    # per-domain val (used by domain_rebalanced runs) grouped across route holdouts
    by_domain = defaultdict(list)
    for name in val_by_route:
        if name == "authentic":
            continue
        for r in route_holdout_rows(name):
            by_domain[_domain(r)].append(r)
    val_by_domain = {d: _RowListTask(rs) for d, rs in by_domain.items() if len(rs) >= 8}

    summary["train_rows"] = len(train)
    summary["val_rows"] = len(val)
    return CurriculumBundle(train, val, val_by_route, val_by_domain, summary)


def _robustness_rowsets(rob, seed):
    """(route, rows) pairs for the robustness routes named in a spec section."""
    out = []
    for route, cfg in (rob.get("routes") or {}).items():
        assert route in ROBUSTNESS_ROUTES, \
            f"unknown robustness route {route!r}; choose from {ROBUSTNESS_ROUTES}"
        rows = list(_load_robustness_rows(route))
        count = (cfg or {}).get("count")
        if count is not None and count < len(rows):
            rng = random.Random(f"{seed}:robustness:{route}")
            rng.shuffle(rows)
            rows = rows[:count]
        out.append((route, rows))
    return out


def _robustness_tasks(rob, seed, noise_rate, epochs, end_punct_rate=0.0):
    """Tasks + summary entries for the robustness routes named in a spec section."""
    tasks, entries = [], {}
    for route, rows in _robustness_rowsets(rob, seed):
        tasks += _epoch_tasks(rows, route, epochs, noise_rate, seed, end_punct_rate)
        entries[route] = {"rows": len(rows), "epochs": epochs}
    return tasks, entries


def _epoch_tasks(rows, route, epochs, noise_rate, seed, end_punct_rate=0.0):
    """One Task per epoch, each with its own noise seed.

    Note this replaces `[task] * epochs`, which repeated a single object -- so every
    epoch saw byte-identical inputs. Distinct seeds let a row read clean on one pass
    and battered on the next.

    `epochs` may be fractional. Equalising passes across a cumulative curriculum
    needs it: a route entering at stage 1 of 3 is re-exposed twice, so three passes
    is 1.5 epochs. The remainder becomes a final Task over a seeded subsample.
    """
    def task(e, rs):
        return _RowListTask(rs, noise_seed=f"{seed}:{route}:{e}", noise_rate=noise_rate,
                            noise_end_punct_rate=end_punct_rate)
    whole = int(epochs)
    tasks = [task(e, rows) for e in range(whole)]
    remainder = epochs - whole
    if remainder > 1e-9 and rows:
        part = list(rows)
        random.Random(f"{seed}:{route}:partial").shuffle(part)
        tasks.append(task(whole, part[:max(1, round(len(rows) * remainder))]))
    return tasks


def _build_flat(spec, seed, mode, register_val, summary):
    epochs = int(spec.get("epochs", 1))
    domain_flatten = mode == "domain_rebalanced"
    noise_rate = float(spec.get("noise", {}).get("rate", 0.0))
    end_punct_rate = float(spec.get("noise", {}).get("end_punct_rate", 0.0))
    tasks = []
    for route, cfg in spec.get("routes", {}).items():
        thr = _route_threshold(spec, route, cfg)
        rows = select_route_rows(route, thr, cfg.get("count"), seed, domain_flatten)
        register_val(route)
        tasks += _epoch_tasks(rows, route, epochs, noise_rate, seed, end_punct_rate)
        summary["routes"][route] = {"threshold": thr, "rows": len(rows)}
    # calibration_qa on top
    cal = spec.get("calibration_qa")
    if cal is not None:
        thr = _route_threshold(spec, CALIBRATION_ROUTE, cal)
        rows = select_route_rows(CALIBRATION_ROUTE, thr, cal.get("count"), seed, domain_flatten)
        register_val(CALIBRATION_ROUTE)
        tasks += _epoch_tasks(rows, CALIBRATION_ROUTE, epochs, noise_rate, seed,
                              end_punct_rate)
        summary["routes"][CALIBRATION_ROUTE] = {"threshold": thr, "rows": len(rows)}
    # robustness routes on top, with their own epoch count -- they are ~1% of the
    # mixture at one pass, so they usually want more epochs than the graded routes.
    # No val is registered for them: the holdout machinery carves a minimum of 16
    # rows per route, which is a real bite out of a 220-row route, and constructed
    # rows are not a meaningful thing to score bpb on. They are judged by talking
    # to the model.
    rob = spec.get("robustness")
    if rob is not None:
        rob_tasks, entries = _robustness_tasks(
            rob, seed, noise_rate, int(rob.get("epochs", epochs)), end_punct_rate
        )
        tasks += rob_tasks
        summary["routes"].update(entries)
    # authentic on top
    auth = spec.get("authentic")
    if auth is not None:
        t = _authentic_task(split="train", turns=auth.get("turns", "all"),
                            count=auth.get("count"), seed=seed)
        tasks += [t] * epochs
        summary["routes"]["authentic"] = {"rows": len(t)}
    return TaskMixture(tasks)


def _build_staged(spec, seed, register_val, summary):
    """Cumulative staged curriculum: stage k trains a mixture of every route added
    through stage k. Foundation data is thus re-exposed each later stage.

    Re-exposure re-renders. The accumulator holds row lists, not Task objects, and
    every stage rebuilds its mixture under a stage-scoped noise seed -- so a row met
    again at stage 2 is battered differently than it was at stage 0. Persisting the
    Tasks instead made re-exposure a byte-identical repeat, which is the one form of
    repetition that buys nothing.
    """
    threshold = int(spec.get("threshold_default", 80))
    noise_rate = float(spec.get("noise", {}).get("rate", 0.0))
    end_punct_rate = float(spec.get("noise", {}).get("end_punct_rate", 0.0))
    # `passes` is the number of times each route's rows are walked over the whole
    # sequence -- the number worth reasoning about, because stages are cumulative and
    # a route is re-exposed by every stage after the one that adds it. Exposure is
    # therefore already uneven at one epoch: 3/2/1 for a 3-stage curriculum. Epochs
    # multiply on top of that, so `passes` is divided by the re-exposure count to get
    # them, and stage 0 correctly needs no multiplier at all.
    passes = spec.get("passes")
    default_epochs = spec.get("epochs", 1)
    # Subsample every graded route to this share of its eligible pool, to hold a
    # total row budget. select_route_rows has already shuffled deterministically, so
    # the head slice is a seeded random draw. Robustness is deliberately exempt: it
    # is the thin part of the mixture and capping it would undo any epoch increase.
    pool_fraction = float(spec.get("pool_fraction", 1.0))
    assert 0.0 < pool_fraction <= 1.0, f"pool_fraction out of range: {pool_fraction}"

    def _pool(route, thr, count):
        rows = select_route_rows(route, thr, count, seed)
        if pool_fraction < 1.0:
            rows = rows[:max(1, round(len(rows) * pool_fraction))]
        return rows

    rob = spec.get("robustness")
    # Robustness enters at stage 0 by default: the model should know how to field a
    # greeting from the start. Its epoch count is its own -- `passes` sizes the graded
    # routes, and matching robustness to them would leave it as thin a slice as before.
    rob_stage = int((rob or {}).get("stage", 0))
    rob_epochs = float((rob or {}).get("epochs", 1))

    stages = spec.get("stages", [])
    active = []           # accumulating (route, rows, epochs) -- re-rendered per stage
    plain = []            # Tasks that carry no noise (authentic), reused as-is
    stage_mixes = []
    summary["stages"] = []
    for stage_index, stage in enumerate(stages):
        stage_info = {"added": []}
        thr = int(stage.get("threshold", threshold))
        reexposures = len(stages) - stage_index
        stage_epochs = stage.get("epochs")
        if stage_epochs is None:
            stage_epochs = passes / reexposures if passes else default_epochs
        stage_epochs = float(stage_epochs)
        stage_info["epochs"] = stage_epochs
        stage_info["passes"] = stage_epochs * reexposures
        for route in stage.get("routes", []):
            rows = _pool(route, thr, stage.get("count"))
            register_val(route)
            active.append((route, rows, stage_epochs))
            stage_info["added"].append({"route": route, "threshold": thr, "rows": len(rows)})
        if stage.get("calibration_qa"):
            rows = _pool(CALIBRATION_ROUTE, thr, None)
            register_val(CALIBRATION_ROUTE)
            active.append((CALIBRATION_ROUTE, rows, stage_epochs))
            stage_info["added"].append({"route": CALIBRATION_ROUTE, "threshold": thr, "rows": len(rows)})
        if rob is not None and stage_index == rob_stage:
            for route, rows in _robustness_rowsets(rob, seed):
                active.append((route, rows, rob_epochs))
                stage_info["added"].append({"route": route, "rows": len(rows),
                                            "epochs": rob_epochs})
        if stage.get("authentic"):
            t = _authentic_task(split="train", turns=stage["authentic"], seed=seed)
            plain.append(t)
            stage_info["added"].append({"route": f"authentic/{stage['authentic']}", "rows": len(t)})
        # Rebuild rather than reuse: the stage index enters the noise seed, so every
        # re-exposure is a fresh rendering of the same rows.
        tasks = list(plain)
        for route, rows, ep in active:
            tasks += _epoch_tasks(rows, route, ep, noise_rate, f"{seed}:s{stage_index}",
                                  end_punct_rate)
        stage_mixes.append(TaskMixture(tasks))
        stage_info["cumulative_rows"] = sum(len(t) for t in tasks)
        summary["stages"].append(stage_info)
    return TaskSequence(stage_mixes)
