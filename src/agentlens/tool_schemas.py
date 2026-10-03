"""Tool descriptions are data sent to the model, not executable functions."""


def schema(name, description, properties, required):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties,
                       "required": required, "additionalProperties": False},
    }}


PATH = {"type": "string", "description": "Path inside the container; relative to /repo."}
TEXT = {"type": "string"}
DOCKER_SCHEMAS = [
    schema("read_file", "Read a UTF-8 file.", {"path": PATH}, ["path"]),
    schema("list_files", "List immediate files in a directory, sorted; not recursive.",
           {"path": PATH}, ["path"]),
    schema("search_code", "Find literal case-sensitive text in Python files recursively.",
           {"query": TEXT, "path": PATH}, ["query", "path"]),
    schema("run_command", "Execute an argument list without a shell; inspect exit_code.",
           {"argv": {"type": "array", "items": TEXT}, "cwd": PATH}, ["argv", "cwd"]),
    schema("apply_patch", "Replace exactly one occurrence of old_text in an existing file.",
           {"path": PATH, "old_text": TEXT, "new_text": TEXT}, ["path", "old_text", "new_text"]),
    schema("run_tests", "Run pytest; exit code 0 passes, 5 means no tests, other codes fail.",
           {"cwd": PATH}, ["cwd"]),
    schema("git_diff", "Show tracked changes against HEAD, staged and unstaged; excludes untracked files.",
           {"cwd": PATH}, ["cwd"]),
]

REPOSITORY_READ_SCHEMAS = [
    schema("list_files", "List sorted files immediately inside a repository directory.",
           {"path": {"type": "string", "description": "Repository-relative directory."}},
           ["path"]),
    schema("read_file", "Read a UTF-8 repository file.",
           {"path": {"type": "string", "description": "Repository-relative file path."}},
           ["path"]),
    schema("search_code", "Search Python files recursively for literal text.",
           {"query": TEXT, "path": {"type": "string", "description": "Repository-relative directory."}},
           ["query", "path"]),
]
