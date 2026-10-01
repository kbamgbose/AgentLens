"""The harness: model -> tool -> feedback -> model, until a final answer."""

from collections.abc import Callable
from typing import Any

from agentlens.tracing import Trace


def run_agent(
    task: str,
    model: Callable[[list[dict]], dict],
    tools: dict[str, Callable[..., Any]],
    max_turns: int = 10,
    trace: Trace | None = None,
) -> tuple[str, list[dict]]:
    """Return the final answer and history; raise if the turn budget runs out.

    Our tiny model contract has two response shapes:
      {"type": "tool_call", "name": "...", "arguments": {...}}
      {"type": "final", "text": "..."}
    A real model adapter can translate its provider's responses into these.
    """
    messages = [{"role": "user", "content": task}]

    def record(event: str, **data) -> None:
        if trace is not None:
            trace.record(event, **data)

    record("run_start", task=task, tools=list(tools), max_turns=max_turns)

    for turn in range(1, max_turns + 1):
        # The model chooses what to do. It does not execute the tool.
        record("model_request", turn=turn, messages=messages)
        try:
            response = model(messages)
        except Exception as error:
            record("model_error", turn=turn, error=f"{type(error).__name__}: {error}")
            record("run_end", status="model_error")
            raise
        record("model_response", turn=turn, response=response)
        messages.append({"role": "assistant", "content": response})

        if response["type"] == "final":
            record("run_end", status="finished", answer=response["text"])
            return response["text"], messages

        if response["type"] != "tool_call":
            record("run_end", status="invalid_response", response=response)
            raise ValueError(f"Unknown response type: {response['type']}")

        # The harness dispatches the request to an executable function.
        name = response["name"]
        record("tool_request", turn=turn, name=name, arguments=response["arguments"])
        try:
            result = {"ok": True, "value": tools[name](**response["arguments"])}
        except Exception as error:  # noqa: BLE001 -- tool failures become model feedback
            # Failed actions are feedback too: the model can try again.
            result = {"ok": False, "error": f"{type(error).__name__}: {error}"}

        record("tool_result", turn=turn, name=name, result=result)
        messages.append({"role": "tool", "name": name, "content": result})

    record("run_end", status="turn_limit")
    raise RuntimeError(f"Agent exhausted its {max_turns} model turns")
