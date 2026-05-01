"""Seed user-attributed Home activity for screenshot dashboards.

Usage:
    python - <bot_id> <channel_ids_csv>

Creates a few stable local users, then adds one attributed user message to
several Home sessions so the Users section can show latest session, channel,
and daily counts.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone


DEMO_USERS = [
    ("casey.viewer@example.test", "Casey Viewer"),
    ("morgan.ops@example.test", "Morgan Ops"),
    ("riley.home@example.test", "Riley Home"),
]

PROMPTS = [
    "Can you give me the latest session status before I switch contexts?",
    "What changed in this channel since the last check-in?",
    "Pull the most useful details from this thread for today's summary.",
]


async def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: python - <bot_id> <channel_ids_csv>")

    _bot_id = sys.argv[1]
    channel_ids = [uuid.UUID(raw) for raw in sys.argv[2].split(",") if raw.strip()]

    from app.db.engine import async_session  # type: ignore
    from app.db.models import Channel, Message, Session, User  # type: ignore
    from app.services.auth import create_local_user  # type: ignore
    from sqlalchemy import select  # type: ignore

    async with async_session() as db:
        users: list[User] = []
        for email, display_name in DEMO_USERS:
            user = (
                await db.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            if user is None:
                user = await create_local_user(
                    db,
                    email=email,
                    display_name=display_name,
                    password="screenshot-password",
                )
            users.append(user)

        channels = (
            await db.execute(select(Channel).where(Channel.id.in_(channel_ids)))
        ).scalars().all()
        channel_by_id = {channel.id: channel for channel in channels}
        now = datetime.now(timezone.utc)

        for user_index, user in enumerate(users):
            for rank, channel_id in enumerate(channel_ids[user_index:user_index + 3]):
                channel = channel_by_id.get(channel_id)
                if channel is None or channel.active_session_id is None:
                    continue
                session = await db.get(Session, channel.active_session_id)
                if session is None:
                    continue

                text = PROMPTS[(user_index + rank) % len(PROMPTS)]
                existing = (
                    await db.execute(
                        select(Message).where(
                            Message.session_id == session.id,
                            Message.role == "user",
                            Message.content == text,
                        )
                    )
                ).scalar_one_or_none()
                created_at = now + timedelta(seconds=120 + user_index * 10 + rank)
                if existing is None:
                    db.add(Message(
                        id=uuid.uuid4(),
                        session_id=session.id,
                        role="user",
                        content=text,
                        metadata_={
                            "source": "web",
                            "sender_type": "human",
                            "sender_id": f"user:{user.id}",
                            "sender_display_name": user.display_name,
                            "screenshot_seed": "home_user_activity",
                        },
                        created_at=created_at,
                    ))
                session.last_active = max(session.last_active or created_at, created_at)

        await db.commit()
        print(f"ok users={len(users)} channels={len(channel_ids)}")


if __name__ == "__main__":
    asyncio.run(main())
