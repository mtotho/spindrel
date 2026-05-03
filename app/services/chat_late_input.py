from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.engine import async_session
from app.db.models import Message, Task


@dataclass
class AbsorbedChatBurst:
    task_id: uuid.UUID
    message_ids: list[uuid.UUID]
    messages: list[Message]
    attachment_payloads: list[dict]
    attachments_by_message_id: dict[uuid.UUID, list[dict]] = field(default_factory=dict)
    session_scoped: bool = False
    task_scheduled_age_seconds: float | None = None


def _uuid_list(raw_ids: Any) -> list[uuid.UUID]:
    if not isinstance(raw_ids, list):
        return []
    parsed: list[uuid.UUID] = []
    for raw_id in raw_ids:
        try:
            parsed.append(uuid.UUID(str(raw_id)))
        except (TypeError, ValueError):
            continue
    return parsed


def _matching_chat_burst_config(task: Task) -> dict[str, Any] | None:
    ecfg = task.execution_config if isinstance(task.execution_config, dict) else {}
    if ecfg.get("chat_burst") is not True:
        return None
    if ecfg.get("absorbed_by_correlation_id"):
        return None
    return ecfg


async def _load_ordered_messages(
    db: AsyncSession,
    message_ids: list[uuid.UUID],
) -> list[Message]:
    if not message_ids:
        return []
    rows = await db.execute(
        select(Message)
        .options(selectinload(Message.attachments))
        .where(Message.id.in_(message_ids))
    )
    by_id = {msg.id: msg for msg in rows.scalars().all()}
    return [by_id[msg_id] for msg_id in message_ids if msg_id in by_id]


def _image_payloads_for_message(message: Message, *, max_images: int) -> list[dict]:
    payloads: list[dict] = []
    if max_images <= 0:
        return payloads
    for attachment in message.attachments or []:
        if len(payloads) >= max_images:
            break
        if attachment.type != "image" or not attachment.file_data:
            continue
        payloads.append({
            "type": "image",
            "content": base64.b64encode(attachment.file_data).decode("ascii"),
            "mime_type": attachment.mime_type or "image/jpeg",
            "name": attachment.filename or "attachment",
            "attachment_id": str(attachment.id),
            "source": "late_chat_burst",
        })
    return payloads


def _message_attachment_payloads(
    messages: list[Message],
    *,
    max_images: int,
) -> tuple[list[dict], dict[uuid.UUID, list[dict]]]:
    all_payloads: list[dict] = []
    by_message_id: dict[uuid.UUID, list[dict]] = {}
    remaining = max_images
    for message in messages:
        payloads = _image_payloads_for_message(message, max_images=remaining)
        if payloads:
            by_message_id[message.id] = payloads
            all_payloads.extend(payloads)
            remaining = max(0, max_images - len(all_payloads))
        if remaining <= 0:
            break
    return all_payloads, by_message_id


async def claim_pending_chat_burst(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    channel_id: uuid.UUID,
    bot_id: str,
    correlation_id: uuid.UUID,
    max_images: int = 6,
    now: datetime | None = None,
) -> AbsorbedChatBurst | None:
    now = now or datetime.now(timezone.utc)
    rows = await db.execute(
        select(Task)
        .where(Task.status == "pending")
        .where(Task.task_type == "api")
        .where(Task.session_id == session_id)
        .where(Task.channel_id == channel_id)
        .where(Task.bot_id == bot_id)
        .order_by(Task.created_at.asc())
        .limit(10)
        .with_for_update(skip_locked=True)
    )
    for task in rows.scalars().all():
        ecfg = _matching_chat_burst_config(task)
        if ecfg is None:
            continue
        message_ids = _uuid_list(ecfg.get("burst_user_msg_ids"))
        if not message_ids:
            message_ids = _uuid_list([ecfg.get("pre_user_msg_id")])
        messages = await _load_ordered_messages(db, message_ids)
        if not messages:
            continue

        attachment_payloads, attachments_by_message_id = _message_attachment_payloads(
            messages,
            max_images=max_images,
        )
        absorbed_config = dict(ecfg)
        absorbed_config.update({
            "absorbed_by_correlation_id": str(correlation_id),
            "absorbed_at": now.isoformat(),
            "absorbed_message_ids": [str(message.id) for message in messages],
        })
        task.status = "complete"
        task.completed_at = now
        task.result = "[absorbed into active turn]"
        task.execution_config = absorbed_config
        await db.flush()

        scheduled_age = None
        if task.created_at is not None:
            created_at = task.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            scheduled_age = max(0.0, (now - created_at).total_seconds())
        return AbsorbedChatBurst(
            task_id=task.id,
            message_ids=[message.id for message in messages],
            messages=messages,
            attachment_payloads=attachment_payloads,
            attachments_by_message_id=attachments_by_message_id,
            session_scoped=bool(absorbed_config.get("session_scoped")),
            task_scheduled_age_seconds=scheduled_age,
        )
    return None


async def drain_pending_chat_burst(
    *,
    session_id: uuid.UUID,
    channel_id: uuid.UUID | None,
    bot_id: str,
    correlation_id: uuid.UUID,
    max_images: int = 6,
) -> AbsorbedChatBurst | None:
    if channel_id is None:
        return None
    async with async_session() as db:
        bundle = await claim_pending_chat_burst(
            db,
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            correlation_id=correlation_id,
            max_images=max_images,
        )
        await db.commit()
        return bundle
