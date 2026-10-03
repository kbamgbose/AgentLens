import io
import json
from urllib.error import HTTPError, URLError

import pytest

from agentlens.loop import run_agent
from agentlens.models import OpenRouterModel, parse_response
from agentlens.tracing import Trace


def completion(message, finish="stop"):
    return {"choices": [{"message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 5}}


def tool_message():
    return {"role": "assistant", "content": None, "tool_calls": [{
        "id": "call_123", "type": "function",
        "function": {"name": "read_file", "arguments": '{"path": "pyproject.toml"}'},
    }]}


def test_provider_round_trip_through_real_loop(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret")
    raw_call = tool_message()
    replies = iter([completion(raw_call, "tool_calls"),
                    completion({"role": "assistant", "content": "The package is agentlens."})])
    requests = []

    def fake_urlopen(request, timeout):
        assert timeout == 60
        assert request.full_url == "https://openrouter.ai/api/v1/chat/completions"
        assert request.get_header("Authorization") == "Bearer test-secret"
        requests.append(json.loads(request.data))
        return io.BytesIO(json.dumps(next(replies)).encode())

    monkeypatch.setattr("agentlens.models.urlopen", fake_urlopen)
    trace = Trace(str(tmp_path))
    answer, _ = run_agent("Read config", OpenRouterModel(trace),
                          {"read_file": lambda path: 'name = "agentlens"'}, trace=trace)
    assert answer == "The package is agentlens."
    assert requests[0]["model"] == "qwen/qwen3.7-flash"
    assert requests[0]["tools"][0]["function"]["name"] == "read_file"
    assert requests[1]["messages"][-2] == raw_call
    feedback = requests[1]["messages"][-1]
    assert feedback["tool_call_id"] == "call_123"
    assert json.loads(feedback["content"])["value"] == 'name = "agentlens"'
    events = [json.loads(line) for line in trace.path.read_text().splitlines()]
    assert len([e for e in events if e["event"] == "api_response"]) == 2
    assert "test-secret" not in trace.path.read_text()


def test_missing_key(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="Set OPENROUTER_API_KEY"):
        OpenRouterModel(Trace(str(tmp_path)))


def test_incomplete_response_is_not_success():
    with pytest.raises(ValueError, match="did not finish"):
        parse_response(completion({"content": "partial answer"}, "length"))


def test_multiple_calls_are_not_silently_dropped():
    message = tool_message()
    message["tool_calls"] *= 2
    with pytest.raises(ValueError, match="one tool call"):
        parse_response(completion(message, "tool_calls"))


def test_malformed_arguments_are_rejected():
    message = tool_message()
    message["tool_calls"][0]["function"]["arguments"] = "[]"
    with pytest.raises(ValueError, match="JSON object"):
        parse_response(completion(message, "tool_calls"))


def test_http_failure_reaches_trace_without_key(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret")

    def fail(request, timeout):
        raise HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr("agentlens.models.urlopen", fail)
    trace = Trace(str(tmp_path))
    with pytest.raises(RuntimeError, match="HTTP 401"):
        run_agent("Read", OpenRouterModel(trace), {}, trace=trace)
    assert '"model_error"' in trace.path.read_text()
    assert "test-secret" not in trace.path.read_text()


@pytest.mark.parametrize("code,explanation", [
    ("429", "Request rate limit"), ("502", "temporarily unavailable"),
    ("402", "insufficient credits"), ("401", "Invalid API key"),
])
def test_429_preserves_code_without_logging_response_body(monkeypatch, tmp_path, code, explanation):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret")
    monkeypatch.setattr("agentlens.models.time.sleep", lambda seconds: None)

    def fail(request, timeout):
        body = {"error": {"code": code, "message": "may contain test-secret or prompt data"}}
        raise HTTPError(request.full_url, int(code), "Failure", {},
                        io.BytesIO(json.dumps(body).encode()))

    monkeypatch.setattr("agentlens.models.urlopen", fail)
    trace = Trace(str(tmp_path))
    with pytest.raises(RuntimeError, match=explanation):
        run_agent("Read", OpenRouterModel(trace), {}, trace=trace)
    events = [json.loads(line) for line in trace.path.read_text().splitlines()]
    details = next(e["data"] for e in events if e["event"] == "api_error")
    assert details["provider_code"] == code
    assert details["http_status"] == int(code)
    assert "test-secret" not in trace.path.read_text()


def test_non_json_http_error_is_still_reported(monkeypatch, tmp_path):
    monkeypatch.setattr("agentlens.models.time.sleep", lambda seconds: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret")

    def fail(request, timeout):
        raise HTTPError(request.full_url, 429, "Too Many Requests", {}, io.BytesIO(b"<html>busy</html>"))

    monkeypatch.setattr("agentlens.models.urlopen", fail)
    with pytest.raises(RuntimeError, match="provider code unavailable"):
        OpenRouterModel(Trace(str(tmp_path)))([{"role": "user", "content": "Read"}])


def test_retry_recovers_without_replaying_tool(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret")
    sleeps, requests, tool_calls = [], [], []
    monkeypatch.setattr("agentlens.models.time.sleep", sleeps.append)

    def transport(request, timeout):
        requests.append(request.data)
        if len(requests) == 1:
            return io.BytesIO(json.dumps(completion(tool_message(), "tool_calls")).encode())
        if len(requests) == 2:
            raise HTTPError(request.full_url, 429, "Busy", {"Retry-After": "15"},
                            io.BytesIO(b'{"error":{"code":"503"}}'))
        return io.BytesIO(json.dumps(completion({"role": "assistant", "content": "done"})).encode())

    def read(path):
        tool_calls.append(path)
        return "file contents"

    monkeypatch.setattr("agentlens.models.urlopen", transport)
    trace = Trace(str(tmp_path))
    answer, _ = run_agent("Read", OpenRouterModel(trace), {"read_file": read}, trace=trace)
    assert answer == "done"
    assert tool_calls == ["pyproject.toml"]
    assert requests[1] == requests[2]
    assert sleeps == [15]
    assert '"api_retry"' in trace.path.read_text()


@pytest.mark.parametrize("code,header,expected_calls,delays", [
    ("503", {}, 3, [10, 20]),
    ("429", {}, 3, [10, 20]),
    ("402", {}, 1, []),
    ("503", {"Retry-After": "120"}, 1, []),
])
def test_retry_is_bounded_and_skips_account_errors(monkeypatch, tmp_path, code, header, expected_calls, delays):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret")
    calls, sleeps = [], []
    monkeypatch.setattr("agentlens.models.time.sleep", sleeps.append)

    def fail(request, timeout):
        calls.append(request)
        raise HTTPError(request.full_url, int(code), "Busy", header,
                        io.BytesIO(json.dumps({"error": {"code": code}}).encode()))

    monkeypatch.setattr("agentlens.models.urlopen", fail)
    with pytest.raises(RuntimeError, match=code):
        OpenRouterModel(Trace(str(tmp_path)))([{"role": "user", "content": "Read"}])
    assert len(calls) == expected_calls
    assert sleeps == delays


@pytest.mark.parametrize("wrapped", [False, True])
def test_timeout_retries_then_succeeds(monkeypatch, tmp_path, wrapped):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret")
    calls, sleeps = [], []
    monkeypatch.setattr("agentlens.models.time.sleep", sleeps.append)

    def transport(request, timeout):
        calls.append(request.data)
        if len(calls) == 1:
            error = TimeoutError("read operation timed out")
            raise URLError(error) if wrapped else error
        return io.BytesIO(json.dumps(completion({"role": "assistant", "content": "done"})).encode())

    monkeypatch.setattr("agentlens.models.urlopen", transport)
    trace = Trace(str(tmp_path))
    assert OpenRouterModel(trace)([{"role": "user", "content": "Read"}])["text"] == "done"
    assert calls[0] == calls[1]
    assert sleeps == [10]
    assert '"error_type": "timeout"' in trace.path.read_text()


def test_read_timeout_stops_after_three_attempts(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret")
    calls, sleeps = [], []
    monkeypatch.setattr("agentlens.models.time.sleep", sleeps.append)

    class SlowResponse(io.BytesIO):
        def read(self, *args):
            raise TimeoutError("read operation timed out")

    def transport(request, timeout):
        calls.append(request)
        return SlowResponse()

    monkeypatch.setattr("agentlens.models.urlopen", transport)
    with pytest.raises(RuntimeError, match="timed out after 3 attempts"):
        OpenRouterModel(Trace(str(tmp_path)))([{"role": "user", "content": "Read"}])
    assert len(calls) == 3
    assert sleeps == [10, 20]


def test_non_timeout_url_error_is_not_retried(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret")
    calls = []

    def fail(request, timeout):
        calls.append(request)
        raise URLError("certificate verification failed")

    monkeypatch.setattr("agentlens.models.urlopen", fail)
    with pytest.raises(URLError):
        OpenRouterModel(Trace(str(tmp_path)))([{"role": "user", "content": "Read"}])
    assert len(calls) == 1


def test_error_in_success_http_response_is_sanitized(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret")
    body = {"error": {"code": 502, "message": "contains test-secret"}}
    monkeypatch.setattr("agentlens.models.urlopen",
                        lambda request, timeout: io.BytesIO(json.dumps(body).encode()))
    trace = Trace(str(tmp_path))
    with pytest.raises(RuntimeError, match="error inside its response"):
        run_agent("Read", OpenRouterModel(trace), {}, trace=trace)
    assert "test-secret" not in trace.path.read_text()
    assert '"response_error"' in trace.path.read_text()
