"""Task worker: runs scheduled/deferred agent tasks and dispatches results."""
import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

import openai
from sqlalchemy import select

from app.agent import dispatchers
from app.agent.bots import get_bot
from app.config import settings
from app.db.engine import async_session
from app.db.models import Channel, Session, Task
from app.services import session_locks

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Recurrence helpers
# ---------------------------------------------------------------------------

_RELATIVE_RE = re.compile(r"^\+(\d+)([smhd])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _parse_recurrence(value: str) -> timedelta | None:
    """Parse a relative offset like +1h, +30m, +1d into a timedelta."""
    m = _RELATIVE_RE.match(value.strip())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return timedelta(seconds=n * _UNIT_SECONDS[unit])


async def _spawn_from_schedule(schedule_id: uuid.UUID) -> None:
    """Spawn a concrete one-off task from an active schedule template.

    Atomically: create the concrete task, advance schedule.scheduled_at, bump run_count.
    """
    async with async_session() as db:
        schedule = await db.get(Task, schedule_id)
        if schedule is None or schedule.status != "active" or not schedule.recurrence:
            return

        interval = _parse_recurrence(schedule.recurrence)
        if not interval:
            logger.warning("Schedule %s has invalid recurrence %r — skipping", schedule.id, schedule.recurrence)
            return

        # Resolve latest content from linked template or workspace file (if any)
        from app.services.prompt_resolution import resolve_prompt
        prompt = await resolve_prompt(
            workspace_id=str(schedule.workspace_id) if schedule.workspace_id else None,
            workspace_file_path=schedule.workspace_file_path,
            template_id=str(schedule.prompt_template_id) if schedule.prompt_template_id else None,
            inline_prompt=schedule.prompt,
            db=db,
        )

        # Create concrete execution task
        concrete = Task(
            bot_id=schedule.bot_id,
            client_id=schedule.client_id,
            session_id=schedule.session_id,
            channel_id=schedule.channel_id,
            prompt=prompt,
            title=schedule.title,
            prompt_template_id=schedule.prompt_template_id,
            workspace_file_path=schedule.workspace_file_path,
            workspace_id=schedule.workspace_id,
            scheduled_at=schedule.scheduled_at,
            status="pending",
            task_type=schedule.task_type,
            dispatch_type=schedule.dispatch_type,
            dispatch_config=dict(schedule.dispatch_config) if schedule.dispatch_config else None,
            callback_config=dict(schedule.callback_config) if schedule.callback_config else None,
            execution_config=dict(schedule.execution_config) if schedule.execution_config else None,
            recurrence=None,  # concrete task, not a schedule
            parent_task_id=schedule.id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(concrete)

        # Advance schedule to next occurrence
        base = schedule.scheduled_at or datetime.now(timezone.utc)
        schedule.scheduled_at = base + interval
        schedule.run_count = (schedule.run_count or 0) + 1

        await db.commit()
        logger.info(
            "Schedule %s spawned concrete task %s (run #%d), next at %s",
            schedule.id, concrete.id, schedule.run_count,
            schedule.scheduled_at.strftime("%Y-%m-%d %H:%M UTC"),
        )


async def spawn_due_schedules() -> None:
    """Find active schedule templates that are due and spawn concrete tasks."""
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        stmt = (
            select(Task.id)
            .where(Task.status == "active")
            .where(Task.recurrence.isnot(None))
            .where(Task.scheduled_at <= now)
            .limit(50)
        )
        schedule_ids = list((await db.execute(stmt)).scalars().all())

    for sid in schedule_ids:
        try:
            await _spawn_from_schedule(sid)
        except Exception:
            logger.exception("Failed to spawn from schedule %s", sid)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _harness_source_correlation(cfg: dict) -> uuid.UUID | None:
    raw = cfg.get("source_correlation_id")
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _harness_sandbox_instance(cfg: dict) -> uuid.UUID | None:
    raw = cfg.get("sandbox_instance_id")
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _parse_claude_json_output(stdout: str) -> dict | None:
    """Try to parse Claude Code --output-format json output.

    Returns the parsed dict if stdout is a valid Claude Code JSON result
    (has "type": "result"), otherwise None for backwards compat with
    non-JSON harnesses.
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


async def run_harness_task(task: Task) -> None:
    """Execute a harness task: run the subprocess, store result, dispatch to output channel."""
    logger.info("Running harness task %s", task.id)
    now = datetime.now(timezone.utc)

    async with async_session() as db:
        t = await db.get(Task, task.id)
        if t is None:
            return
        t.status = "running"
        t.run_at = now
        await db.commit()

    # Read execution params from execution_config (new) with fallback to callback_config (legacy)
    ecfg = task.execution_config or task.callback_config or {}
    cfg = task.callback_config or {}
    harness_name = ecfg.get("harness_name", "")
    working_directory = ecfg.get("working_directory")
    output_dispatch_type = ecfg.get("output_dispatch_type", task.dispatch_type or "none")
    output_dispatch_config = ecfg.get("output_dispatch_config") or dict(task.dispatch_config or {})
    source_correlation_id = _harness_source_correlation(ecfg)
    sandbox_instance_id = _harness_sandbox_instance(ecfg)

    try:
        from app.agent.bots import get_bot
        from app.agent.recording import schedule_harness_completion_record
        from app.services.harness import harness_service, HarnessError
        bot = get_bot(task.bot_id)

        # Resolve latest content from linked template or workspace file (if any)
        from app.services.prompt_resolution import resolve_prompt
        async with async_session() as resolve_db:
            prompt = await resolve_prompt(
                workspace_id=str(task.workspace_id) if task.workspace_id else None,
                workspace_file_path=task.workspace_file_path,
                template_id=str(task.prompt_template_id) if task.prompt_template_id else None,
                inline_prompt=task.prompt,
                db=resolve_db,
            )

        # Pass extra_args from execution_config (used for --resume on retry)
        resume_extra_args: list[str] | None = ecfg.get("resume_extra_args")

        result = await harness_service.run(
            harness_name=harness_name,
            prompt=prompt,
            working_directory=working_directory,
            bot=bot,
            sandbox_instance_id=sandbox_instance_id,
            extra_args=resume_extra_args,
        )

        # Attempt to parse Claude Code JSON output
        claude_data = _parse_claude_json_output(result.stdout)
        claude_session_id: str | None = None

        if claude_data is not None:
            claude_session_id = claude_data.get("session_id")
            cc_result = claude_data.get("result", "")
            cc_is_error = claude_data.get("is_error", False)
            cc_cost = claude_data.get("cost_usd")
            cc_turns = claude_data.get("num_turns")

            parts = []
            if cc_result:
                parts.append(cc_result)
            if cc_is_error:
                parts.append("[claude-code reported error]")
            if result.stderr:
                parts.append(f"[stderr]\n{result.stderr}")
            if result.truncated:
                parts.append("[output truncated]")
            meta_parts = []
            if cc_turns is not None:
                meta_parts.append(f"turns={cc_turns}")
            if cc_cost is not None:
                meta_parts.append(f"cost=${cc_cost:.2f}")
            meta_parts.append(f"{result.duration_ms}ms")
            meta_parts.append(f"exit={result.exit_code}")
            parts.append(f"[{', '.join(meta_parts)}]")
            result_text = "\n".join(parts)
        else:
            # Non-JSON fallback (cursor, other harnesses)
            parts = []
            if result.stdout:
                parts.append(result.stdout)
            if result.stderr:
                parts.append(f"[stderr]\n{result.stderr}")
            if result.truncated:
                parts.append("[output truncated]")
            parts.append(f"[exit {result.exit_code}, {result.duration_ms}ms]")
            result_text = "\n".join(parts)

        # Store claude_session_id on execution_config for potential resume
        async with async_session() as db:
            t = await db.get(Task, task.id)
            if t:
                t.status = "complete"
                t.result = result_text
                t.completed_at = datetime.now(timezone.utc)
                if claude_session_id:
                    merged_ecfg = dict(t.execution_config or t.callback_config or {})
                    merged_ecfg["claude_session_id"] = claude_session_id
                    if claude_data:
                        if claude_data.get("cost_usd") is not None:
                            merged_ecfg["claude_cost_usd"] = claude_data["cost_usd"]
                        if claude_data.get("num_turns") is not None:
                            merged_ecfg["claude_num_turns"] = claude_data["num_turns"]
                    t.execution_config = merged_ecfg
                await db.commit()

        _h_err: str | None = None
        if result.exit_code != 0:
            _h_err = ((result.stderr or "").strip()[:500] or f"non-zero exit {result.exit_code}")
        schedule_harness_completion_record(
            harness_name=harness_name or "unknown",
            task_id=task.id,
            session_id=task.session_id,
            client_id=task.client_id,
            bot_id=task.bot_id,
            correlation_id=source_correlation_id,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            truncated=result.truncated,
            result_text=result_text,
            error=_h_err,
        )
        await asyncio.sleep(0)

        # Build a synthetic task for delivery with the output dispatch config
        output_task = Task(
            id=task.id,
            bot_id=task.bot_id,
            dispatch_type=output_dispatch_type,
            dispatch_config=output_dispatch_config,
        )
        dispatcher = dispatchers.get(output_dispatch_type)
        await dispatcher.deliver(output_task, result_text)

        # Notify parent bot: create a callback task so the parent can react to harness output.
        if cfg.get("notify_parent") and result_text:
            _parent_bot_id = cfg.get("parent_bot_id")
            _parent_session_str = cfg.get("parent_session_id")
            _parent_client_id = cfg.get("parent_client_id")
            if _parent_bot_id and _parent_session_str:
                try:
                    _parent_session_id = uuid.UUID(_parent_session_str)
                    # Build enriched prompt with metadata when structured data is available
                    _cb_header = f"[Harness {harness_name} completed"
                    if claude_data is not None:
                        _meta = []
                        if claude_data.get("num_turns") is not None:
                            _meta.append(f"turns={claude_data['num_turns']}")
                        if claude_data.get("cost_usd") is not None:
                            _meta.append(f"cost=${claude_data['cost_usd']:.2f}")
                        if claude_data.get("is_error"):
                            _meta.append("error=true")
                        if _meta:
                            _cb_header += f" ({', '.join(_meta)})"
                    _cb_header += "]"
                    _cb_task = Task(
                        bot_id=_parent_bot_id,
                        client_id=_parent_client_id,
                        session_id=_parent_session_id,
                        prompt=f"{_cb_header}\n\n{result_text}",
                        status="pending",
                        task_type="callback",
                        dispatch_type=output_dispatch_type,
                        dispatch_config=dict(output_dispatch_config),
                        parent_task_id=task.id,
                        created_at=datetime.now(timezone.utc),
                    )
                    async with async_session() as db:
                        db.add(_cb_task)
                        await db.commit()
                        await db.refresh(_cb_task)
                    logger.info(
                        "Harness task %s: created parent callback task %s (bot=%s, session=%s)",
                        task.id, _cb_task.id, _parent_bot_id, _parent_session_id,
                    )
                except Exception:
                    logger.exception("Failed to create parent callback task for harness task %s", task.id)

    except Exception as exc:
        logger.exception("Harness task %s failed", task.id)

        # Resume retry: check for a session_id we can resume from.
        # Sources: local variable from this run's JSON parse, prior run stored on DB, or prior resume args.
        _resume_session_id = locals().get("claude_session_id") or ecfg.get("claude_session_id")
        _resume_retries = ecfg.get("resume_retries", 0)
        _can_resume = (
            _resume_session_id
            and _resume_retries < settings.HARNESS_MAX_RESUME_RETRIES
        )

        if _can_resume:
            logger.info(
                "Harness task %s: scheduling resume (session=%s, attempt %d/%d)",
                task.id, _resume_session_id, _resume_retries + 1, settings.HARNESS_MAX_RESUME_RETRIES,
            )
            async with async_session() as db:
                t = await db.get(Task, task.id)
                if t:
                    merged_ecfg = dict(t.execution_config or t.callback_config or {})
                    merged_ecfg["resume_extra_args"] = ["--resume", str(_resume_session_id)]
                    merged_ecfg["resume_retries"] = _resume_retries + 1
                    t.execution_config = merged_ecfg
                    t.status = "pending"
                    t.scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=10)
                    t.error = f"resuming (attempt {_resume_retries + 1}): {str(exc)[:200]}"
                    t.prompt = "continue from where you left off"
                    await db.commit()
        else:
            async with async_session() as db:
                t = await db.get(Task, task.id)
                if t:
                    t.status = "failed"
                    t.error = str(exc)[:4000]
                    t.completed_at = datetime.now(timezone.utc)
                    await db.commit()

        try:
            from app.agent.recording import schedule_harness_completion_record

            schedule_harness_completion_record(
                harness_name=harness_name or "unknown",
                task_id=task.id,
                session_id=task.session_id,
                client_id=task.client_id,
                bot_id=task.bot_id,
                correlation_id=source_correlation_id,
                exit_code=-1,
                duration_ms=0,
                truncated=False,
                result_text="",
                error=str(exc)[:4000],
            )
            await asyncio.sleep(0)
        except Exception:
            logger.exception("Failed to schedule harness failure record for task %s", task.id)


async def run_exec_task(task: Task) -> None:
    """Execute a raw exec task: run command in sandbox, store result, dispatch."""
    logger.info("Running exec task %s", task.id)
    now = datetime.now(timezone.utc)

    async with async_session() as db:
        t = await db.get(Task, task.id)
        if t is None:
            return
        t.status = "running"
        t.run_at = now
        await db.commit()

    # Read execution params from execution_config (new) with fallback to callback_config (legacy)
    ecfg = task.execution_config or task.callback_config or {}
    cfg = task.callback_config or {}
    command = ecfg.get("command", "")
    args = ecfg.get("args", [])
    working_directory = ecfg.get("working_directory")
    stream_to = ecfg.get("stream_to")
    output_dispatch_type = ecfg.get("output_dispatch_type", task.dispatch_type or "none")
    output_dispatch_config = ecfg.get("output_dispatch_config") or dict(task.dispatch_config or {})
    source_correlation_id = _harness_source_correlation(ecfg)
    sandbox_instance_id = _harness_sandbox_instance(ecfg)

    try:
        from app.agent.bots import get_bot
        from app.agent.recording import schedule_exec_completion_record
        from app.services.sandbox import sandbox_service
        from app.tools.local.exec_tool import build_exec_script

        bot = get_bot(task.bot_id)
        script = build_exec_script(command, args, working_directory, stream_to)

        if sandbox_instance_id is not None:
            from app.config import settings as _settings
            if not _settings.DOCKER_SANDBOX_ENABLED:
                raise RuntimeError("DOCKER_SANDBOX_ENABLED is false")
            allowed = bot.docker_sandbox_profiles or None
            instance = await sandbox_service.get_instance_for_bot(
                sandbox_instance_id, bot.id, allowed_profiles=allowed
            )
            if instance is None:
                raise RuntimeError("Sandbox instance not found or not allowed")
            result = await sandbox_service.exec(instance, script)
        elif bot.workspace.enabled or bot.shared_workspace_id:
            from app.services.workspace import workspace_service
            ws_result = await workspace_service.exec(bot.id, script, bot.workspace, working_directory or "", bot=bot)
            # Convert to sandbox-compatible result
            from dataclasses import dataclass as _dc
            @_dc
            class _R:
                stdout: str; stderr: str; exit_code: int; truncated: bool; duration_ms: int
            result = _R(stdout=ws_result.stdout, stderr=ws_result.stderr,
                        exit_code=ws_result.exit_code, truncated=ws_result.truncated,
                        duration_ms=ws_result.duration_ms)
        elif bot.bot_sandbox.enabled:
            result = await sandbox_service.exec_bot_local(bot.id, script, bot.bot_sandbox)
        else:
            raise RuntimeError("No sandbox available for exec task")

        parts = []
        if result.stdout:
            parts.append(result.stdout)
        if result.stderr:
            parts.append(f"[stderr]\n{result.stderr}")
        if result.truncated:
            parts.append("[output truncated]")
        parts.append(f"[exit {result.exit_code}, {result.duration_ms}ms]")
        result_text = "\n".join(parts)

        async with async_session() as db:
            t = await db.get(Task, task.id)
            if t:
                t.status = "complete"
                t.result = result_text
                t.completed_at = datetime.now(timezone.utc)
                await db.commit()

        _err: str | None = None
        if result.exit_code != 0:
            _err = ((result.stderr or "").strip()[:500] or f"non-zero exit {result.exit_code}")
        schedule_exec_completion_record(
            command=command,
            task_id=task.id,
            session_id=task.session_id,
            client_id=task.client_id,
            bot_id=task.bot_id,
            correlation_id=source_correlation_id,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            truncated=result.truncated,
            result_text=result_text,
            error=_err,
        )
        await asyncio.sleep(0)

        output_task = Task(
            id=task.id,
            bot_id=task.bot_id,
            dispatch_type=output_dispatch_type,
            dispatch_config=output_dispatch_config,
        )
        dispatcher = dispatchers.get(output_dispatch_type)
        await dispatcher.deliver(output_task, result_text)

        if cfg.get("notify_parent") and result_text:
            _parent_bot_id = cfg.get("parent_bot_id")
            _parent_session_str = cfg.get("parent_session_id")
            _parent_client_id = cfg.get("parent_client_id")
            if _parent_bot_id and _parent_session_str:
                try:
                    _parent_session_id = uuid.UUID(_parent_session_str)
                    _cb_task = Task(
                        bot_id=_parent_bot_id,
                        client_id=_parent_client_id,
                        session_id=_parent_session_id,
                        prompt=f"[Exec task completed: {command}]\n\n{result_text}",
                        status="pending",
                        task_type="callback",
                        dispatch_type=output_dispatch_type,
                        dispatch_config=dict(output_dispatch_config),
                        parent_task_id=task.id,
                        created_at=datetime.now(timezone.utc),
                    )
                    async with async_session() as db:
                        db.add(_cb_task)
                        await db.commit()
                        await db.refresh(_cb_task)
                    logger.info(
                        "Exec task %s: created parent callback task %s (bot=%s, session=%s)",
                        task.id, _cb_task.id, _parent_bot_id, _parent_session_id,
                    )
                except Exception:
                    logger.exception("Failed to create parent callback task for exec task %s", task.id)

    except Exception as exc:
        logger.exception("Exec task %s failed", task.id)
        async with async_session() as db:
            t = await db.get(Task, task.id)
            if t:
                t.status = "failed"
                t.error = str(exc)[:4000]
                t.completed_at = datetime.now(timezone.utc)
                await db.commit()
        try:
            from app.agent.recording import schedule_exec_completion_record

            schedule_exec_completion_record(
                command=command or "unknown",
                task_id=task.id,
                session_id=task.session_id,
                client_id=task.client_id,
                bot_id=task.bot_id,
                correlation_id=source_correlation_id,
                exit_code=-1,
                duration_ms=0,
                truncated=False,
                result_text="",
                error=str(exc)[:4000],
            )
            await asyncio.sleep(0)
        except Exception:
            logger.exception("Failed to schedule exec failure record for task %s", task.id)


async def run_task(task: Task) -> None:
    """Execute a single task: run the agent, store result, dispatch."""
    # Route on task_type (preferred) with fallback to dispatch_type for legacy rows
    if task.task_type == "harness" or (task.task_type == "agent" and task.dispatch_type == "harness"):
        await run_harness_task(task)
        return
    if task.task_type == "exec" or (task.task_type == "agent" and task.dispatch_type == "exec"):
        await run_exec_task(task)
        return

    # Resolve the channel's current active session so tasks always run in the
    # live session, not a stale session_id captured at task-creation time.
    # (Heartbeats already do this in fire_heartbeat; tasks created by bots via
    # create_task or _schedule_next_occurrence can hold an outdated session_id
    # after a channel session reset.)
    if task.channel_id:
        async with async_session() as db:
            channel = await db.get(Channel, task.channel_id)
            if channel and channel.active_session_id:
                if task.session_id != channel.active_session_id:
                    logger.info(
                        "Task %s: resolving stale session %s → channel active session %s",
                        task.id, task.session_id, channel.active_session_id,
                    )
                    task.session_id = channel.active_session_id

    # Respect the per-session active lock.  If a streaming HTTP request is still
    # running for this session, defer this task by 10 seconds rather than running
    # a parallel agent loop.
    if task.session_id and not session_locks.acquire(task.session_id):
        async with async_session() as db:
            t = await db.get(Task, task.id)
            if t:
                t.scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=10)
                await db.commit()
        logger.info("Task %s deferred 10s: session %s is busy", task.id, task.session_id)
        return

    logger.info("Running task %s (bot=%s)", task.id, task.bot_id)
    now = datetime.now(timezone.utc)

    # Mark as running
    async with async_session() as db:
        t = await db.get(Task, task.id)
        if t is None:
            if task.session_id:
                session_locks.release(task.session_id)
            return
        t.status = "running"
        t.run_at = now
        await db.commit()

    try:
        from app.agent.loop import run
        from app.agent.persona import get_persona
        from app.services.sessions import _effective_system_prompt, load_or_create
        bot = get_bot(task.bot_id)

        async with async_session() as db:
            # Detect cross-bot delegation: task.session_id belongs to a different bot
            # In that case, create a proper child delegation session instead of reusing the parent
            parent_for_delegation = None
            delegation_depth = 1
            delegation_root_id = None

            if task.session_id is not None:
                orig_session = await db.get(Session, task.session_id)
                if orig_session is not None and orig_session.bot_id != task.bot_id:
                    parent_for_delegation = task.session_id
                    delegation_depth = (orig_session.depth or 0) + 1
                    delegation_root_id = orig_session.root_session_id or orig_session.id

            if parent_for_delegation is not None:
                # Cross-bot task → create a new child session with delegation linkage
                child_session_id = uuid.uuid4()
                child_session = Session(
                    id=child_session_id,
                    client_id=task.client_id or "task",
                    bot_id=task.bot_id,
                    channel_id=task.channel_id,
                    parent_session_id=parent_for_delegation,
                    root_session_id=delegation_root_id,
                    depth=delegation_depth,
                    source_task_id=task.id,
                )
                db.add(child_session)
                await db.commit()
                messages = [{"role": "system", "content": _effective_system_prompt(bot)}]
                if bot.persona:
                    persona_layer = await get_persona(bot.id, workspace_id=bot.shared_workspace_id)
                    if persona_layer:
                        messages.append({"role": "system", "content": f"[PERSONA]\n{persona_layer}"})
                session_id = child_session_id
                logger.info(
                    "Task %s: cross-bot delegation → child session %s (depth=%d, root=%s)",
                    task.id, child_session_id, delegation_depth, delegation_root_id,
                )
            else:
                session_id, messages = await load_or_create(
                    db, task.session_id, task.client_id or "task", task.bot_id
                )

        import uuid as _uuid
        correlation_id = _uuid.uuid4()
        messages_start = len(messages)  # capture before run() appends new turn

        # Resolve latest content from linked template or workspace file (if any)
        from app.services.prompt_resolution import resolve_prompt
        async with async_session() as resolve_db:
            task_prompt = await resolve_prompt(
                workspace_id=str(task.workspace_id) if task.workspace_id else None,
                workspace_file_path=task.workspace_file_path,
                template_id=str(task.prompt_template_id) if task.prompt_template_id else None,
                inline_prompt=task.prompt,
                db=resolve_db,
            )

        # Model override from execution_config (preferred) or callback_config (legacy)
        _ecfg_pre = task.execution_config or task.callback_config or {}
        _model_override = _ecfg_pre.get("model_override") or None
        _provider_id_override = _ecfg_pre.get("model_provider_id_override") or None

        run_result = await run(
            messages, bot, task_prompt,
            session_id=session_id,
            client_id=task.client_id or "task",
            correlation_id=correlation_id,
            dispatch_type=task.dispatch_type,
            dispatch_config=task.dispatch_config,
            channel_id=task.channel_id,
            model_override=_model_override,
            provider_id_override=_provider_id_override,
        )
        result_text = run_result.response

        # Persist turn to session history so future agent turns see it as context
        from app.services.sessions import persist_turn
        async with async_session() as db:
            await persist_turn(db, session_id, bot, messages, messages_start, correlation_id=correlation_id, channel_id=task.channel_id)

        # Mark complete
        async with async_session() as db:
            t = await db.get(Task, task.id)
            if t:
                t.status = "complete"
                t.result = result_text
                t.completed_at = datetime.now(timezone.utc)
                await db.commit()

        # Dispatch result (including any generated images)
        dispatcher = dispatchers.get(task.dispatch_type)
        await dispatcher.deliver(task, result_text, client_actions=run_result.client_actions)

        _cb = task.callback_config or {}

        # trigger_rag_loop: create an immediate follow-up agent turn so the bot can
        # react to what it just posted. Posts response to the same channel.
        if _cb.get("trigger_rag_loop") and result_text:
            _trl_task = Task(
                bot_id=task.bot_id,
                client_id=task.client_id,
                session_id=session_id,
                prompt=f"[Your scheduled task just ran and posted to the channel. The output was:]\n\n{result_text}",
                status="pending",
                task_type="callback",
                dispatch_type=task.dispatch_type,
                dispatch_config=dict(task.dispatch_config or {}),
                callback_config={"trigger_rag_loop": False},  # prevent loop
                parent_task_id=task.id,
                created_at=datetime.now(timezone.utc),
            )
            async with async_session() as db:
                db.add(_trl_task)
                await db.commit()
            logger.info("Task %s: created trigger_rag_loop follow-up task", task.id)

        # Notify parent: create a callback task for the parent bot if requested
        if _cb.get("notify_parent") and result_text:
            _parent_bot_id = _cb.get("parent_bot_id")
            _parent_session_str = _cb.get("parent_session_id")
            _parent_client_id = _cb.get("parent_client_id")
            if _parent_bot_id and _parent_session_str:
                try:
                    _parent_session_id = uuid.UUID(_parent_session_str)
                    _cb_task = Task(
                        bot_id=_parent_bot_id,
                        client_id=_parent_client_id,
                        session_id=_parent_session_id,
                        prompt=f"[Sub-agent {task.bot_id} completed]\n\n{result_text}",
                        status="pending",
                        task_type="callback",
                        dispatch_type=task.dispatch_type,
                        dispatch_config=dict(task.dispatch_config or {}),
                        parent_task_id=task.id,
                        created_at=datetime.now(timezone.utc),
                    )
                    async with async_session() as db:
                        db.add(_cb_task)
                        await db.commit()
                        await db.refresh(_cb_task)
                    logger.info(
                        "Task %s: created parent callback task %s (bot=%s, session=%s)",
                        task.id, _cb_task.id, _parent_bot_id, _parent_session_id,
                    )
                except Exception:
                    logger.exception("Failed to create parent callback task for task %s", task.id)

    except openai.RateLimitError as exc:
        async with async_session() as db:
            t = await db.get(Task, task.id)
            if t is None:
                return
            if t.retry_count < settings.TASK_RATE_LIMIT_RETRIES:
                t.retry_count += 1
                # Exponential backoff: 65s, 130s, 260s — slightly longer than a 60s TPM window
                delay = settings.LLM_RATE_LIMIT_INITIAL_WAIT * (2 ** (t.retry_count - 1))
                t.status = "pending"
                t.scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
                t.error = f"rate_limited (attempt {t.retry_count}/{settings.TASK_RATE_LIMIT_RETRIES}): {str(exc)[:200]}"
                await db.commit()
                logger.warning(
                    "Task %s rate limited, rescheduled in %ds (attempt %d/%d)",
                    task.id, delay, t.retry_count, settings.TASK_RATE_LIMIT_RETRIES,
                )
            else:
                t.status = "failed"
                t.error = f"rate_limited (max retries exhausted): {str(exc)[:3800]}"
                t.completed_at = datetime.now(timezone.utc)
                await db.commit()
                logger.error("Task %s failed after %d rate limit retries", task.id, t.retry_count)
                # Dispatch error to integration so the user sees it
                _err_text = f"[Error: API rate limit exceeded after {t.retry_count} retries]"
                try:
                    dispatcher = dispatchers.get(task.dispatch_type)
                    await dispatcher.deliver(task, _err_text)
                except Exception:
                    logger.warning("Failed to dispatch rate limit error for task %s", task.id)

    except Exception as exc:
        logger.exception("Task %s failed", task.id)
        async with async_session() as db:
            t = await db.get(Task, task.id)
            if t:
                t.status = "failed"
                t.error = str(exc)[:4000]
                t.completed_at = datetime.now(timezone.utc)
                await db.commit()
        # Dispatch error to integration so the user sees it
        _err_text = f"[Error: {type(exc).__name__}: {str(exc)[:500]}]"
        try:
            dispatcher = dispatchers.get(task.dispatch_type)
            await dispatcher.deliver(task, _err_text)
        except Exception:
            logger.warning("Failed to dispatch error for task %s", task.id)
    finally:
        if task.session_id:
            session_locks.release(task.session_id)


async def fetch_due_tasks() -> list[Task]:
    """Fetch pending tasks that are due to run (scheduled_at <= now or null)."""
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        stmt = (
            select(Task)
            .where(Task.status == "pending")
            .where(
                (Task.scheduled_at.is_(None)) | (Task.scheduled_at <= now)
            )
            .limit(20)
        )
        return list((await db.execute(stmt)).scalars().all())


async def task_worker() -> None:
    """Background worker loop: polls for due tasks every 5 seconds."""
    logger.info("Task worker started")
    while True:
        try:
            if settings.SYSTEM_PAUSED:
                await asyncio.sleep(5)
                continue
            # Spawn concrete tasks from active schedule templates first
            await spawn_due_schedules()
            # Then fetch and run all due concrete tasks
            due = await fetch_due_tasks()
            for task in due:
                asyncio.create_task(run_task(task))
        except Exception:
            logger.exception("task_worker poll error")
        await asyncio.sleep(5)
