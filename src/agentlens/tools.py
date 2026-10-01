"""Executable functions that the harness can dispatch to."""

import subprocess
import sys
from pathlib import Path


def git_diff(cwd: str = ".") -> dict:
    """Show tracked working-tree changes relative to HEAD, including staged edits.

    Requires an existing commit. Untracked files are not included. A clean diff
    has empty stdout; check exit_code first so Git errors aren't mistaken for it.
    Disable external diff helpers and text converters to keep this a plain diff.
    """
    return run_command(
        ["git", "--no-pager", "diff", "--no-ext-diff", "--no-textconv", "--no-color", "HEAD", "--"],
        cwd=cwd,
    )


def run_tests(cwd: str = ".", timeout: float = 30) -> dict:
    """Run pytest discovery in cwd using this agent's Python environment.

    Return stdout, stderr, and pytest's exit code. Zero means pytest passed;
    code 5 means no tests were collected, which must not count as success.
    Tests are executable code, so this tool is not an authorization boundary.
    """
    return run_command([sys.executable, "-m", "pytest", "-q"], cwd=cwd, timeout=timeout)


def apply_patch(path: str, old_text: str, new_text: str) -> dict:
    """Replace one exact text occurrence in an existing UTF-8 file.

    This is a text-replacement patch, not unified-diff syntax. Empty, missing,
    or ambiguous old text is rejected before writing. Include surrounding text
    to disambiguate. Newlines outside the replacement are preserved.
    """
    if not old_text:
        raise ValueError("old_text must not be empty")
    file = Path(path)
    original = file.read_bytes().decode("utf-8")
    start = original.find(old_text)
    if start == -1:
        raise ValueError("old_text was not found; read the current file before editing")
    if original.find(old_text, start + 1) != -1:
        raise ValueError("old_text matches more than once; include more surrounding text")
    updated = original[:start] + new_text + original[start + len(old_text):]
    file.write_bytes(updated.encode("utf-8"))
    return {"path": path, "changed": updated != original}


def run_command(argv: list[str], cwd: str = ".", timeout: float = 10) -> dict:
    """Execute an argument list without a shell and capture the process result.

    Commands run with this process's permissions, not in a sandbox yet.
    A nonzero exit code is returned as data. Launch errors and timeouts propagate
    to the harness. The timeout applies to the direct child, not its descendants.
    """
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise ValueError("argv must be a nonempty list of strings")
    completed = subprocess.run(
        argv,
        cwd=cwd,
        timeout=timeout,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        check=False,
    )
    return {
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "exit_code": completed.returncode,
    }


def list_files(path: str = ".") -> list[str]:
    """Return sorted file paths directly inside a directory, including hidden files.

    Subdirectories are not traversed. Returned paths can be passed to read_file.
    """
    return sorted(str(entry) for entry in Path(path).iterdir() if entry.is_file())


def read_file(path: str) -> str:
    """Read a UTF-8 file; relative paths start at the process's working directory.

    Filesystem errors propagate to the harness, which returns them as feedback.
    This function uses the process's filesystem permissions; it is not a sandbox.
    """
    return Path(path).read_text(encoding="utf-8")


def search_code(query: str, path: str = ".") -> list[dict]:
    """Find case-sensitive literal text in Python files below a directory.

    Return one result per matching line, with 1-based line numbers.
    This first version searches only *.py files, including nested directories.
    Read errors propagate rather than silently producing incomplete results.
    """
    root = Path(path)
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {path}")
    if not query:
        raise ValueError("Search query must not be empty")

    matches = []
    for file in sorted(root.rglob("*.py")):
        if not file.is_file():
            continue
        for line_number, line in enumerate(read_file(str(file)).splitlines(), start=1):
            if query in line:
                matches.append({"path": str(file), "line": line_number, "text": line})
    return matches
