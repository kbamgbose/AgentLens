"""Host-side Docker bridge and a tiny JSON worker running inside the container."""

import json
import subprocess
import sys
from contextlib import suppress
from functools import partial
from pathlib import Path
from uuid import uuid4

from agentlens import tools

TOOL_NAMES = ["read_file", "list_files", "search_code", "run_command",
              "apply_patch", "run_tests", "git_diff"]


def docker(argv: list[str], stdin: str | None = None) -> str:
    result = subprocess.run(
        ["docker", *argv], input=stdin, capture_output=True, text=True, timeout=90,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Docker command failed: {result.stderr.strip()}")
    return result.stdout


class DockerTools:
    """One disposable container per run. No host mounts or forwarded environment."""

    def __init__(self) -> None:
        self.name = f"agentlens-{uuid4().hex}"

    def __enter__(self):
        try:
            docker([
                "run", "--detach", "--name", self.name, "--network", "none",
                "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges=true",
                "--memory", "512m", "--cpus", "1", "--pids-limit", "64",
                "--tmpfs", "/repo:rw,size=32m,uid=10001,gid=10001",
                "--tmpfs", "/tmp:rw,size=64m,mode=1777",
                "agentlens:learning", "python", "-c", "import time; time.sleep(1800)",
            ])
            docker(["exec", "--workdir", "/repo", self.name,
                    "python", "-m", "agentlens.docker_tools", "setup"])
        except Exception:
            with suppress(RuntimeError):
                self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc):
        # Only remove the uniquely named container created for this run.
        docker(["rm", "--force", self.name])

    def call(self, name: str, **arguments):
        if name not in TOOL_NAMES:
            raise ValueError(f"Unknown tool: {name}")
        reply = docker(
            ["exec", "--interactive", "--workdir", "/repo", self.name,
             "python", "-m", "agentlens.docker_tools", "worker"],
            json.dumps({"name": name, "arguments": arguments}),
        )
        result = json.loads(reply)
        if not result["ok"]:
            raise RuntimeError(result["error"])
        return result["value"]

    def registry(self) -> dict:
        return {name: partial(self.call, name) for name in TOOL_NAMES}


def setup_repo() -> None:
    """Fixture setup, not a model action or the first bug-solving task."""
    Path("greeting.txt").write_text("Hello, world!\n", encoding="utf-8")
    Path("arithmetic.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    Path("test_arithmetic.py").write_text(
        "from arithmetic import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    for argv in [
        ["git", "init", "--quiet"], ["git", "add", "."],
        ["git", "-c", "user.name=AgentLens Demo", "-c", "user.email=demo@example.invalid",
         "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "Demo baseline"],
    ]:
        result = tools.run_command(argv)
        if result["exit_code"]:
            raise RuntimeError(result["stderr"])


def worker() -> None:
    request = json.load(sys.stdin)
    try:
        if request["name"] not in TOOL_NAMES:
            raise ValueError("Unknown tool")
        value = getattr(tools, request["name"])(**request["arguments"])
        result = {"ok": True, "value": value}
    except Exception as error:  # noqa: BLE001 -- failures cross the JSON boundary as data
        result = {"ok": False, "error": f"{type(error).__name__}: {error}"}
    print(json.dumps(result))


if __name__ == "__main__":
    if sys.argv[1] == "setup":
        setup_repo()
    elif sys.argv[1] == "worker":
        worker()
