"""Demo replay runtime for screenshots and demos.

Drives the same ``TurnEvent`` bus as the real ``claude-code`` runtime from a
scripted JSONL fixture, so captures of harness-driven channels are
reproducible without real Anthropic OAuth credentials. The runtime is gated
behind the ``SPINDREL_DEMO_HARNESS`` env var: with it unset, the
self-registration call short-circuits and ``demo`` never appears in the
runtime registry, the bot-editor dropdown, or ``/admin/harnesses``.

Fixture format — one JSON object per line, dispatched in order with an
``asyncio.sleep(delay_ms / 1000)`` between events:

    {"type":"thinking",   "text":"...",                  "delay_ms": 700}
    {"type":"tool_call",  "name":"Read","args":{...},   "delay_ms": 250}
    {"type":"tool_result","name":"Read","summary":"...","delay_ms": 450,
      "surface":"rich_result","envelope":{...},"result_summary":{...}}
    {"type":"text",       "chunk":"...",                 "delay_ms":  80}
    {"type":"message_end",                                "delay_ms": 120}

The fixture path resolves in this order:

    1. ``ctx.runtime_settings["fixture"]`` (per-bot/per-session override)
    2. ``SPINDREL_DEMO_HARNESS_FIXTURE`` env (global)
    3. ``scripts/screenshots/fixtures/harness/default.jsonl`` (repo default)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from integrations.sdk import (
    AuthStatus,
    ChannelEventEmitter,
    HarnessModelOption,
    HarnessSlashCommandPolicy,
    RuntimeCapabilities,
    TurnContext,
    TurnResult,
)


logger = logging.getLogger(__name__)


_DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "screenshots"
    / "fixtures"
    / "harness"
    / "default.jsonl"
)


def _resolve_fixture(ctx: TurnContext) -> Path:
    override = (ctx.runtime_settings or {}).get("fixture") if ctx else None
    if isinstance(override, str) and override:
        return Path(override)
    env = os.environ.get("SPINDREL_DEMO_HARNESS_FIXTURE")
    if env:
        return Path(env)
    return _DEFAULT_FIXTURE


def _iter_events(fixture_path: Path) -> list[dict[str, Any]]:
    if not fixture_path.is_file():
        raise RuntimeError(
            f"demo harness fixture not found at {fixture_path}. Set "
            "SPINDREL_DEMO_HARNESS_FIXTURE or place a JSONL file at the "
            "default path."
        )
    events: list[dict[str, Any]] = []
    with fixture_path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            try:
                events.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"demo harness fixture {fixture_path}:{line_no} is not JSON: {exc}"
                ) from exc
    return events


class DemoHarnessRuntime:
    """Scripted replay runtime — drives ``ChannelEventEmitter`` from JSONL."""

    name = "demo"

    _READONLY: frozenset[str] = frozenset({"Read", "Glob", "Grep", "WebSearch"})
    _PLAN_AUTOAPPROVE: frozenset[str] = frozenset({"ExitPlanMode"})

    def readonly_tools(self) -> frozenset[str]:
        return self._READONLY

    def prompts_in_accept_edits(self, tool_name: str) -> bool:
        return tool_name not in self._READONLY

    def autoapprove_in_plan(self, tool_name: str) -> bool:
        return tool_name in self._PLAN_AUTOAPPROVE

    def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(
            display_name="Demo (replay)",
            supported_models=("demo-replay",),
            model_options=(
                HarnessModelOption(
                    id="demo-replay",
                    label="Demo replay",
                    effort_values=(),
                    default_effort=None,
                ),
            ),
            model_is_freeform=False,
            effort_values=(),
            approval_modes=("bypassPermissions",),
            slash_policy=HarnessSlashCommandPolicy(
                allowed_command_ids=frozenset()
            ),
        )

    async def list_models(self) -> tuple[str, ...]:
        return ("demo-replay",)

    def auth_status(self) -> AuthStatus:
        path = _DEFAULT_FIXTURE
        ok = path.is_file()
        return AuthStatus(
            ok=ok,
            detail=(
                f"Replays {path} (no external auth required)."
                if ok
                else f"Default fixture missing at {path}. Drop a JSONL fixture there."
            ),
            suggested_command=None,
        )

    async def start_turn(
        self,
        *,
        ctx: TurnContext,
        prompt: str,
        emit: ChannelEventEmitter,
    ) -> TurnResult:
        fixture = _resolve_fixture(ctx)
        events = _iter_events(fixture)

        final_text_parts: list[str] = []
        tool_call_ids: dict[str, str] = {}

        for ev in events:
            kind = ev.get("type", "")
            delay = float(ev.get("delay_ms", 0)) / 1000.0
            if delay > 0:
                await asyncio.sleep(delay)

            if kind == "thinking":
                emit.thinking(str(ev.get("text", "")))
            elif kind == "tool_call":
                name = str(ev.get("name", "tool"))
                args = ev.get("args", {}) or {}
                if not isinstance(args, dict):
                    args = {"value": args}
                call_id = str(ev.get("id") or f"demo:{len(tool_call_ids) + 1}")
                tool_call_ids[name] = call_id
                emit.tool_start(tool_name=name, arguments=args, tool_call_id=call_id)
            elif kind == "tool_result":
                name = str(ev.get("name", "tool"))
                summary = str(ev.get("summary", ""))
                is_error = bool(ev.get("is_error", False))
                call_id = str(ev.get("id") or tool_call_ids.get(name) or "")
                envelope = ev.get("envelope")
                if not isinstance(envelope, dict):
                    envelope = None
                result_summary = ev.get("result_summary")
                if not isinstance(result_summary, dict):
                    result_summary = None
                surface = ev.get("surface")
                if not isinstance(surface, str) or not surface:
                    surface = None
                emit.tool_result(
                    tool_name=name,
                    result_summary=summary,
                    is_error=is_error,
                    tool_call_id=call_id or None,
                    envelope=envelope,
                    surface=surface,
                    summary=result_summary,
                )
            elif kind == "text":
                chunk = str(ev.get("chunk", ""))
                if chunk:
                    final_text_parts.append(chunk)
                    emit.token(chunk)
            elif kind == "message_end":
                # Synthetic end marker — just flushes the loop.
                pass
            else:
                logger.debug("demo harness: unknown event kind %r — ignoring", kind)

        return TurnResult(
            session_id=f"demo:{uuid.uuid4()}",
            final_text="".join(final_text_parts),
            cost_usd=0.0,
            usage={"input_tokens": 0, "output_tokens": 0},
        )


# Self-registration on integration load — gated behind an env var so the demo
# runtime never appears in real deployments.
def _register() -> None:
    if os.environ.get("SPINDREL_DEMO_HARNESS", "").strip().lower() not in (
        "1", "true", "yes", "on",
    ):
        logger.info(
            "demo_harness: SPINDREL_DEMO_HARNESS is unset — runtime not registered"
        )
        return
    from integrations.sdk import register_runtime

    register_runtime(DemoHarnessRuntime.name, DemoHarnessRuntime())


_register()
