"""Decompose modules must round-trip losslessly and reconstruct valid rows."""
import json, os
from dev.vintage_core import bundle_validation as bv
from dev.vintage_core.repairs import (
    decompose_coqa as dc,
    decompose_jeopardy as dj,
    decompose_squad as ds,
)
from dev.vintage_core.repairs.regen_jeopardy import AUDITED_CORRECTIONS, _candidate_row
from dev.vintage_core.repairs.regen_squad import (
    _local_passage_candidates as squad_candidates,
    _row_ok as squad_row_ok,
)
from dev.vintage_core.repairs.regen_coqa import (
    AUDITED_REVERTS as COQA_AUDITED_REVERTS,
    _apply_audited_reverts as coqa_audited_reverts,
    _local_story_candidates as coqa_candidates,
    _row_ok as coqa_row_ok,
)
from dev.vintage_core.repairs.regen_boolq import (
    AUDITED_REVERTS as BOOLQ_AUDITED_REVERTS,
    _apply_audited_reverts as boolq_audited_reverts,
    _local_passage_candidates as boolq_candidates,
    _row_ok as boolq_row_ok,
)

FILT = os.path.expanduser("~/Developer/think.nano/artifacts/vintage-core-filtered/eval_data")


def _rows(rel):
    return [json.loads(l) for l in open(f"{FILT}/{rel}") if l.strip()]


def test_squad_roundtrip_lossless():
    rows = _rows("reading_comprehension/squad.jsonl")
    for r in rows:
        passage, suffix = ds.split_row(r["context"])
        assert ds.rebuild_row(passage, suffix) == r["context"]
    # suffix keeps the protected question + blank answer verbatim
    _p, suffix = ds.split_row(rows[1]["context"])
    assert suffix.startswith("\nQuestion: ") and suffix.endswith("Answer: ")


def test_squad_dedup_shrinks_workload():
    rows = _rows("reading_comprehension/squad.jsonl")
    groups = ds.unique_passages(rows)
    assert len(groups) < len(rows) // 3  # heavy passage sharing


def test_coqa_roundtrip_lossless():
    rows = _rows("reading_comprehension/coqa.jsonl")
    for r in rows:
        prefix, story, suffix = dc.split_row(r["context"])
        assert dc.rebuild_row(prefix, story, suffix) == r["context"]
    # story never swallows the dialogue/final-question scaffold
    _p, _s, suffix = dc.split_row(rows[1]["context"])
    assert suffix.lstrip("\n").startswith(("Preceding questions:", "Final question:"))
    assert suffix.endswith("Answer: ")


def test_local_squad_extraction_discards_corrupt_scaffold():
    prose = "A suitably old-fashioned passage."
    assert squad_candidates(prose) == [prose]
    assert squad_candidates(
        f"Context: {prose} Question: changed? Answer: filled"
    ) == [prose]


def test_local_coqa_extraction_requires_explicit_story_boundaries():
    text = (
        "An altered introduction.\nSTORY: A preserved story.\n"
        "Earlier queries:\nQuery: changed?\nAnswer: changed\n"
        "Final question:\nQuestion: changed?\nAnswer: filled"
    )
    assert coqa_candidates(text) == ["A preserved story."]
    assert coqa_candidates("An unmarked story followed by a question") == []


def test_local_boolq_extraction_handles_inline_or_unlabelled_question():
    assert boolq_candidates("Passage: Old prose. Question: Is it so?") == ["Old prose."]
    assert boolq_candidates("Old prose.\nDoes it follow?") == ["Old prose."]


def test_longform_gates_reject_whitespace_only_and_question_contamination():
    squad = {"context": "Context: Plain prose.\nQuestion: What?\nAnswer: ", "continuation": "Plain"}
    _passage, squad_suffix = ds.split_row(squad["context"])
    assert squad_row_ok(squad, " Plain prose. ", squad_suffix, 0) is None
    assert squad_row_ok(squad, "Old-fashioned prose. Extra question?", squad_suffix, 0) is None

    boolq = {"query": "Passage: Plain prose.\nQuestion: Is it?", "choices": ["no", "yes"], "gold": 1}
    _passage, boolq_suffix = boolq["query"].split("\nQuestion:", 1)
    boolq_suffix = "\nQuestion:" + boolq_suffix
    assert boolq_row_ok(boolq, " Plain prose. ", boolq_suffix, 0) is None
    assert boolq_row_ok(boolq, "Old-fashioned prose. Is it so?", boolq_suffix, 0) is None


def test_coqa_gate_preserves_source_boundary_space():
    row = {
        "context": "Intro.\nStory: Plain prose.\nFinal question:\nQuestion: What?\nAnswer: ",
        "continuation": "answer",
    }
    prefix, _story, suffix = dc.split_row(row["context"])
    candidate = coqa_row_ok(row, "Old-fashioned prose.", prefix, suffix, 0)
    assert candidate is not None
    assert "Story: Old-fashioned prose." in candidate["context"]


def test_component_coverage_ignores_scaffold_and_boundary_whitespace_only_changes():
    source = {"context": "Intro.\nStory: Plain prose.\nFinal question:\nQuestion: What?\nAnswer: ", "continuation": "Plain"}
    whitespace_only = {**source, "context": source["context"].replace("Story: ", "Story:")}
    changed = {**source, "context": source["context"].replace("Plain prose.", "Old-fashioned prose.")}
    assert not bv.row_is_restyled("coqa", source, whitespace_only)
    assert bv.row_is_restyled("coqa", source, changed)
    assert bv.coverage_counts("coqa", [source, source], [whitespace_only, changed]) == (1, 2)


def test_longform_audited_reverts_are_exact_filtered_rows():
    coqa = _rows("reading_comprehension/coqa.jsonl")
    boolq = _rows("reading_comprehension/boolq.jsonl")
    coqa_reverts = coqa_audited_reverts(coqa, [{} for _ in coqa])
    boolq_reverts = boolq_audited_reverts(boolq, [{} for _ in boolq])
    assert set(coqa_reverts) == COQA_AUDITED_REVERTS == {2364, 2631, 3984}
    assert set(boolq_reverts) == BOOLQ_AUDITED_REVERTS == {401, 1011}
    assert all(coqa_reverts[idx] == coqa[idx] for idx in COQA_AUDITED_REVERTS)
    assert all(boolq_reverts[idx] == boolq[idx] for idx in BOOLQ_AUDITED_REVERTS)


def test_jeopardy_roundtrip_lossless():
    rows = _rows("world_knowledge/jeopardy_all.jsonl")
    for row in rows:
        scaffold, clue = dj.split_context(row["context"])
        assert dj.rebuild_context(scaffold, clue) == row["context"]


def test_jeopardy_rejects_invalid_scaffolds():
    for context in ("No category here", "Mixed Case: a clue", "CATEGORY:"):
        try:
            dj.split_context(context)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid scaffold: {context!r}")


def test_jeopardy_candidate_preserves_answer_slot_and_hides_target():
    source = {
        "context": "RIVERS: This river passes through Cairo in 1892",
        "continuation": "the Nile",
        "category": "rivers",
    }
    accepted = _candidate_row(
        source, "Through Cairo in 1892 passes this river", 0
    )
    assert accepted is not None
    assert accepted["context"].startswith("RIVERS: ")
    assert accepted["continuation"] == source["continuation"]
    assert _candidate_row(source, "The Nile passes through Cairo in 1892", 0) is None
    assert _candidate_row(source, "A river passes through Cairo in 1892", 0) is None


def test_jeopardy_audited_corrections_pass_fail_closed_gate():
    rows = _rows("world_knowledge/jeopardy_all.jsonl")
    assert len(AUDITED_CORRECTIONS) == 21
    for idx, clue in AUDITED_CORRECTIONS.items():
        candidate = _candidate_row(rows[idx], clue, idx)
        assert candidate is not None, idx
        assert candidate != rows[idx]


def test_lambada_sentence_split_lossless_and_marks():
    from dev.vintage_core.repairs import decompose_lambada as dl
    rows = _rows("language_understanding/lambada_openai.jsonl")
    for r in rows[:500]:
        prefix, frag = dl.split_context(r["context"])
        assert dl.rebuild_context(prefix, frag) == r["context"]
        sents = dl.split_sentences(prefix)
        assert "".join(sents) == prefix                       # lossless
        for m in dl.mark_verbatim(sents, r["continuation"]):  # editable chunks have balanced quotes
            if not m["verbatim"]:
                s = m["text"]
                assert s.count('"') % 2 == 0 and s.count("“") == s.count("”")
    # pure-dialogue and target-bearing sentences are frozen; partial dialogue stays editable
    marked = dl.mark_verbatim(
        ['He walked slowly home. ', '"Please run away from this place at once!" ', 'The end.'], "end")
    assert not marked[0]["verbatim"]  # plain narration -> editable
    assert marked[1]["verbatim"]      # pure dialogue (mostly inside quotes)
    assert marked[2]["verbatim"]      # contains target "end" (and is penultimate)


def test_lambada_split_keeps_titles_with_names_and_freezes_open_single_quote():
    from dev.vintage_core.repairs import decompose_lambada as dl

    prefix = 'She spoke to Dr. Hendricks at once. Then she left.'
    chunks = dl.split_sentences(prefix)
    assert "Dr. Hendricks" in chunks[0]
    assert "".join(chunks) == prefix

    marked = dl.mark_verbatim(
        dl.split_sentences('‘Well I do not know why. It has many poems.'),
        "book",
    )
    assert marked[0]["verbatim"]
