"""Channel-scoped session catalog and search helpers."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, ConversationSection, Message, Session, User
from app.tools.local.search_history import _build_session_query

logger = logging.getLogger(__name__)


class ChannelSessionMatchOut(BaseModel):
    kind: str
    source: str
    preview: Optional[str] = None
    message_id: Optional[uuid.UUID] = None
    section_id: Optional[uuid.UUID] = None
    section_sequence: Optional[int] = None


class ChannelSessionSearchRowOut(BaseModel):
    session_id: uuid.UUID
    surface_kind: str
    bot_id: str
    created_at: datetime
    last_active: datetime
    label: Optional[str] = None
    summary: Optional[str] = None
    preview: Optional[str] = None
    message_count: int = 0
    section_count: int = 0
    is_active: bool = False
    is_current: bool = False
    matches: list[ChannelSessionMatchOut] = Field(default_factory=list)


class ChannelSessionListOut(BaseModel):
    sessions: list[ChannelSessionSearchRowOut]


class ChannelSessionSearchOut(BaseModel):
    query: str
    sessions: list[ChannelSessionSearchRowOut]


def _session_surface_kind(session: Session) -> str:
    if session.parent_channel_id is not None:
        return "scratch"
    return "channel"


def _session_label(session: Session, preview: str | None) -> str | None:
    title = (session.title or "").strip()
    if title:
        return title
    summary = (session.summary or "").strip()
    if summary:
        return summary
    fallback = (preview or "").strip()
    return fallback or None


async def _channel_session_rows(
    db: AsyncSession,
    channel: Channel,
    auth,
    *,
    limit: int,
) -> list[Session]:
    channel_sessions = (await db.execute(
        select(Session)
        .where(Session.channel_id == channel.id)
        .order_by(Session.last_active.desc())
        .limit(limit)
    )).scalars().all()

    scratch_sessions: list[Session] = []
    if isinstance(auth, User):
        scratch_sessions = (await db.execute(
            select(Session)
            .where(
                Session.parent_channel_id == channel.id,
                Session.owner_user_id == auth.id,
            )
            .order_by(Session.last_active.desc())
            .limit(limit)
        )).scalars().all()

    by_id: dict[uuid.UUID, Session] = {}
    for session in [*channel_sessions, *scratch_sessions]:
        by_id[session.id] = session
    return sorted(by_id.values(), key=lambda s: s.last_active or s.created_at, reverse=True)[:limit]


async def _session_row_counts_and_previews(
    db: AsyncSession,
    sessions: list[Session],
) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, int], dict[uuid.UUID, str]]:
    if not sessions:
        return {}, {}, {}
    session_ids = [s.id for s in sessions]

    count_rows = (await db.execute(
        select(Message.session_id, func.count(Message.id))
        .where(
            Message.session_id.in_(session_ids),
            Message.role.in_(("user", "assistant")),
        )
        .group_by(Message.session_id)
    )).all()
    message_counts = {sid: int(count) for sid, count in count_rows}

    section_rows = (await db.execute(
        select(ConversationSection.session_id, func.count(ConversationSection.id))
        .where(ConversationSection.session_id.in_(session_ids))
        .group_by(ConversationSection.session_id)
    )).all()
    section_counts = {sid: int(count) for sid, count in section_rows if sid is not None}

    preview_rows = (await db.execute(
        select(Message.session_id, Message.content, Message.created_at)
        .where(
            Message.session_id.in_(session_ids),
            Message.role == "user",
            Message.content.is_not(None),
        )
        .order_by(Message.session_id, Message.created_at.asc())
    )).all()
    previews: dict[uuid.UUID, str] = {}
    for sid, content, _created_at in preview_rows:
        if sid in previews:
            continue
        text = (content or "").strip().replace("\n", " ")
        previews[sid] = text[:120] + ("\u2026" if len(text) > 120 else "")

    return message_counts, section_counts, previews


async def build_session_search_rows(
    db: AsyncSession,
    channel: Channel,
    auth,
    *,
    limit: int,
) -> list[ChannelSessionSearchRowOut]:
    sessions = await _channel_session_rows(db, channel, auth, limit=limit)
    message_counts, section_counts, previews = await _session_row_counts_and_previews(db, sessions)
    return [
        ChannelSessionSearchRowOut(
            session_id=session.id,
            surface_kind=_session_surface_kind(session),
            bot_id=session.bot_id,
            created_at=session.created_at,
            last_active=session.last_active,
            label=_session_label(session, previews.get(session.id)),
            summary=session.summary,
            preview=previews.get(session.id),
            message_count=message_counts.get(session.id, 0),
            section_count=section_counts.get(session.id, 0),
            is_active=session.id == channel.active_session_id,
            is_current=session.is_current,
        )
        for session in sessions
    ]


def _append_session_match(
    matches_by_session: dict[uuid.UUID, list[ChannelSessionMatchOut]],
    session_id: uuid.UUID,
    match: ChannelSessionMatchOut,
    *,
    max_per_session: int = 3,
) -> None:
    bucket = matches_by_session.setdefault(session_id, [])
    if len(bucket) < max_per_session:
        bucket.append(match)


async def search_channel_session_rows(
    db: AsyncSession,
    channel: Channel,
    auth,
    *,
    query: str,
    limit: int,
) -> list[ChannelSessionSearchRowOut]:
    rows = await build_session_search_rows(db, channel, auth, limit=limit)
    row_by_id = {row.session_id: row for row in rows}
    if not row_by_id:
        return []

    matches_by_session: dict[uuid.UUID, list[ChannelSessionMatchOut]] = {}

    message_stmt = _build_session_query(row_by_id.keys(), query=query, role="all", limit=limit * 4)
    messages = (await db.execute(message_stmt)).scalars().all()
    for msg in messages:
        if msg.session_id not in row_by_id:
            continue
        content = (msg.content or "").strip()
        _append_session_match(
            matches_by_session,
            msg.session_id,
            ChannelSessionMatchOut(
                kind="message",
                source="content",
                preview=content[:300],
                message_id=msg.id,
            ),
        )

    from app.tools.local.conversation_history import search_sections

    for session_id in row_by_id:
        try:
            section_matches = await search_sections(session_id, query)
        except Exception:
            logger.debug("Channel session section search failed for session %s", session_id, exc_info=True)
            continue
        for result in section_matches[:3]:
            section = result["section"]
            _append_session_match(
                matches_by_session,
                session_id,
                ChannelSessionMatchOut(
                    kind="section",
                    source=result.get("source") or "section",
                    preview=result.get("snippet") or section.summary,
                    section_id=section.id,
                    section_sequence=section.sequence,
                ),
            )

    ranked: list[ChannelSessionSearchRowOut] = []
    for row in rows:
        row.matches = matches_by_session.get(row.session_id, [])
        if row.matches:
            ranked.append(row)

    ranked.sort(
        key=lambda row: (
            len(row.matches),
            row.last_active,
        ),
        reverse=True,
    )
    return ranked[:limit]
