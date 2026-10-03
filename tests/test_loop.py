import pytest

from agentlens import add, scripted_model
from agentlens.capabilities import Capability
from agentlens.loop import run_agent


def test_tool_result_reaches_next_model_turn():
    answer, history = run_agent("What is 2 + 3?", scripted_model, {"add": add})
    assert answer == "2 + 3 = 5"
    assert [message["role"] for message in history] == [
        "user", "assistant", "tool", "assistant"
    ]
    assert history[2]["content"] == {"ok": True, "value": 5}


def test_tool_failure_is_feedback():
    answer, history = run_agent("What is 2 + 3?", scripted_model, {})
    assert history[2]["content"]["ok"] is False
    assert "KeyError" in answer


def test_turn_limit_stops_repeated_requests():
    calls = []

    def repeating_model(messages):
        calls.append(len(messages))
        return {"type": "tool_call", "name": "add", "arguments": {"a": 1, "b": 1}}

    with pytest.raises(RuntimeError, match="exhausted"):
        run_agent("Keep adding", repeating_model, {"add": add}, max_turns=3)
    assert calls == [1, 3, 5]


def test_capability_denies_tool_action_before_execution():
    executed = []
    def model(messages):
        if messages[-1]["role"] == "user":
            return {"type": "tool_call", "name": "apply_patch", "arguments": {}}
        return {"type": "final", "text": messages[-1]["content"]["error"]}

    capability = Capability("reader", "repo/project-x", frozenset({"read"}))
    answer, history = run_agent(
        "Edit", model, {"apply_patch": lambda: executed.append(True)}, max_turns=2,
        capability=capability, resource="repo/project-x",
    )
    assert not executed
    assert history[2]["content"]["ok"] is False
    assert "does not permit write" in answer


def test_capability_is_scoped_to_resource():
    capability = Capability("reader", "repo/project-x", frozenset({"read"}))
    assert capability.allows("read", "repo/project-x")
    assert not capability.allows("read", "repo/other")
