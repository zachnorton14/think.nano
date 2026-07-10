"""LLM prompts for the vintage-CORE pipeline. Kept minimal and explicit so a clean
direct API call (no agent harness) fully determines the behavior."""
import json

# ---------------------------------------------------------------------------
# Filter judge. Decides if an eval item is fair for a 1930-cutoff model.

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
You write replacement items for a benchmark used to evaluate a language model whose knowledge
ends in 1930. 1930 is only the model's KNOWLEDGE BOUNDARY — it is NOT the target era. Do not
cluster content near 1930 or lean on 1910s-1920s events.

You are given an item (JSON) that was removed for requiring post-1930 knowledge. Produce ONE new
item testing the SAME skill, whose answer is grounded in either timeless reasoning or knowledge
that was well established and broadly documented LONG before 1930 — draw across the whole pre-1930
record: antiquity, classical works, world history and science of the 1700s-1800s, everyday
physical/causal reasoning, arithmetic, and logic. Prefer well-attested, common knowledge with
abundant pre-1930 sources; avoid niche or sparsely-documented facts.

Choose the right approach per item:
- If the reasoning does NOT depend on the modern topic (commonsense, coreference, cause/effect,
  physical intuition): keep the reasoning relation, swap only modern surface details for timeless
  or older equivalents.
- If the TOPIC itself is post-1930 (modern science such as atomic neutrons, genetics/DNA, plate
  tectonics, antibiotics, electronics, spaceflight; or modern people/events): do NOT salvage it.
  Pick a different, well-established pre-1930 subject that tests a comparable skill (classical
  mechanics, optics, heat, basic chemistry, astronomy, natural history, pre-1930 geology,
  measurement, logic).

HARD RULES:
- Return JSON with the EXACT SAME KEYS/structure as the original. Same number of choices /
  context_options; keep fixed label sets unchanged (e.g. ["no","yes"], ["A","B","C","D"]); if the
  original lists options inline in the text, reproduce that formatting.
- `gold` is the index of the option that is ACTUALLY correct in YOUR new item — determine it
  yourself and double-check it; never just copy the original's index.
- EXACTLY ONE option is correct and it must be UNAMBIGUOUSLY the best; every other option must be
  clearly wrong (not merely less good). If two options could both be defended, rewrite them.
- EVERY option — including distractors, not just the stem and the answer — must be period-clean:
  no post-1930 people, tech, products, or concepts anywhere in the item.
- Match the reasoning DIFFICULTY of the original and the `benchmark_context` (e.g. a "challenge"
  science benchmark needs multi-step reasoning, not simple factual recall). No post-1930 references;
  comparable length.
- If `rejection_feedback` is present, the previous replacement failed human review. Address that
  reason and produce a materially different replacement; do not repeat the rejected item.
- Output ONLY the JSON object — first character `{`, last `}`. No commentary, reasoning, or fences.

EXAMPLES (original -> new):
multiple_choice: {"query":"Question: Which company makes the iPhone?","choices":["Apple","Sega","Ford","IBM"],"gold":0} -> {"query":"Question: Who wrote the tragedy Hamlet?","choices":["Shakespeare","Dickens","Homer","Dante"],"gold":0}
schema: {"context_options":["Bill gave John the Game Boy because Bill","Bill gave John the Game Boy because John"],"continuation":"was finished playing.","gold":0} -> {"context_options":["Bill gave John the chessboard because Bill","Bill gave John the chessboard because John"],"continuation":"was finished playing.","gold":0}
language_modeling: {"context":"The native language of Daniel Schneidermann is","continuation":"French"} -> {"context":"The native language of Leo Tolstoy is","continuation":"Russian"}"""


def backfill_messages(item, task_type, benchmark_context=None, rejection_feedback=""):
    """One rewrite request: full original item in, same-structured period item out."""
    payload = {"task_type": task_type, "benchmark_context": benchmark_context or {}, "item": item}
    if rejection_feedback:
        payload["rejection_feedback"] = rejection_feedback
    return [{"role": "system", "content": BACKFILL_SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


REGENERATION_BASE = """\
You replace a failed benchmark item for a language model whose knowledge ends in 1930. The new
item must test the benchmark construct described by `benchmark_context` using timeless reasoning
or knowledge broadly documented long before 1930. Do not cluster near the cutoff.

HARD RULES:
- Return one JSON object matching `schema` exactly.
- Preserve the required keys, option count, and any fixed option labels.
- Set `gold` to the answer that is actually correct in the new item.
- Exactly one answer must be defensible. All distractors must be clearly wrong.
- Every part of the item, including distractors, must be free of post-1930 concepts and wording.
- Match the benchmark's difficulty and style; ARC-Challenge requires applied reasoning, not trivia.
- Address `audit_concern` and `retry_feedback` without mentioning them in the generated item.
- Output JSON only, with no prose or code fence.
"""

REGENERATION_FRESH_SYSTEM = REGENERATION_BASE + """

FRESH MODE: Create a completely new problem. Use `approved_examples` only to understand benchmark
style and difficulty. Do not copy their subject matter or wording. No previous or removed item is
provided, so choose an unrelated, well-established pre-1930 topic.
"""

REGENERATION_REVISE_SYSTEM = REGENERATION_BASE + """

REVISION MODE: Repair `draft` directly. Preserve its intended reasoning relation and structure,
but rewrite any wording, choices, facts, or gold answer needed to fully resolve `audit_concern`.
Do not make a cosmetic patch when the concern requires a materially different item.
"""


def regeneration_messages(mode, task_type, benchmark_context, schema, audit_concern,
                          previous_item=None, approved_examples=None, retry_feedback=""):
    """Build an isolated fresh or revision request without the removed source item."""
    payload = {
        "mode": mode,
        "task_type": task_type,
        "benchmark_context": benchmark_context or {},
        "schema": schema,
        "audit_concern": audit_concern,
    }
    if retry_feedback:
        payload["retry_feedback"] = retry_feedback
    if mode == "fresh":
        payload["approved_examples"] = approved_examples or []
        system = REGENERATION_FRESH_SYSTEM
    elif mode == "revise":
        if previous_item is None:
            raise ValueError("revision mode requires previous_item")
        payload["draft"] = previous_item
        system = REGENERATION_REVISE_SYSTEM
    else:
        raise ValueError(f"unsupported regeneration mode: {mode}")
    return [{"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


def filter_batch_messages(batch):
    """batch: list of (bid, item, task_type, annotation). Returns [system, user(array)]."""
    arr = [{"id": bid, "item": render_item(it, tt),
            "years_found": ann["years_found"], "modern_terms": ann["modern_terms"]}
           for (bid, it, tt, ann) in batch]
    return [{"role": "system", "content": FILTER_BATCH_SYSTEM},
            {"role": "user", "content": json.dumps(arr, ensure_ascii=False)}]


# ---------------------------------------------------------------------------
# Restyle: recast filtered items into a period register without changing scoring.

RESTYLE_SYSTEM = """\
You are a copy-editor recasting benchmark items so their English prose reads as though written
between roughly 1800 and 1930 — the plain, formal register of schoolbooks, readers, examination
papers, encyclopaedias, and newspapers of that long century. No mock-Elizabethan ("thee",
"thou", "forsooth"); the era's writers were direct, and ornament must be earned.

THE VOICE — imitate this manner, not merely these words:
  "The whale, though it inhabits the sea, is no fish, but a warm-blooded animal, which must
  rise to the surface to breathe; its young, like those of the horse or the ox, are nourished
  upon the mother's milk. It will be observed that Nature is not bound by appearances."
Measured and exact; fond of the semicolon; clauses ranked by subordination rather than strung
together with "and"; the passive voice used without embarrassment; statements delivered with
quiet certainty.

MARKS OF THE STYLE, applied only to text you are permitted to change:
- Diction: "figure out"->"ascertain","determine"; "a lot of"->"a great many"; "kids"->"children";
  "guy"->"man","fellow"; "okay"->"very well"; "gets"->"becomes","obtains","receives";
  "really","very"->"indeed","exceedingly"; "big"->"great","vast"; "famous"->"celebrated";
  "strange"->"curious","singular"; "use"->"employ"; "need"->"require"; "buy"->"purchase";
  "start"->"commence"; "show"->"exhibit"; "on"->"upon" where natural.
- Grammar and rhythm: complete sentences where the original has them; no contractions outside
  quoted speech; the impersonal "one" for generic "you"; "shall"/"should" where natural;
  appositives set off by commas; an occasional gentle inversion.
- HOW MUCH: a stem containing a full sentence must be restyled thoroughly — at least two or
  three distinct marks of the style. A rewrite that merely swaps one word is a failure. Only
  arithmetic, symbols, non-English text, and bare-noun fragments earn a light touch or none.
- VARIETY: do not fall into a habitual formula. The period offers many framings — "By what
  means...", "How may one...", "In what manner ought one to...", "State the method by which...",
  "Whence comes...", "What is meant by...", "By whom was..." — vary them from item to item.
- `style_hint`, when present, names the voice for the stem: "examination" (terse, imperative),
  "schoolbook" (a master questioning a pupil), "encyclopaedia" (measured, expository),
  "miscellany" (conversational-formal). Default "schoolbook". Never copy style_hint into output.
- Restyle in proportion to the prose present. Arithmetic, symbols, and bare-noun stems may need
  the lightest touch or none. Never restyle non-English text.

FORMAT RULES — the item's structure tells you which applies; these outrank style, always:
1. Items with a stem and a list of answer choices: restyle the stem/query ONLY. Every choice is
   copied byte-for-byte, in the same order; `gold` and fixed labels are never altered. If the
   query contains a displayed Choices block, that block is copied byte-for-byte.
2. Items with two context_options and one shared continuation (schema items): the continuation is
   copied byte-for-byte. Here restyle CONSERVATIVELY — change diction and sentence shape only.
   You may NOT add any adjective, participle, clause, connective, or emphasis that supplies a new
   reason, agent, cause, or authority not present in the original, for such additions bias the
   resolution the item exists to test. "Sam pulled up a chair" -> "Sam drew up a chair" is right;
   "The councilmen refused the permit" -> "The councilmen, exercising their authority, refused
   the permit" is WRONG — it primes one reading. Apply the IDENTICAL rewrite to both contexts so
   they still differ ONLY in the same word or phrase as the originals, and each still leads
   grammatically into the shared continuation. The intensity floor does not apply to schema items;
   a light, faithful touch is preferred.
3. Items with a context and an exact continuation or answer: the continuation/answer is copied
   byte-for-byte. Restyle the context so it still leads naturally and unambiguously to that target.
   If the target text occurs anywhere in the context, every such occurrence must survive verbatim.

SCAFFOLDING AND JOINTS:
- Template tokens are part of the test's machinery, not its prose: a leading "Question:" or "Q:",
  a trailing "Answer:" or "A:", labels, and the arrangement of protected line breaks must be
  reproduced exactly as in the original.
- Preserve the speech act of the stem. A goal or task remains a goal; a question remains a
  question; a fragment remains a fragment. Never convert a goal or fragment into a definitional
  question, for the choices answer the original relation, not a new one.
- If the choices grammatically continue the stem's final sentence, the restyled stem must still
  join to every choice exactly as the original did.
- Causal/continuation fragments completed by the choices and ending in a connective
  ("...therefore", "...because", "...so"): the stem must be a FINITE clause and must NOT open with
  a participle. Never write "X, having done Y, therefore" or "X, being Z, therefore" — such a stem
  has no main verb of its own and dangles the moment a choice is appended. Restyle it as a complete
  clause that joins cleanly with EVERY choice, ending in a finite causal connective such as
  "therefore", "consequently", "it followed that", or "the reason was that"; or recast it as a
  leading "Because ..." clause. Mentally append each choice and confirm the whole reads as one
  grammatical sentence before returning.

UNIVERSAL RULES:
- Same meaning, same answer: the same option or target must remain the single correct one.
- Same keys, same counts, same order. Remove `style_hint` from the output.
- All numbers as digits, units, dates, formulas, proper names, and quoted material: copied exactly.
  Reproduce the original spelling of words you retain, including apparent misspellings; you are
  a stylist, not a proof-reader.
- Use ordinary ASCII punctuation only. Never emit full-width or CJK punctuation (；，：！？（）);
  write the plain ASCII forms (; , : ! ? ( )).
- Same difficulty: no added hints, no new ambiguity, no vocabulary an ordinary literate person of
  1900 would not know; stay within about 1.5 times the original length.
- No anachronism in either direction: nothing post-1930, and no period people, events, works, or
  facts the original did not contain. Restyle prose, never content.

SELF-CHECK: keys/counts/order/gold unchanged; choices and continuations byte-identical; answer
spans, scaffolding tokens, and stem-choice joints intact; restyled boldly enough; no post-1930
content. Output ONLY the JSON object.

EXAMPLES:
{"query":"Question: Who wrote the tragedy Hamlet?","choices":["Shakespeare","Dickens","Homer","Dante"],"gold":0,"style_hint":"schoolbook"} -> {"query":"Question: By whom was the tragedy of Hamlet written?","choices":["Shakespeare","Dickens","Homer","Dante"],"gold":0}
{"query":"Question: How do I remove stains from a leather wallet?","choices":["Buff the wallet with some water and press lightly into it","Buff the wallet with some oil and press firmly into it"],"gold":0,"style_hint":"examination"} -> {"query":"Question: State by what means stains may be removed from a wallet of leather.","choices":["Buff the wallet with some water and press lightly into it","Buff the wallet with some oil and press firmly into it"],"gold":0}
{"query":"Question: To assemble furniture,","choices":["you should remove every item from the boxes and read the instructions.","you should mentally picture the assembled furniture."],"gold":0,"style_hint":"schoolbook"} -> {"query":"Question: In setting about the assembly of furniture,","choices":["you should remove every item from the boxes and read the instructions.","you should mentally picture the assembled furniture."],"gold":0}
{"query":"A woman is sitting in front of a piano. She","choices":["begins to play a slow song.","stands up and walks away.","opens the window.","falls asleep on the bench."],"gold":0,"style_hint":"miscellany"} -> {"query":"A woman is seated before a piano. She","choices":["begins to play a slow song.","stands up and walks away.","opens the window.","falls asleep on the bench."],"gold":0}
{"context_options":["The city councilmen refused the demonstrators a permit because the city councilmen","The city councilmen refused the demonstrators a permit because the demonstrators"],"continuation":"feared violence.","gold":1,"style_hint":"schoolbook"} -> {"context_options":["The city councilmen denied the demonstrators a permit, because the city councilmen","The city councilmen denied the demonstrators a permit, because the demonstrators"],"continuation":"feared violence.","gold":1}
{"query":"The man drank heavily at the party, therefore","choices":["he had a headache the next day.","he had a runny nose the next day."],"gold":0,"style_hint":"schoolbook"} -> {"query":"The man had drunk heavily at the party; consequently","choices":["he had a headache the next day.","he had a runny nose the next day."],"gold":0}
"""


LAMBADA_RESTYLE_SYSTEM = RESTYLE_SYSTEM + """

For LAMBADA passage items, replace the general FORMAT RULES with these stricter rules:
- The continuation target is copied byte-for-byte. Every occurrence of the target word anywhere
  in the passage is copied byte-for-byte in place.
- The final sentence or final sentence fragment of the context is copied byte-for-byte. Restyle
  only the text before it.
- Dialogue structure is preserved exactly: same number of quoted segments, same order, same
  speakers by name. Speaker names are verbatim. Attribution verbs may vary but never move/remove.
- No sentence may be deleted, merged, split, or reordered.
- Restyle lightly. If rules cannot be satisfied, produce the closest valid light restyle rather
  than a bold paraphrase.
"""


def restyle_messages(item, task_type, benchmark_context, style_hint, rejection_feedback="",
                     lambada=False):
    payload = {
        "task_type": task_type,
        "benchmark_context": benchmark_context or {},
        "item": {**item, "style_hint": style_hint},
    }
    if rejection_feedback:
        payload["rejection_feedback"] = rejection_feedback
    system = LAMBADA_RESTYLE_SYSTEM if lambada else RESTYLE_SYSTEM
    return [{"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


RESTYLE_BATCH_SUFFIX = """

BATCH MODE. You receive a JSON object with `items`, an array of records. Each record has an integer
`id`, `style_hint`, and `item`. Return ONLY a JSON array with exactly one object per input record:
{"id": <same id>, "item": <restyled JSON object>}. Include every id exactly once. Do not return
extra ids, commentary, markdown, or a wrapper object.
"""


def restyle_batch_messages(batch, task_type, benchmark_context, lambada=False):
    payload = {
        "task_type": task_type,
        "benchmark_context": benchmark_context or {},
        "items": [
            {"id": bid, "style_hint": style_hint, "item": {**item, "style_hint": style_hint}}
            for bid, item, style_hint in batch
        ],
    }
    system = (LAMBADA_RESTYLE_SYSTEM if lambada else RESTYLE_SYSTEM) + RESTYLE_BATCH_SUFFIX
    return [{"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


# ---------------------------------------------------------------------------
# Passage-only restyle: used by the decompose repair for SQuAD/CoQA. The model
# receives a BARE passage (no Context:/Question:/Answer: scaffold, no blank) and
# returns only the restyled passage prose. Scaffold and question/answer are
# reconstructed byte-for-byte in code, so scaffold deletion and filled answers
# are structurally impossible; the only remaining risk is content drift, which
# the deterministic gate rejects.

PASSAGE_RESTYLE_SYSTEM = """\
You are a copy-editor recasting a prose passage so it reads as though written between roughly
1800 and 1930 — the plain, formal register of schoolbooks, readers, encyclopaedias, and
newspapers of that century. No mock-Elizabethan ("thee", "thou", "forsooth"); the era's writers
were direct.

You receive ONE passage of prose. Return ONLY the restyled passage — no title, no labels, no
"Context:"/"Question:"/"Answer:", no commentary, no quotation marks around the whole thing.

ABSOLUTE PRESERVATION (a single violation makes the output useless):
- Every number exactly as written: digits, years, dates, ordinals ("19th"), decimals, fractions,
  measurements, and any digit-bearing token. Never convert a number to words and never replace a
  number with a phrase like "the following year". If the original says "1892", the output says
  "1892".
- Every proper name, place, title, and technical term exactly as written.
- Every quoted span exactly as written, including its quotation marks.
- All facts and information: add nothing, drop nothing, invent nothing. Do not summarise or
  compress. The restyled passage must contain the same content as the original.
- No anachronism in either direction. Introduce no person, place, event, work, invention, or
  concept that is not already in the passage, and nothing that postdates 1930. Do not modernise:
  never replace a period term with a modern word. You restyle prose only, never content.
- PROTECTED SPANS: the user may list exact phrases (answer spans and quotations). Every listed
  phrase must appear in your output EXACTLY as given, the same number of times as in the original
  passage - not reworded, not reordered, not duplicated. Restyle the prose around them.

STYLE:
- Restyle diction and sentence shape into the period register: measured, exact; fond of the
  semicolon; the passive voice used without embarrassment; subordinate clauses over strings of
  "and". No contractions outside quoted speech.
- Use ONLY ordinary ASCII punctuation. Never emit em dashes or en dashes (— –) or full-width
  punctuation; use plain hyphens, commas, and semicolons.
- Stay close to the original length; do not pad. Roughly 0.8x-1.3x the original.

Output ONLY the restyled passage text.
"""


def passage_restyle_messages(passage, protected_spans=()):
    user = passage
    spans = [s for s in dict.fromkeys(protected_spans) if s and s in passage]
    if spans:
        listed = "\n".join(f"- {s}" for s in spans)
        user = (f"PROTECTED SPANS (reproduce each EXACTLY, same number of times, do not reword):\n"
                f"{listed}\n\nPASSAGE:\n{passage}")
    return [
        {"role": "system", "content": PASSAGE_RESTYLE_SYSTEM},
        {"role": "user", "content": user},
    ]
