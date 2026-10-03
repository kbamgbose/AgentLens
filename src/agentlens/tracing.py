"""A trace is one JSON object per line, written as events happen."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class Event:
    """An immutable execution record with a JSON snapshot of its payload."""

    run_id: str
    sequence: int
    timestamp: str
    event: str
    data_json: str = field(repr=False)

    @property
    def data(self) -> dict:
        """Return a fresh copy; editing it cannot change this event."""
        return json.loads(self.data_json)

    def to_dict(self) -> dict:
        """Keep the existing JSONL format, with data as an object."""
        return {
            "run_id": self.run_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "event": self.event,
            "data": self.data,
        }


class Trace:
    """Create one trace per run. Existing files are never overwritten."""

    def __init__(self, directory: str = "traces") -> None:
        self.run_id = uuid4().hex
        self.sequence = 0
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.path = Path(directory) / f"{self.run_id}.jsonl"
        self.path.touch(exist_ok=False)

    def record(self, event: str, **data) -> Event:
        entry = Event(
            run_id=self.run_id,
            sequence=self.sequence + 1,
            timestamp=datetime.now(UTC).isoformat(),
            event=event,
            data_json=json.dumps(data),
        )
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry.to_dict()) + "\n")
        self.sequence = entry.sequence
        return entry
