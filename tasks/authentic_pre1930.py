"""
Authentic pre-1930s conversational SFT dataset.
https://huggingface.co/datasets/zachnorton03/authentic-pre1930-sft-conversational
"""

from datasets import load_dataset
from tasks.common import Task

class AuthenticPre1930(Task):
    """ Authentic pre-1930s conversational SFT dataset. """

    def __init__(self, split, **kwargs):
        super().__init__(**kwargs)
        self.ds = load_dataset("zachnorton03/authentic-pre1930-sft-conversational", split=split).shuffle(seed=42)
        self.length = len(self.ds)

    def num_examples(self):
        return self.length

    def get_example(self, index):
        row = self.ds[index]
        messages = row["messages"]
        assert len(messages) >= 2
        first_message = messages[0]
        if first_message["role"] == "system":
            rest_messages = messages[1:]
        else:
            rest_messages = messages
        assert len(rest_messages) >= 2
        for i, message in enumerate(rest_messages):
            expected_role = "user" if i % 2 == 0 else "assistant"
            assert message["role"] == expected_role
            assert isinstance(message["content"], str)
        return {"messages": messages}
