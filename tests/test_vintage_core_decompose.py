"""Decompose modules must round-trip losslessly and reconstruct valid rows."""
import json, os
from dev.vintage_core.repairs import decompose_squad as ds, decompose_coqa as dc

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
