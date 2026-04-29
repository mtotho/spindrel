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
import json
import logging
import os
import subprocess
from typing import Any, Mapping

from integrations.sdk import (
    AllowDeny,
    AuthStatus,
    ChannelEventEmitter,
    HarnessCompactResult,
    HarnessModelOption,
    HarnessRuntimeCommandResult,
    HarnessRuntimeCommandSpec,
    HarnessSlashCommandPolicy,
    HarnessToolSpec,
    RuntimeCapabilities,
    TurnContext,
    TurnResult,
    apply_tool_bridge,
    build_diff_tool_result,
    build_text_tool_result,
    execute_harness_spindrel_tool_result,
    format_question_answer_for_runtime,
    request_harness_approval,
    request_harness_question,
    render_context_hints_for_prompt,
    unified_diff_from_strings,
)

# Probe-import the SDK at module load. The actual SDK calls live inside
# ``start_turn`` (deferred to keep cold-startup snappy), but having this
# top-level import lets ``discover_and_load_harnesses`` see ImportError at
# discover time and auto-run ``pip install -r requirements.txt`` instead of
# silently registering a runtime that fails on first use.
import claude_agent_sdk as _claude_agent_sdk_probe  # noqa: F401

logger = logging.getLogger(__name__)


_CLAUDE_PLUGIN_MUTATING_SUBCOMMANDS = {
    "disable",
    "enable",
    "i",
    "install",
    "remove",
    "uninstall",
    "update",
}
_CLAUDE_MCP_MUTATING_SUBCOMMANDS = {"add", "login", "logout", "remove"}


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
_TEXT_RESULT_TOOLS: frozenset[str] = frozenset({"Read", "Bash", "Glob", "Grep"})


def _allowed_tools_for_mode(mode: str) -> list[str]:
    return list(_BYPASS_ALLOWED) if mode == "bypassPermissions" else list(_RESTRICTED_ALLOWED)


def _effective_permission_mode(ctx: TurnContext) -> str:
    if ctx.session_plan_mode == "planning":
        return "plan"
    return ctx.permission_mode


# Conservative v1 slash-command allowlist for harness sessions on this runtime.
# Excluded by intent (re-add only with documented harness behavior):
#   compact  — harness-aware: triggers Claude native compaction
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
    "compact", "context", "plan", "runtime", "new",
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
_CLAUDE_NATIVE_COMMANDS: tuple[HarnessRuntimeCommandSpec, ...] = (
    HarnessRuntimeCommandSpec(
        id="version",
        label="version",
        description="Show the installed Claude Code CLI version.",
    ),
    HarnessRuntimeCommandSpec(
        id="auth",
        label="auth",
        description="Show Spindrel's Claude Code auth probe result.",
    ),
    HarnessRuntimeCommandSpec(
        id="skills",
        label="skills",
        description="List Claude Code native skills when the installed CLI supports it.",
        fallback_behavior="terminal",
    ),
    HarnessRuntimeCommandSpec(
        id="plugins",
        label="plugins",
        description="List Claude Code native plugins when the installed CLI supports it.",
        aliases=("plugin",),
        fallback_behavior="terminal",
    ),
    HarnessRuntimeCommandSpec(
        id="mcp",
        label="mcp",
        description="List Claude Code native MCP servers when the installed CLI supports it.",
        fallback_behavior="terminal",
    ),
    HarnessRuntimeCommandSpec(
        id="agents",
        label="agents",
        description="List Claude Code native agents when the installed CLI supports it.",
        fallback_behavior="terminal",
    ),
    HarnessRuntimeCommandSpec(
        id="hooks",
        label="hooks",
        description="List Claude Code native hooks when the installed CLI supports it.",
        fallback_behavior="terminal",
    ),
    HarnessRuntimeCommandSpec(
        id="status",
        label="status",
        description="Show Claude Code native status when the installed CLI supports it.",
        fallback_behavior="terminal",
    ),
    HarnessRuntimeCommandSpec(
        id="doctor",
        label="doctor",
        description="Run Claude Code native diagnostics when the installed CLI supports it.",
        fallback_behavior="terminal",
    ),
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
            native_commands=_CLAUDE_NATIVE_COMMANDS,
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

        permission_mode = _effective_permission_mode(ctx)
        options_kwargs: dict[str, Any] = {
            "cwd": ctx.workdir,
            "allowed_tools": _allowed_tools_for_mode(permission_mode),
            "permission_mode": permission_mode,
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
        _set_env_kwarg(ClaudeAgentOptions, options_kwargs, ctx.env)
        _set_streaming_permission_hooks(ClaudeAgentOptions, options_kwargs)
        # ctx.runtime_settings is reserved for future Claude/Codex-specific knobs.

        result_meta: dict[str, Any] = {"claude_spindrel_tool_results": {}}

        async def _attach(specs: tuple[HarnessToolSpec, ...]) -> list[str]:
            return _attach_claude_mcp_bridge(
                ctx,
                options_kwargs,
                specs,
                bridge_results=result_meta["claude_spindrel_tool_results"],
            )

        await apply_tool_bridge(ctx, self, attach=_attach)

        opts = ClaudeAgentOptions(**options_kwargs)

        # tool_use_id → tool_name lookup so ``ToolResultBlock`` (which only
        # carries tool_use_id) can publish a meaningful tool_name on result.
        tool_name_by_use_id: dict[str, str] = {}
        final_text_parts: list[str] = []

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
            metadata={
                "claude_native_slash_commands": result_meta.get("claude_native_slash_commands") or [],
                "input_manifest": ctx.input_manifest.metadata(),
            },
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
        _set_env_kwarg(ClaudeAgentOptions, options_kwargs, ctx.env)
        _set_streaming_permission_hooks(ClaudeAgentOptions, options_kwargs)
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

    async def execute_native_command(
        self,
        *,
        command_id: str,
        args: tuple[str, ...],
        ctx: TurnContext,
    ) -> HarnessRuntimeCommandResult:
        del ctx
        if command_id == "auth":
            status = self.auth_status()
            return HarnessRuntimeCommandResult(
                command_id=command_id,
                title="Claude Code auth",
                detail=status.detail,
                status="ok" if status.ok else "error",
                payload={
                    "ok": status.ok,
                    "detail": status.detail,
                    "suggested_command": status.suggested_command,
                },
            )
        if command_id == "version":
            try:
                proc = subprocess.run(
                    ["claude", "--version"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except Exception as exc:
                return HarnessRuntimeCommandResult(
                    command_id=command_id,
                    title="Claude Code version failed",
                    detail=str(exc),
                    status="error",
                )
            detail = (proc.stdout or proc.stderr or "").strip()
            return HarnessRuntimeCommandResult(
                command_id=command_id,
                title="Claude Code version",
                detail=detail or f"claude --version exited {proc.returncode}",
                status="ok" if proc.returncode == 0 else "error",
                payload={"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr},
            )
        cli_command = _claude_management_command(command_id, args)
        terminal_handoff = _claude_management_terminal_handoff(command_id, args)
        if terminal_handoff is not None:
            return terminal_handoff
        if cli_command is not None:
            try:
                proc = subprocess.run(
                    cli_command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
            except Exception as exc:
                return HarnessRuntimeCommandResult(
                    command_id=command_id,
                    title="Claude Code command failed",
                    detail=str(exc),
                    status="error",
                    payload={"suggested_command": " ".join(cli_command)},
                )
            detail = (proc.stdout or proc.stderr or "").strip()
            return HarnessRuntimeCommandResult(
                command_id=command_id,
                title=f"Claude Code {command_id}",
                detail=detail or f"{' '.join(cli_command)} exited {proc.returncode}",
                status="ok" if proc.returncode == 0 else "terminal_handoff",
                payload={
                    "returncode": proc.returncode,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                    "suggested_command": " ".join(cli_command),
                },
            )
        return HarnessRuntimeCommandResult(
            command_id=command_id,
            title="Unsupported Claude Code command",
            detail=f"Claude Code native command {command_id!r} is not whitelisted.",
            status="unsupported",
        )


def _native_terminal_handoff(
    *,
    command_id: str,
    args: tuple[str, ...],
    suggested_command: str,
    detail: str,
) -> HarnessRuntimeCommandResult:
    return HarnessRuntimeCommandResult(
        command_id=command_id,
        title="Open terminal for native command",
        detail=detail,
        status="terminal_handoff",
        payload={"args": list(args), "suggested_command": suggested_command},
    )


def _claude_management_terminal_handoff(
    command_id: str,
    args: tuple[str, ...],
) -> HarnessRuntimeCommandResult | None:
    cleaned_args = tuple(arg.strip() for arg in args if arg and arg.strip())
    first = cleaned_args[0].lower() if cleaned_args else ""
    if command_id in {"plugins", "plugin"} and first in _CLAUDE_PLUGIN_MUTATING_SUBCOMMANDS:
        return _native_terminal_handoff(
            command_id=command_id,
            args=cleaned_args,
            suggested_command=" ".join(("claude", "plugin", *cleaned_args)),
            detail=(
                "Claude Code plugin management changes runtime-owned configuration. "
                "Open a terminal to run this interactive or mutating command."
            ),
        )
    if command_id == "mcp" and first in _CLAUDE_MCP_MUTATING_SUBCOMMANDS:
        return _native_terminal_handoff(
            command_id=command_id,
            args=cleaned_args,
            suggested_command=" ".join(("claude", "mcp", *cleaned_args)),
            detail=(
                "Claude Code MCP changes runtime-owned configuration or OAuth state. "
                "Open a terminal to run this interactive or mutating command."
            ),
        )
    return None


def _claude_management_command(command_id: str, args: tuple[str, ...]) -> list[str] | None:
    cleaned_args = [arg.strip() for arg in args if arg and arg.strip()]
    if command_id in {"plugins", "plugin"}:
        subcommand = cleaned_args or ["list"]
        return ["claude", "plugin", *subcommand]
    if command_id in {"skills", "mcp", "agents", "hooks"}:
        subcommand = cleaned_args or ["list"]
        return ["claude", command_id, *subcommand]
    if command_id in {"status", "doctor"}:
        return ["claude", command_id, *cleaned_args]
    return None


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


async def _pre_tool_use_continue_hook(*_args: Any, **_kwargs: Any) -> dict[str, str]:
    """Keep Claude Python streaming permission callbacks open.

    Current Claude Agent SDK docs require a PreToolUse hook that continues
    when using ``can_use_tool`` with streaming responses.
    """
    return {"decision": "continue"}


def _set_streaming_permission_hooks(
    options_cls: Any,
    options_kwargs: dict[str, Any],
) -> None:
    """Add the documented PreToolUse hook when the installed SDK accepts hooks."""
    try:
        sig = inspect.signature(options_cls)
    except (TypeError, ValueError):
        return
    has_var_kwargs = any(
        param.kind is inspect.Parameter.VAR_KEYWORD
        for param in sig.parameters.values()
    )
    if "hooks" not in sig.parameters and not has_var_kwargs:
        logger.warning(
            "claude-code: installed ClaudeAgentOptions exposes no hooks kwarg; "
            "can_use_tool may not fire reliably in streaming mode"
        )
        return
    hooks = dict(options_kwargs.get("hooks") or {})
    pre_tool_hooks = list(hooks.get("PreToolUse") or [])
    if _pre_tool_use_continue_hook not in pre_tool_hooks:
        pre_tool_hooks.append(_pre_tool_use_continue_hook)
    hooks["PreToolUse"] = pre_tool_hooks
    options_kwargs["hooks"] = hooks


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


def _set_env_kwarg(
    options_cls: Any,
    options_kwargs: dict[str, Any],
    env: Mapping[str, str],
) -> None:
    if not env:
        return
    try:
        sig = inspect.signature(options_cls)
        names = set(sig.parameters)
    except Exception:
        names = set(getattr(options_cls, "__annotations__", {}) or {})
    if "env" in names:
        options_kwargs["env"] = dict(env)
    elif "extra_env" in names:
        options_kwargs["extra_env"] = dict(env)
    else:
        logger.warning(
            "claude-code: installed ClaudeAgentOptions exposes no env kwarg; "
            "Project runtime env was not injected into this Claude turn"
        )


def _attach_claude_mcp_bridge(
    ctx: TurnContext,
    options_kwargs: dict[str, Any],
    specs: tuple[HarnessToolSpec, ...],
    *,
    bridge_results: dict[str, list[Any]] | None = None,
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
    server_name = "spindrel"
    allowed_tool_names = frozenset(spec.name for spec in specs)
    for spec in specs:
        parameters = spec.parameters or {"type": "object", "properties": {}}

        async def _handler(args: dict[str, Any], *, _name: str = spec.name) -> dict[str, Any]:
            result = await execute_harness_spindrel_tool_result(
                ctx,
                tool_name=_name,
                arguments=args,
                allowed_tool_names=allowed_tool_names,
            )
            text = result.text
            if _name == "get_tool_info":
                text = _rewrite_get_tool_info_for_claude_mcp(text, server_name=server_name)
            if bridge_results is not None and (
                result.envelope or result.surface or result.summary
            ):
                key = _claude_spindrel_result_key(
                    _claude_mcp_callable_name(_name, server_name=server_name),
                    args,
                    server_name=server_name,
                )
                bridge_results.setdefault(key, []).append(result)
            return {"content": [{"type": "text", "text": text or ""}]}

        try:
            sdk_tools.append(tool(spec.name, spec.description or spec.name, parameters)(_handler))
        except Exception:
            logger.exception("claude-code: failed to wrap Spindrel tool %s", spec.name)

    if not sdk_tools:
        return []

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


def _rewrite_get_tool_info_for_claude_mcp(text: str, *, server_name: str) -> str:
    """Rewrite discovery schemas to Claude's MCP-prefixed callable name."""
    try:
        payload = json.loads(text)
    except Exception:
        return text
    if not isinstance(payload, dict):
        return text
    schema = payload.get("schema")
    if not isinstance(schema, dict):
        return text
    fn = schema.get("function")
    if not isinstance(fn, dict):
        return text
    raw_name = fn.get("name")
    if not isinstance(raw_name, str) or not raw_name.strip():
        return text
    callable_name = _claude_mcp_callable_name(raw_name.strip(), server_name=server_name)
    if callable_name == raw_name and payload.get("callable_name") == callable_name:
        return text
    fn["name"] = callable_name
    payload["callable_name"] = callable_name
    payload["harness_bridge"] = {
        "runtime": "claude-code",
        "mcp_server": server_name,
        "canonical_tool_name": raw_name,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _claude_mcp_callable_name(name: str, *, server_name: str) -> str:
    prefix = f"mcp__{server_name}__"
    if name.startswith(prefix):
        return name
    if name.startswith("mcp__"):
        return prefix + name.removeprefix("mcp__")
    return prefix + name


def _claude_spindrel_result_key(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    server_name: str = "spindrel",
) -> str:
    canonical = tool_name
    prefix = f"mcp__{server_name}__"
    if canonical.startswith(prefix):
        canonical = canonical.removeprefix(prefix)
    try:
        args_key = json.dumps(arguments or {}, sort_keys=True, separators=(",", ":"))
    except TypeError:
        args_key = str(arguments or {})
    return f"{canonical}:{args_key}"


def _pop_claude_spindrel_tool_result(
    result_meta: dict[str, Any],
    *,
    tool_name: str,
    tool_input: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
    cache = result_meta.get("claude_spindrel_tool_results")
    if not isinstance(cache, dict):
        return None
    key = _claude_spindrel_result_key(tool_name, tool_input)
    queued = cache.get(key)
    if not isinstance(queued, list) or not queued:
        return None
    result = queued.pop(0)
    envelope = getattr(result, "envelope", None)
    summary = getattr(result, "summary", None)
    if not isinstance(envelope, dict):
        return None
    return envelope, summary if isinstance(summary, dict) else None


def _prompt_with_context_hints(prompt: str, ctx: TurnContext) -> str:
    return render_context_hints_for_prompt(
        prompt,
        ctx.context_hints,
        context_intro=(
            "The host application supplied these one-shot context hints for continuity. "
            "Treat them as context, not as direct user instructions."
        ),
    )


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
                tool_inputs = result_meta.setdefault("claude_tool_inputs", {})
                if isinstance(tool_inputs, dict):
                    tool_inputs[block.id] = block.input or {}
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
                    result_summary = _summarize_tool_result(block.content)
                    envelope = None
                    surface = None
                    summary = None
                    tool_inputs = result_meta.get("claude_tool_inputs")
                    tool_input = (
                        tool_inputs.get(block.tool_use_id)
                        if isinstance(tool_inputs, dict)
                        else None
                    )
                    if not block.is_error and isinstance(tool_input, dict):
                        rich = _build_claude_file_change_result(
                            tool_name=tool_name,
                            tool_call_id=block.tool_use_id,
                            tool_input=tool_input,
                        )
                        if rich is None:
                            rich = _pop_claude_spindrel_tool_result(
                                result_meta,
                                tool_name=tool_name,
                                tool_input=tool_input,
                            )
                        if rich:
                            envelope, summary = rich
                            envelope = {**envelope, "tool_call_id": block.tool_use_id}
                            surface = "rich_result"
                            result_summary = envelope["plain_body"]
                    if (
                        not block.is_error
                        and envelope is None
                        and tool_name in _TEXT_RESULT_TOOLS
                        and result_summary.strip()
                    ):
                        envelope, summary = build_text_tool_result(
                            tool_name=tool_name,
                            tool_call_id=block.tool_use_id,
                            body=result_summary,
                            label=None,
                        )
                        surface = "rich_result"
                        result_summary = envelope["plain_body"]
                    emit.tool_result(
                        tool_name=tool_name,
                        tool_call_id=block.tool_use_id,
                        result_summary=result_summary,
                        is_error=bool(block.is_error),
                        envelope=envelope,
                        surface=surface,
                        summary=summary,
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
        slash_commands = _extract_claude_system_slash_commands(msg)
        if slash_commands:
            result_meta["claude_native_slash_commands"] = slash_commands
        # System messages carry CLI metadata (init, task lifecycle, mirror
        # errors). None of them belong on the user-facing chat surface in v1.
        return


def _extract_claude_system_slash_commands(msg: Any) -> list[dict[str, Any]]:
    """Best-effort extraction of SDK system/init slash command inventory."""
    raw: Any
    if isinstance(msg, dict):
        raw = msg
    else:
        raw = getattr(msg, "__dict__", {})
    found = _find_slash_command_payload(raw)
    if isinstance(found, list):
        return [item for item in found if isinstance(item, dict)]
    return []


def _find_slash_command_payload(value: Any) -> Any:
    if isinstance(value, dict):
        if isinstance(value.get("slash_commands"), list):
            return value["slash_commands"]
        if isinstance(value.get("slashCommands"), list):
            return value["slashCommands"]
        for child in value.values():
            found = _find_slash_command_payload(child)
            if found is not None:
                return found
    if isinstance(value, (list, tuple)):
        for child in value:
            found = _find_slash_command_payload(child)
            if found is not None:
                return found
    return None


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


def _build_claude_file_change_result(
    *,
    tool_name: str,
    tool_call_id: str,
    tool_input: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Build a file-change envelope from Claude tool-call arguments.

    Claude's Edit tool carries both ``old_string`` and ``new_string`` in the
    runtime event. That is enough to display the patch without reading the
    workspace after the turn. Write carries the target content, so expose it as
    a text envelope and let the UI's existing code preview renderer color it.
    MultiEdit remains summary-only unless the runtime starts supplying a
    complete diff payload.
    """
    path = tool_input.get("file_path") or tool_input.get("path")
    if tool_name == "Write":
        content = tool_input.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            return None
        return build_text_tool_result(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            body=content,
            label=f"Wrote {path}",
            summary_kind="write",
            subject_type="file",
            path=path,
            preview_text=None,
        )

    if tool_name != "Edit":
        return None
    old = tool_input.get("old_string")
    new = tool_input.get("new_string")
    if not all(isinstance(value, str) for value in (path, old, new)):
        return None
    diff_body = unified_diff_from_strings(old=old, new=new, path=path)
    if not diff_body.strip():
        return None
    return build_diff_tool_result(
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        diff_body=diff_body,
        path=path,
    )


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
