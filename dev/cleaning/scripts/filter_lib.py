"""Fast anachronism matcher + scan/should-drop logic.

Builds a matcher that avoids a 400+ term regex alternation (seconds per book):
single-word terms via set membership, multi-word phrases gated by first token,
punctuation terms + format tells via small regexes. ~35x faster, identical results.
"""
import re

import config

FORMAT_TELL_PATTERNS = {
    "copyright_post_1930": r"(?:©|copyright|\(c\))\s*(?:19[3-9]\d|20\d\d)",
    "modern_year_reserved": r"all\s+rights\s+reserved",
    "isbn": r"\bisbn(?:-1[03])?\b",
    # URLs -- tightened to real host shapes. Loose forms (\bwww\. and word.tld)
    # matched OCR garbage and prose: bare "www.", "www.y appard", "being.com
    # municative", the price "6d.net", the headword "bor.net". These now require a
    # plausible domain so genuine scanner URLs (www.hathitrust.org, books.google.com,
    # lib.harvard.edu) still match while OCR noise / prices / word-joins are spared.
    "url_www": r"\bwww\.[a-z0-9][a-z0-9-]*\.[a-z]{2,}",
    "url_http": r"https?://",
    "url_dotcom": r"(?<![\w.])[a-z][a-z0-9-]*\.[a-z][a-z0-9-]*\.(?:com|org|net|edu|gov)\b(?![\w])",
    "loc_cip": r"library\s+of\s+congress\s+cata-?\s*loging|cataloging-in-publication",
    "printed_usa_modern": r"printed\s+in\s+the\s+united\s+states\s+of\s+america",
    "gutenberg_license": r"project\s+gutenberg(?:-tm)?(?:\s+(?:license|ebook|literary))",
    "email_addr": r"\b[\w.-]+@[\w.-]+\.\w{2,}\b",
}

PUNCT_TERM_PATTERNS = {
    "9/11": r"9/11",
    "c#": r"\bc#",
    "c++": r"\bc\+\+",
    "node.js": r"\bnode\.js\b",
}

# Word tokenizer for the fast scanner. The document is lowercased first, so this
# only needs the lowercase class. A token starts with a letter/digit and may
# contain internal apostrophes/hyphens (so "mcdonald's", "hip-hop" stay intact).
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'\-]*")


def compile_matchers(banned_terms):
    """Build a fast matcher instead of one giant regex alternation.

    A 400+ term alternation in Python's `re` is O(terms) work at every position
    in the text, which is seconds per multi-MB book. Instead:
      - single-word terms  -> membership test against a frozenset (O(1) per token)
      - multi-word phrases -> gated by first word: only tested where their leading
                              token actually occurs (no alternation scan)
      - punctuation terms  -> a handful of explicit literal regexes
      - format tells       -> the existing high-precision regexes (already cheap)
    This is ~35x faster than the alternation with identical results.
    """
    single = set()
    phrases_by_first = {}   # first_word -> [(full_phrase, [word, ...]), ...]
    for t in banned_terms:
        tl = t.lower()
        if tl in PUNCT_TERM_PATTERNS:
            continue  # handled by the punct regexes below
        words = tl.split()
        if len(words) == 1 and TOKEN_RE.fullmatch(tl):
            single.add(tl)
        else:
            phrases_by_first.setdefault(words[0], []).append((tl, words))
    # Longest phrase first within each bucket so we record the most specific match.
    for k in phrases_by_first:
        phrases_by_first[k].sort(key=lambda x: -len(x[1]))

    format_res = {
        name: re.compile(pat, re.IGNORECASE)
        for name, pat in FORMAT_TELL_PATTERNS.items()
    }
    punct_res = {
        name: re.compile(pat, re.IGNORECASE)
        for name, pat in PUNCT_TERM_PATTERNS.items()
    }
    return {
        "single": frozenset(single),
        "phrases_by_first": phrases_by_first,
        "punct_res": punct_res,
        "format_res": format_res,
    }



# Module-level matcher state, initialized by init_matcher(banned_terms, tiers).
SINGLE_TERMS = frozenset()
PHRASES_BY_FIRST = {}
PUNCT_RES = {}
FORMAT_RES = {}
TIERS = {}   # term -> 1 | 2 | 3 | "strip"


def tier_of(term):
    """Tier for a matched signal. Format/punct hits default appropriately:
    format tells are strip-only; a term not in the tier map falls back to tier 2."""
    if term.startswith("format:"):
        return "strip"
    return TIERS.get(term, 2)


def init_matcher(banned_terms, tiers=None):
    """Compile the fast matcher from the final banned term list + tier map and
    publish everything to module globals used by scan_text/decide_drop."""
    global SINGLE_TERMS, PHRASES_BY_FIRST, PUNCT_RES, FORMAT_RES, TIERS
    m = compile_matchers(banned_terms)
    SINGLE_TERMS = m["single"]
    PHRASES_BY_FIRST = m["phrases_by_first"]
    PUNCT_RES = m["punct_res"]
    FORMAT_RES = m["format_res"]
    TIERS = dict(tiers or {})
    return m


# Scan window comes from config.
SCAN_CHARS = config.SCAN_CHARS or None
SCAN_TAIL_CHARS = config.SCAN_TAIL_CHARS
MIN_BANNED_HITS = config.MIN_BANNED_HITS


def scan_text(text):
    """Return (distinct_terms, distinct_kinds) found in text.

    distinct_terms: sorted list of matched banned terms/phrases (lowercased) plus
                    "format:<name>" entries for format-tell/punctuation hits.
    distinct_kinds: sorted list of high-level kinds: "phrase" (a term/phrase hit)
                    and/or the format-tell category names that fired.

    The drop decision is made separately by decide_drop(terms), which weighs the
    tier of each matched term.
    """
    if not isinstance(text, str) or not text:
        return [], []

    # Window cap: modern forewords, footnotes, copyright pages, ISBN blocks and
    # digitization boilerplate live at the front (and sometimes tail) of a book,
    # essentially never buried mid-chapter. Capping keeps per-doc cost bounded.
    if SCAN_CHARS is None or len(text) <= SCAN_CHARS:
        scan = text
    else:
        head = text[:SCAN_CHARS]
        tail = text[-SCAN_TAIL_CHARS:] if SCAN_TAIL_CHARS else ""
        scan = head + "\n" + tail
    low = scan.lower()

    terms = set()
    kinds = set()

    # Single-word terms (O(1) per token) + first-token-gated multi-word phrases.
    toks = TOKEN_RE.findall(low)
    n = len(toks)
    for i, tok in enumerate(toks):
        if tok in SINGLE_TERMS:
            terms.add(tok)
            kinds.add("phrase")
        bucket = PHRASES_BY_FIRST.get(tok)
        if bucket:
            for phrase, words in bucket:
                L = len(words)
                if i + L <= n and toks[i:i + L] == words:
                    terms.add(phrase)
                    kinds.add("phrase")
                    break  # longest phrase in this bucket matched first

    # Punctuation terms (9/11, c++, ...) -- literal regexes.
    for name, rx in PUNCT_RES.items():
        if rx.search(low):
            terms.add(name)
            kinds.add("phrase")

    # High-precision format tells (ISBN, (c)19xx+, URLs, LoC CIP, ...).
    for name, rx in FORMAT_RES.items():
        if rx.search(low):
            terms.add(f"format:{name}")
            kinds.add(name)

    return sorted(terms), sorted(kinds)


def classify_hits(distinct_terms):
    """Split matched signals by tier. Returns dict with lists per tier."""
    out = {1: [], 2: [], 3: [], "strip": []}
    for t in distinct_terms:
        out[tier_of(t)].append(t)
    return out


def decide_drop(distinct_terms):
    """Tiered drop decision -- drop only on strong evidence.

      - any tier-1 hit                         -> DROP (decisive)
      - >=2 distinct tier2/tier3 with >=1 tier2 -> DROP (corroborated)
      - otherwise                              -> KEEP

    tier-3 (polysemous) never triggers a drop on its own; strip-only/format
    signals (boilerplate, URLs) never contribute to the decision at all.

    Returns (drop: bool, reason: str, by_tier: dict).
    """
    by_tier = classify_hits(distinct_terms)
    n1, n2, n3 = len(by_tier[1]), len(by_tier[2]), len(by_tier[3])
    if n1 >= 1:
        return True, "tier1", by_tier
    if n2 >= 1 and (n2 + n3) >= 2:
        return True, "corroborated_tier2", by_tier
    return False, "kept", by_tier


def should_drop(distinct_terms):
    """Back-compat boolean wrapper around decide_drop."""
    return decide_drop(distinct_terms)[0]
