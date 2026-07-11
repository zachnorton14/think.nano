"""Final-sentence decomposition for LAMBADA restyle.

A LAMBADA row is a book passage whose continuation is the final word to predict; the context ends
mid-final-sentence. The task depends on the *final sentence* being an unaltered clue, so we freeze
the final sentence fragment (everything after the last sentence-ending mark) byte-for-byte and
restyle only the earlier text. Reconstruction guarantees the frozen fragment survives, so the
strict LAMBADA validator's final-fragment and target checks cannot fail on the frozen tail.
"""
from __future__ import annotations

import re

_SENTENCE_MARK_RE = re.compile(r"[.!?]")


def final_fragment(context: str) -> str:
    """Text after the last sentence-ending mark (the frozen final-sentence fragment)."""
    matches = list(_SENTENCE_MARK_RE.finditer(context))
    if not matches:
        return context
    return context[matches[-1].end():]


def split_context(context: str):
    """Return (prefix, fragment) with prefix+fragment == context. Prefix is restyled."""
    frag = final_fragment(context)
    prefix = context[: len(context) - len(frag)]
    return prefix, frag


def rebuild_context(restyled_prefix: str, fragment: str) -> str:
    return f"{restyled_prefix}{fragment}"
