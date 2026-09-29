import pytest

from agentlens.tools import search_code


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
