# ---------------------------------------------------------------------------
# FILTER FUNCTIONS
#
# scan_text: find every anachronism hit in a document, using the FAST matcher
# built in the previous cell (single-word set + first-token-gated phrases +
# punctuation/format regexes). This avoids a 400+ term regex alternation, which
# is seconds-per-book slow on multi-MB OCR text; the fast path is ~35x quicker
# with identical results.
# should_drop: apply Hla's rule -- drop the whole document if it has enough hits.
#
# No text is mutated. Kept documents are written through byte-for-byte, so this
# stage only ever removes whole books (never edits them).
# ---------------------------------------------------------------------------


def scan_text(text):
    """Return (distinct_terms, distinct_kinds) found in text.

    distinct_terms: sorted list of matched banned terms/phrases (lowercased) plus
                    "format:<name>" entries for format-tell/punctuation hits.
    distinct_kinds: sorted list of high-level kinds: "phrase" (a term/phrase hit)
                    and/or the format-tell category names that fired.
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


def should_drop(distinct_terms):
    """Hla's rule: drop when the document contains >= MIN_BANNED_HITS distinct
    banned signals. Default MIN_BANNED_HITS = 1 (one hit anywhere scraps it)."""
    return len(distinct_terms) >= MIN_BANNED_HITS


# Quick self-check so a bad regex surfaces immediately when this cell runs.
_pos = "This 1998 reprint (ISBN 0-123) discusses the transistor and DNA."
_neg = "A treatise on the aeroplane, radio, and the theory of relativity, 1928."
_pt, _pk = scan_text(_pos)
_nt, _nk = scan_text(_neg)
print("Filter self-check:")
print(f"  modern sample  -> drop={should_drop(_pt)} hits={_pt}")
print(f"  vintage sample -> drop={should_drop(_nt)} hits={_nt}")
assert should_drop(_pt), "Expected the modern sample to be dropped."
assert not should_drop(_nt), "Vintage sample should survive (allow-listed terms)."
print("  OK: modern dropped, vintage kept.")
