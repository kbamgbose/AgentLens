import json

import pytest

from agentlens import add, scripted_model
from agentlens.loop import run_agent
from agentlens.tracing import Trace


def read_events(trace):
    return [json.loads(line) for line in trace.path.read_text().splitlines()]


def test_trace_preserves_interactions_and_history_snapshots(tmp_path):
    trace = Trace(str(tmp_path))
    run_agent("What is 2 + 3?", scripted_model, {"add": add}, trace=trace)
    events = read_events(trace)
    assert [e["event"] for e in events] == [
        "run_start", "model_request", "model_response", "tool_request",
        "tool_result", "model_request", "model_response", "run_end",
    ]
    assert [e["sequence"] for e in events] == list(range(1, 9))
    assert all(e["run_id"] == trace.run_id for e in events)
    assert len(events[1]["data"]["messages"]) == 1
    assert len(events[5]["data"]["messages"]) == 3
    assert events[4]["data"]["result"] == {"ok": True, "value": 5}
    assert events[-1]["data"]["answer"] == "2 + 3 = 5"


def test_trace_records_tool_failure_and_turn_limit(tmp_path):
    trace = Trace(str(tmp_path))
    with pytest.raises(RuntimeError, match="exhausted"):
        run_agent("Add", scripted_model, {}, max_turns=1, trace=trace)
    events = read_events(trace)
    assert events[4]["data"]["result"]["ok"] is False
    assert events[-1]["data"]["status"] == "turn_limit"


def test_model_failure_is_recorded_and_reraised(tmp_path):
    def broken_model(messages):
        raise ConnectionError("offline")

    trace = Trace(str(tmp_path))
    with pytest.raises(ConnectionError, match="offline"):
        run_agent("Hello", broken_model, {}, trace=trace)
    events = read_events(trace)
    assert events[-2]["event"] == "model_error"
    assert events[-2]["data"]["error"] == "ConnectionError: offline"
    assert events[-1]["data"]["status"] == "model_error"
