"""Inference-time shaping of the user's turn.

The failure this addresses: the model answers well when a visitor types a
well-formed question and poorly when they type the way people actually type --
"whats the tide table for tuesday", "texas", "i love you". No terminal mark, no
capital, often a fragment.

The cause is distributional, not a missing instruction. SFT user turns are
almost all well-formed prose: tasks/synth-pre1930.py drops the terminal mark on
only `end_punct_rate` of turns (0.05 in the C3Rv3 configs), so an unpunctuated
turn lands in a thin part of the training distribution and the model continues
the fragment instead of answering it. That is also why system prompting does
nothing here -- this tokenizer has no system special token, so a system prompt
is just prose merged into the first user turn (see Tokenizer.render_conversation),
and prose cannot describe a token distribution to a 32-layer model.

Two independent fixes live here, both off by default:

`repair_user_text` -- append a period to a turn that ends without punctuation,
before it is tokenized. Costs nothing: no context, no latency. It appends one
character and changes nothing else. Casing is the visitor's own text and stays
as typed; a question mark would mean guessing at the visitor's intent, and a
period is what an unmarked turn would most often have carried anyway. It only
fixes the surface form -- a turn that is unpunctuated *and* a bare fragment gets
moved partway toward the training distribution, not all the way.

`priming turns` -- prepend one short user/assistant exchange the visitor never
sees, in which the *user* turn is itself unpunctuated and lowercase and the
assistant answers well anyway. This demonstrates the mapping rather than
describing it, which is the thing a system prompt structurally cannot do. Costs
a few dozen tokens of context per request, and the fake assistant reply also
sets voice and reply length -- pick it as carefully as you would pick an SFT row.

The two compose: repair the visible turn, prime with an unrepaired one.
"""

import json

# A trailing mark in this set means the visitor already terminated the turn, or
# terminated it deliberately open (a colon before a list, a comma or dash before
# a thought they mean to continue). Either way, do not append to it.
_ALREADY_TERMINATED = ".!?…:;,-–—"

# Stripped before we look at the tail, so 'is this right)' and '"who goes there"'
# are still seen as needing a mark.
_CLOSERS = "\"'`’”)]}»"


def _ends_inside_code_fence(text):
    """True if an odd number of ``` fences means the turn ends inside a block."""
    return text.count("```") % 2 == 1


def needs_terminal_mark(text):
    """True if `text` is a turn we should append a sentence-final mark to."""
    stripped = text.rstrip()
    if not stripped or _ends_inside_code_fence(stripped):
        return False
    tail = stripped.rstrip(_CLOSERS)
    if not tail:
        return False
    return tail[-1] not in _ALREADY_TERMINATED


def repair_user_text(text):
    """Return `text` with a period appended, if it ends without punctuation.

    Conservative by construction: it appends exactly one character, never edits
    or re-cases what the visitor typed, and declines on anything that looks
    deliberate (a trailing colon or dash, an unclosed code fence). Whitespace is
    preserved, since a visitor who pasted a block meant the block.
    """
    if not text or not needs_terminal_mark(text):
        return text
    # Append inside the trailing whitespace so 'hello \n' stays 'hello.\n'.
    body = text.rstrip()
    return body + "." + text[len(body):]


def repair_messages(messages):
    """Apply repair_user_text to user turns only, returning new message dicts.

    Assistant turns are history the model itself produced -- rewriting them would
    put text in the transcript that the model never generated.
    """
    out = []
    for message in messages:
        role = message.get("role") if isinstance(message, dict) else message.role
        if role == "user":
            if isinstance(message, dict):
                message = {**message, "content": repair_user_text(message["content"])}
            else:
                message = message.model_copy(
                    update={"content": repair_user_text(message.content)})
        out.append(message)
    return out


# The built-in priming exchange. Deliberately:
#   * one pair, not three -- every pair is context the visitor paid for
#   * the user turn is lowercase, unpunctuated and a fragment: the exact shape
#     we are trying to teach the model to answer
#   * the assistant turn is short, well-formed and topic-free, so it sets reply
#     length and register without committing the conversation to a subject
#   * it reads as an opening pleasantry, so a visitor whose real first message
#     is "hello" does not produce a duplicate-greeting transcript
DEFAULT_PRIMING_TURNS = [
    {"role": "user", "content": "hey hows it going"},
    {"role": "assistant", "content": "Well enough, thank you — a quiet morning, and the better for company. What is on your mind?"},
]


class PrimingTurnsError(ValueError):
    """Raised when a priming-turn definition is malformed."""


def validate_priming_turns(turns):
    """Check that `turns` can be spliced in front of a real conversation.

    The rendering code (and render_conversation's own assertions) require strict
    user/assistant alternation starting at user, so the priming block must start
    with user, end with assistant, and have even length -- otherwise the
    visitor's first real turn lands in the assistant slot.
    """
    if not isinstance(turns, list) or not turns:
        raise PrimingTurnsError("priming turns must be a non-empty list")
    if len(turns) % 2:
        raise PrimingTurnsError(
            f"priming turns must be complete user/assistant pairs, got {len(turns)} messages")
    for i, message in enumerate(turns):
        if not isinstance(message, dict):
            raise PrimingTurnsError(f"priming turn {i} is not an object")
        expected = "user" if i % 2 == 0 else "assistant"
        if message.get("role") != expected:
            raise PrimingTurnsError(
                f"priming turn {i} has role {message.get('role')!r}, expected {expected!r}")
        if not isinstance(message.get("content"), str) or not message["content"].strip():
            raise PrimingTurnsError(f"priming turn {i} has empty content")
    return [{"role": m["role"], "content": m["content"]} for m in turns]


def load_priming_turns(spec):
    """Resolve a CLI/env spec into a validated list of priming messages.

    "" or None -> [] (feature off); "default" -> DEFAULT_PRIMING_TURNS;
    anything else is a path to JSON holding either a bare list of messages or
    {"messages": [...]}, matching the conversation format used elsewhere.
    """
    if not spec:
        return []
    if spec == "default":
        return validate_priming_turns(DEFAULT_PRIMING_TURNS)
    with open(spec, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("messages")
    return validate_priming_turns(data)
