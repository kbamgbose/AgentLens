"""A trace is one JSON object per line, written as events happen."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


class Trace:
    """Create one trace per run. Existing files are never overwritten."""

    def __init__(self, directory: str = "traces") -> None:
        self.run_id = uuid4().hex
        self.sequence = 0
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.path = Path(directory) / f"{self.run_id}.jsonl"
        self.path.touch(exist_ok=False)

    def record(self, event: str, **data) -> None:
        self.sequence += 1
        entry = {
            "run_id": self.run_id,
            "sequence": self.sequence,
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event,
            "data": data,
        }
        # Serialize now, so later changes to messages cannot alter earlier events.
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry) + "\n")
