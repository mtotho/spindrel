"""Seed the pipeline task's sub-session so PipelineRunLive renders.

Usage:
    python - <task_id>

The `/channels/:channelId/runs/:taskId` modal waits on
`tasks.run_session_id` to be populated (then mounts `SessionChatView`
against that session). On a real run, `spawn_sub_session` + anchor-message
writes that id the moment the first step fires. For a frozen screenshot we
do the same moves by hand:

- ensure `task.run_isolation = "sub_session"`
- create a Session (session_type="pipeline_run", source_task_id=task.id,
  parent_session_id=<channel's active session>)
- set `task.run_session_id = session.id`
- seed a few messages on the sub-session so it looks like step 1/2 finished
  and step 3 is running.

Idempotent: if the sub-session already has >= 4 messages we bail.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone


PIPELINE_RUN_MESSAGES = [
    (
        "user",
        "Kick off the **Nightly backup** pipeline when you're ready.",
    ),
    (
        "assistant",
        (
            "Starting pipeline **Nightly backup** — 3 steps: "
            "Collect inputs → Summarize overnight → Post to channel."
        ),
    ),
    (
        "assistant",
        (
            "✓ **Step 1/3 · Collect inputs** — gathered overnight alerts (3), "
            "calendar (2 events), weather (clear, 58°F)."
        ),
    ),
    (
        "assistant",
        (
            "✓ **Step 2/3 · Summarize overnight** — draft ready: 1 camera outage "
            "(resolved), 0 push notifications missed, delivery en route."
        ),
    ),
    (
        "assistant",
        "▶ **Step 3/3 · Post to channel** — posting summary…",
    ),
]


async def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python - <task_id>")

    task_uuid = uuid.UUID(sys.argv[1])

    from app.db.engine import async_session  # type: ignore
    from app.db.models import Channel, Message, Session, Task  # type: ignore
    from sqlalchemy import func, select  # type: ignore

    async with async_session() as db:
        task = (
            await db.execute(select(Task).where(Task.id == task_uuid))
        ).scalar_one_or_none()
        if task is None:
            raise SystemExit(f"Task {task_uuid} not found")

        # Parent session = the channel's active session (where the anchor
        # message would live on a real run).
        parent_session_id: uuid.UUID | None = None
        if task.channel_id is not None:
            channel = (
                await db.execute(
                    select(Channel).where(Channel.id == task.channel_id)
                )
            ).scalar_one_or_none()
            if channel is not None:
                parent_session_id = channel.active_session_id

        # Reuse existing sub-session if present, else create one.
        sub: Session | None = None
        if task.run_session_id is not None:
            sub = (
                await db.execute(
                    select(Session).where(Session.id == task.run_session_id)
                )
            ).scalar_one_or_none()

        if sub is None:
            sub = Session(
                id=uuid.uuid4(),
                client_id=task.client_id or f"pipeline-run:{task.id}",
                bot_id=task.bot_id,
                channel_id=None,
                parent_session_id=parent_session_id,
                root_session_id=parent_session_id,
                depth=1 if parent_session_id else 0,
                source_task_id=task.id,
                session_type="pipeline_run",
                title=task.title,
            )
            db.add(sub)
            await db.flush()

        task.run_isolation = "sub_session"
        task.run_session_id = sub.id

        # Skip seeding if already populated.
        count = (
            await db.execute(
                select(func.count(Message.id)).where(Message.session_id == sub.id)
            )
        ).scalar() or 0
        if count >= len(PIPELINE_RUN_MESSAGES):
            await db.commit()
            print(
                f"ok (skip messages) task={task.id} session={sub.id} "
                f"existing={count}"
            )
            return

        now = datetime.now(timezone.utc) - timedelta(minutes=2)
        step = timedelta(seconds=25)
        for i, (role, text) in enumerate(PIPELINE_RUN_MESSAGES):
            db.add(
                Message(
                    id=uuid.uuid4(),
                    session_id=sub.id,
                    role=role,
                    content=text,
                    created_at=now + step * i,
                )
            )

        await db.commit()
        print(
            f"ok task={task.id} session={sub.id} "
            f"inserted={len(PIPELINE_RUN_MESSAGES)}"
        )


if __name__ == "__main__":
    asyncio.run(main())
