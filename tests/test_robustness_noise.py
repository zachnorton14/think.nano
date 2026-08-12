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
