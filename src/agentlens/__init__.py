"""A small, executable demonstration of the core loop."""

import argparse
import json
import sys
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory

from agentlens.loop import run_agent
from agentlens.models import OpenRouterModel
from agentlens.tools import (
    apply_patch,
    git_diff,
    list_files,
    read_file,
    run_command,
    run_tests,
    search_code,
)
from agentlens.tracing import Trace


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


def scripted_command_model(messages: list[dict]) -> dict:
    """Request Python's version, then report the actual process result."""
    if messages[-1]["role"] == "user":
        return {
            "type": "tool_call",
            "name": "run_command",
            "arguments": {"argv": [sys.executable, "--version"]},
        }

    result = messages[-1]["content"]
    if not result["ok"]:
        return {"type": "final", "text": f"The tool failed: {result['error']}"}
    process = result["value"]
    return {
        "type": "final",
        "text": (
            f"Exit code: {process['exit_code']}\n"
            f"stdout: {process['stdout']}\nstderr: {process['stderr']}"
        ),
    }


def scripted_patch_model(messages: list[dict], path: str) -> dict:
    """Read, edit, and read back a disposable file using a fixed policy."""
    if messages[-1]["role"] == "user":
        return {"type": "tool_call", "name": "read_file", "arguments": {"path": path}}
    result = messages[-1]["content"]
    if not result["ok"]:
        return {"type": "final", "text": f"The tool failed: {result['error']}"}
    if messages[-1]["name"] == "apply_patch":
        return {"type": "tool_call", "name": "read_file", "arguments": {"path": path}}
    already_edited = any(
        message["role"] == "tool" and message["name"] == "apply_patch"
        for message in messages
    )
    if already_edited:
        return {"type": "final", "text": f"File after editing:\n{result['value']}"}
    return {
        "type": "tool_call",
        "name": "apply_patch",
        "arguments": {"path": path, "old_text": "Hello, world!", "new_text": "Hello, agent!"},
    }


def scripted_test_model(messages: list[dict], cwd: str) -> dict:
    """Request pytest, then distinguish a passing suite from other outcomes."""
    if messages[-1]["role"] == "user":
        return {"type": "tool_call", "name": "run_tests", "arguments": {"cwd": cwd}}
    result = messages[-1]["content"]
    if not result["ok"]:
        return {"type": "final", "text": f"The tool failed: {result['error']}"}
    process = result["value"]
    status = "Tests passed" if process["exit_code"] == 0 else "Test run did not pass"
    return {
        "type": "final",
        "text": (
            f"{status} (exit code {process['exit_code']})\n"
            f"{process['stdout']}\n{process['stderr']}"
        ),
    }


def prepare_demo_repo(directory: str) -> None:
    """Create a baseline commit only in the disposable demo directory."""
    Path(directory, "greeting.txt").write_text("Hello, world!\n", encoding="utf-8")
    commands = [
        ["git", "init", "--quiet"],
        ["git", "add", "greeting.txt"],
        ["git", "-c", "user.name=AgentLens Demo", "-c", "user.email=demo@example.invalid",
         "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
         "commit", "--quiet", "-m", "Demo baseline"],
    ]
    for command in commands:
        result = run_command(command, cwd=directory)
        if result["exit_code"] != 0:
            raise RuntimeError(f"Demo setup failed: {result['stderr']}")


def scripted_diff_model(messages: list[dict], cwd: str) -> dict:
    """Make one known edit, then inspect Git's actual diff."""
    if messages[-1]["role"] == "user":
        return {
            "type": "tool_call", "name": "apply_patch",
            "arguments": {
                "path": str(Path(cwd) / "greeting.txt"),
                "old_text": "Hello, world!", "new_text": "Hello, agent!",
            },
        }
    result = messages[-1]["content"]
    if not result["ok"]:
        return {"type": "final", "text": f"The tool failed: {result['error']}"}
    if messages[-1]["name"] == "apply_patch":
        return {"type": "tool_call", "name": "git_diff", "arguments": {"cwd": cwd}}
    process = result["value"]
    if process["exit_code"] != 0:
        return {"type": "final", "text": f"Git failed: {process['stderr']}"}
    return {"type": "final", "text": process["stdout"] or "No tracked changes relative to HEAD."}


def run_demo(task, model) -> None:
    trace = Trace()
    print(f"Trace file: {trace.path}")
    answer, messages = run_agent(
        task,
        model,
        {
            "list_files": list_files,
            "read_file": read_file,
            "search_code": search_code,
            "run_command": run_command,
            "apply_patch": apply_patch,
            "run_tests": run_tests,
            "git_diff": git_diff,
        },
        trace=trace,
    )
    print(json.dumps(messages, indent=2))
    print(f"\nFinal answer: {answer}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an AgentLens learning demonstration")
    parser.add_argument("--demo", choices=["command", "patch", "tests", "diff", "live", "live-docker"], default="command")
    args = parser.parse_args()
    if args.demo == "live-docker":
        from agentlens.docker_tools import DockerTools
        from agentlens.tool_schemas import DOCKER_SCHEMAS

        trace = Trace()
        print(f"Trace file: {trace.path}")
        try:
            model = OpenRouterModel(trace, tool_schemas=DOCKER_SCHEMAS)
        except ValueError as error:
            parser.error(str(error))
        with DockerTools() as environment:
            trace.record("environment_ready", container=environment.name, cwd="/repo")
            answer, _ = run_agent(
                "You work in /repo inside a disposable Linux container. List the files, "
                "read greeting.txt, and replace 'Hello, world!' with 'Hello, agent!'. "
                "Find the add function using search_code. Use run_command to check Python's "
                "version, run the tests, and inspect the Git diff. Report the actual results. "
                "Request one tool at a time.",
                model, environment.registry(), max_turns=16, trace=trace,
            )
            # Inspect outcomes independently of the model's final claim.
            checks = {
                "greeting": environment.call("read_file", path="greeting.txt"),
                "tests": environment.call("run_tests", cwd="."),
                "diff": environment.call("git_diff", cwd="."),
            }
            trace.record("verification", **checks)
            print(f"\nFinal answer: {answer}")
            print("Independent verification:", json.dumps(checks, indent=2))
        trace.record("environment_removed", container=environment.name)
    elif args.demo == "live":
        trace = Trace()
        print(f"Trace file: {trace.path}")
        try:
            model = OpenRouterModel(trace)
        except ValueError as error:
            parser.error(str(error))

        def read_project_file(path: str) -> str:
            # An explicit restriction for this exercise, enforced in code too.
            if path != "pyproject.toml":
                raise PermissionError("This demo only permits reading pyproject.toml")
            return read_file(path)

        answer, _ = run_agent(
            "Read pyproject.toml. What is the package name, required Python version, "
            "and CLI entry point? Quote the relevant configuration lines.",
            model, {"read_file": read_project_file}, max_turns=4, trace=trace,
        )
        print(f"\nFinal answer: {answer}")
    elif args.demo == "command":
        run_demo("Show the current Python interpreter's version", scripted_command_model)
    elif args.demo == "diff":
        with TemporaryDirectory(prefix="agentlens-diff-") as directory:
            prepare_demo_repo(directory)
            run_demo(
                f"Replace 'Hello, world!' with 'Hello, agent!' in {directory}/greeting.txt "
                "and inspect the diff",
                partial(scripted_diff_model, cwd=directory),
            )
    elif args.demo == "tests":
        with TemporaryDirectory(prefix="agentlens-tests-") as directory:
            Path(directory, "test_example.py").write_text(
                "def test_addition():\n    assert 2 + 3 == 5\n", encoding="utf-8"
            )
            run_demo(
                f"Run the tests in {directory} and report the result",
                partial(scripted_test_model, cwd=directory),
            )
    else:
        # This is environment setup, not a model action. Each run gets a fresh file.
        with TemporaryDirectory(prefix="agentlens-patch-") as directory:
            path = str(Path(directory) / "greeting.txt")
            Path(path).write_text("Hello, world!\n", encoding="utf-8")
            run_demo(
                f"Read {path}, replace 'Hello, world!' with 'Hello, agent!', then read it back",
                partial(scripted_patch_model, path=path),
            )
