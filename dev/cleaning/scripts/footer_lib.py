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
#
# IMPORTANT: only HIGH-PRECISION, modern-artifact patterns belong here. Patterns
# built around ordinary English verbs ("printed by", "manufactured by", "reproduced
# by") or generic short-string shapes (call numbers, "accession") were REMOVED after
# a sample audit showed them deleting real prose -- e.g. "afterward printed by Mr.
# Martin", Moby-Dick's "oil is still manufactured in Nantucket", and the chapter
# heading "ACCESSION OF CHARLEMAGNE". Everything kept here is a specific modern
# preservation/print-on-demand colophon or a digitization artifact.
FOOTER_LINE_PATTERNS = {
    # modern preservation / print-on-demand colophons (specific phrasings only)
    "pod_preservation_photocopy": r"\bpreservation\s+photocopy\b",
    "pod_laser": r"\blaser[-\s]?print",
    "pod_createspace": r"\bcreatespace\b",
    "pod_lightning": r"\blightning\s+source\b",
    "pod_acid_free_archival": r"\bacid[-\s]?free\s+archival\b",
    "pod_ansi_paper": r"\bansi(?:/niso)?\s+z39\.48\b",   # the archival-paper standard line
    "pod_made_in_usa": r"\bmade\s+in\s+the\s+usa\b",
    # digitization artifacts (specific, not the verb "reproduced")
    "repro_this_was_produced": r"\bthis\s+(?:book|edition|volume)\s+is\s+a\s+preservation\b",
    "repro_facsimile": r"\bauthori[sz]ed\s+facsimile\b|\buniversity\s+microfilms\b",
    "digitized_by_google": r"\bdigiti[sz]ed\s+by\s+google\b",
    # library book-plate line (whole-line only)
    "lib_ex_libris": r"^\s*ex\s*libris\b",
    # bare page-number lines: "42", "- 42 -", "[ 42 ]", "p. 42"
    "page_num_bare": r"^\s*[\[\(\-–—]*\s*(?:p\.?\s*)?\d{1,4}\s*[\]\)\-–—]*\s*$",
}

# Format tells reused from filter_lib -- but NOT email_addr: its one sample hit was
# an OCR'd numeric table, and emails are effectively absent from pre-1930 text.
_SAFE_FORMAT_TELLS = {k: v for k, v in FORMAT_TELL_PATTERNS.items() if k != "email_addr"}
_ALL_PATTERNS = {**_SAFE_FORMAT_TELLS, **FOOTER_LINE_PATTERNS}
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
