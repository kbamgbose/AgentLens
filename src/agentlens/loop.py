"""The harness: model -> tool -> feedback -> model, until a final answer."""

from collections.abc import Callable
from typing import Any


def run_agent(
    task: str,
    model: Callable[[list[dict]], dict],
    tools: dict[str, Callable[..., Any]],
    max_turns: int = 10,
) -> tuple[str, list[dict]]:
    """Return the final answer and history; raise if the turn budget runs out.

    Our tiny model contract has two response shapes:
      {"type": "tool_call", "name": "...", "arguments": {...}}
      {"type": "final", "text": "..."}
    A real model adapter can translate its provider's responses into these.
    """
    messages = [{"role": "user", "content": task}]

    for _ in range(max_turns):
        # The model chooses what to do. It does not execute the tool.
        response = model(messages)
        messages.append({"role": "assistant", "content": response})

        if response["type"] == "final":
            return response["text"], messages

        if response["type"] != "tool_call":
            raise ValueError(f"Unknown response type: {response['type']}")

        # The harness dispatches the request to an executable function.
        name = response["name"]
        try:
            result = {"ok": True, "value": tools[name](**response["arguments"])}
        except Exception as error:  # noqa: BLE001 -- tool failures become model feedback
            # Failed actions are feedback too: the model can try again.
            result = {"ok": False, "error": f"{type(error).__name__}: {error}"}

        messages.append({"role": "tool", "name": name, "content": result})

    raise RuntimeError(f"Agent exhausted its {max_turns} model turns")
