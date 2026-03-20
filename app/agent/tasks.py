"""Task worker: runs scheduled/deferred agent tasks and dispatches results."""
import asyncio
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.agent.bots import get_bot
from app.db.engine import async_session
from app.db.models import Task

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

async def run_task(task: Task) -> None:
    """Execute a single task: run the agent, store result, dispatch."""
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
        bot = get_bot(task.bot_id)
        from app.services.sessions import load_or_create
        async with async_session() as db:
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

        # Schedule next occurrence if recurring
        if task.recurrence:
            await _schedule_next_occurrence(task)

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
