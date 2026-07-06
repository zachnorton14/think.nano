from dev.vintage_core.reconcile import reconcile_reason


def _record(src="llm"):
    return {"keep": True, "src": src, "reason": "legacy decision"}


def test_reconcile_removes_unresolved_filter_errors():
    assert reconcile_reason("squad", 1, {"context": "old text", "continuation": "answer"},
                            _record("error"))


def test_reconcile_removes_current_science_policy_hits():
    reason = reconcile_reason(
        "arc_challenge", 1,
        {"query": "How many neutrons?", "choices": ["one", "two"], "gold": 0},
        _record(),
    )
    assert reason == "current science policy: neutrons"


def test_reconcile_keeps_adjudicated_natural_satellite_use():
    item = {"query": "Which natural satellite orbits Earth?", "choices": ["Moon", "Sun"],
            "gold": 0}
    assert reconcile_reason("arc_easy", 1, item, _record()) is None


def test_reconcile_keeps_known_foreign_language_rna_false_positive():
    item = {"query": "Sentence: Nyangka-rna kamu kutjupanku.",
            "choices": ["A", "B", "C", "D"], "gold": 0}
    assert reconcile_reason("bigbench_language_identification", 2211, item, _record()) is None


def test_reconcile_removes_non_satellite_modern_terms():
    item = {"context": "She read the story online.", "continuation": "online"}
    assert reconcile_reason("coqa", 1, item, _record()) == "current temporal policy: online"
