"""Small repository-understanding questions with transparent keyword graders."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RepositoryEval:
    name: str
    question: str
    required_facts: tuple[str, ...]
    forbidden_claims: tuple[str, ...] = ()


REPOSITORY_EVALS = (
    RepositoryEval(
        "package_metadata",
        "What is this package called, which Python versions does it require, and "
        "what CLI function does the agentlens command call?",
        ("agentlens", ">=3.12", "agentlens:main"),
    ),
    RepositoryEval(
        "agent_loop",
        "Describe how run_agent handles a tool call and returns its result to the model.",
        ("model", "tool", "result", "messages"),
    ),
    RepositoryEval(
        "patch_safety",
        "What conditions make apply_patch reject a replacement before it writes? "
        "When a tool raises one of these errors, what does the agent loop do with it?",
        ("empty", "not found", "more than once", "feedback", "loop"),
        ("halt execution entirely", "halt the agent", "ends the run"),
    ),
    RepositoryEval(
        "trace_event",
        "What identifies and orders a trace event, and can changing event.data alter it?",
        ("run_id", "sequence", "timestamp", "fresh", "cannot"),
    ),
    RepositoryEval(
        "capability_scope",
        "How does run_agent check a capability, and what important authorization "
        "limitations does this first version have?",
        ("action", "resource", "exact", "path", "branch", "unrestricted"),
    ),
)


def grade_repository_answer(evaluation: RepositoryEval, answer: str) -> dict:
    """Score required facts and flag known false claims for this question."""
    normalized = answer.casefold()
    found = tuple(fact for fact in evaluation.required_facts if fact.casefold() in normalized)
    missing = tuple(fact for fact in evaluation.required_facts if fact not in found)
    contradictions = tuple(
        claim for claim in evaluation.forbidden_claims if claim.casefold() in normalized
    )
    score = len(found) / len(evaluation.required_facts)
    if contradictions:
        score = 0.0
    return {
        "passed": not missing and not contradictions,
        "score": score,
        "found": found,
        "missing": missing,
        "contradictions": contradictions,
    }
