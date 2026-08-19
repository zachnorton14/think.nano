from scripts.ifeval_generate_nanochat import render_ifeval_prompt
from scripts.model_inference_probe import (
    build_prompt,
    parse_profiles,
    prepare_profile,
)


PRIMING = [
    {"role": "user", "content": "hey hows it going"},
    {"role": "assistant", "content": "Well enough."},
]


class FakeTokenizer:
    def __init__(self):
        self.encoded = []
        self.rendered = None

    def get_bos_token_id(self):
        return 1

    def encode_special(self, value):
        return {
            "<|user_start|>": 2,
            "<|user_end|>": 3,
            "<|assistant_start|>": 4,
            "<|assistant_end|>": 5,
        }[value]

    def encode(self, value):
        self.encoded.append(value)
        return [100 + len(self.encoded)]

    def render_for_completion(self, conversation):
        self.rendered = conversation
        return [1, 2, 3]


def test_default_probe_profiles_are_independent():
    profiles = parse_profiles("bare,system,inference")
    assert profiles == ["bare", "system", "inference"]
    bare = prepare_profile("bare", "whats the weather", "persona", PRIMING)
    system = prepare_profile("system", "whats the weather", "persona", PRIMING)
    inference = prepare_profile("inference", "whats the weather", "persona", PRIMING)
    assert bare["sent"] == "whats the weather"
    assert not bare["system_text"] and not bare["priming_turns"]
    assert system["system_text"] == "persona" and not system["priming_turns"]
    assert inference["sent"] == "whats the weather."
    assert not inference["system_text"] and inference["priming_turns"] == PRIMING


def test_full_profile_composes_system_repair_and_priming():
    full = prepare_profile("full", "texas", "persona", PRIMING)
    assert full["sent"] == "texas."
    assert full["system_text"] == "persona"
    assert full["priming_turns"] == PRIMING


def test_system_prompt_merges_into_first_user_turn_like_serving():
    tokenizer = FakeTokenizer()
    build_prompt(tokenizer, "real question", "persona", PRIMING)
    assert tokenizer.encoded == [
        "persona\n\nhey hows it going",
        "Well enough.",
        "real question",
    ]


def test_ifeval_uses_the_tokenizers_required_conversation_wrapper():
    tokenizer = FakeTokenizer()
    assert render_ifeval_prompt(tokenizer, "Do the thing") == [1, 2, 3]
    assert tokenizer.rendered == {
        "messages": [
            {"role": "user", "content": "Do the thing"},
            {"role": "assistant", "content": ""},
        ]
    }
