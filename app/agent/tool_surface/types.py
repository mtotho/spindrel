"""Typed result + trace-event shapes for the tool-surface composer."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agent.bots import BotConfig

# Trace events emitted during composition. Kept as `dict[str, Any]` to match
# the existing wire shape consumed by `assemble_context` and downstream tracing
# consumers. A typed union can replace this once every emitter is migrated.
ToolSurfaceTraceEvent = dict[str, Any]


@dataclass
class ToolSurfaceResult:
    """The materialized tool surface for one assembly turn.

    Returned as the terminal value of `compose_stream(...)`. Captures
    everything `assemble_context` needs to wire the tool surface into the
    rest of the pipeline (downstream prompt injection, finalization tracing,
    budget accounting).
    """

    # Final tool schemas the LLM sees this turn. None when no surface was
    # composed (e.g. policy disables tool exposure entirely).
    pre_selected_tools: list[dict[str, Any]] | None = None

    # Names corresponding to `pre_selected_tools`; used for authorization
    # checks at dispatch time and for trace emission.
    authorized_names: set[str] | None = None

    # Skill enrollment outputs. `bot` may be replaced in-flight when
    # enrolled skill ids merge into the bot config.
    bot: BotConfig | None = None
    enrolled_ids: list[str] = field(default_factory=list)
    source_map: dict[str, str] = field(default_factory=dict)

    # Discovery diagnostics surfaced to traces and the budget UI.
    tool_discovery_info: dict[str, Any] = field(
        default_factory=lambda: {"tool_retrieval_enabled": False}
    )

    # True when retrieval ran out of budget mid-pass and pruned candidates.
    # Heartbeat and memory_flush modes never set this.
    exhausted: bool = False
