from agentlens.evals import REPOSITORY_EVALS, grade_repository_answer


def test_repository_eval_set_has_five_distinct_questions():
    assert len(REPOSITORY_EVALS) == 5
    assert len({evaluation.name for evaluation in REPOSITORY_EVALS}) == 5


def test_grader_reports_full_and_partial_credit():
    evaluation = REPOSITORY_EVALS[0]
    assert grade_repository_answer(evaluation, "agentlens requires >=3.12; agentlens:main") == {
        "passed": True,
        "score": 1.0,
        "found": evaluation.required_facts,
        "missing": (),
        "contradictions": (),
    }
    partial = grade_repository_answer(evaluation, "agentlens needs >=3.12")
    assert partial["passed"] is False
    assert partial["score"] == 2 / 3
    assert partial["missing"] == ("agentlens:main",)


def test_grader_ignores_case():
    evaluation = REPOSITORY_EVALS[0]
    assert grade_repository_answer(
        evaluation, "AGENTLENS >=3.12 AGENTLENS:MAIN"
    )["passed"]


def test_patch_grader_rejects_correct_conditions_with_false_error_handling():
    evaluation = next(item for item in REPOSITORY_EVALS if item.name == "patch_safety")
    answer = (
        "Empty old_text, text not found, or more than once are rejected. "
        "Errors halt execution entirely."
    )
    grade = grade_repository_answer(evaluation, answer)
    assert grade["passed"] is False
    assert grade["score"] == 0.0
    assert "feedback" in grade["missing"]
    assert grade["contradictions"] == ("halt execution entirely",)


def test_patch_grader_accepts_errors_returned_as_feedback_to_loop():
    evaluation = next(item for item in REPOSITORY_EVALS if item.name == "patch_safety")
    answer = (
        "Empty old_text, text not found, or more than once are rejected before writes. "
        "The loop catches these errors and sends them back as feedback."
    )
    assert grade_repository_answer(evaluation, answer)["passed"]
