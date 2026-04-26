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

import logging
import os
from typing import Any

from integrations.sdk import (
    AllowDeny,
    AuthStatus,
    ChannelEventEmitter,
    HarnessSlashCommandPolicy,
    RuntimeCapabilities,
    TurnContext,
    TurnResult,
    execute_harness_spindrel_tool,
    list_harness_spindrel_tools,
    request_harness_approval,
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
_BYPASS_ALLOWED: tuple[str, ...] = (
    "Read", "Glob", "Grep", "Bash", "Edit", "Write",
    "Task", "WebFetch", "WebSearch", "ExitPlanMode",
)
_RESTRICTED_ALLOWED: tuple[str, ...] = ("Read", "Glob", "Grep", "WebSearch")


def _allowed_tools_for_mode(mode: str) -> list[str]:
    return list(_BYPASS_ALLOWED) if mode == "bypassPermissions" else list(_RESTRICTED_ALLOWED)


# Conservative v1 slash-command allowlist for harness sessions on this runtime.
# Excluded by intent (re-add only with documented harness behavior):
#   compact  — harness-aware: resets native resume and injects summary
#   plan     — Spindrel chat-mode toggle; conflicts with Claude's native plan
#   context  — harness-aware: shows native resume/status summary
#   find     — channel-scoped keyword search; Spindrel-only semantics
#   effort   — Claude has no effort knob (typed /effort returns friendly no-op)
#   skills + any Spindrel-tool-control commands — runtime owns tools
#
# `model` IS in the allowlist so the picker shows it and typed `/model X`
# discovers + executes. The header model pill is the canonical UI surface,
# but the slash command is a parallel write path that must also work.
_CLAUDE_GENERIC_SLASH_ALLOWED: frozenset[str] = frozenset({
    "help", "rename", "stop", "style", "theme", "clear",
    "sessions", "scratch", "split", "focus", "model", "compact", "context",
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
            model_is_freeform=True,
            # Claude Code SDK has no effort knob today. Typed /effort still
            # routes to the harness handler, which returns a friendly no-op.
            effort_values=(),
            approval_modes=("bypassPermissions", "acceptEdits", "default", "plan"),
            slash_policy=HarnessSlashCommandPolicy(
                allowed_command_ids=_CLAUDE_GENERIC_SLASH_ALLOWED,
            ),
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
            # Phase 4: per-session harness model from harness_settings. SDK
            # forwards to the underlying CLI/API; unknown ids surface as SDK
            # errors during construction or first turn — adapter is the only
            # layer that needs to know the kwarg name.
            options_kwargs["model"] = ctx.model
        # ctx.effort / ctx.runtime_settings intentionally unused — Claude Code
        # SDK exposes no effort knob and no opaque runtime knobs in v1.
        await _maybe_attach_spindrel_tool_bridge(ctx, options_kwargs)

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

        decision: AllowDeny = await request_harness_approval(
            ctx=ctx, runtime=runtime, tool_name=tool_name, tool_input=tool_input,
        )
        if decision.allow:
            return PermissionResultAllow()
        return PermissionResultDeny(
            message=decision.reason or "denied", interrupt=False,
        )

    return _can_use_tool


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


async def _maybe_attach_spindrel_tool_bridge(
    ctx: TurnContext,
    options_kwargs: dict[str, Any],
) -> None:
    """Expose effective Spindrel tools to Claude as an in-process MCP server.

    This is deliberately best-effort: older SDK versions without the helper
    keep running native Claude tools, while installed SDKs get the dynamic
    Spindrel tool set resolved for the current session/channel.
    """
    if ctx.channel_id is None:
        return
    try:
        async with ctx.db_session_factory() as db:
            specs = await list_harness_spindrel_tools(db, ctx)
    except Exception:
        logger.exception("claude-code: failed to list Spindrel bridge tools")
        return
    if not specs:
        return

    try:
        from claude_agent_sdk import create_sdk_mcp_server, tool  # type: ignore
    except Exception:
        logger.warning(
            "claude-code: SDK does not expose in-process MCP helpers; "
            "Spindrel tool bridge disabled for this turn"
        )
        return

    sdk_tools: list[Any] = []
    for spec in specs:
        parameters = spec.parameters or {"type": "object", "properties": {}}

        async def _handler(args: dict[str, Any], *, _name: str = spec.name) -> str:
            return await execute_harness_spindrel_tool(
                ctx,
                tool_name=_name,
                arguments=args,
            )

        try:
            sdk_tools.append(tool(spec.name, spec.description or spec.name, parameters)(_handler))
        except Exception:
            logger.exception("claude-code: failed to wrap Spindrel tool %s", spec.name)

    if not sdk_tools:
        return
    server_name = "spindrel"
    try:
        server = create_sdk_mcp_server(
            name=server_name,
            version="1.0.0",
            tools=sdk_tools,
        )
    except Exception:
        logger.exception("claude-code: failed to create Spindrel MCP bridge")
        return
    mcp_servers = dict(options_kwargs.get("mcp_servers") or {})
    mcp_servers[server_name] = server
    options_kwargs["mcp_servers"] = mcp_servers
    allowed = list(options_kwargs.get("allowed_tools") or [])
    allowed.extend(f"mcp__{server_name}__{spec.name}" for spec in specs)
    options_kwargs["allowed_tools"] = allowed


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
