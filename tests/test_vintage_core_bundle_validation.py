from dev.vintage_core import bundle_validation as validation


def test_digit_tokens_cover_old_validator_blind_spots():
    assert validation.digit_tokens("1892. In the 19th century, c1600 and 1/4 remained.") == [
        "1892",
        "19th",
        "c1600",
        "1/4",
    ]


def test_language_modeling_rejects_filled_answer_and_scaffold_loss():
    original = {
        "context": "Context: A week-long event was held.\nQuestion: How long was it?\nAnswer: ",
        "continuation": "a week",
    }
    filled = {
        "context": "Context: A week-long event was held.\nQuestion: How long was it?\nAnswer: a week",
        "continuation": "a week",
    }
    reasons = [issue.reason for issue in validation.validate_pair("squad", "language_modeling", 0, original, filled)]
    assert "continuation occurrence count changed" in reasons
    assert "context no longer ends in a blank Answer: cue" in reasons

    no_question = {"context": "A week-long event was held.", "continuation": "a week"}
    reasons = [issue.reason for issue in validation.validate_pair("squad", "language_modeling", 0, original, no_question)]
    assert "protected scaffold marker sequence/placement changed" in reasons


def test_multiple_choice_rejects_new_choice_text_in_query():
    original = {
        "query": "Question: Through what does an aeroplane travel?",
        "choices": ["atmosphere.", "lithosphere."],
        "gold": 0,
    }
    leaked = {
        **original,
        "query": "Question: Through what atmosphere does an aeroplane travel?",
    }
    reasons = [issue.reason for issue in validation.validate_pair("arc_easy", "multiple_choice", 0, original, leaked)]
    assert any(reason.startswith("choice text newly appears") for reason in reasons)


def test_schema_rejects_new_terminal_punctuation_collision():
    original = {
        "context_options": ["Alice cared for Bob", "Alice cared for Alice"],
        "continuation": ".",
        "gold": 0,
    }
    broken = {
        **original,
        "context_options": ["Alice attended to Bob.", "Alice attended to Alice."],
    }
    reasons = [issue.reason for issue in validation.validate_pair("winograd", "schema", 0, original, broken)]
    assert "new punctuation collision at continuation joint" in reasons


def test_jeopardy_requires_visible_category_and_metadata_key():
    original = {
        "context": "WORLD HISTORY: This general crossed the Alps",
        "continuation": "Hannibal",
        "category": "world_history",
    }
    broken = {"context": "This general crossed the Alps", "continuation": "Hannibal"}
    reasons = [issue.reason for issue in validation.validate_pair("jeopardy", "language_modeling", 0, original, broken)]
    assert any(reason.startswith("keys changed") for reason in reasons)


def test_clean_pair_passes():
    original = {
        "query": "Question: Which object is largest?",
        "choices": ["a mouse", "a horse"],
        "gold": 1,
    }
    candidate = {
        "query": "Question: Which of these objects is the greater in size?",
        "choices": ["a mouse", "a horse"],
        "gold": 1,
    }
    assert validation.validate_pair("openbook_qa", "multiple_choice", 0, original, candidate) == []


def test_exact_copy_task_set_excludes_restyled_lambada():
    # LAMBADA is now restyled (final-sentence-frozen), not a designated copy task.
    assert "lambada_openai" not in validation.EXACT_COPY_TASKS
    assert "bigbench_qa_wikidata" in validation.EXACT_COPY_TASKS


def test_lambada_gate_enforces_final_fragment_and_sentence_count():
    original = {"context": "He walked home. She waited by the", "continuation": "door"}
    ok = {"context": "He went home. She waited by the", "continuation": "door"}
    assert validation.validate_pair("lambada_openai", "language_modeling", 0, original, ok) == []
    bad = {"context": "She waited by the", "continuation": "door"}
    assert any("sentence count" in i.reason for i in
               validation.validate_pair("lambada_openai", "language_modeling", 0, original, bad))
    bad2 = {"context": "He walked home. She stood by the", "continuation": "door"}
    assert any("final sentence fragment" in i.reason for i in
               validation.validate_pair("lambada_openai", "language_modeling", 0, original, bad2))
