"""Lossless category/clue decomposition for Vintage CORE Jeopardy rows."""

from __future__ import annotations

import re


_PREFIX = re.compile(r"^([A-Z][A-Z ]+:)(\s*)(.+)$", re.DOTALL)


def split_context(context: str) -> tuple[str, str]:
    match = _PREFIX.match(context)
    if not match:
        raise ValueError("Jeopardy context lacks an uppercase category prefix")
    scaffold = match.group(1) + match.group(2)
    return scaffold, match.group(3)


def rebuild_context(scaffold: str, clue: str) -> str:
    if not scaffold.rstrip().endswith(":"):
        raise ValueError("invalid Jeopardy category scaffold")
    if not clue.strip():
        raise ValueError("empty Jeopardy clue")
    return scaffold + clue
