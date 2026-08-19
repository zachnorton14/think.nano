"""Unit tests for the unpunctuated-input fixes.

Offline only: no model, no tokenizer, no network.

    python -m pytest tests/test_prompt_shaping.py -v
"""

import json

import pytest

from nanochat.prompt_shaping import (
    DEFAULT_PRIMING_TURNS,
    PrimingTurnsError,
    load_priming_turns,
    looks_like_question,
    needs_terminal_mark,
    repair_messages,
    repair_user_text,
    validate_priming_turns,
)


# --- repair_user_text: the cases the fix exists for ---------------------------

@pytest.mark.parametrize("typed,expected", [
    ("whats the weather like", "whats the weather like?"),
    ("how do i read a sextant", "how do i read a sextant?"),
    ("who was napoleon", "who was napoleon?"),
    ("texas", "texas."),
    ("i love you", "i love you."),
    ("tell me a joke", "tell me a joke."),
    ("do you like poetry", "do you like poetry?"),
])
def test_repairs_the_shapes_that_fail(typed, expected):
    assert repair_user_text(typed) == expected


def test_casing_is_never_touched():
    # The repair appends; it does not edit. Recasing the opening word cannot fix
    # "napoleon" further in without guessing at proper nouns, and the visitor's
    # text is the visitor's.
    for typed in ["texas", "whats the weather like", "i love you"]:
        assert repair_user_text(typed)[:-1] == typed


def test_a_wellformed_turn_is_left_alone():
    for text in ["What is the weather like?", "Tell me about Texas.", "Stop!",
                 "Well… I wonder.", "He said “yes.”"]:
        assert repair_user_text(text) == text


@pytest.mark.parametrize("text", [
    "write me a list:",        # a colon promises something the visitor is about to type
    "and another thing,",      # mid-thought comma
    "wait -",                  # trailing dash
    "the year was 1930.",
])
def test_deliberate_endings_are_not_touched(text):
    assert not needs_terminal_mark(text)
    assert repair_user_text(text) == text


def test_code_fences_are_left_open():
    text = "run this\n```\nprint(1)"
    assert not needs_terminal_mark(text)
    # A closed block is ordinary text again and gets its mark after the fence.
    assert needs_terminal_mark("run this\n```\nprint(1)\n```")


def test_closing_bracket_or_quote_still_gets_a_mark():
    assert repair_user_text('is this right)') == 'is this right)?'
    # The mark lands after the closer, and the opening word of the clause -- not
    # the quoted words -- decides which mark it is.
    assert repair_user_text('he said "who goes there"') == 'he said "who goes there".'


def test_trailing_whitespace_is_preserved():
    assert repair_user_text("hello  \n") == "hello.  \n"


def test_empty_and_blank_are_returned_unchanged():
    for text in ["", "   ", "\n"]:
        assert repair_user_text(text) == text


def test_the_question_heuristic_can_be_switched_off():
    # The always-"." variant, so a probe run can show whether guessing the mark
    # is worth anything over the simplest possible fix.
    assert repair_user_text("whats the weather like", question_mark=False) == "whats the weather like."
    assert repair_user_text("texas", question_mark=False) == "texas."


# --- the question heuristic, including where it knowingly gives up -----------

@pytest.mark.parametrize("typed", [
    "whats the weather like",     # wh-word, contracted
    "how do i read a sextant",    # wh-word
    "do you like poetry",         # auxiliary + subject
    "is this right",
    "have you seen the paper",
    "can anyone explain the tides",
    "shall we",                   # elliptical, but the subject rule still catches it
])
def test_recognized_questions(typed):
    assert looks_like_question(typed)


@pytest.mark.parametrize("typed", [
    # Auxiliaries that open a statement, not a question. These are why the
    # auxiliary rule requires a subject: "have a good day?" is worse output
    # than any question this rule misses.
    "have a good day",
    "do not worry",
    "will do",
    "can do",
    "must be nice",
    "was napoleon short",         # auxiliary + proper noun: a real miss
    "any idea when the tide turns",  # question word buried mid-clause: a real miss
])
def test_the_heuristic_falls_back_to_a_period(typed):
    # Every one of these gets ".", which is the safe direction to be wrong in.
    assert not looks_like_question(typed)
    assert repair_user_text(typed).endswith(".")


def test_only_the_last_clause_decides_the_mark():
    # A statement followed by a question is a question.
    assert looks_like_question("i went to sea. how do you read a sextant")
    # ...and the reverse.
    assert not looks_like_question("what a day. i went to sea")


def test_at_most_one_character_is_appended():
    for typed in ["texas", "whats up", "hello there friend"]:
        assert len(repair_user_text(typed)) == len(typed) + 1


# --- repair_messages ---------------------------------------------------------

def test_assistant_turns_are_never_rewritten():
    # Rewriting them would put text in the transcript the model never generated.
    messages = [
        {"role": "user", "content": "whats the tide table for tuesday"},
        {"role": "assistant", "content": "high water a little after noon"},
        {"role": "user", "content": "thanks"},
    ]
    out = repair_messages(messages)
    assert out[0]["content"] == "whats the tide table for tuesday?"
    assert out[1]["content"] == "high water a little after noon"
    assert out[2]["content"] == "thanks."


def test_repair_messages_does_not_mutate_the_input():
    messages = [{"role": "user", "content": "texas"}]
    repair_messages(messages)
    assert messages[0]["content"] == "texas"


# --- priming turns -----------------------------------------------------------

def test_the_builtin_priming_block_is_valid():
    turns = validate_priming_turns(DEFAULT_PRIMING_TURNS)
    assert [m["role"] for m in turns] == ["user", "assistant"]


def test_the_builtin_priming_user_turn_is_unpunctuated():
    # The whole point of the example: it is the input shape SFT is thin on. If
    # someone "tidies" it, the block stops demonstrating anything.
    assert needs_terminal_mark(DEFAULT_PRIMING_TURNS[0]["content"])
    assert DEFAULT_PRIMING_TURNS[0]["content"][0].islower()


def test_a_repaired_turn_never_needs_repairing_twice():
    for typed in ["texas", "whats the weather like", "have a good day"]:
        once = repair_user_text(typed)
        assert repair_user_text(once) == once


def test_the_shipped_persona_file_loads():
    turns = load_priming_turns("configs/priming_turns/pre1930-companion.json")
    assert [m["role"] for m in turns] == ["user", "assistant"] * (len(turns) // 2)
    assert all(needs_terminal_mark(m["content"]) for m in turns if m["role"] == "user")


@pytest.mark.parametrize("bad", [
    [],                                                                    # empty
    [{"role": "user", "content": "hi"}],                                   # odd length
    [{"role": "assistant", "content": "hi"}, {"role": "user", "content": "hi"}],  # wrong order
    [{"role": "user", "content": " "}, {"role": "assistant", "content": "hi"}],   # blank turn
])
def test_malformed_priming_blocks_are_rejected(bad):
    # An odd-length or misordered block would put the visitor's first real turn
    # in the assistant slot, which render_conversation asserts against anyway --
    # better to fail at boot than per request.
    with pytest.raises(PrimingTurnsError):
        validate_priming_turns(bad)


def test_empty_spec_means_the_feature_is_off():
    assert load_priming_turns("") == []
    assert load_priming_turns(None) == []


def test_default_spec_returns_the_builtin():
    assert load_priming_turns("default") == DEFAULT_PRIMING_TURNS


def test_a_bare_list_file_is_accepted_too(tmp_path):
    path = tmp_path / "turns.json"
    path.write_text(json.dumps([
        {"role": "user", "content": "hey"},
        {"role": "assistant", "content": "Hello there."},
    ]), encoding="utf-8")
    assert len(load_priming_turns(str(path))) == 2


# --- rendering: the hosted path actually splices the block --------------------
#
# dev/hosting/beam/conversation.py is what the deployment renders with, so the
# properties that matter (the block is there, it is not evicted, it is not
# repaired) are asserted against that module rather than a copy of its logic.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev" / "hosting" / "beam"))
from conversation import render_conversation_tokens  # noqa: E402


class StubTokenizer:
    """One token per word, plus distinguishable specials. Enough to assert
    structure and token counts without loading a real BPE tokenizer."""

    SPECIALS = {"<|bos|>": 0, "<|user_start|>": 1, "<|user_end|>": 2,
                "<|assistant_start|>": 3, "<|assistant_end|>": 4}

    def get_bos_token_id(self):
        return 0

    def encode_special(self, name):
        return self.SPECIALS[name]

    def encode(self, text):
        return [100 + i for i, _ in enumerate(text.split())]


def _segments(tokens):
    """[(role, content tokens), ...] from a rendered prompt.

    The trailing assistant_start that primes the completion has no matching end
    token, so it is deliberately not reported as a segment.
    """
    starts, ends = {1: "user", 3: "assistant"}, {2, 4}
    out, role, buf = [], None, []
    for token in tokens[1:]: # skip bos
        if token in starts:
            role, buf = starts[token], []
        elif token in ends:
            out.append((role, buf))
            role = None
        elif role:
            buf.append(token)
    return out


def _roles(tokens):
    """The sequence of complete turns in a rendered prompt."""
    return [role for role, _ in _segments(tokens)]


def test_priming_block_is_rendered_in_front_of_the_conversation():
    tok = StubTokenizer()
    messages = [{"role": "user", "content": "texas"}]
    plain = render_conversation_tokens(tok, 4096, messages, 100)
    primed = render_conversation_tokens(tok, 4096, messages, 100,
                                        priming_turns=DEFAULT_PRIMING_TURNS)
    assert _roles(plain) == ["user"]
    assert _roles(primed) == ["user", "assistant", "user"]
    assert len(primed) > len(plain)


def test_priming_block_survives_history_eviction():
    tok = StubTokenizer()
    # A long history that cannot fit, forcing the eviction loop to run.
    messages = []
    for i in range(40):
        messages.append({"role": "user", "content": f"question {i} " + "word " * 40})
        messages.append({"role": "assistant", "content": "answer " + "word " * 40})
    messages.append({"role": "user", "content": "and now the last question"})
    primed = render_conversation_tokens(tok, 512, messages, 100,
                                        priming_turns=DEFAULT_PRIMING_TURNS)
    assert len(primed) <= 512 - 100
    # Still opens on the priming pair: it is standing context, not history.
    assert _roles(primed)[:2] == ["user", "assistant"]
    assert len(primed) > len(render_conversation_tokens(tok, 512, messages, 100))


def test_the_system_prompt_merges_into_the_first_priming_turn():
    # The tokenizer has no system special token, so the prompt has to lead the
    # first user turn -- which is the priming one once priming is on.
    tok = StubTokenizer()
    messages = [{"role": "user", "content": "texas"}]
    system = "you are a person of 1930"
    primed = render_conversation_tokens(tok, 4096, messages, 100,
                                        priming_turns=DEFAULT_PRIMING_TURNS,
                                        default_system_prompt=system)
    segments = _segments(primed)
    merged = f"{system}\n\n{DEFAULT_PRIMING_TURNS[0]['content']}"
    assert segments[0] == ("user", tok.encode(merged))
    # ...and not into the visitor's own turn, which is left exactly as typed.
    assert segments[-1] == ("user", tok.encode("texas"))


def test_fix_punctuation_repairs_only_the_visitors_turn():
    tok = StubTokenizer()
    seen = []

    class RecordingTokenizer(StubTokenizer):
        def encode(self, text):
            seen.append(text)
            return super().encode(text)

    render_conversation_tokens(RecordingTokenizer(), 4096,
                               [{"role": "user", "content": "whats the weather like"}],
                               100, priming_turns=DEFAULT_PRIMING_TURNS,
                               fix_punctuation=True)
    assert "whats the weather like?" in seen
    # The priming user turn stays unpunctuated: repairing it would delete the
    # very example it exists to provide.
    assert DEFAULT_PRIMING_TURNS[0]["content"] in seen
