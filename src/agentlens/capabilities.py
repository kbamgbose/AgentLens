"""A tiny explicit permission check for a run's tool actions and resource."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    """Permission for a named agent to use actions on one run resource."""

    agent: str
    resource: str
    actions: frozenset[str]

    def allows(self, action: str, resource: str) -> bool:
        return resource == self.resource and action in self.actions


TOOL_ACTIONS = {
    "read_file": "read", "list_files": "read", "search_code": "read",
    "git_diff": "read", "run_command": "execute", "run_tests": "execute",
    "apply_patch": "write", "add": "execute",
}
