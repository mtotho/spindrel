"""Durable read receipts and unread notification delivery."""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session
from app.db.models import (
    Channel,
    ChannelIntegration,
    ChannelMember,
    Message,
    NotificationTarget,
    PushSubscription,
    Session,
    SessionReadState,
    UnreadNotificationRule,
)
from app.services import user_events
from app.services.notifications import NotificationPayload, normalize_slug, send_notification

logger = logging.getLogger(__name__)

VISIBLE_TTL_SECONDS = 45
DEFAULT_REMINDER_DELAY_MINUTES = 5

_visible_sessions: dict[tuple[uuid.UUID, uuid.UUID], datetime] = {}
_reminder_task: asyncio.Task | None = None


@dataclass(slots=True)
class UnreadRule:
    enabled: bool = True
    target_ids: list[uuid.UUID] | None = None
    immediate_enabled: bool = True
    reminder_enabled: bool = True
    reminder_delay_minutes: int = DEFAULT_REMINDER_DELAY_MINUTES
    preview_policy: str = "short"


def serialize_read_state(row: SessionReadState) -> dict[str, Any]:
    return {
        "user_id": str(row.user_id),
        "session_id": str(row.session_id),
        "channel_id": str(row.channel_id) if row.channel_id else None,
        "last_read_message_id": str(row.last_read_message_id) if row.last_read_message_id else None,
        "last_read_at": row.last_read_at.isoformat() if row.last_read_at else None,
        "first_unread_at": row.first_unread_at.isoformat() if row.first_unread_at else None,
        "latest_unread_at": row.latest_unread_at.isoformat() if row.latest_unread_at else None,
        "latest_unread_message_id": str(row.latest_unread_message_id) if row.latest_unread_message_id else None,
        "latest_unread_correlation_id": str(row.latest_unread_correlation_id) if row.latest_unread_correlation_id else None,
        "unread_agent_reply_count": row.unread_agent_reply_count,
        "reminder_due_at": row.reminder_due_at.isoformat() if row.reminder_due_at else None,
        "reminder_sent_at": row.reminder_sent_at.isoformat() if row.reminder_sent_at else None,
    }


def is_session_visible(user_id: uuid.UUID, session_id: uuid.UUID, *, now: datetime | None = None) -> bool:
    at = _visible_sessions.get((user_id, session_id))
    if at is None:
        return False
    now = now or datetime.now(timezone.utc)
    if at + timedelta(seconds=VISIBLE_TTL_SECONDS) < now:
        _visible_sessions.pop((user_id, session_id), None)
        return False
    return True


def mark_session_visible(user_id: uuid.UUID, session_id: uuid.UUID) -> None:
    _visible_sessions[(user_id, session_id)] = datetime.now(timezone.utc)


async def _get_or_create_state(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    channel_id: uuid.UUID | None,
) -> SessionReadState:
    row = (await db.execute(
        select(SessionReadState).where(
            SessionReadState.user_id == user_id,
            SessionReadState.session_id == session_id,
        )
    )).scalar_one_or_none()
    if row is not None:
        if channel_id and row.channel_id != channel_id:
            row.channel_id = channel_id
        return row
    row = SessionReadState(
        id=uuid.uuid4(),
        user_id=user_id,
        session_id=session_id,
        channel_id=channel_id,
    )
    db.add(row)
    await db.flush()
    return row


async def latest_message_id(db: AsyncSession, session_id: uuid.UUID) -> uuid.UUID | None:
    return (await db.execute(
        select(Message.id)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1)
    )).scalar_one_or_none()


async def mark_session_read(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    source: str,
    surface: str | None = None,
    message_id: uuid.UUID | None = None,
) -> SessionReadState:
    session = await db.get(Session, session_id)
    channel_id = session.channel_id or session.parent_channel_id if session else None
    if message_id is None:
        message_id = await latest_message_id(db, session_id)
    now = datetime.now(timezone.utc)
    row = await _get_or_create_state(db, user_id=user_id, session_id=session_id, channel_id=channel_id)
    row.last_read_message_id = message_id
    row.last_read_at = now
    row.last_read_source = source
    row.last_read_surface = surface
    row.first_unread_at = None
    row.latest_unread_at = None
    row.latest_unread_message_id = None
    row.latest_unread_correlation_id = None
    row.unread_agent_reply_count = 0
    row.initial_notified_at = None
    row.reminder_due_at = None
    row.reminder_sent_at = None
    row.updated_at = now
    await db.flush()
    user_events.publish(user_id, "read_state_updated", {"state": serialize_read_state(row)})
    return row


async def mark_session_visible_and_read(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    source: str = "web_visible",
    surface: str | None = None,
) -> SessionReadState:
    mark_session_visible(user_id, session_id)
    return await mark_session_read(db, user_id=user_id, session_id=session_id, source=source, surface=surface)


async def mark_channel_read(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    channel_id: uuid.UUID,
    source: str = "web_channel_read",
) -> list[SessionReadState]:
    session_ids = (await db.execute(
        select(Session.id).where(
            (Session.channel_id == channel_id) | (Session.parent_channel_id == channel_id)
        )
    )).scalars().all()
    rows: list[SessionReadState] = []
    for session_id in session_ids:
        rows.append(await mark_session_read(db, user_id=user_id, session_id=session_id, source=source))
    return rows


async def mark_all_read(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    source: str = "web_all_read",
) -> int:
    rows = (await db.execute(
        select(SessionReadState).where(
            SessionReadState.user_id == user_id,
            SessionReadState.unread_agent_reply_count > 0,
        )
    )).scalars().all()
    now = datetime.now(timezone.utc)
    for row in rows:
        row.last_read_message_id = row.latest_unread_message_id
        row.last_read_at = now
        row.last_read_source = source
        row.first_unread_at = None
        row.latest_unread_at = None
        row.latest_unread_message_id = None
        row.latest_unread_correlation_id = None
        row.unread_agent_reply_count = 0
        row.initial_notified_at = None
        row.reminder_due_at = None
        row.reminder_sent_at = None
        row.updated_at = now
        user_events.publish(user_id, "read_state_updated", {"state": serialize_read_state(row)})
    await db.flush()
    return len(rows)


async def _recipient_user_ids(db: AsyncSession, session: Session, channel_id: uuid.UUID | None) -> list[uuid.UUID]:
    ids: set[uuid.UUID] = set()
    if session.owner_user_id:
        ids.add(session.owner_user_id)
    channel = await db.get(Channel, channel_id) if channel_id else None
    if channel and channel.user_id:
        ids.add(channel.user_id)
    if channel_id:
        member_ids = (await db.execute(
            select(ChannelMember.user_id).where(ChannelMember.channel_id == channel_id)
        )).scalars().all()
        ids.update(member_ids)
    return list(ids)


def _is_unread_worthy(record: Message) -> bool:
    if record.role != "assistant":
        return False
    meta = record.metadata_ or {}
    if meta.get("hidden") or meta.get("source") == "notification":
        return False
    content = record.content or ""
    return bool(str(content).strip())


async def _resolve_rule(db: AsyncSession, user_id: uuid.UUID, channel_id: uuid.UUID | None) -> UnreadRule:
    global_rule = (await db.execute(
        select(UnreadNotificationRule).where(
            UnreadNotificationRule.user_id == user_id,
            UnreadNotificationRule.channel_id.is_(None),
        )
    )).scalar_one_or_none()
    channel_rule = None
    if channel_id:
        channel_rule = (await db.execute(
            select(UnreadNotificationRule).where(
                UnreadNotificationRule.user_id == user_id,
                UnreadNotificationRule.channel_id == channel_id,
            )
        )).scalar_one_or_none()

    rule = UnreadRule()
    if global_rule:
        rule.enabled = global_rule.enabled
        rule.target_ids = [uuid.UUID(str(item)) for item in (global_rule.target_ids or []) if item]
        rule.immediate_enabled = global_rule.immediate_enabled
        rule.reminder_enabled = global_rule.reminder_enabled
        rule.reminder_delay_minutes = max(1, global_rule.reminder_delay_minutes or DEFAULT_REMINDER_DELAY_MINUTES)
        rule.preview_policy = global_rule.preview_policy or "short"
    if channel_rule:
        rule.enabled = channel_rule.enabled
        channel_targets = [uuid.UUID(str(item)) for item in (channel_rule.target_ids or []) if item]
        if channel_rule.target_mode == "replace":
            rule.target_ids = channel_targets
        elif channel_targets:
            rule.target_ids = list(dict.fromkeys([*(rule.target_ids or []), *channel_targets]))
        rule.immediate_enabled = channel_rule.immediate_enabled
        rule.reminder_enabled = channel_rule.reminder_enabled
        rule.reminder_delay_minutes = max(1, channel_rule.reminder_delay_minutes or rule.reminder_delay_minutes)
        rule.preview_policy = channel_rule.preview_policy or rule.preview_policy
    if not rule.target_ids:
        rule.target_ids = await _default_push_target_ids(db, user_id)
    return rule


async def _default_push_target_ids(db: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    rows = (await db.execute(
        select(NotificationTarget).where(
            NotificationTarget.kind == "user_push",
            NotificationTarget.enabled.is_(True),
        )
    )).scalars().all()
    matches = [
        row.id for row in rows
        if str((row.config or {}).get("user_id") or "") == str(user_id)
    ]
    if matches:
        return matches
    has_subscription = (await db.execute(
        select(PushSubscription.id).where(PushSubscription.user_id == user_id).limit(1)
    )).scalar_one_or_none()
    if not has_subscription:
        return []
    row = NotificationTarget(
        id=uuid.uuid4(),
        slug=normalize_slug(f"user-{user_id}-push"),
        label="User push",
        kind="user_push",
        config={"user_id": str(user_id), "only_if_inactive": True},
        enabled=True,
        allowed_bot_ids=[],
        created_by="unread_default",
    )
    db.add(row)
    await db.flush()
    return [row.id]


async def _expand_target_ids(db: AsyncSession, target_ids: list[uuid.UUID]) -> list[NotificationTarget]:
    expanded: list[NotificationTarget] = []
    seen: set[uuid.UUID] = set()

    async def visit(target_id: uuid.UUID) -> None:
        if target_id in seen:
            return
        seen.add(target_id)
        target = await db.get(NotificationTarget, target_id)
        if not target or not target.enabled:
            return
        if target.kind == "group":
            for child in target.config.get("target_ids") or []:
                try:
                    await visit(uuid.UUID(str(child)))
                except ValueError:
                    continue
            return
        expanded.append(target)

    for target_id in target_ids:
        await visit(target_id)
    return expanded


async def _filter_targets_for_channel(
    db: AsyncSession,
    *,
    targets: list[NotificationTarget],
    channel_id: uuid.UUID | None,
) -> list[NotificationTarget]:
    if channel_id is None:
        return targets
    integrations = (await db.execute(
        select(ChannelIntegration.integration_type, ChannelIntegration.client_id)
        .where(ChannelIntegration.channel_id == channel_id)
    )).all()
    mirrored_bindings = {(itype, client_id) for itype, client_id in integrations}
    out: list[NotificationTarget] = []
    for target in targets:
        config = target.config or {}
        if target.kind == "channel" and str(config.get("channel_id") or "") == str(channel_id):
            continue
        if target.kind == "integration_binding":
            key = (config.get("integration_type"), config.get("client_id"))
            if key in mirrored_bindings:
                continue
        out.append(target)
    return out


def _preview(record: Message, policy: str) -> str:
    if policy == "none":
        return "New reply is waiting."
    text = str(record.content or "").strip().replace("\n", " ")
    if policy == "full":
        return text[:500] or "New reply is waiting."
    return (text[:180] + "...") if len(text) > 180 else (text or "New reply is waiting.")


async def _send_unread_notification(
    *,
    target_ids: list[uuid.UUID],
    title: str,
    body: str,
    url: str | None,
    session_id: uuid.UUID,
    bot_id: str | None,
    reminder: bool,
) -> None:
    payload = NotificationPayload(
        title=title,
        body=body,
        url=url,
        severity="info",
        tag=f"unread:{session_id}",
    )
    for target_id in target_ids:
        try:
            await send_notification(
                target_id,
                payload,
                sender_type="unread_reminder" if reminder else "unread",
                sender_id=str(session_id),
                bot_id=bot_id,
                enforce_bot_grant=False,
                actor_label="Unread Reminder" if reminder else "Unread",
            )
        except Exception:
            logger.warning("unread notification failed target=%s session=%s", target_id, session_id, exc_info=True)


async def process_persisted_messages(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    bus_channel_id: uuid.UUID | None,
    records: list[Message],
) -> None:
    record_ids = [record.id for record in records if record.id is not None]
    if not record_ids:
        return
    rows = (await db.execute(
        select(Message).where(Message.id.in_(record_ids))
    )).scalars().all()
    rows_by_id = {row.id: row for row in rows}
    persisted = [rows_by_id[record_id] for record_id in record_ids if record_id in rows_by_id]
    messages = [record for record in persisted if _is_unread_worthy(record)]
    if not messages:
        return
    session = await db.get(Session, session_id)
    if session is None:
        return
    channel_id = session.channel_id or session.parent_channel_id or bus_channel_id
    recipient_ids = await _recipient_user_ids(db, session, channel_id)
    if not recipient_ids:
        return
    latest = messages[-1]
    now = datetime.now(timezone.utc)
    pending_sends: list[tuple[list[uuid.UUID], str, str, str | None, str | None, uuid.UUID]] = []

    for user_id in recipient_ids:
        if is_session_visible(user_id, session_id, now=now):
            await mark_session_read(
                db,
                user_id=user_id,
                session_id=session_id,
                source="visible_agent_reply",
                surface="web",
                message_id=latest.id,
            )
            continue

        rule = await _resolve_rule(db, user_id, channel_id)
        row = await _get_or_create_state(db, user_id=user_id, session_id=session_id, channel_id=channel_id)
        was_unread = row.unread_agent_reply_count > 0
        row.first_unread_at = row.first_unread_at or messages[0].created_at or now
        row.latest_unread_at = latest.created_at or now
        row.latest_unread_message_id = latest.id
        row.latest_unread_correlation_id = latest.correlation_id
        row.unread_agent_reply_count = int(row.unread_agent_reply_count or 0) + len(messages)
        row.reminder_due_at = (
            now + timedelta(minutes=rule.reminder_delay_minutes)
            if rule.enabled and rule.reminder_enabled
            else None
        )
        row.reminder_sent_at = None
        row.updated_at = now
        user_events.publish(user_id, "read_state_updated", {"state": serialize_read_state(row)})

        if rule.enabled and rule.immediate_enabled and not was_unread and rule.target_ids:
            targets = await _expand_target_ids(db, rule.target_ids)
            targets = await _filter_targets_for_channel(db, targets=targets, channel_id=channel_id)
            if targets:
                row.initial_notified_at = now
                channel = await db.get(Channel, channel_id) if channel_id else None
                title = f"New reply in {channel.name}" if channel else "New agent reply"
                url = f"/channels/{channel_id}" if channel_id else None
                pending_sends.append((
                    [target.id for target in targets],
                    title,
                    _preview(latest, rule.preview_policy),
                    url,
                    session.bot_id,
                    session_id,
                ))

    await db.commit()
    for target_ids, title, body, url, bot_id, sid in pending_sends:
        await _send_unread_notification(
            target_ids=target_ids,
            title=title,
            body=body,
            url=url,
            session_id=sid,
            bot_id=bot_id,
            reminder=False,
        )


async def send_due_reminders_once() -> int:
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        rows = (await db.execute(
            select(SessionReadState)
            .where(
                SessionReadState.unread_agent_reply_count > 0,
                SessionReadState.reminder_due_at.isnot(None),
                SessionReadState.reminder_due_at <= now,
                SessionReadState.reminder_sent_at.is_(None),
            )
            .order_by(SessionReadState.reminder_due_at)
            .limit(100)
        )).scalars().all()
        pending: list[tuple[list[uuid.UUID], str, str, str | None, str | None, uuid.UUID]] = []
        for row in rows:
            rule = await _resolve_rule(db, row.user_id, row.channel_id)
            if not (rule.enabled and rule.reminder_enabled and rule.target_ids):
                row.reminder_sent_at = now
                row.updated_at = now
                continue
            targets = await _expand_target_ids(db, rule.target_ids)
            targets = await _filter_targets_for_channel(db, targets=targets, channel_id=row.channel_id)
            if not targets:
                row.reminder_sent_at = now
                row.updated_at = now
                continue
            latest = await db.get(Message, row.latest_unread_message_id) if row.latest_unread_message_id else None
            session = await db.get(Session, row.session_id)
            channel = await db.get(Channel, row.channel_id) if row.channel_id else None
            count = row.unread_agent_reply_count
            title = f"{count} unread agent {'replies' if count != 1 else 'reply'}"
            if channel:
                title = f"{title} in {channel.name}"
            body = _preview(latest, rule.preview_policy) if latest else "Unread reply is waiting."
            url = f"/channels/{row.channel_id}" if row.channel_id else None
            row.reminder_sent_at = now
            row.updated_at = now
            pending.append(([target.id for target in targets], title, body, url, session.bot_id if session else None, row.session_id))
        await db.commit()
    for target_ids, title, body, url, bot_id, session_id in pending:
        await _send_unread_notification(
            target_ids=target_ids,
            title=title,
            body=body,
            url=url,
            session_id=session_id,
            bot_id=bot_id,
            reminder=True,
        )
    return len(pending)


async def unread_reminder_worker() -> None:
    while True:
        try:
            await send_due_reminders_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("unread reminder worker tick failed")
        await asyncio.sleep(60)


def start_unread_reminder_worker() -> asyncio.Task:
    global _reminder_task
    if _reminder_task is None or _reminder_task.done():
        _reminder_task = asyncio.create_task(unread_reminder_worker())
    return _reminder_task
