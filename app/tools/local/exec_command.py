"""exec_command tool — runs shell commands in the bot's workspace.

When the bot has workspace.enabled=True, commands route through the WorkspaceService
(Docker container or host, depending on workspace.type). Falls back to legacy
bot_sandbox / host_exec for bots not yet migrated to workspace config.
"""
import json
import logging

from app.agent.bots import get_bot
from app.agent.context import current_bot_id
from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "exec_command",
        "description": (
            "Execute a shell command in the bot's workspace. "
            "Routes to Docker container or host depending on workspace config. "
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
})
async def exec_command(command: str, working_dir: str = "") -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "no_bot_context", "message": "No bot context available."})

    bot = get_bot(bot_id)

    # New workspace path
    if bot.workspace.enabled:
        try:
            from app.services.workspace import workspace_service
            result = await workspace_service.exec(bot_id, command, bot.workspace, working_dir)
            return json.dumps({
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "truncated": result.truncated,
                "duration_ms": result.duration_ms,
                "workspace_type": result.workspace_type,
            })
        except Exception as e:
            return json.dumps({"error": "workspace_error", "message": str(e)})

    # Legacy: bot_sandbox path
    if bot.bot_sandbox.enabled:
        if not bot.bot_sandbox.image:
            return json.dumps({"error": "config_error", "message": "bot_sandbox.image is not set."})
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
            })
        except Exception as e:
            return json.dumps({"error": "sandbox_error", "message": str(e)})

    # Legacy: host execution path
    if not working_dir:
        return json.dumps({"error": "missing_param", "message": "working_dir is required for host execution."})

    try:
        from app.services.host_exec import (
            HostExecAccessDeniedError,
            HostExecBlockedError,
            HostExecError,
            host_exec_service,
        )
        result = await host_exec_service.run(command, working_dir, bot.host_exec)
    except HostExecAccessDeniedError as e:
        return json.dumps({"error": "access_denied", "message": str(e)})
    except HostExecBlockedError as e:
        return json.dumps({"error": "blocked", "message": str(e)})
    except HostExecError as e:
        return json.dumps({"error": "exec_error", "message": str(e)})
    except Exception as e:
        return json.dumps({"error": "unexpected_error", "message": str(e)})

    return json.dumps({
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "truncated": result.truncated,
        "duration_ms": result.duration_ms,
        "dry_run": result.dry_run,
    })
