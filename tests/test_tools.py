import subprocess
import sys

import pytest

from agentlens.tools import apply_patch, git_diff, run_command, run_tests, search_code


def test_diff_includes_staged_and_unstaged_changes(tmp_path):
    from agentlens import prepare_demo_repo

    prepare_demo_repo(str(tmp_path))
    assert git_diff(str(tmp_path)) == {"stdout": "", "stderr": "", "exit_code": 0}
    (tmp_path / "greeting.txt").write_text("Staged greeting\n", encoding="utf-8")
    assert run_command(["git", "add", "greeting.txt"], cwd=str(tmp_path))["exit_code"] == 0
    assert "+Staged greeting" in git_diff(str(tmp_path))["stdout"]
    (tmp_path / "greeting.txt").write_text("Staged greeting\nExtra line\n", encoding="utf-8")
    (tmp_path / "untracked.txt").write_text("not included", encoding="utf-8")
    result = git_diff(str(tmp_path))
    assert result["exit_code"] == 0
    assert "-Hello, world!" in result["stdout"]
    assert "+Staged greeting\n+Extra line" in result["stdout"]
    assert "untracked.txt" not in result["stdout"]


def test_diff_reports_non_repository_and_missing_head(tmp_path):
    assert git_diff(str(tmp_path))["exit_code"] != 0
    assert run_command(["git", "init", "--quiet"], cwd=str(tmp_path))["exit_code"] == 0
    result = git_diff(str(tmp_path))
    assert result["exit_code"] != 0
    assert result["stderr"]


def test_scripted_diff_inspects_actual_edit(tmp_path):
    from functools import partial

    from agentlens import prepare_demo_repo, scripted_diff_model
    from agentlens.loop import run_agent

    prepare_demo_repo(str(tmp_path))
    answer, history = run_agent(
        "Edit and inspect", partial(scripted_diff_model, cwd=str(tmp_path)),
        {"apply_patch": apply_patch, "git_diff": git_diff},
    )
    assert (tmp_path / "greeting.txt").read_text() == "Hello, agent!\n"
    assert "-Hello, world!" in answer and "+Hello, agent!" in answer
    assert history[-2]["name"] == "git_diff"


@pytest.mark.parametrize("expression,code,summary", [
    ("2 + 3 == 5", 0, "1 passed"),
    ("2 + 3 == 6", 1, "1 failed"),
    (None, 5, "no tests ran"),
])
def test_run_tests_reports_real_suite_outcome(tmp_path, expression, code, summary):
    from functools import partial

    from agentlens import scripted_test_model
    from agentlens.loop import run_agent

    if expression is not None:
        (tmp_path / "test_example.py").write_text(
            f"def test_example():\n    assert {expression}\n", encoding="utf-8"
        )
    answer, history = run_agent(
        "Run tests", partial(scripted_test_model, cwd=str(tmp_path)),
        {"run_tests": run_tests},
    )
    result = history[2]["content"]
    assert result["ok"] is True  # The tool ran, even when pytest reports failure.
    assert result["value"]["exit_code"] == code
    assert summary in result["value"]["stdout"]
    assert ("Tests passed" in answer) == (code == 0)


def test_patch_preserves_surrounding_bytes(tmp_path):
    file = tmp_path / "greeting.txt"
    file.write_bytes(b"before\r\nHello, world!\r\nafter\r\n")
    result = apply_patch(str(file), "Hello, world!", "Hello, agent!")
    assert result == {"path": str(file), "changed": True}
    assert file.read_bytes() == b"before\r\nHello, agent!\r\nafter\r\n"


@pytest.mark.parametrize("original,old", [("hello", ""), ("hello", "missing"),
                                         ("hello hello", "hello"), ("aaa", "aa")])
def test_invalid_patch_leaves_file_unchanged(tmp_path, original, old):
    file = tmp_path / "example.txt"
    file.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError):
        apply_patch(str(file), old, "replacement")
    assert file.read_text(encoding="utf-8") == original


def test_scripted_patch_changes_actual_file(tmp_path):
    from functools import partial

    from agentlens import scripted_patch_model
    from agentlens.loop import run_agent
    from agentlens.tools import read_file

    file = tmp_path / "greeting.txt"
    file.write_text("Hello, world!\n", encoding="utf-8")
    answer, history = run_agent(
        "Edit the greeting", partial(scripted_patch_model, path=str(file)),
        {"read_file": read_file, "apply_patch": apply_patch},
    )
    assert file.read_text(encoding="utf-8") == "Hello, agent!\n"
    assert "Hello, agent!" in answer
    assert [m["name"] for m in history if m["role"] == "tool"] == [
        "read_file", "apply_patch", "read_file"
    ]


def test_search_returns_nested_matches_with_line_numbers(tmp_path):
    nested = tmp_path / "package"
    nested.mkdir()
    source = nested / "example.py"
    source.write_text("# Example\ndef example():\n    return 'example'\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("example", encoding="utf-8")

    assert search_code("example", str(tmp_path)) == [
        {"path": str(source), "line": 2, "text": "def example():"},
        {"path": str(source), "line": 3, "text": "    return 'example'"},
    ]
    assert search_code("missing", str(tmp_path)) == []


def test_search_rejects_invalid_requests(tmp_path):
    with pytest.raises(NotADirectoryError):
        search_code("example", str(tmp_path / "missing"))
    with pytest.raises(ValueError, match="empty"):
        search_code("", str(tmp_path))


def test_command_captures_output_and_uses_working_directory(tmp_path):
    result = run_command(
        [sys.executable, "-c", "from pathlib import Path; print(Path.cwd())"],
        cwd=str(tmp_path),
    )
    assert result == {"stdout": f"{tmp_path.resolve()}\n", "stderr": "", "exit_code": 0}


def test_command_returns_nonzero_exit_and_stderr():
    result = run_command(
        [sys.executable, "-c", "import sys; print('failed', file=sys.stderr); sys.exit(2)"]
    )
    assert result == {"stdout": "", "stderr": "failed\n", "exit_code": 2}


def test_command_timeout():
    with pytest.raises(subprocess.TimeoutExpired):
        run_command([sys.executable, "-c", "import time; time.sleep(60)"], timeout=0.1)


def test_command_does_not_interpret_shell_syntax():
    result = run_command([sys.executable, "-c", "import sys; print(sys.argv[1])", "$(whoami)"])
    assert result["stdout"] == "$(whoami)\n"
