import json

import pytest

from dev.vintage_core import client, restyle


def _mc_with_embedded_choices():
    return {
        "query": "Question: Where would one deposit money?\nChoices:\nA. bank\nB. barn\nAnswer:",
        "choices": ["bank", "barn"],
        "gold": 0,
    }


def test_restyle_validate_preserves_embedded_choices_block():
    original = _mc_with_embedded_choices()
    valid = {
        **original,
        "query": "Question: At what establishment would one deposit money?\nChoices:\nA. bank\nB. barn\nAnswer:",
    }
    assert restyle.validate_item(valid, original, "multiple_choice")["gold"] == 0
    changed_protected_block = {
        **original,
        "query": "Question: At what establishment would one deposit money?\nChoices:\nA. bank\nB. stable\nAnswer:",
    }
    repaired = restyle.validate_item(changed_protected_block, original, "multiple_choice")
    assert "B. barn" in repaired["query"]
    assert "B. stable" not in repaired["query"]


def test_restyle_reconstructs_protected_query_scaffold():
    original = _mc_with_embedded_choices()
    generated = {
        **original,
        "query": "At what establishment would one deposit money?",
    }
    item = restyle.validate_item(generated, original, "multiple_choice")
    assert item["query"].startswith("Question: ")
    assert item["query"].endswith("\nChoices:\nA. bank\nB. barn\nAnswer:")


def test_restyle_rejects_speech_act_drift_for_goal_stems():
    original = {
        "query": "Question: To assemble furniture,",
        "choices": ["read the instructions.", "guess where the pieces go."],
        "gold": 0,
    }
    drift = {
        **original,
        "query": "Question: What is the correct method for assembling furniture?",
    }
    with pytest.raises(restyle.ValidationError, match="speech act"):
        restyle.validate_item(drift, original, "multiple_choice")


def test_restyle_rejects_too_light_full_sentence_rewrites():
    original = {
        "query": "Question: How do I ready a guinea pig cage for its new occupants?",
        "choices": ["use paper bedding.", "use torn jeans."],
        "gold": 0,
    }
    timid = {
        **original,
        "query": "Question: How do I prepare a guinea pig cage for its new occupants?",
    }
    with pytest.raises(restyle.ValidationError, match="style too light"):
        restyle.validate_item(timid, original, "multiple_choice")


def test_restyle_validate_rejects_choice_and_gold_changes():
    original = {"query": "Question: Which is largest?", "choices": ["rat", "horse"], "gold": 1}
    with pytest.raises(restyle.ValidationError, match="choices changed"):
        restyle.validate_item({**original, "choices": ["rat", "elephant"]}, original, "multiple_choice")
    with pytest.raises(restyle.ValidationError, match="gold changed"):
        restyle.validate_item({**original, "gold": 0}, original, "multiple_choice")


def test_schema_minimal_pair_difference_is_preserved():
    original = {
        "context_options": ["The council refused the marchers because the council", "The council refused the marchers because the marchers"],
        "continuation": "feared violence.",
        "gold": 0,
    }
    valid = {
        "context_options": ["The council declined the marchers' request because the council", "The council declined the marchers' request because the marchers"],
        "continuation": "feared violence.",
        "gold": 0,
    }
    assert restyle.validate_item(valid, original, "schema")["gold"] == 0
    invalid = {
        "context_options": ["The council declined the marchers' request because the aldermen", "The council declined the marchers' request because the marchers"],
        "continuation": "feared violence.",
        "gold": 0,
    }
    with pytest.raises(restyle.ValidationError, match="minimal-pair"):
        restyle.validate_item(invalid, original, "schema")


def test_lambada_validator_requires_final_fragment_and_target_count():
    original = {
        "context": 'He saw a curious mark. "Look here," said Tom. It was a sign',
        "continuation": "sign",
    }
    valid = {
        "context": 'He observed a curious mark. "Look here," said Tom. It was a sign',
        "continuation": "sign",
    }
    assert restyle.validate_item(valid, original, "language_modeling", restyle.LAMBADA)["continuation"] == "sign"
    changed_final = {
        "context": 'He observed a curious mark. "Look here," said Tom. It was no sign',
        "continuation": "sign",
    }
    with pytest.raises(restyle.ValidationError, match="final sentence"):
        restyle.validate_item(changed_final, original, "language_modeling", restyle.LAMBADA)
    removed_target = {
        "context": 'He observed a sign. "Look here," said Tom. It was a sign',
        "continuation": "sign",
    }
    with pytest.raises(restyle.ValidationError, match="target occurrence"):
        restyle.validate_item(removed_target, original, "language_modeling", restyle.LAMBADA)


def test_manual_repeat_copy_has_exact_32_records():
    rows = restyle._manual_repeat_copy_items()
    assert len(rows) == 32
    assert rows[1]["continuation"] == "sparrow sparrow wren sparrow sparrow wren sparrow sparrow wren"
    assert rows[30]["continuation"] == "good day good day good day good day good day"


def test_restyle_uses_paid_endpoint_only_after_rate_limit(monkeypatch):
    calls = []

    def fake_chat_json(messages, model, base_url, **kwargs):
        calls.append((model, base_url, kwargs))
        if len(calls) == 1:
            raise client.RateLimited("free tier cooling")
        return {"query": "Question: Which is largest?", "choices": ["rat", "horse"], "gold": 1}

    monkeypatch.setattr(restyle, "chat_json", fake_chat_json)
    result = restyle._chat_json_with_fallback([], 0.0, 128)
    assert result["gold"] == 1
    assert calls[0][0] == restyle.config.RESTYLE_MODEL
    assert calls[1][0] == restyle.config.RESTYLE_FALLBACK_MODEL


def test_batch_response_requires_exact_ids():
    response = [
        {"id": 1, "item": {"query": "q", "choices": ["a", "b"], "gold": 0}},
        {"id": 2, "item": {"query": "q", "choices": ["a", "b"], "gold": 0}},
    ]
    assert set(restyle._parse_batch_response(response, {1, 2})) == {1, 2}
    with pytest.raises(restyle.ValidationError, match="missing"):
        restyle._parse_batch_response(response[:1], {1, 2})
    with pytest.raises(restyle.ValidationError, match="unexpected"):
        restyle._parse_batch_response([{"id": 3, "item": {}}], {1, 2})


def test_paid_equivalent_uses_mimo_go_rates():
    delta = {"prompt": 1000, "cached": 200, "completion": 500}
    expected = (800 * 0.14 + 200 * 0.0028 + 500 * 0.28) / 1_000_000
    assert restyle._paid_equivalent(delta) == pytest.approx(expected)


def test_batch_generation_validates_each_item(monkeypatch):
    task = {
        "label": "demo",
        "task_type": "multiple_choice",
        "dataset_uri": "demo.jsonl",
        "data": [
            {"query": "Question: Which is largest?", "choices": ["rat", "horse"], "gold": 1},
            {"query": "Question: Which is smallest?", "choices": ["rat", "horse"], "gold": 0},
        ],
    }

    def fake_batch(messages, temperature, max_tokens, item_count):
        return [
            {"id": 0, "item": task["data"][0]},
            {"id": 1, "item": task["data"][1]},
        ]

    monkeypatch.setattr(restyle, "_chat_batch_json_with_fallback", fake_batch)
    wrappers = restyle._generate_batch_valid(task, [0, 1], {}, {}, {}, retries=1)
    assert wrappers[0]["candidate"]["gold"] == 1
    assert wrappers[1]["candidate"]["gold"] == 0


def test_wrapper_rejects_stale_prompt_version():
    task = {
        "label": "demo",
        "task_type": "multiple_choice",
        "dataset_uri": "demo.jsonl",
        "data": [{"query": "Question: Which is largest?", "choices": ["rat", "horse"], "gold": 1}],
    }
    wrapper = restyle._wrapper(task, 0, task["data"][0], 1)
    wrapper["prompt_version"] = "old"
    with pytest.raises(restyle.ValidationError, match="stale prompt"):
        restyle._validate_wrapper(task, wrapper)


def test_audit_flags_length_spike():
    task = {
        "label": "demo",
        "task_type": "multiple_choice",
        "data": [{"query": "Question: Which is largest?", "choices": ["rat", "horse"], "gold": 1}],
    }
    wrapper = {
        "idx": 0,
        "candidate": {
            "query": "Question: Which is largest? " + ("Indeed. " * 50),
            "choices": ["rat", "horse"],
            "gold": 1,
        },
    }
    assert "length > 1.5x" in restyle._audit_flags(task, wrapper)


def test_restyle_normalizes_fullwidth_punctuation():
    # winograd:123 class — full-width comma leaks in but is a lossless cosmetic fix.
    original = {
        "context_options": ["As it was raining, I carried the umbrella because I",
                            "As it was raining, I carried the umbrella because the umbrella"],
        "continuation": " kept dry.",
        "gold": 0,
    }
    generated = {
        "context_options": ["As it was raining，I bore the umbrella because I",
                            "As it was raining，I bore the umbrella because the umbrella"],
        "continuation": " kept dry.",
        "gold": 0,
    }
    item = restyle.validate_item(generated, original, "schema")
    assert "，" not in item["context_options"][0]
    assert item["context_options"][0] == "As it was raining,I bore the umbrella because I"


def test_restyle_rejects_dangling_participial_causal_joint():
    # copa:39/40 class — participial opening + trailing causal connective dangles.
    original = {
        "query": "The friends decided to share the hamburger, therefore",
        "choices": ["they cut the hamburger in half.", "they ordered fries with the hamburger."],
        "gold": 0,
    }
    bad = {
        **original,
        "query": "The friends having resolved upon sharing their hamburger, consequently",
    }
    with pytest.raises(restyle.ValidationError, match="dangling participial causal joint"):
        restyle.validate_item(bad, original, "multiple_choice")
    # a finite causal stem ending in a connective is accepted
    good = {
        **original,
        "query": "The friends had resolved to share the hamburger; consequently",
    }
    assert restyle.validate_item(good, original, "multiple_choice")["gold"] == 0
