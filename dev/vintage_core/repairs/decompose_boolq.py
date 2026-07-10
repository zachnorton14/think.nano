"""Passage-level decomposition for BoolQ restyle regeneration.

BoolQ is a multiple-choice item whose ``query`` is ``Passage: <passage>\\nQuestion: <question>``
with fixed choices ``["no", "yes"]``. The yes/no answer is not a span of the passage, so only the
passage prose is restyled; the ``Passage:`` prefix, the question, choices, and gold are kept
byte-for-byte. This removes the scaffold/question/quote corruption the whole-item restyle caused.
"""
from __future__ import annotations

_PREFIX = "Passage: "
_QMARK = "\nQuestion:"


def split_query(query: str):
    """Return (passage, suffix) where suffix is the exact ``\\nQuestion: ...`` tail."""
    if not query.startswith(_PREFIX):
        raise ValueError("missing 'Passage: ' prefix")
    i = query.rfind(_QMARK)
    if i < 0:
        raise ValueError("missing '\\nQuestion:' marker")
    return query[len(_PREFIX):i], query[i:]


def rebuild_query(restyled_passage: str, suffix: str) -> str:
    return f"{_PREFIX}{restyled_passage}{suffix}"


def unique_passages(rows):
    groups = {}
    for idx, r in enumerate(rows):
        passage, _suffix = split_query(r["query"])
        groups.setdefault(passage, []).append(idx)
    return groups
