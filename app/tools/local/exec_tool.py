"""delegate_to_exec — raw command execution inside a bot sandbox."""
import json
import logging
import shlex
import uuid
from datetime import datetime, timezone

from app.agent.context import (
    current_bot_id,
    current_client_id,
    current_correlation_id,
    current_dispatch_config,
    current_dispatch_type,
    current_session_id,
)
from app.tools.registry import register

logger = logging.getLogger(__name__)

EXEC_OUTPUT_DIR = "/tmp/exec-output"
SAFE_STREAM_PREFIXES = ("/tmp/",)


def _validate_stream_to(path: str) -> str | None:
    """Return an error message if stream_to path is unsafe, else None."""
    if not any(path.startswith(p) for p in SAFE_STREAM_PREFIXES):
        return f"stream_to must start with one of {SAFE_STREAM_PREFIXES}"
    if "\n" in path or "\x00" in path:
        return "stream_to contains invalid characters"
    return None


def build_exec_script(
    command: str,
    args: list[str] | None,
    working_directory: str | None,
    stream_to: str | None,
) -> str:
    """Build a shell script for sandbox execution with optional tee wrapper."""
    argv = [command] + (args or [])
    inner = shlex.join(argv)

    parts: list[str] = []

    if working_directory:
        parts.append(f"cd {shlex.quote(working_directory)}")

    if stream_to:
        # mkdir + tee wrapper; portable exit-code capture (no PIPESTATUS)
        exit_file = f"{EXEC_OUTPUT_DIR}/.exit_code"
        parts.append(f"mkdir -p {shlex.quote(EXEC_OUTPUT_DIR)}")
        parts.append(
            f"{{ {inner} ; echo $? > {shlex.quote(exit_file)} ; }} 2>&1"
            f" | tee {shlex.quote(stream_to)}; "
            f"exit $(cat {shlex.quote(exit_file)})"
        )
    else:
        parts.append(inner)

    return " && ".join(parts)


@register({
    "type": "function",
    "function": {
        "name": "delegate_to_exec",
        "description": (
            "Run any shell command inside the bot's sandbox (docker container). "
            "Use mode=sync (default) to wait for the result. "
            "Use mode=deferred for background execution; result posts to the channel when done. "
            "Output is written to a log file that can be tailed mid-run via exec_sandbox. "
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Executable name (e.g. python, npm, curl).",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Arguments to pass to the command.",
                },
                "working_directory": {
                    "type": "string",
                    "description": "Working directory inside the container.",
                },
                "sandbox_instance_id": {
                    "type": "string",
                    "description": (
                        "Optional UUID of a specific sandbox instance. "
                        "If omitted, falls back to the bot's bot_sandbox config."
                    ),
                },
                "stream_to": {
                    "type": "string",
                    "description": (
                        "File path inside the container for live output (tee'd). "
                        "Must start with /tmp/. If omitted in deferred mode, defaults to "
                        "/tmp/exec-output/<task_id>.log."
                    ),
                },
                "mode": {
                    "type": "string",
                    "enum": ["sync", "deferred"],
                    "default": "sync",
                    "description": (
                        "sync (default): wait for command to finish and return output. "
                        "deferred: run in background, post result to channel when done."
                    ),
                },
                "reply_in_thread": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Deferred mode only. Post result as a Slack thread reply."
                    ),
                },
                "notify_parent": {
                    "type": "boolean",
                    "default": True,
                    "description": (
                        "Deferred mode only. Re-run parent agent with the result when complete."
                    ),
                },
            },
            "required": ["command"],
        },
    },
})
async def delegate_to_exec(
    command: str,
    args: list[str] | None = None,
    working_directory: str | None = None,
    sandbox_instance_id: str | None = None,
    stream_to: str | None = None,
    mode: str = "sync",
    reply_in_thread: bool = False,
    notify_parent: bool = True,
) -> str:
    # Coerce string booleans from LLMs
    if isinstance(reply_in_thread, str):
        reply_in_thread = reply_in_thread.strip().lower() not in ("false", "0", "no", "")
    if isinstance(notify_parent, str):
        notify_parent = notify_parent.strip().lower() not in ("false", "0", "no", "")

    from app.agent.bots import get_bot

    parent_bot_id = current_bot_id.get() or "default"
    try:
        bot = get_bot(parent_bot_id)
    except Exception as exc:
        return json.dumps({"error": f"Could not load bot: {exc}"})

    # Validate stream_to if provided
    if stream_to:
        err = _validate_stream_to(stream_to)
        if err:
            return json.dumps({"error": err})

    # Validate working_directory
    if working_directory:
        wd = working_directory.strip()
        if "\n" in wd or "\x00" in wd:
            return json.dumps({"error": "Invalid working directory."})
        working_directory = wd

    # Parse sandbox_instance_id
    sbx: uuid.UUID | None = None
    if sandbox_instance_id:
        try:
            sbx = uuid.UUID(str(sandbox_instance_id).strip())
        except (ValueError, TypeError):
            return json.dumps({"error": f"Invalid sandbox_instance_id: {sandbox_instance_id}"})

    if mode == "deferred":
        return await _exec_deferred(
            command=command,
            args=args,
            working_directory=working_directory,
            sandbox_instance_id=sbx,
            stream_to=stream_to,
            bot_id=parent_bot_id,
            reply_in_thread=reply_in_thread,
            notify_parent=notify_parent,
        )

    # Sync mode
    return await _exec_sync(
        command=command,
        args=args,
        working_directory=working_directory,
        sandbox_instance_id=sbx,
        stream_to=stream_to,
        bot=bot,
    )


async def _exec_sync(
    *,
    command: str,
    args: list[str] | None,
    working_directory: str | None,
    sandbox_instance_id: uuid.UUID | None,
    stream_to: str | None,
    bot,
) -> str:
    """Execute command synchronously in sandbox and return result."""
    from app.config import settings
    from app.services.sandbox import sandbox_service

    script = build_exec_script(command, args, working_directory, stream_to)

    try:
        if sandbox_instance_id is not None:
            if not settings.DOCKER_SANDBOX_ENABLED:
                return json.dumps({"error": "DOCKER_SANDBOX_ENABLED is false."})
            allowed = bot.docker_sandbox_profiles or None
            instance = await sandbox_service.get_instance_for_bot(
                sandbox_instance_id, bot.id, allowed_profiles=allowed
            )
            if instance is None:
                return json.dumps({"error": "Sandbox instance not found or not allowed."})
            exec_res = await sandbox_service.exec(instance, script)
        elif bot.bot_sandbox.enabled:
            exec_res = await sandbox_service.exec_bot_local(bot.id, script, bot.bot_sandbox)
        else:
            return json.dumps({"error": "No sandbox available. Enable bot_sandbox or provide sandbox_instance_id."})

        output: dict = {
            "exit_code": exec_res.exit_code,
            "duration_ms": exec_res.duration_ms,
        }
        if exec_res.truncated:
            output["truncated"] = True
        if exec_res.stdout:
            output["stdout"] = exec_res.stdout
        if exec_res.stderr:
            output["stderr"] = exec_res.stderr
        if stream_to:
            output["output_file"] = stream_to
        return json.dumps(output)

    except Exception as exc:
        logger.exception("delegate_to_exec sync failed")
        return json.dumps({"error": str(exc)})


async def _exec_deferred(
    *,
    command: str,
    args: list[str] | None,
    working_directory: str | None,
    sandbox_instance_id: uuid.UUID | None,
    stream_to: str | None,
    bot_id: str,
    reply_in_thread: bool,
    notify_parent: bool,
) -> str:
    """Create a deferred exec task."""
    from app.db.engine import async_session
    from app.db.models import Task

    session_id = current_session_id.get()
    client_id = current_client_id.get()
    dispatch_type = current_dispatch_type.get()
    dispatch_config = dict(current_dispatch_config.get() or {})
    src_corr = current_correlation_id.get()

    delivery_config = dict(dispatch_config)
    delivery_config["reply_in_thread"] = reply_in_thread

    callback_cfg: dict = {
        "command": command,
        "args": args or [],
        "working_directory": working_directory,
        "output_dispatch_type": dispatch_type or "none",
        "output_dispatch_config": delivery_config,
    }
    if stream_to:
        callback_cfg["stream_to"] = stream_to
    if sandbox_instance_id is not None:
        callback_cfg["sandbox_instance_id"] = str(sandbox_instance_id)
    if notify_parent and session_id is not None:
        callback_cfg["notify_parent"] = True
        callback_cfg["parent_bot_id"] = bot_id
        callback_cfg["parent_session_id"] = str(session_id)
        if client_id:
            callback_cfg["parent_client_id"] = client_id
    if src_corr is not None:
        callback_cfg["source_correlation_id"] = str(src_corr)

    task = Task(
        bot_id=bot_id,
        client_id=client_id,
        session_id=session_id,
        prompt=f"{command} {shlex.join(args or [])}".strip(),
        status="pending",
        dispatch_type="exec",
        dispatch_config={},
        callback_config=callback_cfg,
    )
    async with async_session() as db:
        db.add(task)
        await db.commit()
        await db.refresh(task)

    # Determine output file path (use stream_to if set, else deterministic path)
    output_file = stream_to or f"{EXEC_OUTPUT_DIR}/{task.id}.log"
    # Patch stream_to into callback_config if it wasn't explicitly set
    if not stream_to:
        callback_cfg["stream_to"] = output_file
        async with async_session() as db:
            t = await db.get(Task, task.id)
            if t:
                t.callback_config = callback_cfg
                await db.commit()

    logger.info("Deferred exec task created: %s (command=%s)", task.id, command)
    return json.dumps({
        "task_id": str(task.id),
        "status": "deferred",
        "output_file": output_file,
    })
