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
    """Build the chat messages for one filter decision (few-shot inlined)."""
    msgs = [{"role": "system", "content": FILTER_SYSTEM}]
    for ex_in, ex_out in FILTER_EXAMPLES:
        msgs.append({"role": "user", "content": json.dumps(ex_in, ensure_ascii=False)})
        msgs.append({"role": "assistant", "content": json.dumps(ex_out, ensure_ascii=False)})
    payload = {
        "item": render_item(item, task_type),
        "years_found": annotation["years_found"],
        "modern_terms": annotation["modern_terms"],
    }
    msgs.append({"role": "user", "content": json.dumps(payload, ensure_ascii=False)})
    return msgs
