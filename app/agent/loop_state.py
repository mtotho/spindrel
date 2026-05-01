import uuid
from dataclasses import dataclass, field
from typing import Any

from app.agent.bots import BotConfig
from app.agent.loop_cycle_detection import ToolCallSignature


@dataclass(frozen=True)
class LoopRunContext:
    """Stable identifiers and flags for one agent loop run."""
    bot: BotConfig
    session_id: uuid.UUID | None
    client_id: str | None
    correlation_id: uuid.UUID | None
    channel_id: uuid.UUID | None
    compaction: bool
    native_audio: bool
    user_msg_index: int | None
    turn_start: int


@dataclass
class LoopRunState:
    """Mutable cross-stage state for a single agent loop run."""
    messages: list[dict]
    transcript_emitted: bool = False
    embedded_client_actions: list[dict] = field(default_factory=list)
    tool_calls_made: list[str] = field(default_factory=list)
    tool_envelopes_made: list[dict] = field(default_factory=list)
    transcript_entries: list[dict] = field(default_factory=list)
    thinking_content: str = ""
    tool_call_trace: list[ToolCallSignature] = field(default_factory=list)
    tool_result_cache: dict[ToolCallSignature, str] = field(default_factory=dict)
    mutating_tool_call_seen: set[ToolCallSignature] = field(default_factory=set)
    tools_to_enroll: list[str] = field(default_factory=list)
    loop_broken_reason: str | None = None
    detected_cycle_len: int = 0
    current_prompt_tokens_total: int = 0
    soft_budget_slimmed: bool = False
    last_pruned_after_iteration: int | None = None
    iteration_injected_images: list[dict[str, Any]] = field(default_factory=list)
    terminated: bool = False

    def append_thinking(self, content: str) -> None:
        if not content:
            return
        if self.thinking_content:
            self.thinking_content += "\n\n"
        self.thinking_content += content


LoopDispatchState = LoopRunState
