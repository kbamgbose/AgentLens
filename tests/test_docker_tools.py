import json
import os

import pytest

from agentlens.docker_tools import TOOL_NAMES, DockerTools
from agentlens.tool_schemas import DOCKER_SCHEMAS


def test_registry_matches_schemas():
    assert set(DockerTools().registry()) == set(TOOL_NAMES)
    assert {s["function"]["name"] for s in DOCKER_SCHEMAS} == set(TOOL_NAMES)


def test_bridge_transports_json_not_shell(monkeypatch):
    calls = []

    def fake_docker(argv, stdin=None):
        calls.append((argv, stdin))
        return json.dumps({"ok": True, "value": "literal"})

    monkeypatch.setattr("agentlens.docker_tools.docker", fake_docker)
    assert DockerTools().call("read_file", path="$(whoami)") == "literal"
    assert json.loads(calls[0][1])["arguments"]["path"] == "$(whoami)"
    assert "$(whoami)" not in calls[0][0]


@pytest.mark.skipif(os.environ.get("AGENTLENS_DOCKER_TEST") != "1",
                    reason="Opt-in test requires a built image and Docker engine")
def test_all_tools_in_isolated_container(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "host-only-test-key")
    with DockerTools() as env:
        assert "greeting.txt" in env.call("list_files", path=".")
        assert env.call("read_file", path="greeting.txt") == "Hello, world!\n"
        assert env.call("search_code", query="def add", path=".")[0]["path"] == "arithmetic.py"
        result = env.call("run_command", argv=["python", "-c",
            ("import os; print(os.getuid()); print(os.getenv('OPENROUTER_API_KEY')); "
             "print(os.path.exists('/var/run/docker.sock'))")], cwd=".")
        assert result["stdout"] == "10001\nNone\nFalse\n"
        assert env.call("apply_patch", path="greeting.txt", old_text="world", new_text="agent")["changed"]
        assert env.call("run_tests", cwd=".")["exit_code"] == 0
        assert "+Hello, agent!" in env.call("git_diff", cwd=".")["stdout"]
        denied = env.call("run_command", argv=["touch", "/workspace/blocked"], cwd=".")
        assert denied["exit_code"] != 0
