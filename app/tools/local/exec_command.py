"""exec_command tool — runs shell commands in the bot's workspace.

When the bot has workspace.enabled=True, commands route through the shared
WorkspaceService server-subprocess path. Falls back to legacy bot_sandbox /
host_exec for old configs that are not in a shared workspace.
"""
import json
import logging

from app.agent.bots import get_bot
from app.agent.context import current_bot_id, current_channel_id
from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "exec_command",
        "description": (
            "Execute a shell command in the bot's workspace. "
            "Runs as a server-side subprocess against the shared workspace. "
            "Supports pipes, shell features, and chaining (&&, ||). "
            "Use for build commands, git operations, file manipulation, running scripts, etc. "
            "For commands with verbose output (package managers, compilers, build tools), "
            "use quiet flags to avoid filling context: apt-get install -qq -y, pip install -q, "
            "npm install --silent, make -s, cargo build -q, etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "Shell command to run. "
                        "Example: 'git log --oneline -10 | grep feat' "
                        "or 'cd src && python3 -m pytest tests/ -v'"
                    ),
                },
                "working_dir": {
                    "type": "string",
                    "description": (
                        "Working directory inside the workspace. "
                        "For Docker workspaces, defaults to /workspace. "
                        "For host workspaces, defaults to the workspace root."
                    ),
                },
            },
            "required": ["command"],
        },
    },
}, safety_tier="exec_capable", requires_bot_context=True, returns={
    "type": "object",
    "properties": {
        "stdout": {"type": "string"},
        "stderr": {"type": "string"},
        "exit_code": {"type": "integer"},
        "truncated": {"type": "boolean"},
        "duration_ms": {"type": "number"},
        "workspace_type": {"type": "string"},
        "sandbox": {"type": "string"},
        "dry_run": {"type": "boolean"},
        "error": {"type": "string"},
        "message": {"type": "string"},
    },
})
async def exec_command(command: str, working_dir: str = "") -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "no_bot_context", "message": "No bot context available."}, ensure_ascii=False)

    bot = get_bot(bot_id)

    # Workspace execution (all bots are in shared workspace, workspace.enabled is always true)
    if bot.workspace.enabled:
        # --- Bot hooks: before_access ---
        from app.services.bot_hooks import run_before_access, run_after_exec, schedule_after_write
        effective_working_dir = working_dir or "/workspace"
        runtime_env = None
        ch_id = current_channel_id.get()
        if ch_id is not None:
            try:
                from app.db.engine import async_session
                from app.services.project_runtime import load_project_runtime_environment_for_id
                from app.services.projects import is_project_like_surface, resolve_channel_work_surface_by_id

                async with async_session() as db:
                    surface = await resolve_channel_work_surface_by_id(db, ch_id, bot)
                    if is_project_like_surface(surface):
                        if not working_dir:
                            working_dir = surface.root_host_path
                            effective_working_dir = working_dir
                        if surface.project_id:
                            runtime_env = await load_project_runtime_environment_for_id(db, surface.project_id)
            except Exception:
                logger.debug("Could not resolve project runtime for exec_command", exc_info=True)
        block_err = await run_before_access(bot_id, effective_working_dir)
        if block_err:
            return json.dumps({"error": "hook_blocked", "message": block_err}, ensure_ascii=False)

        try:
            from app.services.workspace import workspace_service
            result = await workspace_service.exec(
                bot_id,
                command,
                bot.workspace,
                working_dir,
                bot=bot,
                extra_env=dict(runtime_env.env) if runtime_env is not None else None,
                redact_output=runtime_env.redact_text if runtime_env is not None else None,
            )

            # --- Bot hooks: after_exec + after_write ---
            await run_after_exec(bot_id, effective_working_dir)
            schedule_after_write(bot_id, effective_working_dir)

            return json.dumps({
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "truncated": result.truncated,
                "duration_ms": result.duration_ms,
                "workspace_type": result.workspace_type,
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": "workspace_error", "message": str(e)}, ensure_ascii=False)

    # Legacy: bot_sandbox path
    if bot.bot_sandbox.enabled:
        if not bot.bot_sandbox.image:
            return json.dumps({"error": "config_error", "message": "bot_sandbox.image is not set."}, ensure_ascii=False)
        try:
            from app.services.sandbox import sandbox_service
            result = await sandbox_service.exec_bot_local(bot_id, command, bot.bot_sandbox)
            return json.dumps({
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "truncated": result.truncated,
                "duration_ms": result.duration_ms,
                "sandbox": "bot-local",
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": "sandbox_error", "message": str(e)}, ensure_ascii=False)

    # Legacy: host execution path
    if not working_dir:
        return json.dumps({"error": "missing_param", "message": "working_dir is required for host execution."}, ensure_ascii=False)

    try:
        from app.services.host_exec import (
            HostExecAccessDeniedError,
            HostExecBlockedError,
            HostExecError,
            host_exec_service,
        )
        result = await host_exec_service.run(command, working_dir, bot.host_exec)
    except HostExecAccessDeniedError as e:
        return json.dumps({"error": "access_denied", "message": str(e)}, ensure_ascii=False)
    except HostExecBlockedError as e:
        return json.dumps({"error": "blocked", "message": str(e)}, ensure_ascii=False)
    except HostExecError as e:
        return json.dumps({"error": "exec_error", "message": str(e)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "unexpected_error", "message": str(e)}, ensure_ascii=False)

    return json.dumps({
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "truncated": result.truncated,
        "duration_ms": result.duration_ms,
        "dry_run": result.dry_run,
    }, ensure_ascii=False)
