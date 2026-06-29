"""LLM prompts for the vintage-CORE pipeline. Kept minimal and explicit so a clean
direct API call (no agent harness) fully determines the behavior."""
import json

# ---------------------------------------------------------------------------
# Filter judge (Artifact A). Decides if an eval item is fair for a 1930-cutoff model.

FILTER_SYSTEM = """\
You audit benchmark questions for a language model whose knowledge ends in 1930 — a \
"vintage" model trained only on text written before 1930.

Decide whether each item is TEMPORALLY FAIR for such a model. Judge ONLY temporal \
appropriateness — never difficulty, quality, or correctness.

REMOVE an item if answering it requires knowledge of anything that postdates 1930:
- a post-1930 year anywhere in the text (decisive);
- a person, place, organization, brand, or creative work that came to prominence after 1930
  (this includes NAMED ENTITIES with no year and no modern word in the text — e.g. a
  contemporary journalist, a modern company, a recent film — use your own knowledge to date them);
- a post-1930 technology, invention, scientific discovery, event, or concept
  (e.g. computers, the internet, software, spaceflight, nuclear weapons, modern medicine).

KEEP an item if its content is timeless or pre-1930:
- physical/causal commonsense, arithmetic, logic, abstract reasoning;
- pre-1930 science (gravity, photosynthesis, evolution), classical history and literature;
- everyday objects and concepts that existed before 1930 (television ~1927, automobile,
  telephone, radio, electricity all predate the cutoff — keep unless used in an explicitly
  post-1930 way).

You are given the item plus a regex annotation: `years_found` (post-1930 years detected) and
`modern_terms` (post-1930 vocabulary detected). If `years_found` is non-empty, REMOVE. Treat
`modern_terms` as a hint, not proof — confirm with your own judgment (e.g. "satellite" may mean a moon).

Return ONLY JSON: {"keep": true|false, "reason": "<=12 words"}. The reason names the specific
anachronism when removing, or says "timeless" / "pre-1930" when keeping.\
"""

FILTER_EXAMPLES = [
    ({"item": 'Question: Which NFL team represented the NFC at Super Bowl 50?\nAnswer: Carolina Panthers',
      "years_found": [2015], "modern_terms": ["super bowl"]},
     {"keep": False, "reason": "Super Bowl 50 (2016) postdates 1930"}),
    ({"item": 'The man turned on the faucet, therefore\n[0] the toilet filled with water.\n[1] water flowed from the spout.',
      "years_found": [], "modern_terms": []},
     {"keep": True, "reason": "timeless physical commonsense"}),
    ({"item": 'The native language of Daniel Schneidermann is\nAnswer: French',
      "years_found": [], "modern_terms": []},
     {"keep": False, "reason": "Daniel Schneidermann is a modern (b.1958) journalist"}),
]


def render_item(item, task_type):
    """Compact, faithful one-item view for the judge (not the scored prompt)."""
    if task_type == "multiple_choice":
        lines = [item["query"]] + ["[%d] %s" % (i, c) for i, c in enumerate(item["choices"])]
        return "\n".join(lines)
    if task_type == "schema":
        lines = ["[%d] %s" % (i, c) for i, c in enumerate(item["context_options"])]
        return "\n".join(lines) + "\ncontinuation: " + item["continuation"]
    # language_modeling
    return item["context"] + "\n-> " + item["continuation"]


def filter_messages(item, task_type, annotation):
    """Single-item filter messages (used as the per-item fallback path)."""
    msgs = [{"role": "system", "content": FILTER_SYSTEM}]
    for ex_in, ex_out in FILTER_EXAMPLES:
        msgs.append({"role": "user", "content": json.dumps(ex_in, ensure_ascii=False)})
        msgs.append({"role": "assistant", "content": json.dumps(ex_out, ensure_ascii=False)})
    payload = {"item": render_item(item, task_type),
               "years_found": annotation["years_found"],
               "modern_terms": annotation["modern_terms"]}
    msgs.append({"role": "user", "content": json.dumps(payload, ensure_ascii=False)})
    return msgs


# Batch mode: one STABLE system message (maximally prefix-cacheable) + one user array.
FILTER_BATCH_SYSTEM = FILTER_SYSTEM + """

BATCH MODE. You receive a JSON array of items, each with an integer "id". Return ONLY a JSON
array with exactly one object per input item: {"id": <same id>, "keep": true|false,
"reason": "<=12 words"}. Include every id exactly once. Example:
INPUT:  [{"id":0,"item":"The man turned on the faucet, therefore [0] the toilet filled [1] water flowed","years_found":[],"modern_terms":[]},
         {"id":1,"item":"The native language of Daniel Schneidermann is -> French","years_found":[],"modern_terms":[]}]
OUTPUT: [{"id":0,"keep":true,"reason":"timeless physical commonsense"},
         {"id":1,"keep":false,"reason":"Daniel Schneidermann (b.1958) postdates 1930"}]"""


# ---------------------------------------------------------------------------
# Backfill (Stage 2): rewrite a REMOVED (post-1930) item into a period-valid one of the
# SAME structure, to restore N on low-count benchmarks. GLM-5.2.

BACKFILL_SYSTEM = """\
You write evaluation questions for a language model whose knowledge ends in 1930.

You are given a benchmark item (as JSON) that was REMOVED because answering it needs post-1930
knowledge. Produce a NEW item that a well-read person in 1930 could answer, testing the SAME skill.
Use the provided benchmark_context to preserve the benchmark's construct, scoring style, and
approximate difficulty. Do not copy that context into the generated item.

HARD RULES:
- Return a JSON object with the EXACT SAME KEYS and structure as the original `item`.
- Keep the same task shape: same number of choices / context_options; `gold` is the integer index
  of the single correct option (unchanged key); for language-modeling keep `context` + `continuation`.
- If the original embeds its options inline in the text (e.g. "Choices: A. ... B. ..."), reproduce
  that exact formatting in your new text and keep the options list identical in form (e.g. ["A","B",...]).
- Replace ALL post-1930 content — people, events, technology, products, brands, dates — with
  period-appropriate (pre-1930) content and register. NO post-1930 references, no years after 1930.
- Exactly ONE clearly-correct answer. Comparable difficulty and length to the original.
- Output ONLY the JSON object. No commentary, no reasoning, no explanations, no code fences.
- The first character of your response must be `{` and the last character must be `}`.

EXAMPLE (multiple_choice, text options):
ORIGINAL: {"query":"Question: Which company makes the iPhone?","choices":["Apple","Sega","Ford","IBM"],"gold":0}
NEW:      {"query":"Question: Which company is famous for the Model T automobile?","choices":["Ford","Cunard","Singer","Bell"],"gold":0}

EXAMPLE (schema):
ORIGINAL: {"context_options":["Bill gave John the Game Boy because Bill","Bill gave John the Game Boy because John"],"continuation":"was finished playing.","gold":0}
NEW:      {"context_options":["Bill gave John the chessboard because Bill","Bill gave John the chessboard because John"],"continuation":"was finished playing.","gold":0}

EXAMPLE (language_modeling):
ORIGINAL: {"context":"The native language of Daniel Schneidermann is","continuation":"French"}
NEW:      {"context":"The native language of Victor Hugo is","continuation":"French"}"""


def backfill_messages(item, task_type, benchmark_context=None):
    """One rewrite request: full original item in, same-structured period item out."""
    payload = {"task_type": task_type, "benchmark_context": benchmark_context or {}, "item": item}
    return [{"role": "system", "content": BACKFILL_SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


def filter_batch_messages(batch):
    """batch: list of (bid, item, task_type, annotation). Returns [system, user(array)]."""
    arr = [{"id": bid, "item": render_item(it, tt),
            "years_found": ann["years_found"], "modern_terms": ann["modern_terms"]}
           for (bid, it, tt, ann) in batch]
    return [{"role": "system", "content": FILTER_BATCH_SYSTEM},
            {"role": "user", "content": json.dumps(arr, ensure_ascii=False)}]
