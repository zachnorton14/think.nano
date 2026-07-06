from dev.vintage_core.repackage import VINTAGE_DESCRIPTIONS


EXPECTED_TASKS = {
    "bigbench_repeat_copy_logic", "copa", "bigbench_operators", "agi_eval_lsat_ar",
    "winograd", "openbook_qa", "arc_challenge", "commonsense_qa", "winogrande",
    "piqa", "jeopardy", "arc_easy", "boolq", "lambada_openai", "coqa",
    "bigbench_language_identification", "hellaswag_zeroshot", "hellaswag", "squad",
    "bigbench_qa_wikidata",
}


def test_vintage_descriptions_cover_every_packaged_task_without_embedded_counts():
    assert set(VINTAGE_DESCRIPTIONS) == EXPECTED_TASKS
    for label, description in VINTAGE_DESCRIPTIONS.items():
        assert description.strip()
        assert not any(char.isdigit() for char in description), label


def test_arc_challenge_description_is_not_arc_easy_copy():
    description = VINTAGE_DESCRIPTIONS["arc_challenge"].lower()
    assert "difficult" in description
    assert "arc-easy" not in description
