from nanochat.tokenizer import RustBPETokenizer


class _CharacterTokenizer:
    """Minimal tokenizer surface for exercising conversation rendering."""

    _special = {
        "<|user_start|>": -2,
        "<|user_end|>": -3,
        "<|assistant_start|>": -4,
        "<|assistant_end|>": -5,
    }

    def get_bos_token_id(self):
        return -1

    def encode_special(self, text):
        return self._special[text]

    def encode(self, text):
        return [ord(character) for character in text]


def test_tool_parts_are_rendered_as_ordinary_text():
    tokenizer = _CharacterTokenizer()
    conversation = {
        "messages": [
            {"role": "user", "content": "What is six times seven?"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Checking: "},
                    {"type": "python", "text": "6*7"},
                    {"type": "python_output", "text": "42"},
                    {"type": "text", "text": "."},
                ],
            },
        ]
    }

    ids, mask = RustBPETokenizer.render_conversation(tokenizer, conversation)
    assistant_text = "".join(
        chr(token_id)
        for token_id, mask_value in zip(ids, mask)
        if mask_value and token_id >= 0
    )

    assert assistant_text == "Checking: <<6*7=42>>."

