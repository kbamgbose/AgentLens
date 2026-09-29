"""Executable functions that the harness can dispatch to."""

from pathlib import Path


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
