"""
GSM8K evaluation.
https://huggingface.co/datasets/openai/gsm8k

Example problem instance:

Question:
Weng earns $12 an hour for babysitting. Yesterday, she just did 50 minutes of babysitting. How much did she earn?
Answer:
Weng earns 12/60 = $<<12/60=0.2>>0.2 per minute.
Working 50 minutes, she earned 0.2 x 50 = $<<0.2*50=10>>10.
#### 10

Notice that GSM8K uses tool calls inside << >> tags.
"""

import json
import os
import re
from pathlib import Path
from datasets import load_dataset
from tasks.common import Task


GSM_RE = re.compile(r"#### (\-?[0-9\.\,]+)")
def extract_answer(completion):
    """
    Extract the numerical answer after #### marker.
    Follows official code for normalization:
    https://github.com/openai/grade-school-math/blob/3101c7d5072418e28b9008a6636bde82a006892c/grade_school_math/dataset.py#L28
    """
    match = GSM_RE.search(completion)
    if match:
        match_str = match.group(1).strip()
        match_str = match_str.replace(",", "")
        return match_str
    return None


class GSM8K(Task):

    def __init__(self, subset, split, variant="raw", data_dir=None, **kwargs):
        super().__init__(**kwargs)
        assert subset in ["main", "socratic"], "GSM8K subset must be main|socratic"
        assert split in ["train", "test"], "GSM8K split must be train|test"
        assert variant in ["raw", "vintage"], "GSM8K variant must be raw|vintage"
        self.variant = variant
        if variant == "raw":
            # Preserve the historical behavior (including deterministic shuffle) by default.
            self.ds = load_dataset("openai/gsm8k", subset, split=split).shuffle(seed=42)
        else:
            assert subset == "main", "Vintage GSM8K is only packaged for the main subset"
            default_dir = Path(__file__).resolve().parents[1] / "artifacts" / "vintage-gsm8k" / "data"
            dataset_dir = Path(data_dir or os.getenv("VINTAGE_GSM8K_DATA_DIR", default_dir))
            filepath = dataset_dir / f"{split}.jsonl"
            if not filepath.exists():
                raise FileNotFoundError(
                    f"Vintage GSM8K is not packaged at {filepath}. "
                    "Run `python -m dev.vintage_gsm8k package` after review and verification."
                )
            with filepath.open("r", encoding="utf-8") as handle:
                self.ds = [json.loads(line) for line in handle if line.strip()]

    @property
    def eval_type(self):
        return 'generative'

    def num_examples(self):
        return len(self.ds)

    def get_example(self, index):
        """ Get a single problem from the dataset. """
        row = self.ds[index]
        question = row['question'] # string of the question prompt
        answer = row['answer'] # string of the full solution and the answer after #### marker
        if self.variant == "vintage":
            return {
                "messages": [
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": answer},
                ],
            }

        # Create and return the legacy raw Conversation object.
        # This is tricky because GSM8K uses tool calls, which we need to parse here.
        assistant_message_parts = []
        parts = re.split(r'(<<[^>]+>>)', answer)
        for part in parts:
            if part.startswith('<<') and part.endswith('>>'):
                # This is a calculator tool call
                inner = part[2:-2]  # Remove << >>
                # Split on = to get expression and result
                if '=' in inner:
                    expr, result = inner.rsplit('=', 1)
                else:
                    expr, result = inner, ""
                # Add the tool call as a part
                assistant_message_parts.append({"type": "python", "text": expr})
                # Add the result as a part
                assistant_message_parts.append({"type": "python_output", "text": result})
            else:
                # Regular text in between tool calls
                assistant_message_parts.append({"type": "text", "text": part})
        # Now put it all together
        messages = [
            {"role": "user", "content": question}, # note: simple string
            {"role": "assistant", "content": assistant_message_parts}, # note: list of parts (as dicts)
        ]
        conversation = {
            "messages": messages,
        }
        return conversation

    def evaluate(self, conversation, assistant_response):
        """
        Given (conversation, completion), return evaluation outcome (0 = wrong, 1 = correct)
        Note that:
        - the conversation has both user AND assistant message (containing the ground truth answer)
        - the assistant_response is usually the alternative assistant message achieved via sampling

        Both legacy list-part responses and plain-string vintage responses are accepted.
        """
        def response_text(content):
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                text_parts = [
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                return "".join(text_parts)
            raise TypeError(f"Expected string or list-part answer, got {type(content)}")

        # First extract the ground truth answer
        assistant_message = conversation['messages'][-1]
        assert assistant_message['role'] == "assistant", "Last message must be from the Assistant"
        # Extract both the ground truth answer and the predicted answer
        ref_num = extract_answer(response_text(assistant_message['content']))
        pred_num = extract_answer(response_text(assistant_response))
        # Compare and return the success as int
        is_correct = int(pred_num == ref_num)
        return is_correct

    def reward(self, conversation, assistant_response):
        """
        Used during RL. To keep things simple, just re-use the evaluation above.
        Later this could be made more complex (e.g. format matching etc.)
        """
        is_correct = self.evaluate(conversation, assistant_response)
        is_correct_float = float(is_correct)
        return is_correct_float
