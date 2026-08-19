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

`repair_user_text` -- put the terminal mark back before the turn is tokenized.
Costs nothing, no context, no latency. It only fixes the surface form: a turn
that is unpunctuated *and* a bare fragment gets moved partway toward the
training distribution, not all the way. Casing is deliberately left alone --
that is the visitor's own text, and there is no way to fix "napoleon" without
guessing at proper nouns.

Which mark to append is a heuristic (see `looks_like_question`), and "." is the
fallback. Pass question_mark=False to skip the heuristic entirely and always
append "." -- scripts/punctuation_probe.py runs both so you can see whether the
heuristic earns its keep on your checkpoint.

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

# A wh-word opening the final clause is a question in nearly every case, so it
# stands alone. Includes the apostrophe-less contractions ("whats", "hows")
# that show up in exactly the unpunctuated typing we are trying to repair.
_WH_OPENERS = frozenset("""
who what when where why how which whose whom
whats hows whens wheres whys whos
""".split())

# An auxiliary opening the clause is ambiguous on its own -- "have a good day"
# and "do not worry" open exactly like "have you seen" and "do you like". So an
# auxiliary only votes question when a subject follows it.
_AUX_OPENERS = frozenset("""
is are was were do does did can could will would should shall may might
have has had am must
""".split())

_SUBJECTS = frozenset("""
i you he she it we they there that this these those
anyone anybody someone somebody everyone nobody
""".split())


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


def looks_like_question(text):
    """Guess whether the final clause of `text` is a question.

    A heuristic, and knowingly an imperfect one: a wh-word opens a question, and
    an auxiliary opens one only when a subject follows it. It is tuned to be
    wrong in the cheap direction -- it misses questions ("was napoleon short",
    "any idea when the tide turns") more readily than it invents them, because
    the miss falls back to "." and "." is what an unmarked turn would most often
    have carried anyway.
    """
    # Split on sentence-final marks and newlines so only the last clause votes:
    # "i went to sea. how do you read a sextant" is a question.
    last = text.rstrip()
    for sep in ".!?…\n":
        last = last.rsplit(sep, 1)[-1]
    words = [w.strip(",").lower() for w in last.strip().lstrip(_CLOSERS + "(¿").split()]
    if not words:
        return False
    if words[0] in _WH_OPENERS:
        return True
    return words[0] in _AUX_OPENERS and len(words) > 1 and words[1] in _SUBJECTS


def repair_user_text(text, question_mark=True):
    """Return `text` with a sentence-final mark, if it is missing one.

    Conservative by construction: it appends exactly one character, never edits
    or re-cases what the visitor typed, and declines on anything that looks
    deliberate (a trailing colon or dash, an unclosed code fence). Whitespace is
    preserved, since a visitor who pasted a block meant the block.

    `question_mark=False` always appends "." and skips looks_like_question.
    """
    if not text or not needs_terminal_mark(text):
        return text
    mark = "?" if question_mark and looks_like_question(text) else "."
    # Append inside the trailing whitespace so 'hello \n' stays 'hello.\n'.
    body = text.rstrip()
    return body + mark + text[len(body):]


def repair_messages(messages, question_mark=True):
    """Apply repair_user_text to user turns only, returning new message dicts.

    Assistant turns are history the model itself produced -- rewriting them would
    put text in the transcript that the model never generated.
    """
    out = []
    for message in messages:
        role = message.get("role") if isinstance(message, dict) else message.role
        if role == "user":
            if isinstance(message, dict):
                message = {**message,
                           "content": repair_user_text(message["content"], question_mark)}
            else:
                message = message.model_copy(
                    update={"content": repair_user_text(message.content, question_mark)})
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
