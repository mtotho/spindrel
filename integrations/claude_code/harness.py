"""Claude Code harness runtime — drives the Claude Agent SDK in-process.

Lives inside the ``claude_code`` integration so the SDK + CLI install live
with the integration's own ``requirements.txt`` (not the base image / not
the global pyproject). The ``app/services/agent_harnesses/`` registry is
populated when this module is imported on integration load — see
``register_runtime`` call at bottom of file.

Auth is OAuth-only via the bundled CLI (``claude login`` writes
``~/.claude/.credentials.json`` or ``$CLAUDE_CONFIG_DIR/.credentials.json``).
We never set ``ANTHROPIC_API_KEY`` from this driver — if the user's CLI is
logged in, the SDK inherits those creds; if not, the SDK will fail at
construction and we surface that as a turn error.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
from typing import Any

from integrations.sdk import (
    AllowDeny,
    AuthStatus,
    ChannelEventEmitter,
    HarnessCompactResult,
    HarnessModelOption,
    HarnessSlashCommandPolicy,
    HarnessToolSpec,
    RuntimeCapabilities,
    TurnContext,
    TurnResult,
    apply_tool_bridge,
    execute_harness_spindrel_tool,
    format_question_answer_for_runtime,
    request_harness_approval,
    request_harness_question,
)

# Probe-import the SDK at module load. The actual SDK calls live inside
# ``start_turn`` (deferred to keep cold-startup snappy), but having this
# top-level import lets ``discover_and_load_harnesses`` see ImportError at
# discover time and auto-run ``pip install -r requirements.txt`` instead of
# silently registering a runtime that fails on first use.
import claude_agent_sdk as _claude_agent_sdk_probe  # noqa: F401

logger = logging.getLogger(__name__)


# Per-mode SDK ``allowed_tools`` resolver.
#
# ``allowed_tools`` short-circuits the SDK's permission prompter — listed
# tools never hit ``can_use_tool`` regardless of ``permission_mode``. So the
# allowlist itself is mode-driven:
#
#   bypassPermissions: full set; SDK runs everything, can_use_tool short-circuits in helper
#   acceptEdits / default / plan: read-only set; everything else routes to can_use_tool
#
# Edit/Write are NOT in the restricted set — the SDK's ``acceptEdits``
# permission_mode auto-approves them through a separate gate (verified
# against SDK 0.1.68 source).
# AskUserQuestion is intentionally NOT in either allowlist: it must route
# through can_use_tool so Spindrel can render a durable native question card
# instead of letting the SDK's transient prompt surface handle it.
_BYPASS_ALLOWED: tuple[str, ...] = (
    "Read", "Glob", "Grep", "Bash", "Edit", "Write",
    "Task", "WebFetch", "WebSearch", "ExitPlanMode",
)
_RESTRICTED_ALLOWED: tuple[str, ...] = ("Read", "Glob", "Grep", "WebSearch")


def _allowed_tools_for_mode(mode: str) -> list[str]:
    return list(_BYPASS_ALLOWED) if mode == "bypassPermissions" else list(_RESTRICTED_ALLOWED)


# Conservative v1 slash-command allowlist for harness sessions on this runtime.
# Excluded by intent (re-add only with documented harness behavior):
#   compact  — harness-aware: triggers Claude native compaction
#   plan     — Spindrel chat-mode toggle; conflicts with Claude's native plan
#   context  — harness-aware: shows native resume/status summary
#   find     — channel-scoped keyword search; Spindrel-only semantics
#   skills + any Spindrel-tool-control commands — runtime owns tools
#
# `model` IS in the allowlist so the picker shows it and typed `/model X`
# discovers + executes. The header model pill is the canonical UI surface,
# but the slash command is a parallel write path that must also work.
_CLAUDE_GENERIC_SLASH_ALLOWED: frozenset[str] = frozenset({
    "help", "rename", "stop", "style", "theme", "clear",
    "sessions", "scratch", "split", "focus", "model", "effort",
    "compact", "context", "new",
})


# Curated list of Claude model aliases the SDK CLI accepts. Ordered most
# capable → least. Snapshot — refresh by restarting the server after a
# CLI/SDK upgrade. The header pill + the harness `/model` picker both
# display this list; freeform text input still works for unknown ids.
_CLAUDE_KNOWN_MODELS: tuple[str, ...] = (
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
)
_CLAUDE_EFFORT_VALUES: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")


def _credential_path() -> str:
    """Resolve the on-disk credential path the CLI writes after `claude login`.

    Per https://code.claude.com/docs/en/authentication the file lives at
    ``$CLAUDE_CONFIG_DIR/.credentials.json`` (NOTE: leading dot), defaulting
    to ``~/.claude/.credentials.json``.
    """
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR", os.path.expanduser("~/.claude"))
    return os.path.join(config_dir, ".credentials.json")




class ClaudeCodeRuntime:
    """Drives the Claude Agent SDK against a workspace dir."""

    name = "claude-code"

    # ------------------------------------------------------------------
    # Tool classification — consumed by request_harness_approval (Phase 3).
    # Phase 2 ships these as no-ops effectively (start_turn still hardcodes
    # bypass-equivalent allowlist); Phase 3 wires them into the SDK options
    # and the can_use_tool callback.
    # ------------------------------------------------------------------

    _READONLY: frozenset[str] = frozenset({"Read", "Glob", "Grep", "WebSearch"})
    _SDK_ACCEPT_EDITS_NATIVE: frozenset[str] = frozenset({"Edit", "Write"})
    _PLAN_AUTOAPPROVE: frozenset[str] = frozenset({"ExitPlanMode"})

    def readonly_tools(self) -> frozenset[str]:
        return self._READONLY

    def prompts_in_accept_edits(self, tool_name: str) -> bool:
        return tool_name not in self._READONLY and tool_name not in self._SDK_ACCEPT_EDITS_NATIVE

    def autoapprove_in_plan(self, tool_name: str) -> bool:
        return tool_name in self._PLAN_AUTOAPPROVE

    def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(
            display_name="Claude Code",
            # Freeform input is allowed (SDK accepts any string the CLI
            # accepts), but list_models() returns the curated set the UI
            # picker shows by default.
            supported_models=_CLAUDE_KNOWN_MODELS,
            model_options=tuple(
                HarnessModelOption(
                    id=model,
                    label=model,
                    effort_values=_CLAUDE_EFFORT_VALUES,
                    default_effort="high",
                )
                for model in _CLAUDE_KNOWN_MODELS
            ),
            model_is_freeform=True,
            effort_values=_CLAUDE_EFFORT_VALUES,
            approval_modes=("bypassPermissions", "acceptEdits", "default", "plan"),
            slash_policy=HarnessSlashCommandPolicy(
                allowed_command_ids=_CLAUDE_GENERIC_SLASH_ALLOWED,
            ),
            native_compaction=True,
            context_window_tokens=200_000,
        )

    async def list_models(self) -> tuple[str, ...]:
        # Curated list of currently-known Claude model aliases the SDK CLI
        # accepts. This is a snapshot — restart the server to refresh after
        # a CLI/SDK upgrade. If the Claude Agent SDK ever exposes a
        # programmatic catalog, swap this for an SDK call.
        return _CLAUDE_KNOWN_MODELS

    async def start_turn(
        self,
        *,
        ctx: TurnContext,
        prompt: str,
        emit: ChannelEventEmitter,
    ) -> TurnResult:
        # Late import keeps the SDK out of cold-startup paths and lets the
        # rest of the app boot when the SDK isn't installed (e.g. test envs).
        from claude_agent_sdk import (  # type: ignore
            ClaudeAgentOptions,
            ClaudeSDKClient,
        )

        if not os.path.isdir(ctx.workdir):
            raise RuntimeError(
                f"Harness workdir does not exist: {ctx.workdir!r}. "
                "Create it (mkdir + git clone your repo) before sending a message."
            )

        options_kwargs: dict[str, Any] = {
            "cwd": ctx.workdir,
            "allowed_tools": _allowed_tools_for_mode(ctx.permission_mode),
            "permission_mode": ctx.permission_mode,
            # ``can_use_tool`` is set unconditionally — even in bypassPermissions
            # the helper short-circuits in O(1). This is defensive: if a future
            # SDK change surfaces a tool through the prompter despite the full
            # allowlist, we get a quick allow rather than a stall.
            "can_use_tool": _make_can_use_tool(ctx, runtime=self),
        }
        if ctx.harness_session_id:
            options_kwargs["resume"] = ctx.harness_session_id
        if ctx.model:
            options_kwargs["model"] = ctx.model
        _set_effort_kwarg(ClaudeAgentOptions, options_kwargs, ctx.effort)
        # ctx.runtime_settings is reserved for future Claude/Codex-specific knobs.

        async def _attach(specs: tuple[HarnessToolSpec, ...]) -> list[str]:
            return _attach_claude_mcp_bridge(ctx, options_kwargs, specs)

        await apply_tool_bridge(ctx, self, attach=_attach)

        opts = ClaudeAgentOptions(**options_kwargs)

        # tool_use_id → tool_name lookup so ``ToolResultBlock`` (which only
        # carries tool_use_id) can publish a meaningful tool_name on result.
        tool_name_by_use_id: dict[str, str] = {}
        final_text_parts: list[str] = []
        result_meta: dict[str, Any] = {}

        async with ClaudeSDKClient(options=opts) as client:
            await client.query(_prompt_with_context_hints(prompt, ctx))
            async for msg in client.receive_response():
                _bridge_message(
                    msg,
                    ctx=ctx,
                    emit=emit,
                    tool_name_by_use_id=tool_name_by_use_id,
                    final_text_parts=final_text_parts,
                    result_meta=result_meta,
                )

        # SDK guarantees a ResultMessage at end of stream; if it didn't fire
        # (network drop, etc.), fall back to the resume id we were given so
        # we don't lose the conversation thread.
        final_session_id = result_meta.get("session_id") or ctx.harness_session_id or ""
        if not final_session_id:
            logger.warning(
                "claude-code driver: no session_id reported and no prior "
                "session_id to fall back on; resume on next turn will fail"
            )

        if result_meta.get("is_error"):
            raise RuntimeError(
                f"Claude Code turn ended with error: "
                f"{result_meta.get('result') or 'unknown'}"
            )

        return TurnResult(
            session_id=final_session_id,
            final_text="".join(final_text_parts),
            cost_usd=result_meta.get("total_cost_usd"),
            usage=result_meta.get("usage"),
        )

    async def compact_session(
        self,
        *,
        ctx: TurnContext,
    ) -> HarnessCompactResult:
        from claude_agent_sdk import (  # type: ignore
            ClaudeAgentOptions,
            ClaudeSDKClient,
        )

        if not ctx.harness_session_id:
            return HarnessCompactResult(
                ok=False,
                session_id=None,
                detail="No native Claude session exists yet. Start a turn before compacting.",
                error="missing_harness_session_id",
            )
        if not os.path.isdir(ctx.workdir):
            return HarnessCompactResult(
                ok=False,
                session_id=ctx.harness_session_id,
                detail=f"Harness workdir does not exist: {ctx.workdir!r}.",
                error="missing_workdir",
            )

        options_kwargs: dict[str, Any] = {
            "cwd": ctx.workdir,
            "resume": ctx.harness_session_id,
            "allowed_tools": _allowed_tools_for_mode(ctx.permission_mode),
            "permission_mode": ctx.permission_mode,
            "can_use_tool": _make_can_use_tool(ctx, runtime=self),
        }
        if ctx.model:
            options_kwargs["model"] = ctx.model
        _set_effort_kwarg(ClaudeAgentOptions, options_kwargs, ctx.effort)
        opts = ClaudeAgentOptions(**options_kwargs)

        result_meta: dict[str, Any] = {}
        compact_events: list[dict[str, Any]] = []
        try:
            async with ClaudeSDKClient(options=opts) as client:
                await client.query("/compact")
                async for msg in client.receive_response():
                    _bridge_compact_message(
                        msg,
                        result_meta=result_meta,
                        compact_events=compact_events,
                    )
        except Exception as exc:
            logger.exception("claude-code native compact failed for session %s", ctx.spindrel_session_id)
            return HarnessCompactResult(
                ok=False,
                session_id=ctx.harness_session_id,
                detail=f"Claude native compact failed: {exc}",
                error=str(exc),
                metadata={"compact_events": compact_events},
            )

        if result_meta.get("is_error"):
            detail = str(result_meta.get("result") or "Claude native compact ended with an error.")
            return HarnessCompactResult(
                ok=False,
                session_id=result_meta.get("session_id") or ctx.harness_session_id,
                detail=detail,
                usage=result_meta.get("usage"),
                error=detail,
                metadata={"compact_events": compact_events, "result": result_meta.get("result")},
            )

        return HarnessCompactResult(
            ok=True,
            session_id=result_meta.get("session_id") or ctx.harness_session_id,
            detail="Claude native compaction completed.",
            usage=result_meta.get("usage"),
            metadata={
                "compact_events": compact_events,
                "result": result_meta.get("result"),
                "total_cost_usd": result_meta.get("total_cost_usd"),
            },
        )

    def auth_status(self) -> AuthStatus:
        path = _credential_path()
        if os.path.exists(path):
            return AuthStatus(ok=True, detail=f"Logged in via {path}")
        return AuthStatus(
            ok=False,
            detail=(
                f"Credentials not found at {path}. "
                f"Click 'Run claude login' below — a terminal opens inside the "
                f"Spindrel container with the command pre-seeded."
            ),
            suggested_command="claude login",
        )


def _make_can_use_tool(ctx: TurnContext, *, runtime: ClaudeCodeRuntime) -> Any:
    """Build a ``can_use_tool`` callback that delegates to the shared helper.

    The helper (``request_harness_approval``) reads ``ctx.permission_mode``
    and the runtime's tool classification methods (``readonly_tools``,
    ``prompts_in_accept_edits``, ``autoapprove_in_plan``) to decide allow /
    deny / ask. On ask, it writes a ``ToolApproval`` row, registers a
    Future, publishes ``APPROVAL_REQUESTED``, and awaits the user's
    decision.

    Returns: an async callback matching the Claude SDK's ``CanUseTool``
    signature ``(str, dict, ToolPermissionContext) -> Awaitable[PermissionResult]``.
    """

    async def _can_use_tool(
        tool_name: str, tool_input: dict[str, Any], _sdk_ctx: Any
    ) -> Any:
        # Late import — SDK is loaded inside the integration's venv.
        from claude_agent_sdk import (  # type: ignore
            PermissionResultAllow,
            PermissionResultDeny,
        )

        if tool_name == "AskUserQuestion":
            try:
                result = await request_harness_question(
                    ctx=ctx,
                    runtime_name=runtime.name,
                    tool_input=tool_input or {},
                )
            except asyncio.TimeoutError:
                return PermissionResultDeny(
                    message="User question expired without an answer.",
                    interrupt=False,
                )
            except Exception as exc:
                logger.exception("claude-code: AskUserQuestion bridge failed")
                return PermissionResultDeny(message=str(exc), interrupt=False)
            return _permission_allow_with_updated_input(
                PermissionResultAllow,
                format_question_answer_for_runtime(result, tool_input or {}),
            )

        decision: AllowDeny = await request_harness_approval(
            ctx=ctx, runtime=runtime, tool_name=tool_name, tool_input=tool_input,
        )
        if decision.allow:
            return PermissionResultAllow()
        return PermissionResultDeny(
            message=decision.reason or "denied", interrupt=False,
        )

    return _can_use_tool


def _permission_allow_with_updated_input(
    permission_result_allow: Any,
    updated_input: dict[str, Any],
) -> Any:
    try:
        return permission_result_allow(updated_input=updated_input)
    except TypeError:
        allowed = permission_result_allow()
        try:
            setattr(allowed, "updated_input", updated_input)
        except Exception:
            logger.warning(
                "claude-code: PermissionResultAllow does not accept updated_input; "
                "falling back to plain allow"
            )
        return allowed


def _set_effort_kwarg(
    options_cls: Any,
    options_kwargs: dict[str, Any],
    effort: str | None,
) -> None:
    """Map Spindrel's harness effort onto the installed SDK option shape.

    Claude's Python SDK has shifted the effort kwarg across releases (``effort``
    → ``thinking={"effort": ...}`` → ``extra_args=["--effort", ...]``). The
    inspection lives at the call site so app/ never references SDK kwarg names.
    """
    if not effort:
        return
    try:
        sig = inspect.signature(options_cls)
        names = set(sig.parameters)
    except Exception:
        names = set(getattr(options_cls, "__annotations__", {}) or {})
    if "effort" in names:
        options_kwargs["effort"] = effort
    elif "thinking" in names:
        options_kwargs["thinking"] = {"effort": effort}
    elif "extra_args" in names:
        options_kwargs.setdefault("extra_args", [])
        options_kwargs["extra_args"].extend(["--effort", effort])
    else:
        logger.warning(
            "claude-code: installed ClaudeAgentOptions exposes no effort/thinking kwarg; "
            "ignoring harness effort=%s for this turn",
            effort,
        )


def _attach_claude_mcp_bridge(
    ctx: TurnContext,
    options_kwargs: dict[str, Any],
    specs: tuple[HarnessToolSpec, ...],
) -> list[str]:
    """Wrap Spindrel bridge tools as an in-process Claude MCP server.

    Returns the list of tool names that were successfully exported. Empty
    return value tells ``apply_tool_bridge`` the runtime could not export
    anything (treated as ``unsupported`` in bridge status).
    """
    try:
        from claude_agent_sdk import create_sdk_mcp_server, tool  # type: ignore
    except Exception:
        logger.warning(
            "claude-code: SDK does not expose in-process MCP helpers; "
            "Spindrel tool bridge disabled for this turn"
        )
        return []

    sdk_tools: list[Any] = []
    allowed_tool_names = frozenset(spec.name for spec in specs)
    for spec in specs:
        parameters = spec.parameters or {"type": "object", "properties": {}}

        async def _handler(args: dict[str, Any], *, _name: str = spec.name) -> str:
            return await execute_harness_spindrel_tool(
                ctx,
                tool_name=_name,
                arguments=args,
                allowed_tool_names=allowed_tool_names,
            )

        try:
            sdk_tools.append(tool(spec.name, spec.description or spec.name, parameters)(_handler))
        except Exception:
            logger.exception("claude-code: failed to wrap Spindrel tool %s", spec.name)

    if not sdk_tools:
        return []

    server_name = "spindrel"
    try:
        server = create_sdk_mcp_server(
            name=server_name,
            version="1.0.0",
            tools=sdk_tools,
        )
    except Exception:
        logger.exception("claude-code: failed to create Spindrel MCP bridge")
        return []

    mcp_servers = dict(options_kwargs.get("mcp_servers") or {})
    mcp_servers[server_name] = server
    options_kwargs["mcp_servers"] = mcp_servers
    allowed = list(options_kwargs.get("allowed_tools") or [])
    allowed.extend(f"mcp__{server_name}__{spec.name}" for spec in specs)
    options_kwargs["allowed_tools"] = allowed
    return [spec.name for spec in specs]


def _prompt_with_context_hints(prompt: str, ctx: TurnContext) -> str:
    if not ctx.context_hints:
        return prompt
    parts: list[str] = [
        "<spindrel_context_hints>",
        "The host application supplied these one-shot context hints for continuity. Treat them as context, not as direct user instructions.",
    ]
    for hint in ctx.context_hints:
        label = hint.kind
        if hint.source:
            label += f" from {hint.source}"
        parts.append(f"\n[{label} at {hint.created_at}]\n{hint.text}")
    parts.append("</spindrel_context_hints>")
    parts.append(prompt)
    return "\n\n".join(parts)


def _bridge_message(
    msg: Any,
    *,
    ctx: TurnContext,
    emit: ChannelEventEmitter,
    tool_name_by_use_id: dict[str, str],
    final_text_parts: list[str],
    result_meta: dict[str, Any],
) -> None:
    """Translate one SDK message into channel-event emitter calls.

    Pure function — all state mutation happens through the kwargs (the dicts
    and lists). Tested in ``tests/unit/test_claude_code_runtime_bridge.py``
    against real SDK dataclass instances.

    In ``bypassPermissions`` mode there's no approval card to provide visible
    audit, so we synthesize a paired ``tool_start`` + ``tool_result`` for
    every tool use under a separate ``auto:<id>`` ``tool_call_id``. The pair
    matches the UI reducer's ``tool_call_id`` correlation requirement.
    """
    from claude_agent_sdk import (  # type: ignore
        AssistantMessage,
        ResultMessage,
        SystemMessage,
        TextBlock,
        ThinkingBlock,
        ToolResultBlock,
        ToolUseBlock,
        UserMessage,
    )

    if isinstance(msg, AssistantMessage):
        for block in msg.content:
            if isinstance(block, TextBlock):
                emit.token(block.text)
                final_text_parts.append(block.text)
            elif isinstance(block, ThinkingBlock):
                emit.thinking(block.thinking)
            elif isinstance(block, ToolUseBlock):
                tool_name_by_use_id[block.id] = block.name
                emit.tool_start(
                    tool_name=block.name,
                    tool_call_id=block.id,
                    arguments=block.input or {},
                )
                if ctx.permission_mode == "bypassPermissions":
                    audit_id = f"auto:{block.id}"
                    emit.tool_start(
                        tool_name="auto-approved",
                        tool_call_id=audit_id,
                        arguments={"tool": block.name},
                    )
                    emit.tool_result(
                        tool_name="auto-approved",
                        tool_call_id=audit_id,
                        result_summary=(
                            f"Auto-approved {block.name} (bypassPermissions mode)"
                        ),
                        is_error=False,
                    )
            # Server-side blocks (ServerToolUseBlock etc.) are intentionally
            # skipped in v1 — they're rare and the SDK reports them as part
            # of the assistant text anyway.
        return

    if isinstance(msg, UserMessage):
        # Tool results synthesized by the SDK come back as UserMessage rows.
        if isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, ToolResultBlock):
                    tool_name = tool_name_by_use_id.get(block.tool_use_id, "unknown")
                    emit.tool_result(
                        tool_name=tool_name,
                        tool_call_id=block.tool_use_id,
                        result_summary=_summarize_tool_result(block.content),
                        is_error=bool(block.is_error),
                    )
        return

    if isinstance(msg, ResultMessage):
        result_meta["session_id"] = msg.session_id
        result_meta["total_cost_usd"] = msg.total_cost_usd
        result_meta["usage"] = msg.usage
        result_meta["is_error"] = msg.is_error
        result_meta["result"] = msg.result
        return

    if isinstance(msg, SystemMessage):
        # System messages carry CLI metadata (init, task lifecycle, mirror
        # errors). None of them belong on the user-facing chat surface in v1.
        return


def _bridge_compact_message(
    msg: Any,
    *,
    result_meta: dict[str, Any],
    compact_events: list[dict[str, Any]],
) -> None:
    from claude_agent_sdk import ResultMessage, SystemMessage  # type: ignore

    if isinstance(msg, ResultMessage):
        result_meta["session_id"] = msg.session_id
        result_meta["total_cost_usd"] = msg.total_cost_usd
        result_meta["usage"] = msg.usage
        result_meta["is_error"] = msg.is_error
        result_meta["result"] = msg.result
        return

    if isinstance(msg, SystemMessage):
        raw = {
            "subtype": getattr(msg, "subtype", None),
            "data": getattr(msg, "data", None),
        }
        subtype = str(raw.get("subtype") or "")
        data = raw.get("data")
        if subtype == "compact_boundary" or (
            isinstance(data, dict) and data.get("subtype") == "compact_boundary"
        ):
            compact_events.append({
                "subtype": "compact_boundary",
                "data": data if isinstance(data, dict) else {},
            })
        return


def _summarize_tool_result(content: Any) -> str:
    """Coerce a ToolResultBlock.content into a short string for the bus payload."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content if len(content) <= 4000 else content[:4000] + "…"
    if isinstance(content, list):
        # Each item is a {"type": "...", "text": "..."} dict per Anthropic shape.
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or ""
                if text:
                    parts.append(text)
        joined = "\n".join(parts)
        return joined if len(joined) <= 4000 else joined[:4000] + "…"
    # Fallback for unexpected shapes.
    return str(content)[:4000]


# ----------------------------------------------------------------------------
# Self-registration on integration load
# ----------------------------------------------------------------------------
# When ``app.services.agent_harnesses.discover_and_load_harnesses()`` imports
# this module (only fires for active integrations), this side-effect registers
# the runtime in the global registry. If the integration is disabled or the
# SDK isn't installed yet, the import is skipped and ``claude-code`` simply
# won't appear in the bot-editor dropdown / /admin/harnesses listing.
def _register() -> None:
    from integrations.sdk import register_runtime

    register_runtime(ClaudeCodeRuntime.name, ClaudeCodeRuntime())


_register()
