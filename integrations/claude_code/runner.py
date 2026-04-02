"""Shared runner for executing Claude Code CLI inside Docker workspace containers.

Both the sync tool (run_claude_code) and deferred executor call through here.
Execution uses sandbox_service.exec_bot_local() — the claude CLI must be
available inside the bot's workspace Docker image.
"""
from __future__ import annotations

import json
import logging
import shlex
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ClaudeCodeResult:
    """Structured result from a Claude Code CLI invocation."""

    result: str = ""
    session_id: str | None = None
    is_error: bool = False
    cost_usd: float | None = None
    num_turns: int | None = None
    duration_ms: int | None = None
    duration_api_ms: int | None = None
    exit_code: int = 0
    stderr: str = ""


def build_claude_cli_args(
    *,
    max_turns: int | None = None,
    model: str | None = None,
    permission_mode: str | None = None,
    system_prompt: str | None = None,
    resume_session_id: str | None = None,
    allowed_tools: list[str] | None = None,
) -> list[str]:
    """Build CLI argument list for the claude command.

    Always includes --output-format json. Other flags are added based on
    non-None parameters.
    """
    args: list[str] = ["--output-format", "json"]

    if permission_mode == "bypassPermissions":
        args.append("--dangerously-skip-permissions")

    if max_turns is not None:
        args.extend(["--max-turns", str(max_turns)])

    if model:
        args.extend(["--model", model])

    if system_prompt:
        args.extend(["--system-prompt", system_prompt])

    if resume_session_id:
        args.extend(["--resume", resume_session_id])

    if allowed_tools:
        for tool in allowed_tools:
            args.extend(["--allowedTools", tool])

    return args


def build_script(
    prompt: str,
    cli_args: list[str],
    working_directory: str | None = None,
) -> str:
    """Build a shell script that pipes the prompt to claude via heredoc stdin.

    Uses a heredoc pattern to safely pass the prompt via stdin.
    """
    inner = shlex.join(["claude"] + cli_args + ["-p"])
    delim = f"__CLAUDE_PROMPT_{uuid.uuid4().hex[:8]}__"
    if working_directory:
        return f"cd {shlex.quote(working_directory)} && {inner} <<'{delim}'\n{prompt}\n{delim}"
    return f"{inner} <<'{delim}'\n{prompt}\n{delim}"


def parse_exec_result(stdout: str, stderr: str, exit_code: int, duration_ms: int) -> ClaudeCodeResult:
    """Parse docker exec output into a ClaudeCodeResult.

    Uses the same JSON parsing logic as _parse_claude_json_output in tasks.py.
    Falls back to raw stdout if JSON parsing fails.
    """
    result = ClaudeCodeResult(
        exit_code=exit_code,
        stderr=stderr,
        duration_ms=duration_ms,
    )

    # Try parsing Claude Code --output-format json output
    parsed = _parse_json_output(stdout)
    if parsed is not None:
        result.result = parsed.get("result", "")
        result.session_id = parsed.get("session_id")
        result.is_error = parsed.get("is_error", False)
        result.cost_usd = parsed.get("cost_usd")
        result.num_turns = parsed.get("num_turns")
        result.duration_api_ms = parsed.get("duration_api_ms")
    elif exit_code != 0:
        # Non-zero exit with no JSON — treat stdout as error message
        result.result = stdout.strip() if stdout else f"claude exited with code {exit_code}"
        result.is_error = True
    else:
        # Success exit but no JSON — return raw stdout
        result.result = stdout.strip()

    return result


def _parse_json_output(stdout: str) -> dict | None:
    """Parse Claude Code --output-format json output.

    Returns the parsed dict if stdout is a valid Claude Code JSON result
    (has "type": "result"), otherwise None.
    """
    if not stdout or not stdout.strip().startswith("{"):
        return None
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("type") != "result":
        return None
    return data


async def run_in_container(
    *,
    bot_id: str,
    prompt: str,
    working_directory: str | None = None,
    max_turns: int | None = None,
    system_prompt: str | None = None,
    resume_session_id: str | None = None,
    allowed_tools: list[str] | None = None,
    timeout: int | None = None,
) -> ClaudeCodeResult:
    """Execute Claude Code CLI inside the bot's Docker workspace container.

    Builds the CLI command, runs it via exec_bot_local, and parses the JSON output.

    Raises ValueError if the bot has no Docker workspace configured.
    """
    from app.agent.bots import get_bot
    from app.services.sandbox import sandbox_service, workspace_to_sandbox_config
    from integrations.claude_code.config import settings as cc_settings

    bot = get_bot(bot_id)

    # Validate workspace docker config
    if not bot.workspace or not bot.workspace.enabled:
        raise ValueError(
            f"Bot {bot_id!r} has no workspace enabled. "
            "Claude Code requires workspace.enabled=true with workspace.type=docker."
        )
    if not bot.workspace.docker or not bot.workspace.docker.image:
        raise ValueError(
            f"Bot {bot_id!r} has no Docker workspace configured. "
            "Claude Code requires workspace.type=docker with an image that has the claude CLI installed."
        )

    # Resolve effective settings
    effective_max_turns = max_turns if max_turns is not None else cc_settings.MAX_TURNS
    effective_allowed = allowed_tools if allowed_tools is not None else cc_settings.ALLOWED_TOOLS
    effective_timeout = timeout if timeout is not None else cc_settings.TIMEOUT

    # Build CLI args
    cli_args = build_claude_cli_args(
        max_turns=effective_max_turns,
        model=cc_settings.MODEL,
        permission_mode=cc_settings.PERMISSION_MODE,
        system_prompt=system_prompt,
        resume_session_id=resume_session_id,
        allowed_tools=effective_allowed,
    )

    # Resolve container working directory
    container_wd = "/workspace"
    if working_directory:
        container_wd = f"/workspace/{working_directory}"

    # Build script
    script = build_script(prompt, cli_args, working_directory=container_wd)

    # Get sandbox config from workspace config
    sandbox_config = workspace_to_sandbox_config(bot)

    logger.info(
        "[claude_code] exec bot=%s image=%r wd=%s timeout=%ds",
        bot_id, sandbox_config.image, container_wd, effective_timeout,
    )

    # Execute in container
    exec_result = await sandbox_service.exec_bot_local(
        bot_id,
        script,
        sandbox_config,
        timeout=effective_timeout,
    )

    return parse_exec_result(
        stdout=exec_result.stdout,
        stderr=exec_result.stderr,
        exit_code=exec_result.exit_code,
        duration_ms=exec_result.duration_ms,
    )
