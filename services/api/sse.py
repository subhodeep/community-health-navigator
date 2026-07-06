"""SSE helpers: formatting public events and tee-parsing the agent's upstream stream.

The agent service emits the same SSE event schema as the public API
(shared.schemas.SSEEvent), so lines are forwarded verbatim while being
parsed on the side to accumulate the assistant turn for persistence.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional


def format_sse(event: str, data: Any) -> str:
    """Render one public SSE frame: `data: {"event": ..., "data": ...}\\n\\n`."""
    payload = json.dumps({"event": event, "data": data}, default=str)
    return f"data: {payload}\n\n"


class StreamAccumulator:
    """Accumulates the assistant turn while the upstream SSE stream is proxied.

    Collects token text, the citations list, the chart_spec payload, and any
    action_request payload; tracks whether a terminal `done` event was seen.
    """

    def __init__(self) -> None:
        self._parts: list[str] = []
        self.citations: Optional[list[dict[str, Any]]] = None
        self.chart_spec: Optional[dict[str, Any]] = None
        self.action_request: Optional[dict[str, Any]] = None
        self.done_seen: bool = False

    @property
    def content(self) -> str:
        return "".join(self._parts)

    @property
    def has_content(self) -> bool:
        return bool(
            self._parts or self.citations or self.chart_spec or self.action_request
        )

    def feed(self, line: str) -> None:
        """Parse one raw SSE line (`data: {json}`); non-data or malformed lines are ignored."""
        line = line.strip()
        if not line.startswith("data:"):
            return
        try:
            event = json.loads(line[len("data:") :].strip())
        except (json.JSONDecodeError, ValueError):
            return
        if not isinstance(event, dict):
            return
        name, data = event.get("event"), event.get("data")
        if name == "token" and isinstance(data, dict):
            self._parts.append(str(data.get("text", "")))
        elif name == "citations" and isinstance(data, list):
            self.citations = data
        elif name == "chart_spec" and isinstance(data, dict):
            self.chart_spec = data
        elif name == "action_request" and isinstance(data, dict):
            self.action_request = data
        elif name == "done":
            self.done_seen = True


async def relay_lines(
    lines: AsyncIterator[str], accumulator: StreamAccumulator
) -> AsyncIterator[str]:
    """Tee the upstream SSE line stream: feed each line to `accumulator`,
    then yield it verbatim (newline restored) for the client."""
    async for line in lines:
        accumulator.feed(line)
        yield f"{line}\n"
