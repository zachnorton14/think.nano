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


# Sentence-array decomposition: split the (already tail-frozen) prefix into a lossless array of
# sentences so each can be restyled/reverted independently. A boundary is a run of . ! ? plus an
# optional closing quote and whitespace, only when the next sentence clearly starts (uppercase or
# an opening quote). This deliberately does NOT split "'What?' she said." because "she" is
# lowercase - when unsure we keep the chunk whole, per the conservative rule.
_QUOTE_CHARS = "\"'“”‘’"
_BOUNDARY_RE = re.compile(
    r'([.!?]+[' + re.escape('"\'”’') + r']?\s+)(?=[A-Z' + re.escape('"\'“‘') + r'])'
)


QUOTED_SPAN_RE = re.compile(r"``.*?''|\"(?:\\.|[^\"\\])*\"|“[^”]*”|‘[^’]*’", re.DOTALL)


def _quotes_balanced(text: str) -> bool:
    """True if double-quote dialogue is balanced within the chunk (do not split mid-quote)."""
    return text.count('"') % 2 == 0 and text.count("“") == text.count("”")


def split_sentences(prefix: str):
    """Lossless split (''.join == prefix); never break inside a double-quoted span."""
    parts = _BOUNDARY_RE.split(prefix)
    raw, i = [], 0
    while i < len(parts):
        chunk = parts[i] + (parts[i + 1] if i + 1 < len(parts) else "")
        if chunk:
            raw.append(chunk)
        i += 2
    # merge forward until each chunk's double quotes are balanced (a quote spanning a sentence
    # boundary must stay in one element, or the per-element quote check cannot protect it)
    sents, buf = [], ""
    for chunk in raw:
        buf += chunk
        if _quotes_balanced(buf):
            sents.append(buf)
            buf = ""
    if buf:
        sents.append(buf)
    return sents or [prefix]


def _is_pure_dialogue(text: str) -> bool:
    """True when the sentence is mostly a quotation (nothing legally editable outside it)."""
    inside = sum(len(m) for m in QUOTED_SPAN_RE.findall(text))
    body = len(text.strip())
    return body > 0 and inside / body > 0.7


def mark_verbatim(sents, target: str):
    """Return [{text, verbatim}]; verbatim sentences are copied exactly (never sent to the model).

    Frozen: the head fragment, the penultimate cue before the tail, target-bearing sentences, and
    pure-dialogue sentences. Partial-dialogue sentences stay editable - the per-element quote check
    protects the quotation, and freezing them would strand narration in dialogue-heavy passages.
    """
    tl = (target or "").lower()
    n = len(sents)
    out = []
    for i, s in enumerate(sents):
        head_truncated = i == 0 and s.strip()[:1].islower()  # mid-word head like "ep research..."
        penultimate = i >= n - 1                              # strongest cue before the frozen tail
        target_cue = bool(tl) and tl in s.lower()
        out.append({"text": s, "verbatim": head_truncated or penultimate or target_cue or _is_pure_dialogue(s)})
    return out
