"""A small, executable demonstration of the core loop."""

import json

from agentlens.loop import run_agent
from agentlens.tools import list_files, read_file, search_code


def add(a: int, b: int) -> int:
    return a + b


def scripted_model(messages: list[dict]) -> dict:
    """A test double, not an LLM: only handles this demonstration task."""
    if messages[-1]["role"] == "user":
        return {"type": "tool_call", "name": "add", "arguments": {"a": 2, "b": 3}}

    result = messages[-1]["content"]
    if not result["ok"]:
        return {"type": "final", "text": f"The tool failed: {result['error']}"}
    return {"type": "final", "text": f"2 + 3 = {result['value']}"}


def scripted_file_model(messages: list[dict]) -> dict:
    """List a directory, read its first file, then echo its contents.

    This is still a hardcoded policy, not an LLM interpreting the task.
    """
    if messages[-1]["role"] == "user":
        return {
            "type": "tool_call",
            "name": "list_files",
            "arguments": {"path": "src/agentlens"},
        }

    result = messages[-1]["content"]
    if not result["ok"]:
        return {"type": "final", "text": f"The tool failed: {result['error']}"}
    if messages[-1]["name"] == "list_files":
        files = result["value"]
        if not files:
            return {"type": "final", "text": "The directory contains no files."}
        return {
            "type": "tool_call",
            "name": "read_file",
            "arguments": {"path": files[0]},
        }
    return {"type": "final", "text": f"File contents:\n{result['value']}"}


def scripted_search_model(messages: list[dict]) -> dict:
    """A fixed search demonstration; still not an LLM interpreting the task."""
    if messages[-1]["role"] == "user":
        return {
            "type": "tool_call",
            "name": "search_code",
            "arguments": {"query": "def run_agent(", "path": "src/agentlens"},
        }

    result = messages[-1]["content"]
    if not result["ok"]:
        return {"type": "final", "text": f"The tool failed: {result['error']}"}
    matches = result["value"]
    if not matches:
        return {"type": "final", "text": "No matching lines found."}
    locations = "\n".join(
        f"{match['path']}:{match['line']}: {match['text']}" for match in matches
    )
    return {"type": "final", "text": f"Matching lines:\n{locations}"}


def main() -> None:
    answer, messages = run_agent(
        "Find lines containing 'def run_agent(' under src/agentlens",
        scripted_search_model,
        {"list_files": list_files, "read_file": read_file, "search_code": search_code},
    )
    print(json.dumps(messages, indent=2))
    print(f"\nFinal answer: {answer}")
