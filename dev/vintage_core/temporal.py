"""Regex prescan — a real (non-advisory) first-pass filter that feeds the LLM judge.

Two signals, both passed to the LLM as annotations:
- post-1930 YEAR: authoritative. An item whose text contains a year > 1930 is removed
  outright (code-enforced) — it references a post-cutoff date.
- modern TERMS: high-precision post-1930 vocabulary (website, software, smartphone, ...).
  These are genuine modernisms (verified against the corpus), but a few are ambiguous
  (e.g. "satellite" could be a moon), so the LLM makes the final call on term-only hits.

Terms calibrated for a 1930 cutoff: 'television' (1927) and 'nfl' (1920) are NOT modern
and were removed; 'compute' excluded (false-positives on bigbench_operators).
"""
import re

CUTOFF_YEAR = 1930

YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20\d{2})\b")
MODERN_RE = re.compile(
    r"\b(internet|software|website|online|smartphone|iphone|android|google|"
    r"facebook|twitter|youtube|super bowl|laptop|astronaut|spacecraft|satellite|"
    r"covid|video game|microchip|transistor|helicopter)\w*",
    re.I,
)

# GENUINELY post-1930 science/tech the MODERN_RE misses. Safety net for VALIDATING generated
# backfill items (GLM doesn't know these postdate 1930). Deliberately conservative — terms that
# predate 1930 are EXCLUDED to avoid rejecting valid items: mitochondria (1898), continental
# drift (1912, Wegener), quantum theory (1900-1927), penicillin (1928), polymer (1920s), the
# electron/proton, chromosomes, sonar (WWI). Kept: things clearly after 1930.
SCIENCE_POST1930_RE = re.compile(
    r"(\bneutron\w*|plate tectonic\w*|\bsubduction|transform fault|"
    r"\bdna\b|deoxyribonucleic|\brna\b|genetic code|antibiotic\w*|"
    r"\bradar\b|jet engine|atomic bomb|nuclear (?:weapon|reactor|bomb|fission)|"
    r"\becosystem\w*|cell[ -]?cycle|photo[ -]?cop\w*|xerox|ribosome\w*)",
    re.I,
)


def science_anachronisms(item):
    """Sorted unique post-1930 science/tech terms found (validation safety net for backfill)."""
    return sorted(set(m.lower().strip() for m in SCIENCE_POST1930_RE.findall(item_text(item))))


def item_text(item):
    """Concatenate all text fields of an eval item, regardless of task type."""
    out = []
    for key in ("query", "context", "continuation", "choices", "context_options"):
        v = item.get(key)
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list):
            out += [str(x) for x in v]
    return " ".join(out)


def post_cutoff_years(item):
    """Sorted list of years > CUTOFF_YEAR in the item text (authoritative removal signal)."""
    yrs = [int(y) for y in YEAR_RE.findall(item_text(item))]
    return sorted(set(y for y in yrs if y > CUTOFF_YEAR))


def modern_terms(item):
    """Sorted unique high-precision modern terms found (LLM-adjudicated hint)."""
    return sorted(set(m.lower() for m in MODERN_RE.findall(item_text(item))))


def annotate(item):
    """Regex annotation passed to the LLM: years_found (hard) + modern_terms (hint)."""
    years = post_cutoff_years(item)
    return {"years_found": years, "modern_terms": modern_terms(item), "regex_remove": bool(years)}


def regex_flag(item):
    """True if either signal fires (used by dry-run stats for a lower-bound count)."""
    return bool(post_cutoff_years(item)) or bool(modern_terms(item))
