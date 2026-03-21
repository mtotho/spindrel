"""Task worker: runs scheduled/deferred agent tasks and dispatches results."""
import asyncio
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
from app.db.models import Session, Task
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


async def _schedule_next_occurrence(task: Task) -> None:
    interval = _parse_recurrence(task.recurrence or "")
    if not interval:
        logger.warning("Task %s has invalid recurrence %r — skipping", task.id, task.recurrence)
        return
    next_run = datetime.now(timezone.utc) + interval
    async with async_session() as db:
        db.add(Task(
            bot_id=task.bot_id,
            client_id=task.client_id,
            session_id=task.session_id,
            prompt=task.prompt,
            scheduled_at=next_run,
            status="pending",
            dispatch_type=task.dispatch_type,
            dispatch_config=task.dispatch_config,
            recurrence=task.recurrence,
            parent_task_id=task.id,
            created_at=datetime.now(timezone.utc),
        ))
        await db.commit()
    logger.info("Task %s recurring: next run at %s", task.id, next_run.strftime("%Y-%m-%d %H:%M UTC"))


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

    cfg = task.callback_config or {}
    harness_name = cfg.get("harness_name", "")
    working_directory = cfg.get("working_directory")
    output_dispatch_type = cfg.get("output_dispatch_type", "none")
    output_dispatch_config = cfg.get("output_dispatch_config") or {}
    source_correlation_id = _harness_source_correlation(cfg)
    sandbox_instance_id = _harness_sandbox_instance(cfg)

    try:
        from app.agent.bots import get_bot
        from app.agent.recording import schedule_harness_completion_record
        from app.services.harness import harness_service, HarnessError
        bot = get_bot(task.bot_id)

        result = await harness_service.run(
            harness_name=harness_name,
            prompt=task.prompt,
            working_directory=working_directory,
            bot=bot,
            sandbox_instance_id=sandbox_instance_id,
        )

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
                    _cb_task = Task(
                        bot_id=_parent_bot_id,
                        client_id=_parent_client_id,
                        session_id=_parent_session_id,
                        prompt=f"[Harness {harness_name} completed]\n\n{result_text}",
                        status="pending",
                        dispatch_type=output_dispatch_type,
                        dispatch_config=dict(output_dispatch_config),
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


async def run_task(task: Task) -> None:
    """Execute a single task: run the agent, store result, dispatch."""
    if task.dispatch_type == "harness":
        await run_harness_task(task)
        return

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
                    parent_session_id=parent_for_delegation,
                    root_session_id=delegation_root_id,
                    depth=delegation_depth,
                )
                db.add(child_session)
                await db.commit()
                messages = [{"role": "system", "content": _effective_system_prompt(bot)}]
                if bot.persona:
                    persona_layer = await get_persona(bot.id)
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
        run_result = await run(
            messages, bot, task.prompt,
            session_id=session_id,
            client_id=task.client_id or "task",
            correlation_id=correlation_id,
            dispatch_type=task.dispatch_type,
            dispatch_config=task.dispatch_config,
        )
        result_text = run_result.response

        # Persist turn to session history so future agent turns see it as context
        from app.services.sessions import persist_turn
        async with async_session() as db:
            await persist_turn(db, session_id, bot, messages, messages_start, correlation_id=correlation_id)

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
                dispatch_type=task.dispatch_type,
                dispatch_config=dict(task.dispatch_config or {}),
                callback_config={"trigger_rag_loop": False},  # prevent loop
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
                        dispatch_type=task.dispatch_type,
                        dispatch_config=dict(task.dispatch_config or {}),
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

        # Schedule next occurrence if recurring
        if task.recurrence:
            await _schedule_next_occurrence(task)

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

    except Exception as exc:
        logger.exception("Task %s failed", task.id)
        async with async_session() as db:
            t = await db.get(Task, task.id)
            if t:
                t.status = "failed"
                t.error = str(exc)[:4000]
                t.completed_at = datetime.now(timezone.utc)
                await db.commit()
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
            due = await fetch_due_tasks()
            for task in due:
                asyncio.create_task(run_task(task))
        except Exception:
            logger.exception("task_worker poll error")
        await asyncio.sleep(5)
