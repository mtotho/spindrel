"""Task worker: runs scheduled/deferred agent tasks and dispatches results."""
import asyncio
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import openai
from sqlalchemy import select

from app.agent.bots import get_bot
from app.config import settings
from app.db.engine import async_session
from app.db.models import Session, Task

logger = logging.getLogger(__name__)

_http = httpx.AsyncClient(timeout=30.0)


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
# Dispatchers
# ---------------------------------------------------------------------------

class SlackDispatcher:
    async def deliver(self, task: Task, result: str) -> None:
        cfg = task.dispatch_config or {}
        channel_id = cfg.get("channel_id")
        thread_ts = cfg.get("thread_ts")
        token = cfg.get("token")
        if not channel_id or not token:
            logger.warning("SlackDispatcher: missing channel_id or token for task %s", task.id)
            return
        reply_in_thread = cfg.get("reply_in_thread", True)
        payload: dict = {
            "channel": channel_id,
            "text": result,
        }
        if thread_ts and reply_in_thread:
            payload["thread_ts"] = thread_ts

        # Display name / icon overrides (requires chat:write.customize scope)
        try:
            bot_config = get_bot(task.bot_id)
            username = bot_config.slack_display_name or bot_config.name or None
            if username:
                payload["username"] = username
            if bot_config.slack_icon_emoji:
                payload["icon_emoji"] = bot_config.slack_icon_emoji
            elif bot_config.slack_icon_url:
                payload["icon_url"] = bot_config.slack_icon_url
        except Exception:
            pass  # bot not found or no display config — use Slack app defaults

        try:
            r = await _http.post(
                "https://slack.com/api/chat.postMessage",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            r.raise_for_status()
            data = r.json()
            if not data.get("ok"):
                logger.error("Slack API error for task %s: %s", task.id, data.get("error"))
                return
            from app.services.sessions import store_slack_echo_as_passive

            await store_slack_echo_as_passive(
                task.session_id, task.client_id, task.bot_id, result,
            )
        except Exception:
            logger.exception("SlackDispatcher.deliver failed for task %s", task.id)


class WebhookDispatcher:
    async def deliver(self, task: Task, result: str) -> None:
        cfg = task.dispatch_config or {}
        url = cfg.get("url")
        if not url:
            logger.warning("WebhookDispatcher: missing url for task %s", task.id)
            return
        try:
            r = await _http.post(url, json={"task_id": str(task.id), "result": result})
            r.raise_for_status()
        except Exception:
            logger.exception("WebhookDispatcher.deliver failed for task %s", task.id)


class InternalDispatcher:
    async def deliver(self, task: Task, result: str) -> None:
        """Persist result as a user message in a parent session so the parent bot can process it."""
        cfg = task.dispatch_config or {}
        session_id_str = cfg.get("session_id")
        if not session_id_str:
            logger.warning("InternalDispatcher: missing session_id for task %s", task.id)
            return
        try:
            from app.db.models import Message, Session
            session_id = uuid.UUID(session_id_str)
            async with async_session() as db:
                session = await db.get(Session, session_id)
                if not session:
                    logger.error("InternalDispatcher: session %s not found for task %s", session_id, task.id)
                    return
                db.add(Message(
                    session_id=session_id,
                    role="user",
                    content=f"[Task {task.id} completed]\n\n{result}",
                    created_at=datetime.now(timezone.utc),
                ))
                await db.commit()
        except Exception:
            logger.exception("InternalDispatcher.deliver failed for task %s", task.id)


class NoneDispatcher:
    async def deliver(self, task: Task, result: str) -> None:
        pass  # result stored in DB only; caller polls get_task


DISPATCHERS: dict[str, SlackDispatcher | WebhookDispatcher | InternalDispatcher | NoneDispatcher] = {
    "slack": SlackDispatcher(),
    "webhook": WebhookDispatcher(),
    "internal": InternalDispatcher(),
    "none": NoneDispatcher(),
}


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

    cfg = task.dispatch_config or {}
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
        dispatcher = DISPATCHERS.get(output_dispatch_type, DISPATCHERS["none"])
        await dispatcher.deliver(output_task, result_text)

        # Notify parent bot: create a callback task so the parent can react to harness output.
        if cfg.get("_notify_parent") and result_text:
            _parent_bot_id = cfg.get("_parent_bot_id")
            _parent_session_str = cfg.get("_parent_session_id")
            _parent_client_id = cfg.get("_parent_client_id")
            if _parent_bot_id and _parent_session_str:
                try:
                    _parent_session_id = uuid.UUID(_parent_session_str)
                    _cb_cfg = {k: v for k, v in output_dispatch_config.items() if not k.startswith("_")}
                    _cb_task = Task(
                        bot_id=_parent_bot_id,
                        client_id=_parent_client_id,
                        session_id=_parent_session_id,
                        prompt=f"[Harness {harness_name} completed]\n\n{result_text}",
                        status="pending",
                        dispatch_type=output_dispatch_type,
                        dispatch_config=_cb_cfg,
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

    logger.info("Running task %s (bot=%s)", task.id, task.bot_id)
    now = datetime.now(timezone.utc)

    # Mark as running
    async with async_session() as db:
        t = await db.get(Task, task.id)
        if t is None:
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
        run_result = await run(
            messages, bot, task.prompt,
            session_id=session_id,
            client_id=task.client_id or "task",
            correlation_id=correlation_id,
            dispatch_type=task.dispatch_type,
            dispatch_config=task.dispatch_config,
        )
        result_text = run_result.response

        # Mark complete
        async with async_session() as db:
            t = await db.get(Task, task.id)
            if t:
                t.status = "complete"
                t.result = result_text
                t.completed_at = datetime.now(timezone.utc)
                await db.commit()

        # Dispatch result
        dispatcher = DISPATCHERS.get(task.dispatch_type or "none", DISPATCHERS["none"])
        await dispatcher.deliver(task, result_text)

        # Notify parent: create a callback task for the parent bot if requested
        _cfg = task.dispatch_config or {}
        if _cfg.get("_notify_parent") and result_text:
            _parent_bot_id = _cfg.get("_parent_bot_id")
            _parent_session_str = _cfg.get("_parent_session_id")
            _parent_client_id = _cfg.get("_parent_client_id")
            if _parent_bot_id and _parent_session_str:
                try:
                    _parent_session_id = uuid.UUID(_parent_session_str)
                    # Callback dispatch config: same as original but strip internal _* keys
                    _cb_cfg = {k: v for k, v in _cfg.items() if not k.startswith("_")}
                    _cb_task = Task(
                        bot_id=_parent_bot_id,
                        client_id=_parent_client_id,
                        session_id=_parent_session_id,
                        prompt=f"[Sub-agent {task.bot_id} completed]\n\n{result_text}",
                        status="pending",
                        dispatch_type=task.dispatch_type,
                        dispatch_config=_cb_cfg,
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
