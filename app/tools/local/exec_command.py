"""exec_command tool — runs shell commands on the host or inside a bot-local sandbox.

When the bot has bot_sandbox.enabled=True, commands are transparently routed into the
per-bot Docker container instead of the host. All other behaviour (access control,
result format) is identical.
"""
import json
import logging

from app.agent.bots import get_bot
from app.agent.context import current_bot_id
from app.services.host_exec import (
    HostExecAccessDeniedError,
    HostExecBlockedError,
    HostExecError,
    host_exec_service,
)
from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "exec_command",
        "description": (
            "Execute a shell command. "
            "Routes to the bot-local Docker sandbox when sandbox mode is enabled; "
            "otherwise runs on the host. "
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
                        "Absolute path to the working directory. "
                        "Required for host execution; optional when running in bot sandbox."
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

    # Route to bot-local sandbox if enabled
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

    # Host execution path
    if not working_dir:
        return json.dumps({"error": "missing_param", "message": "working_dir is required for host execution."})

    try:
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
