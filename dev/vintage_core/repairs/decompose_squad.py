"""Passage-level decomposition for SQuAD restyle regeneration.

SQuAD rows are ``Context: <passage>\\nQuestion: <question>\\nAnswer: `` with the answer
as the continuation. The whole-row restyle failed systemically: the model deleted the
``Question:`` scaffold, filled the answer blank, and dropped numbers under output pressure.

This module restyles ONLY the passage prose and reconstructs the ``Context:``/``Question:``/
``Answer:`` scaffold byte-for-byte from the immutable filtered original, so the failure classes
(scaffold deletion, filled answers) become structurally impossible. Passages repeat across
questions, so we deduplicate: ~923 unique passages back ~4284 rows.
"""
from __future__ import annotations

import re

_CTX_PREFIX = "Context: "
_QUESTION_RE = re.compile(r"\nQuestion: .*\nAnswer: ?$", re.S)


def split_row(context: str):
    """Return (passage, suffix) where suffix is the exact ``\\nQuestion: ...\\nAnswer: `` tail.

    Raises ValueError if the row does not match the expected scaffold, so a malformed row
    is never silently mangled.
    """
    if not context.startswith(_CTX_PREFIX):
        raise ValueError("missing 'Context: ' prefix")
    m = _QUESTION_RE.search(context)
    if not m:
        raise ValueError("missing '\\nQuestion: ...\\nAnswer:' suffix")
    passage = context[len(_CTX_PREFIX): m.start()]
    suffix = context[m.start():]
    return passage, suffix


def rebuild_row(restyled_passage: str, suffix: str) -> str:
    """Reconstruct the full context from a restyled passage + the immutable scaffold suffix."""
    return f"{_CTX_PREFIX}{restyled_passage}{suffix}"


def unique_passages(rows):
    """Map passage -> sorted list of row indices sharing it (dedup key for regeneration)."""
    groups = {}
    for idx, r in enumerate(rows):
        passage, _suffix = split_row(r["context"])
        groups.setdefault(passage, []).append(idx)
    return groups
