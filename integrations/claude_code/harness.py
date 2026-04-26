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

from app.services.agent_harnesses.base import (
    AuthStatus,
    ChannelEventEmitter,
    TurnResult,
)

logger = logging.getLogger(__name__)


# v1 default tool allowlist. ``acceptEdits`` only auto-approves Edit/Write;
# anything else (Bash, Glob, etc.) hits the SDK's prompter and would hang
# when there's no TUI on the other end. An explicit allowlist short-circuits
# the prompter for the listed tools.
DEFAULT_ALLOWED_TOOLS: tuple[str, ...] = (
    "Read",
    "Glob",
    "Grep",
    "Bash",
    "Edit",
    "Write",
    "Task",
    "WebFetch",
    "WebSearch",
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

    async def start_turn(
        self,
        *,
        workdir: str,
        prompt: str,
        session_id: str | None,
        emit: ChannelEventEmitter,
    ) -> TurnResult:
        # Late import keeps the SDK out of cold-startup paths and lets the
        # rest of the app boot when the SDK isn't installed (e.g. test envs).
        from claude_agent_sdk import (  # type: ignore
            ClaudeAgentOptions,
            ClaudeSDKClient,
        )

        if not os.path.isdir(workdir):
            raise RuntimeError(
                f"Harness workdir does not exist: {workdir!r}. "
                "Create it (mkdir + git clone your repo) before sending a message."
            )

        options_kwargs: dict[str, Any] = {
            "cwd": workdir,
            "allowed_tools": list(DEFAULT_ALLOWED_TOOLS),
            "permission_mode": "acceptEdits",
        }
        if session_id:
            options_kwargs["resume"] = session_id

        opts = ClaudeAgentOptions(**options_kwargs)

        # tool_use_id → tool_name lookup so ``ToolResultBlock`` (which only
        # carries tool_use_id) can publish a meaningful tool_name on result.
        tool_name_by_use_id: dict[str, str] = {}
        final_text_parts: list[str] = []
        result_meta: dict[str, Any] = {}

        async with ClaudeSDKClient(options=opts) as client:
            await client.query(prompt)
            async for msg in client.receive_response():
                _bridge_message(
                    msg,
                    emit=emit,
                    tool_name_by_use_id=tool_name_by_use_id,
                    final_text_parts=final_text_parts,
                    result_meta=result_meta,
                )

        # SDK guarantees a ResultMessage at end of stream; if it didn't fire
        # (network drop, etc.), fall back to the resume id we were given so
        # we don't lose the conversation thread.
        final_session_id = result_meta.get("session_id") or session_id or ""
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
                f"Run `claude login` inside the Spindrel container, "
                f"or bind-mount your host's $CLAUDE_CONFIG_DIR into the container."
            ),
        )


def _bridge_message(
    msg: Any,
    *,
    emit: ChannelEventEmitter,
    tool_name_by_use_id: dict[str, str],
    final_text_parts: list[str],
    result_meta: dict[str, Any],
) -> None:
    """Translate one SDK message into channel-event emitter calls.

    Pure function — all state mutation happens through the kwargs (the dicts
    and lists). Tested in ``tests/unit/test_claude_code_runtime_bridge.py``
    against real SDK dataclass instances.
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
    from app.services.agent_harnesses import register_runtime

    register_runtime(ClaudeCodeRuntime.name, ClaudeCodeRuntime())


_register()
