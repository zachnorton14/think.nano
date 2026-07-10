"""Decompose modules must round-trip losslessly and reconstruct valid rows."""
import json, os
from dev.vintage_core.repairs import (
    decompose_coqa as dc,
    decompose_jeopardy as dj,
    decompose_squad as ds,
)
from dev.vintage_core.repairs.regen_jeopardy import _candidate_row

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
