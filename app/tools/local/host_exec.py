"""Host shell execution tool."""
import json

from app.agent.bots import get_bot
from app.agent.context import current_bot_id
from app.services.host_exec import (
    HostExecAccessDeniedError,
    HostExecBlockedError,
    HostExecError,
    host_exec_service,
)
from app.tools.registry import register


@register({
    "type": "function",
    "function": {
        "name": "run_host_command",
        "description": (
            "Execute a shell command on the host system. "
            "Supports pipes, shell features, and chaining (&&, ||). "
            "Use for build commands, git operations, file manipulation, running scripts, etc."
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
                    "description": "Absolute path to the working directory. Must be within an allowed path.",
                },
            },
            "required": ["command", "working_dir"],
        },
    },
})
async def run_host_command(command: str, working_dir: str) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "no_bot_context", "message": "No bot context available."})

    bot = get_bot(bot_id)

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
