"""Story-level decomposition for CoQA restyle regeneration.

A CoQA row is ``<intro>\\nStory: <story>[\\nPreceding questions: ...]\\nFinal question:\\n
Question: <q>\\nAnswer: ``. The dialogue history (prior questions AND their gold answers) and the
final question are score-sensitive scaffold; only the ``Story:`` prose should be restyled.

This module restyles only the story and reconstructs everything else byte-for-byte from the
immutable filtered original, so scaffold deletion, filled final answers, and corruption of prior
answers are structurally impossible. Stories repeat across a conversation's turns, so we
deduplicate: ~553 unique stories back ~4270 rows.
"""
from __future__ import annotations

_STORY_MARK = "Story:"
_END_MARKS = ("\nPreceding questions:", "\nFinal question:")


def split_row(context: str):
    """Return (prefix, story, suffix) with prefix+story+suffix == context.

    prefix ends at ``Story:``; story is the story prose; suffix is the dialogue/final-question
    scaffold. Raises ValueError if the row does not match the expected layout.
    """
    si = context.find(_STORY_MARK)
    if si < 0:
        raise ValueError("missing 'Story:' marker")
    story_start = si + len(_STORY_MARK)
    ends = [context.find(m, story_start) for m in _END_MARKS]
    ends = [e for e in ends if e >= 0]
    if not ends:
        raise ValueError("missing 'Preceding questions:'/'Final question:' scaffold")
    end = min(ends)
    prefix = context[:story_start]
    story = context[story_start:end]
    suffix = context[end:]
    return prefix, story, suffix


def rebuild_row(prefix: str, restyled_story: str, suffix: str) -> str:
    return f"{prefix}{restyled_story}{suffix}"


def unique_stories(rows):
    """Map story -> sorted list of row indices sharing it (dedup key for regeneration)."""
    groups = {}
    for idx, r in enumerate(rows):
        _prefix, story, _suffix = split_row(r["context"])
        groups.setdefault(story, []).append(idx)
    return groups
