"""run_script — programmatic tool calling via a Python script in the bot's workspace.

Pattern:
    The bot writes a short Python script. We drop ``spindrel.py`` next to it,
    run ``python script.py`` in the shared workspace, capture stdout/stderr,
    and return them. Any ``tools.NAME(**kwargs)`` call inside the script POSTs
    to ``/api/v1/internal/tools/exec`` with the per-bot scoped API key — so
    the script orchestrates many tool calls in one round-trip without
    dragging intermediate JSON through model context.

Use this over a chain of individual tool calls when:
    - You'd otherwise loop the model: "for each X, get Y" patterns
    - Filtering / aggregating tool output before responding
    - Joining results from two or more tools

Output schemas:
    Tools listed by ``list_tool_signatures`` declare their return shape.
    Use that to know what fields to access in your script.
"""
from __future__ import annotations

import json
import logging
import shlex

from app.agent.context import current_bot_id, current_correlation_id, current_channel_id
from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "run_script",
        "description": (
            "Run a short Python script in your workspace that can call any tool "
            "you have access to as `tools.NAME(**kwargs)`. Use this for multi-step "
            "tool work — 'for each X, get Y' loops, filtering across lists, "
            "joining results from two tools — instead of a chain of individual "
            "tool calls. Only what you `print()` returns to context, so intermediate "
            "data stays out. Call `list_tool_signatures()` first if you don't know "
            "the return shape of the tools you want to compose. Use `tools.signatures()` "
            "or `tools.call(name, **kwargs)` from inside the script too."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": (
                        "Python source to execute. Auto-imports `from spindrel import tools`; "
                        "use `tools.tool_name(**kwargs)` to dispatch. Print the distilled "
                        "result you want returned. Raises ToolError on policy deny / "
                        "approval-required / network errors — `try/except` if you want "
                        "to handle gracefully."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": (
                        "One-sentence description of what this script does. Surfaces in "
                        "the trace and in any approval prompt."
                    ),
                },
                "timeout_s": {
                    "type": "integer",
                    "description": "Max script wall-clock time (default 60, max 300).",
                },
            },
            "required": ["script", "description"],
        },
    },
}, safety_tier="exec_capable", requires_bot_context=True, returns={
    "type": "object",
    "properties": {
        "stdout": {"type": "string"},
        "stderr": {"type": "string"},
        "exit_code": {"type": "integer"},
        "duration_ms": {"type": "integer"},
        "truncated": {"type": "boolean"},
        "script_dir": {"type": "string", "description": "Workspace path of the scratch dir (kept for debug)"},
        "error": {"type": "string"},
    },
    "required": ["exit_code"],
})
async def run_script(script: str, description: str, timeout_s: int = 60) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "no_bot_context", "exit_code": -1}, ensure_ascii=False)

    if not script or not script.strip():
        return json.dumps({"error": "empty_script", "exit_code": -1}, ensure_ascii=False)

    try:
        timeout_clamped = max(5, min(int(timeout_s or 60), 300))
    except (TypeError, ValueError):
        timeout_clamped = 60

    from app.agent.bots import get_bot
    bot = get_bot(bot_id)
    if not bot or not bot.workspace.enabled:
        return json.dumps(
            {"error": "workspace_not_enabled", "exit_code": -1,
             "hint": "run_script requires a shared workspace; this bot has none."},
            ensure_ascii=False,
        )

    from app.services.workspace import workspace_service
    from app.services.script_runner import (
        prepare_scratch_dir,
        write_script_files,
        cleanup_scratch_dir,
    )

    workspace_root = workspace_service.get_workspace_root(bot_id, bot)
    correlation_id = current_correlation_id.get(None)
    channel_id = current_channel_id.get(None)

    scratch = prepare_scratch_dir(
        workspace_root,
        str(correlation_id) if correlation_id else None,
    )
    script_path, helper_path = write_script_files(scratch, script)

    # Compose the shell command. We export the parent correlation id + channel
    # id as env vars so the helper can stitch them onto every dispatched call.
    env_exports: list[str] = []
    if correlation_id:
        env_exports.append(f"export SPINDREL_PARENT_CORRELATION_ID={shlex.quote(str(correlation_id))}")
    if channel_id:
        env_exports.append(f"export SPINDREL_CHANNEL_ID={shlex.quote(str(channel_id))}")
    env_exports.append(f"export SPINDREL_TOOL_TIMEOUT={timeout_clamped}")

    # Use python3 (most workspaces alias both, but python3 is safer on hosts
    # where python is python2). The cwd is set to the scratch dir so spindrel.py
    # imports cleanly from the script's local dir.
    script_dir_str = str(scratch)
    full_cmd = " && ".join([
        *env_exports,
        f"cd {shlex.quote(script_dir_str)}",
        "python3 script.py",
    ])

    # Open the inner-tool-call budget for this script. Keyed by the parent
    # correlation id so /api/v1/internal/tools/exec can look it up on each
    # dispatch. None/missing correlation id → no budget (call is untracked),
    # matching the behavior of every other correlation-keyed subsystem.
    from app.config import settings as _cfg
    from app.services.script_budget import (
        close_budget as _close_budget,
        open_budget as _open_budget,
    )
    budget_key = str(correlation_id) if correlation_id else None
    budget_limit = bot.max_script_tool_calls or _cfg.AGENT_MAX_SCRIPT_TOOL_CALLS
    if budget_key:
        await _open_budget(budget_key, budget_limit)

    keep_scratch = False
    try:
        result = await workspace_service.exec(
            bot_id, full_cmd, bot.workspace,
            working_dir=script_dir_str, bot=bot,
        )
        payload: dict = {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "truncated": result.truncated,
            "script_dir": script_dir_str,
            "workspace_type": result.workspace_type,
        }
        if budget_key:
            spent_limit = await _close_budget(budget_key)
            if spent_limit is not None:
                spent, limit = spent_limit
                payload["tool_calls_used"] = spent
                payload["tool_calls_limit"] = limit
        # Keep scratch dir on non-zero exit so the bot can inspect / re-run.
        keep_scratch = result.exit_code != 0
        if result.exit_code != 0:
            payload["hint"] = (
                f"Script exited non-zero. Scratch dir preserved at {script_dir_str} for inspection. "
                "Read script.py + spindrel.py + stderr to diagnose."
            )
        return json.dumps(payload, ensure_ascii=False)
    except Exception as exc:
        logger.exception("run_script: exec failed for bot %s", bot_id)
        keep_scratch = True
        return json.dumps({
            "error": "exec_failed",
            "exit_code": -1,
            "message": str(exc),
            "script_dir": script_dir_str,
        }, ensure_ascii=False)
    finally:
        if budget_key:
            await _close_budget(budget_key)
        if not keep_scratch:
            cleanup_scratch_dir(scratch)
