"""Seed a recent session row for a screenshot channel.

Usage:
    python - <channel_id> <bot_id> <rank> <unread:0|1>

The helper is idempotent. It creates one channel-scoped session per channel
with stable client_id, realistic messages, optional unread state for every
user, and staggered last_active timestamps so the Home dashboard has a
predictable recent-session list.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone


PROMPTS = [
    "Review the morning brief and flag anything that needs a decision.",
    "Check the house status and tell me what changed since yesterday.",
    "Summarize the inbox items that are ready for a response.",
    "Look over the deploy queue and call out anything risky.",
    "Review the pipeline run and note the next useful action.",
    "Scan the dashboard for stale widgets or missing data.",
]

REPLIES = [
    "The brief is current. Calendar prep is done, the package watcher is active, and no urgent decision is waiting.",
    "House status is mostly quiet. Camera 4 is offline, the NVR restart is queued, and the hallway sensor checked in two minutes ago.",
    "Inbox is down to three actionable threads. The vendor reply is drafted and the billing question needs one attachment.",
    "Deploy queue is healthy. The API migration passed smoke tests and the web rollout is waiting for a manual approval.",
    "Pipeline is on step two of three. Snapshot completed, rsync is running, and restore verification is still pending.",
    "Dashboard data is fresh. Notes and todo widgets updated recently, while the standing order widget is due for its next tick.",
]


async def main() -> None:
    if len(sys.argv) != 5:
        raise SystemExit("usage: python - <channel_id> <bot_id> <rank> <unread:0|1>")

    channel_id = uuid.UUID(sys.argv[1])
    bot_id = sys.argv[2]
    rank = int(sys.argv[3])
    make_unread = sys.argv[4] == "1"

    from app.db.engine import async_session  # type: ignore
    from app.db.models import Channel, ConversationSection, Message, Session, SessionReadState, User  # type: ignore
    from sqlalchemy import delete, func, select  # type: ignore

    async with async_session() as db:
        channel = (
            await db.execute(select(Channel).where(Channel.id == channel_id))
        ).scalar_one_or_none()
        if channel is None:
            raise SystemExit(f"Channel {channel_id} not found")

        now = datetime.now(timezone.utc)
        last_active = now + timedelta(seconds=60 - rank)
        session_client_id = f"screenshot:home-recent:{channel_id}"
        session = None
        if channel.active_session_id:
            session = await db.get(Session, channel.active_session_id)
        if session is None:
            session = (
                await db.execute(select(Session).where(Session.client_id == session_client_id))
            ).scalar_one_or_none()
        if session is None:
            session = Session(
                id=uuid.uuid4(),
                client_id=session_client_id,
                bot_id=bot_id,
                channel_id=channel_id,
                session_type="channel",
            )
            db.add(session)
            await db.flush()

        channel.active_session_id = session.id
        session.client_id = session_client_id
        session.title = f"{channel.name} review"
        session.summary = f"Recent workspace check for {channel.name}."
        session.last_active = last_active
        session.is_current = True

        message_count = (
            await db.execute(select(func.count(Message.id)).where(Message.session_id == session.id))
        ).scalar() or 0
        if message_count == 0:
            prompt = PROMPTS[rank % len(PROMPTS)]
            reply = REPLIES[rank % len(REPLIES)]
            user_message = Message(
                id=uuid.uuid4(),
                session_id=session.id,
                role="user",
                content=prompt,
                created_at=last_active - timedelta(minutes=4),
            )
            assistant_message = Message(
                id=uuid.uuid4(),
                session_id=session.id,
                role="assistant",
                content=reply,
                created_at=last_active,
            )
            db.add(user_message)
            db.add(assistant_message)
            db.add(ConversationSection(
                id=uuid.uuid4(),
                channel_id=channel_id,
                session_id=session.id,
                sequence=1,
                title="Recent check",
                summary=reply,
                transcript=f"User: {prompt}\nAssistant: {reply}",
                message_count=2,
            ))
            await db.flush()
        else:
            assistant_message = (
                await db.execute(
                    select(Message)
                    .where(Message.session_id == session.id, Message.role == "assistant")
                    .order_by(Message.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

        await db.execute(delete(SessionReadState).where(SessionReadState.session_id == session.id))
        if make_unread and assistant_message is not None:
            users = (await db.execute(select(User))).scalars().all()
            for user in users:
                db.add(SessionReadState(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    session_id=session.id,
                    channel_id=channel_id,
                    first_unread_at=assistant_message.created_at,
                    latest_unread_at=assistant_message.created_at,
                    latest_unread_message_id=assistant_message.id,
                    unread_agent_reply_count=1,
                    created_at=now,
                    updated_at=now,
                ))

        await db.commit()
        print(f"ok channel={channel_id} session={session.id} unread={int(make_unread)}")


if __name__ == "__main__":
    asyncio.run(main())
