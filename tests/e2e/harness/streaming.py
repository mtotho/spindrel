"""SSE stream parsing for the /chat/stream endpoint."""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class StreamEvent:
    """A single event from an SSE stream."""

    type: str
    data: dict

    @classmethod
    def from_line(cls, line: str) -> StreamEvent | None:
        """Parse a JSON-lines event from the stream.

        Returns None for blank lines, comments, or unparseable data.
        """
        line = line.strip()
        if not line:
            return None

        # SSE format: "data: {...}" or bare JSON lines
        if line.startswith("data: "):
            line = line[6:]
        elif line.startswith(":"):
            # SSE comment
            return None

        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None

        event_type = payload.get("type", payload.get("event", "unknown"))
        return cls(type=event_type, data=payload)


@dataclass
class StreamResult:
    """Aggregated result from consuming an SSE stream."""

    events: list[StreamEvent] = field(default_factory=list)
    response_text: str = ""
    tools_used: list[str] = field(default_factory=list)
    session_id: str | None = None
    raw_lines: list[str] = field(default_factory=list)

    @property
    def tool_events(self) -> list[StreamEvent]:
        return [e for e in self.events if e.type in ("tool_start", "tool_result")]

    @property
    def error_events(self) -> list[StreamEvent]:
        return [e for e in self.events if e.type == "error"]

    @property
    def event_types(self) -> list[str]:
        return [e.type for e in self.events]

    def add_event(self, event: StreamEvent) -> None:
        self.events.append(event)

        # session_id is injected into every event by the router
        if "session_id" in event.data and not self.session_id:
            self.session_id = event.data["session_id"]

        if event.type == "response":
            self.response_text = event.data.get("text", event.data.get("content", ""))
            self.session_id = event.data.get("session_id", self.session_id)
        elif event.type in ("tool_start", "tool_result"):
            tool_name = event.data.get("tool", event.data.get("name", ""))
            if tool_name and tool_name not in self.tools_used:
                self.tools_used.append(tool_name)
