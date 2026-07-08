"""Line-level footer / boilerplate stripping (Stage 0.5).

Removes reprint / OCR footer lines that wrap the genuine old text -- URLs, "printed
in the United States of America", "all rights reserved", photocopy / print-on-demand
colophons, ISBN lines, bare page numbers, library stamps -- WITHOUT touching the
book body.

Design:
  - A line is removed only if a footer pattern matches AND the line is "footer-like":
    either short (< FOOTER_MAX_LINE_CHARS) or the match covers most of the line. This
    keeps a long prose sentence that merely contains a URL mid-line.
  - After the line pass, if a document would lose more than FOOTER_MAX_DOC_LINE_FRAC of
    its non-empty lines, we KEEP it unstripped and flag it (guards against a pattern
    going haywire on an unusual document).

Pure and testable: no HF, no network. Thresholds come from config.
"""
import re

import config
from filter_lib import FORMAT_TELL_PATTERNS

# --- Footer-specific line patterns (in addition to the format tells) --------
# Each maps a name -> regex. Matching is case-insensitive.
FOOTER_LINE_PATTERNS = {
    # print-on-demand / reproduction colophons
    "pod_photocopy": r"\bphotocopy\b",
    "pod_laser": r"\blaser[-\s]?print",
    "pod_createspace": r"\bcreatespace\b",
    "pod_lightning": r"\blightning\s+source\b",
    "pod_printed_by": r"\bprinted\s+(?:by|and\s+bound)\b",
    "pod_made_in_usa": r"\bmade\s+in\s+the\s+usa\b",
    "pod_manufactured": r"\bmanufactured\s+(?:by|in)\b",
    "repro_scanned": r"\b(?:scanned|digiti[sz]ed|reproduced)\s+by\b",
    "repro_produced": r"\bthis\s+(?:book|edition|volume)\s+was\s+(?:produced|reproduced|reprinted)\b",
    "repro_facsimile": r"\bauthori[sz]ed\s+facsimile\b|\buniversity\s+microfilms\b",
    # library / archive stamps commonly OCR'd into footers
    "lib_ex_libris": r"^\s*ex\s*libris\b",
    "lib_accession": r"^\s*accession(?:\s+(?:no\.?|number))?\b",
    "lib_call_number": r"^\s*(?:call\s+(?:no\.?|number)|[A-Za-z]{1,3}\s*\d{2,5}(?:\.\d+)?\s*)$",
    "lib_property_of": r"^\s*(?:property\s+of|in\s+the\s+custody\s+of)\b",
    # bare page-number lines: "42", "- 42 -", "[ 42 ]", "p. 42"
    "page_num_bare": r"^\s*[\[\(\-–—]*\s*(?:p\.?\s*)?\d{1,4}\s*[\]\)\-–—]*\s*$",
}

# Format tells that are safe to treat as footer markers (reuse from filter_lib).
# (All FORMAT_TELL_PATTERNS qualify -- they are all reprint/boilerplate signals.)
_ALL_PATTERNS = {**FORMAT_TELL_PATTERNS, **FOOTER_LINE_PATTERNS}
_COMPILED = {name: re.compile(pat, re.IGNORECASE) for name, pat in _ALL_PATTERNS.items()}

# A line that is ONLY punctuation/digits/whitespace (short) is OCR noise -> drop.
_NOISE_LINE_RE = re.compile(r"^[\W\d_]+$")


def _line_is_footer(line):
    """Return the name of the first footer pattern that flags this line, or None.

    A pattern only counts if the line is footer-like: short, or the match spans
    most of the line's non-space characters (so mid-prose URLs are spared).
    """
    stripped = line.strip()
    if not stripped:
        return None

    short = len(stripped) <= config.FOOTER_MAX_LINE_CHARS
    # short pure-noise lines (page rules, dot leaders, stray punctuation) -> noise
    if short and _NOISE_LINE_RE.match(stripped) and len(stripped) <= 12:
        return "ocr_noise"

    for name, rx in _COMPILED.items():
        m = rx.search(stripped)
        if not m:
            continue
        if short:
            return name
        # long line: only strip if the match dominates it (footer glued to a line)
        coverage = (m.end() - m.start()) / max(len(stripped), 1)
        if coverage >= 0.6:
            return name
    return None


def strip_footers(text):
    """Remove footer/boilerplate lines from a document.

    Returns (clean_text, removed, flagged) where:
      removed  : list of (pattern_name, line_text) actually removed
      flagged  : True if the doc hit the removed-fraction cap and was KEPT unstripped
    """
    if not isinstance(text, str) or not text:
        return text, [], False

    lines = text.split("\n")
    n_nonempty = sum(1 for ln in lines if ln.strip())
    kept, removed = [], []
    for line in lines:
        name = _line_is_footer(line)
        if name is None:
            kept.append(line)
        else:
            removed.append((name, line.strip()))

    # Guardrail: if too much of the document was flagged, don't trust it -- keep
    # the original unchanged and report it for auditing.
    if n_nonempty and (len(removed) / n_nonempty) > config.FOOTER_MAX_DOC_LINE_FRAC:
        return text, removed, True

    clean = "\n".join(kept)
    # collapse the runs of blank lines that removals can leave behind
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip("\n")
    return clean, removed, False
