"""Translate our tiny loop's messages to and from OpenRouter's HTTP API."""

import json
import os
import sys
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agentlens.tracing import Trace

READ_FILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read the project's pyproject.toml to answer questions about its configuration.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "enum": ["pyproject.toml"]}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}


def api_error_details(error: HTTPError) -> dict:
    """Extract only a numeric provider code; never log arbitrary error bodies."""
    code = None
    try:
        body = json.loads(error.read(8192))
        candidate = str(body["error"]["code"])
        if candidate.isascii() and candidate.isdigit() and len(candidate) <= 6:
            code = candidate
    except (ValueError, KeyError, TypeError):
        pass
    finally:
        error.close()
    explanations = {
        "400": "Invalid request; check the model parameters.",
        "401": "Invalid API key; check OPENROUTER_API_KEY.",
        "402": "Account has insufficient credits; check OpenRouter credits.",
        "403": "Request forbidden; check account permissions.",
        "408": "Provider request timed out.",
        "429": "Request rate limit reached; wait before retrying.",
        "502": "Provider temporarily unavailable or returned an invalid response.",
        "503": "No model provider is currently available for this request.",
    }
    return {
        "http_status": error.code,
        "provider_code": code,
        "explanation": explanations.get(str(error.code), "Check OpenRouter's error reference and account console."),
    }


def api_messages(history: list[dict]) -> list[dict]:
    """Preserve the provider's call ID so each result answers the correct call."""
    messages = [{
        "role": "system",
        "content": "You are a repository assistant. Read the file before answering. "
                   "Request at most one tool per response. Base your answer on tool results.",
    }]
    pending_id = None
    for message in history:
        if message["role"] == "user":
            messages.append(message)
        elif message["role"] == "assistant":
            response = message["content"]
            messages.append(response["provider_message"])
            if response["type"] == "tool_call":
                pending_id = response["call_id"]
        elif message["role"] == "tool":
            if pending_id is None:
                raise ValueError("Tool result has no matching model request")
            messages.append({
                "role": "tool", "tool_call_id": pending_id,
                "content": json.dumps(message["content"]),
            })
            pending_id = None
    return messages


def retry_delay(header: str | None, attempt: int) -> float:
    """Honor Retry-After when supplied; otherwise wait 10, then 20 seconds."""
    fallback = 10 * attempt
    if header is None:
        return fallback
    if header.isascii() and header.isdigit():
        return max(fallback, int(header))
    try:
        date = parsedate_to_datetime(header)
        return max(fallback, (date - datetime.now(UTC)).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return fallback


def parse_response(body: dict) -> dict:
    """Adapt one complete response; never silently drop additional tool calls."""
    choice = body["choices"][0]
    message = choice["message"]
    calls = message.get("tool_calls") or []
    if choice["finish_reason"] not in {"stop", "tool_calls"}:
        raise ValueError(f"Model response did not finish normally: {choice['finish_reason']}")
    if calls:
        if len(calls) != 1:
            raise ValueError("This learning loop supports one tool call per model turn")
        call = calls[0]
        arguments = call["function"]["arguments"]
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be a JSON object")
        return {
            "type": "tool_call", "name": call["function"]["name"],
            "arguments": arguments, "call_id": call["id"], "provider_message": message,
        }
    if choice["finish_reason"] != "stop" or not isinstance(message.get("content"), str):
        raise ValueError("Expected a final text answer")
    return {"type": "final", "text": message["content"], "provider_message": message}


class OpenRouterModel:
    """Callable like scripted_model; only the decision source changes."""

    def __init__(self, trace: Trace, tool_schemas: list[dict] | None = None) -> None:
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not self.api_key:
            raise ValueError("Set OPENROUTER_API_KEY in your terminal before running --demo live")
        self.trace = trace
        self.tool_schemas = [READ_FILE_SCHEMA] if tool_schemas is None else tool_schemas

    def __call__(self, messages: list[dict]) -> dict:
        payload = {
            "model": "qwen/qwen3.7-flash",
            "messages": api_messages(messages),
            "tools": self.tool_schemas,
            "tool_choice": "auto",
            "stream": False,
            "max_tokens": 4096,
        }
        # Log the body, never the Authorization header or API key.
        request = Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        for attempt in range(1, 4):
            self.trace.record("api_request", attempt=attempt, payload=payload)
            print(f"Contacting Qwen3.7 Flash (attempt {attempt}/3; 60s socket timeout)...",
                  file=sys.stderr)
            try:
                with urlopen(request, timeout=60) as response:
                    body = json.load(response)
            except HTTPError as error:
                delay = retry_delay(error.headers.get("Retry-After") if error.headers else None, attempt)
                details = api_error_details(error)
                self.trace.record("api_error", attempt=attempt, **details)
                transient = details["http_status"] in {408, 429, 502, 503}
                if transient and attempt < 3 and delay <= 60:
                    self.trace.record("api_retry", attempt=attempt, delay_seconds=delay,
                                      provider_code=details["provider_code"])
                    print(f"OpenRouter {details['provider_code']}: retrying model request in "
                          f"{delay:g}s (retry {attempt}/2).", file=sys.stderr)
                    time.sleep(delay)
                    continue
                raise RuntimeError(
                    f"OpenRouter returned HTTP {details['http_status']} "
                    f"(provider code {details['provider_code'] or 'unavailable'}) "
                    f"after {attempt} attempt(s). {details['explanation']}"
                ) from None
            except (TimeoutError, URLError) as error:
                # urllib can wrap a connection timeout in URLError. Do not retry
                # unrelated failures such as certificate verification errors.
                if isinstance(error, URLError) and not isinstance(error.reason, TimeoutError):
                    raise
                self.trace.record("api_error", attempt=attempt, error_type="timeout")
                if attempt < 3:
                    delay = 10 * attempt
                    self.trace.record("api_retry", attempt=attempt, delay_seconds=delay,
                                      reason="timeout")
                    print(f"OpenRouter request timed out; retrying in {delay}s "
                          f"(retry {attempt}/2).", file=sys.stderr)
                    time.sleep(delay)
                    continue
                raise RuntimeError(
                    "OpenRouter request timed out after 3 attempts. No response was received; "
                    "try again later. Completed tool actions were not replayed."
                ) from None
            if "error" in body:
                # HTTP 200 can still carry a provider failure. Do not log raw error text.
                self.trace.record("api_error", attempt=attempt, error_type="response_error")
                raise RuntimeError("OpenRouter returned an error inside its response; no tool was executed.")
            self.trace.record("api_response", attempt=attempt, response=body)
            return parse_response(body)
