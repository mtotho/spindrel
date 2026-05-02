"""Typed envelope for one harness-backed turn.

A ``HarnessTurnRequest`` is the host-side payload that crosses the seam
between callers (interactive ``run_turn``, task runner, heartbeat) and
``run_harness_turn`` in ``turn_host``. Before this struct existed the seam
was 13 loose keyword arguments unpacked at three callsites with no shared
shape; ``_harness_task_turn_overrides`` returned a partial dict that was
splatted via ``**``. One typed object replaces both.

This is *not* the runtime-facing input: that's ``TurnContext`` in
``base.py``, which the harness adapter sees. ``HarnessTurnRequest`` lives
one layer up, between Spindrel callers and the host orchestrator.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from app.agent.bots import BotConfig


@dataclass(frozen=True)
class HarnessTurnRequest:
    """Inputs to a single harness turn invocation.

    Built once per turn at the call site, threaded through the
    ``_run_harness_turn`` wrapper into ``run_harness_turn``. The host
    orchestrator reads fields directly; nothing mutates the request.
    """

    channel_id: uuid.UUID | None
    bus_key: uuid.UUID
    session_id: uuid.UUID
    turn_id: uuid.UUID
    bot: BotConfig
    user_message: str
    correlation_id: uuid.UUID
    msg_metadata: Mapping[str, Any] | None
    pre_user_msg_id: uuid.UUID | None
    suppress_outbox: bool
    is_heartbeat: bool = False
    harness_model_override: str | None = None
    harness_effort_override: str | None = None
    harness_permission_mode_override: str | None = None
    harness_tool_names: tuple[str, ...] = ()
    harness_skill_ids: tuple[str, ...] = ()
    harness_attachments: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        # Callers historically pass list-or-tuple for these three fields.
        # Normalize once so downstream code can rely on tuple identity
        # (e.g., for memoization keys) without re-coercing.
        for name in ("harness_tool_names", "harness_skill_ids", "harness_attachments"):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                object.__setattr__(self, name, tuple(value))

    def with_task_execution_config(self, ecfg: Mapping[str, Any]) -> "HarnessTurnRequest":
        """Return a copy with task ``execution_config`` overrides applied.

        Replaces the old ``_harness_task_turn_overrides`` helper. Folds:

        * ``tools`` → ``harness_tool_names`` (deduped, with optional
          ``report_issue`` injection when ``allow_issue_reporting`` is set).
        * ``skills`` → ``harness_skill_ids`` (deduped).
        * ``skip_tool_approval`` → ``harness_permission_mode_override`` set
          to ``"bypassPermissions"`` (or ``None`` when the flag is unset).
        """
        tool_names = _dedupe_strings(ecfg.get("tools") or ())
        if bool(ecfg.get("allow_issue_reporting")) and "report_issue" not in tool_names:
            tool_names = tool_names + ("report_issue",)
        skill_ids = _dedupe_strings(ecfg.get("skills") or ())
        permission_mode = (
            "bypassPermissions" if bool(ecfg.get("skip_tool_approval")) else None
        )
        pre_user_msg_id = self.pre_user_msg_id
        if pre_user_msg_id is None and ecfg.get("pre_user_msg_id"):
            try:
                pre_user_msg_id = uuid.UUID(str(ecfg.get("pre_user_msg_id")))
            except (TypeError, ValueError):
                pre_user_msg_id = None
        return replace(
            self,
            pre_user_msg_id=pre_user_msg_id,
            harness_tool_names=tool_names,
            harness_skill_ids=skill_ids,
            harness_permission_mode_override=permission_mode,
        )


def _dedupe_strings(values: Any) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw).strip()
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return tuple(out)


__all__ = ["HarnessTurnRequest"]
