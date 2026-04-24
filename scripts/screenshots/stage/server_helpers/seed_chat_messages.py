"""Seed a handful of chat messages so a channel renders non-empty on capture.

Usage:
    python - <channel_id> <bot_id>

Idempotent: if the channel's active session already has >= 4 messages, skip.
Otherwise, find-or-create a session linked to the channel and insert four
messages (two user + two assistant) with realistic copy.

Avoids LLM cost — we're inserting DB rows that look like a past turn pair.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone


USER_ASSISTANT_PAIRS = [
    (
        "What's on the radar for tonight?",
        (
            "Three things worth a look:\n\n"
            "1. **Camera 4 offline** since 18:42 — I queued a restart on the NVR, "
            "it should be back within 2 minutes.\n"
            "2. **Amazon delivery** is out for delivery; the standing-order watcher "
            "will ping you when it clears.\n"
            "3. **Docs refresh PR** is green and waiting on your review — one merge "
            "conflict on `index.md`, already resolved in the draft."
        ),
    ),
    (
        "Nice. Kick off a pipeline run for the nightly backup when you're ready.",
        (
            "On it. Started **Nightly backup** pipeline — 3 steps: snapshot Postgres, "
            "rsync /opt/thoth-data, verify with a restore dry-run. "
            "Progress will update in the run pane; I'll ping here when it completes "
            "or if any step needs your attention."
        ),
    ),
]


async def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: python - <channel_id> <bot_id>")

    channel_id = sys.argv[1]
    bot_id = sys.argv[2]
    channel_uuid = uuid.UUID(channel_id)

    from app.db.engine import async_session  # type: ignore
    from app.db.models import Channel, Message, Session  # type: ignore
    from sqlalchemy import select, func  # type: ignore

    async with async_session() as db:
        channel = (
            await db.execute(select(Channel).where(Channel.id == channel_uuid))
        ).scalar_one_or_none()
        if channel is None:
            raise SystemExit(f"Channel {channel_id} not found")

        session_id = channel.active_session_id
        session: Session | None = None
        if session_id is not None:
            session = (
                await db.execute(select(Session).where(Session.id == session_id))
            ).scalar_one_or_none()

        if session is None:
            # Create a new channel-scoped session.
            session = Session(
                id=uuid.uuid4(),
                client_id=f"seed:{channel_id}",
                bot_id=bot_id,
                channel_id=channel_uuid,
                session_type="channel",
            )
            db.add(session)
            await db.flush()
            channel.active_session_id = session.id

        # Skip if already seeded.
        count = (
            await db.execute(
                select(func.count(Message.id)).where(Message.session_id == session.id)
            )
        ).scalar() or 0
        if count >= 4:
            print(f"skip channel={channel_id} session={session.id} already has {count} messages")
            return

        now = datetime.now(timezone.utc) - timedelta(minutes=8)
        step = timedelta(minutes=1, seconds=30)
        for i, (user_text, assistant_text) in enumerate(USER_ASSISTANT_PAIRS):
            db.add(
                Message(
                    id=uuid.uuid4(),
                    session_id=session.id,
                    role="user",
                    content=user_text,
                    created_at=now + step * (i * 2),
                )
            )
            db.add(
                Message(
                    id=uuid.uuid4(),
                    session_id=session.id,
                    role="assistant",
                    content=assistant_text,
                    created_at=now + step * (i * 2 + 1),
                )
            )

        await db.commit()
        print(
            f"ok channel={channel_id} session={session.id} "
            f"inserted={len(USER_ASSISTANT_PAIRS) * 2}"
        )


if __name__ == "__main__":
    asyncio.run(main())
