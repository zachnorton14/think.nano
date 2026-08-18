"""Input-noise transform for the SFT curriculum.

Offline only: nothing here touches Hugging Face.

    python -m pytest tests/test_robustness_noise.py -v
"""

from importlib import import_module

synth = import_module("tasks.synth-pre1930")


QUESTION = "What is the reason that the tides follow the moon?"


def test_noise_is_deterministic_for_a_seed():
    a = synth.noise_text(QUESTION, "seed:1", 1.0)
    b = synth.noise_text(QUESTION, "seed:1", 1.0)
    assert a == b


def test_different_seeds_give_different_damage():
    variants = {synth.noise_text(QUESTION, f"seed:{i}", 1.0) for i in range(40)}
    assert len(variants) > 1, "noise should vary across seeds"


def test_rate_zero_never_touches_the_text():
    for i in range(50):
        assert synth.noise_text(QUESTION, f"seed:{i}", 0.0) == QUESTION


def test_noise_never_empties_the_text():
    for i in range(200):
        assert synth.noise_text("Why?", f"seed:{i}", 1.0).strip()


def test_assistant_turns_are_never_noised():
    # The whole point: a corrupted question is context, a corrupted answer is a
    # target the model learns to reproduce.
    answer = "It is nineteen hundred and thirty."
    conv = {"messages": [
        {"role": "user", "content": QUESTION},
        {"role": "assistant", "content": answer},
        {"role": "user", "content": "And the year before?"},
        {"role": "assistant", "content": answer},
    ]}
    out = synth._noised_conversation(conv, "seed", 1.0)
    assert [m["content"] for m in out["messages"] if m["role"] == "assistant"] == [answer, answer]
    assert any(m["content"] != c["content"]
               for m, c in zip(out["messages"], conv["messages"]) if m["role"] == "user")


def test_original_conversation_is_not_mutated():
    conv = {"messages": [{"role": "user", "content": QUESTION},
                         {"role": "assistant", "content": "Because."}]}
    synth._noised_conversation(conv, "seed", 1.0)
    assert conv["messages"][0]["content"] == QUESTION


def test_epoch_tasks_are_distinct_and_reseeded():
    rows = [{"question": QUESTION, "answer": "Because.", "doc_index": "1"}]
    tasks = synth._epoch_tasks(rows, "demo", 5, 1.0, 1930)
    assert len({id(t) for t in tasks}) == 5, "each epoch needs its own Task"
    seeds = {t.noise_seed for t in tasks}
    assert len(seeds) == 5, "each epoch needs its own noise seed"
    rendered = {t.get_example(0)["messages"][0]["content"] for t in tasks}
    assert len(rendered) > 1, "epochs should not all render identically"


def test_epoch_tasks_without_noise_match_the_old_behaviour():
    rows = [{"question": QUESTION, "answer": "Because.", "doc_index": "1"}]
    tasks = synth._epoch_tasks(rows, "demo", 3, 0.0, 1930)
    rendered = {t.get_example(0)["messages"][0]["content"] for t in tasks}
    assert rendered == {QUESTION}


# -----------------------------------------------------------------------------
# Robustness routes reach both curriculum builders. Offline: the HF loader is
# stubbed, so these assert the wiring, not the download.

import pytest


@pytest.fixture
def stub_rows(monkeypatch):
    rows = [{"question": f"q{i}", "answer": f"a{i}", "doc_index": str(i)} for i in range(10)]
    monkeypatch.setattr(synth, "_load_robustness_rows", lambda route: list(rows))
    return rows


ROB_SPEC = {
    "epochs": 3,
    "routes": {"conversation_qa": {}, "unparseable_qa": {"count": 4}},
}


def test_flat_mode_includes_robustness_with_its_own_epochs(stub_rows):
    spec = {"mode": "flat", "epochs": 1, "routes": {}, "robustness": dict(ROB_SPEC)}
    bundle = synth.build_curriculum(spec)
    routes = bundle.summary["routes"]
    assert routes["conversation_qa"] == {"rows": 10, "epochs": 3}
    assert routes["unparseable_qa"] == {"rows": 4, "epochs": 3}   # count respected
    assert len(bundle.train) == (10 + 4) * 3


def test_staged_mode_adds_robustness_at_its_stage_and_re_exposes_it(stub_rows):
    spec = {
        "mode": "staged",
        "stages": [{"routes": []}, {"routes": []}, {"routes": []}],
        "robustness": {"stage": 1, "epochs": 1, "routes": {"era_qa": {}}},
    }
    bundle = synth.build_curriculum(spec)
    stages = bundle.summary["stages"]
    assert [a["route"] for a in stages[0]["added"]] == []
    assert [a["route"] for a in stages[1]["added"]] == ["era_qa"]
    # stages are cumulative, so it persists into stage 2 without being re-added
    assert stages[1]["cumulative_rows"] == 10
    assert stages[2]["cumulative_rows"] == 10
    assert [a["route"] for a in stages[2]["added"]] == []


def test_unknown_robustness_route_is_rejected(stub_rows):
    spec = {"mode": "flat", "epochs": 1, "routes": {},
            "robustness": {"routes": {"not_a_route": {}}}}
    with pytest.raises(AssertionError, match="unknown robustness route"):
        synth.build_curriculum(spec)


# -----------------------------------------------------------------------------
# The widened mangling surface

def test_every_noise_family_can_fire():
    fired = set()
    for i in range(600):
        for fam, ops in synth._NOISE_FAMILIES.items():
            import random as _r
            if ops[0]("What is a needle used for?", _r.Random(i)) != "What is a needle used for?":
                fired.add(fam)
    assert fired == set(synth._NOISE_FAMILIES), f"never fired: {set(synth._NOISE_FAMILIES) - fired}"


def test_noise_reaches_doubled_punctuation_and_caps_slips():
    q = "Hello"
    seen = {synth.noise_text(q, f"s{i}", 1.0) for i in range(300)}
    assert any(v.endswith(("!!", "??", "?!")) or v.count("!") > 1 for v in seen), "no doubled punctuation"
    assert any(v[:2].isupper() and not v.isupper() for v in seen if len(v) > 2), "no caps slip"
    assert any(v.isupper() for v in seen), "no shout"


def test_noise_never_produces_empty_or_whitespace():
    for text in ("Hello", "Why?", "a", "It is so.", "?"):
        for i in range(150):
            assert synth.noise_text(text, f"{text}:{i}", 1.0).strip()


# -----------------------------------------------------------------------------
# Terminal punctuation. The reported failure is a clean, short, unpunctuated turn
# ("Texas", "I love you"), so the dose of *ending*-mark removal is a number worth
# pinning rather than a by-product of the family weights.


def test_drop_end_punct_survives_trailing_whitespace():
    # rstrip("?!.") alone is a silent no-op the moment a space trails the mark.
    assert synth._drop_end_punct("Is this real? ", None) == "Is this real"


def test_drop_end_punct_reaches_marks_behind_a_closer():
    assert synth._drop_end_punct('He said "yes."', None) == 'He said "yes"'
    assert synth._drop_end_punct("(is it so?)", None) == "(is it so)"


def test_drop_end_punct_covers_the_softer_marks():
    for text, want in [("Is this real,", "Is this real"),
                       ("Well; ", "Well"),
                       ("Wait...", "Wait"),
                       ("So…", "So")]:
        assert synth._drop_end_punct(text, None) == want


def test_drop_end_punct_never_empties():
    assert synth._drop_end_punct("?!.", None) == "?!."


def test_end_punct_rate_is_independent_of_the_family_rate():
    # rate=0 means no family mangle, but the terminal mark must still come off --
    # that is the whole point: clean text, missing punctuation.
    q = "I love you."
    out = {synth.noise_text(q, f"s{i}", 0.0, 1.0) for i in range(20)}
    assert out == {"I love you"}


def test_rate_zero_and_no_end_rate_still_never_touches_the_text():
    for i in range(50):
        assert synth.noise_text(QUESTION, f"seed:{i}", 0.0, 0.0) == QUESTION


def test_configured_end_punct_rate_strips_about_a_tenth():
    # The dose the v2 configs ship. Measured over the punctuated turns, since the
    # corpus already carries unpunctuated rows (unparseable_qa, era_qa).
    n = 6000
    stripped = sum(1 for i in range(n)
                   if not synth.noise_text(QUESTION, f"s{i}", 0.3, 0.05).rstrip().endswith("?"))
    assert 0.07 <= stripped / n <= 0.15, stripped / n


# -----------------------------------------------------------------------------
# pool_fraction: hold a row budget while stage epochs go up.


def test_pool_fraction_scales_graded_routes_but_not_robustness(monkeypatch):
    graded = [{"question": f"q{i}", "answer": "a", "doc_index": str(i), "score": 95}
              for i in range(1000)]
    monkeypatch.setattr(synth, "_load_graded_rows", lambda route: list(graded))
    monkeypatch.setattr(synth, "_route_holdout", lambda route: frozenset())
    monkeypatch.setattr(synth, "_load_robustness_rows", lambda route: [
        {"question": f"r{i}", "answer": "a", "doc_index": f"r{i}"} for i in range(100)])

    spec = {
        "mode": "staged", "epochs": 1, "pool_fraction": 0.5, "threshold_default": 80,
        "stages": [{"routes": ["knowledge_qa"]}],
        "robustness": {"stage": 0, "epochs": 1, "routes": {"typo_qa": {"count": None}}},
    }
    summary = {}
    synth._build_staged(spec, 1930, lambda r: None, summary)
    added = {a["route"]: a["rows"] for a in summary["stages"][0]["added"]}
    assert added["knowledge_qa"] == 500, added
    assert added["typo_qa"] == 100, "robustness must stay uncapped"


def test_pool_fraction_defaults_to_the_whole_pool(monkeypatch):
    graded = [{"question": f"q{i}", "answer": "a", "doc_index": str(i), "score": 95}
              for i in range(300)]
    monkeypatch.setattr(synth, "_load_graded_rows", lambda route: list(graded))
    monkeypatch.setattr(synth, "_route_holdout", lambda route: frozenset())
    summary = {}
    synth._build_staged({"mode": "staged", "stages": [{"routes": ["knowledge_qa"]}]},
                        1930, lambda r: None, summary)
    assert summary["stages"][0]["added"][0]["rows"] == 300


def _stub(monkeypatch, n=1000):
    graded = [{"question": f"q{i}", "answer": "a", "doc_index": str(i), "score": 95}
              for i in range(n)]
    monkeypatch.setattr(synth, "_load_graded_rows", lambda route: list(graded))
    monkeypatch.setattr(synth, "_route_holdout", lambda route: frozenset())


def _passes_per_route(seq, route_rows):
    """How many times each route's rows are walked over the whole sequence."""
    return sum(len(mix) for mix in seq.tasks) / route_rows


def test_cumulative_reexposure_is_already_uneven_at_one_epoch(monkeypatch):
    # The thing that makes `epochs` the wrong knob: a route added at stage 0 is
    # re-exposed by every later stage, so it sees 3 passes to stage 2's 1.
    _stub(monkeypatch, 100)
    spec = {"mode": "staged", "stages": [{"routes": ["a"]}, {"routes": ["b"]},
                                         {"routes": ["c"]}]}
    seq = synth._build_staged(spec, 1930, lambda r: None, {})
    assert [len(m) for m in seq.tasks] == [100, 200, 300]


def test_passes_equalises_exposure_across_stages(monkeypatch):
    _stub(monkeypatch, 100)
    spec = {"mode": "staged", "passes": 3,
            "stages": [{"routes": ["a"]}, {"routes": ["b"]}, {"routes": ["c"]}]}
    summary = {}
    seq = synth._build_staged(spec, 1930, lambda r: None, summary)
    assert [st["passes"] for st in summary["stages"]] == [3.0, 3.0, 3.0]
    assert [st["epochs"] for st in summary["stages"]] == [1.0, 1.5, 3.0]
    # 3 passes x 3 routes x 100 rows
    assert sum(len(m) for m in seq.tasks) == 900


def test_fractional_epochs_add_a_subsampled_tail():
    rows = [{"question": f"q{i}", "answer": "a", "doc_index": str(i)} for i in range(100)]
    tasks = synth._epoch_tasks(rows, "demo", 1.5, 0.0, 1930)
    assert [len(t) for t in tasks] == [100, 50]


def test_fractional_epochs_are_deterministic():
    rows = [{"question": f"q{i}", "answer": "a", "doc_index": str(i)} for i in range(100)]
    a = synth._epoch_tasks(rows, "demo", 1.5, 0.0, 1930)[1]
    b = synth._epoch_tasks(rows, "demo", 1.5, 0.0, 1930)[1]
    assert [x["doc_index"] for x in a.rows] == [x["doc_index"] for x in b.rows]


def test_explicit_stage_epochs_still_override_passes(monkeypatch):
    _stub(monkeypatch, 100)
    spec = {"mode": "staged", "passes": 3,
            "stages": [{"routes": ["a"], "epochs": 2}, {"routes": ["b"]}]}
    summary = {}
    synth._build_staged(spec, 1930, lambda r: None, summary)
    assert summary["stages"][0]["epochs"] == 2.0
    assert summary["stages"][1]["epochs"] == 3.0
