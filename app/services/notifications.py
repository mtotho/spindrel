"""Core notification target service.

Notification targets are admin-managed destinations that wrap existing
delivery primitives: Web Push, channel outbox delivery, direct integration
binding render, and best-effort groups.
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session
from app.db.models import (
    Channel,
    ChannelIntegration,
    Message as MessageRow,
    NotificationDelivery,
    NotificationTarget,
    PushSubscription,
    Session as SessionRow,
    UsageSpikeConfig,
    User,
)

logger = logging.getLogger(__name__)

TARGET_KINDS = {"user_push", "channel", "integration_binding", "group"}
SEVERITIES = {"info", "success", "warning", "critical"}


@dataclass(slots=True)
class NotificationPayload:
    title: str
    body: str
    url: str | None = None
    severity: str = "info"
    tag: str | None = None


def normalize_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or f"target-{uuid.uuid4().hex[:8]}"


def serialize_target(row: NotificationTarget) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "slug": row.slug,
        "label": row.label,
        "kind": row.kind,
        "config": row.config or {},
        "enabled": row.enabled,
        "allowed_bot_ids": row.allowed_bot_ids or [],
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def serialize_delivery(row: NotificationDelivery) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "target_id": str(row.target_id) if row.target_id else None,
        "root_target_id": str(row.root_target_id) if row.root_target_id else None,
        "sender_type": row.sender_type,
        "sender_id": row.sender_id,
        "title": row.title,
        "body_preview": row.body_preview,
        "url": row.url,
        "severity": row.severity,
        "tag": row.tag,
        "attempts": row.attempts,
        "succeeded": row.succeeded,
        "delivery_details": row.delivery_details or [],
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def bot_can_use_target(target: NotificationTarget, bot_id: str | None) -> bool:
    if not target.enabled:
        return False
    allowed = [str(item) for item in (target.allowed_bot_ids or []) if item]
    return bool(bot_id and bot_id in allowed)


async def list_targets(db: AsyncSession, *, bot_id: str | None = None, include_disabled: bool = False) -> list[NotificationTarget]:
    q = select(NotificationTarget).order_by(NotificationTarget.label)
    if not include_disabled:
        q = q.where(NotificationTarget.enabled.is_(True))
    rows = list((await db.execute(q)).scalars().all())
    if bot_id is None:
        return rows
    return [row for row in rows if bot_can_use_target(row, bot_id)]


async def available_destinations(db: AsyncSession) -> dict[str, Any]:
    from app.agent.hooks import _meta_registry, get_integration_meta

    options: list[dict[str, Any]] = []

    push_rows = (await db.execute(
        select(User, PushSubscription.id)
        .join(PushSubscription, PushSubscription.user_id == User.id)
        .order_by(User.display_name)
    )).all()
    seen_users: set[uuid.UUID] = set()
    for user, _sub_id in push_rows:
        if user.id in seen_users:
            continue
        seen_users.add(user.id)
        options.append({
            "kind": "user_push",
            "label": f"{user.display_name} push",
            "config": {"user_id": str(user.id), "only_if_inactive": True},
            "description": user.email,
        })

    channels = (await db.execute(select(Channel).order_by(Channel.name))).scalars().all()
    for channel in channels:
        options.append({
            "kind": "channel",
            "label": f"#{channel.name}",
            "config": {"channel_id": str(channel.id)},
            "description": channel.integration or channel.bot_id,
        })

    bindings = (await db.execute(
        select(ChannelIntegration).order_by(ChannelIntegration.integration_type, ChannelIntegration.client_id)
    )).scalars().all()
    seen_bindings: set[tuple[str, str]] = set()
    for binding in bindings:
        key = (binding.integration_type, binding.client_id)
        if key in seen_bindings:
            continue
        meta = get_integration_meta(binding.integration_type)
        if binding.dispatch_config is None and not (meta and meta.resolve_dispatch_config):
            continue
        seen_bindings.add(key)
        options.append({
            "kind": "integration_binding",
            "label": binding.display_name or binding.client_id,
            "config": {"integration_type": binding.integration_type, "client_id": binding.client_id},
            "description": binding.integration_type,
        })

    available_integrations = [
        {"integration_type": itype, "client_id_prefix": meta.client_id_prefix}
        for itype, meta in _meta_registry.items()
        if meta.resolve_dispatch_config is not None
    ]
    return {"options": options, "integrations": available_integrations}


async def send_notification(
    target_id: uuid.UUID,
    payload: NotificationPayload,
    *,
    sender_type: str,
    sender_id: str | None = None,
    bot_id: str | None = None,
    enforce_bot_grant: bool = False,
    actor_label: str = "Notification",
) -> dict[str, Any]:
    if not payload.title.strip() or not payload.body.strip():
        raise ValueError("title and body are required")
    if payload.severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {sorted(SEVERITIES)}")

    async with async_session() as db:
        target = await db.get(NotificationTarget, target_id)
        if not target:
            raise ValueError("notification target not found")
        if not target.enabled:
            raise ValueError("notification target is disabled")
        if enforce_bot_grant and not bot_can_use_target(target, bot_id):
            raise PermissionError("bot is not allowed to use this notification target")

    details: list[dict[str, Any]] = []
    await _send_target(target_id, payload, details, seen=set(), actor_label=actor_label)
    attempts = len(details)
    succeeded = sum(1 for detail in details if detail.get("success"))

    async with async_session() as db:
        delivery = NotificationDelivery(
            target_id=target_id,
            root_target_id=target_id,
            sender_type=sender_type,
            sender_id=sender_id,
            title=payload.title,
            body_preview=payload.body[:500],
            url=payload.url,
            severity=payload.severity,
            tag=payload.tag,
            attempts=attempts,
            succeeded=succeeded,
            delivery_details=details,
        )
        db.add(delivery)
        await db.commit()
        await db.refresh(delivery)
        result = serialize_delivery(delivery)
    return {"attempts": attempts, "succeeded": succeeded, "delivery": result, "details": details}


async def _send_target(
    target_id: uuid.UUID,
    payload: NotificationPayload,
    details: list[dict[str, Any]],
    *,
    seen: set[uuid.UUID],
    actor_label: str,
) -> None:
    if target_id in seen:
        details.append({"target_id": str(target_id), "success": False, "error": "group cycle detected"})
        return
    seen.add(target_id)

    async with async_session() as db:
        target = await db.get(NotificationTarget, target_id)
        if not target:
            details.append({"target_id": str(target_id), "success": False, "error": "target not found"})
            return
        config = target.config or {}
        target_ref = {"id": str(target.id), "label": target.label, "kind": target.kind}

    if not target.enabled:
        details.append({"target": target_ref, "success": False, "error": "target disabled"})
        return

    if target.kind == "group":
        child_ids = [str(item) for item in (config.get("target_ids") or []) if item]
        if not child_ids:
            details.append({"target": target_ref, "success": False, "error": "group has no targets"})
            return
        for child in child_ids:
            try:
                await _send_target(uuid.UUID(child), payload, details, seen=set(seen), actor_label=actor_label)
            except ValueError as exc:
                details.append({"target": target_ref, "child_id": child, "success": False, "error": str(exc)})
        return

    detail: dict[str, Any] = {"target": target_ref, "success": False}
    try:
        if target.kind == "user_push":
            await _send_user_push(config, payload, detail)
        elif target.kind == "channel":
            await _send_channel(config, payload, detail, actor_label=actor_label)
        elif target.kind == "integration_binding":
            await _send_integration_binding(config, payload, detail, actor_label=actor_label)
        else:
            detail["error"] = f"unknown target kind: {target.kind}"
    except Exception as exc:  # noqa: BLE001
        detail["error"] = str(exc)
        logger.warning("notification send failed for target %s: %s", target_id, exc)
    details.append(detail)


async def _send_user_push(config: dict[str, Any], payload: NotificationPayload, detail: dict[str, Any]) -> None:
    from app.services.push import PushDisabledError, send_push

    user_id_raw = config.get("user_id")
    if not user_id_raw:
        detail["error"] = "missing user_id"
        return
    user_id = uuid.UUID(str(user_id_raw))
    only_if_inactive = bool(config.get("only_if_inactive", True))
    async with async_session() as db:
        try:
            result = await send_push(
                db,
                user_id,
                payload.title,
                payload.body,
                url=payload.url,
                tag=payload.tag,
                only_if_inactive=only_if_inactive,
            )
        except PushDisabledError as exc:
            detail["error"] = str(exc)
            return
    detail.update({
        "success": result.sent > 0 or result.skipped_active,
        "sent": result.sent,
        "failed": result.failed,
        "pruned": result.pruned,
        "skipped_active": result.skipped_active,
    })
    if not detail["success"]:
        detail["error"] = "no subscribed devices delivered"


async def _send_channel(config: dict[str, Any], payload: NotificationPayload, detail: dict[str, Any], *, actor_label: str) -> None:
    channel_id_raw = config.get("channel_id")
    if not channel_id_raw:
        detail["error"] = "missing channel_id"
        return
    channel_id = uuid.UUID(str(channel_id_raw))
    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        session_id: uuid.UUID | None = None
        if channel:
            session_id = channel.active_session_id
            if session_id is None:
                session_id = (await db.execute(
                    select(SessionRow.id)
                    .where(SessionRow.channel_id == channel_id)
                    .order_by(SessionRow.created_at.desc())
                    .limit(1)
                )).scalar_one_or_none()
    if not channel:
        detail["error"] = "channel not found"
        return

    from app.domain.actor import ActorRef
    from app.domain.channel_events import ChannelEvent, ChannelEventKind
    from app.domain.message import Message as DomainMessage
    from app.domain.payloads import MessagePayload
    from app.services.channel_events import publish_typed
    from app.services.outbox_publish import enqueue_new_message_for_channel

    content = f"{payload.title}\n\n{payload.body}" if payload.title else payload.body
    metadata = {"source": "notification", "severity": payload.severity, "tag": payload.tag}
    message_id = uuid.uuid4()
    created_at = datetime.now(timezone.utc)
    if session_id is not None:
        async with async_session() as db:
            row = MessageRow(
                id=message_id,
                session_id=session_id,
                role="system",
                content=content,
                metadata_=metadata,
                created_at=created_at,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            created_at = row.created_at or created_at
    domain_msg = DomainMessage(
        id=message_id,
        session_id=session_id or uuid.UUID(int=0),
        role="system",
        content=content,
        created_at=created_at,
        actor=ActorRef.system("notification", actor_label),
        metadata=metadata,
        channel_id=channel_id,
    )
    await enqueue_new_message_for_channel(channel_id, domain_msg)
    publish_typed(
        channel_id,
        ChannelEvent(
            channel_id=channel_id,
            kind=ChannelEventKind.NEW_MESSAGE,
            payload=MessagePayload(message=domain_msg),
        ),
    )
    detail["success"] = True


async def _send_integration_binding(config: dict[str, Any], payload: NotificationPayload, detail: dict[str, Any], *, actor_label: str) -> None:
    integration_type = config.get("integration_type")
    client_id = config.get("client_id")
    if not integration_type or not client_id:
        detail["error"] = "missing integration_type or client_id"
        return

    from app.agent.hooks import get_integration_meta
    from app.domain.actor import ActorRef
    from app.domain.channel_events import ChannelEvent, ChannelEventKind
    from app.domain.dispatch_target import parse_dispatch_target
    from app.domain.message import Message as DomainMessage
    from app.domain.payloads import MessagePayload
    from app.integrations import renderer_registry

    meta = get_integration_meta(integration_type)
    if not meta or not meta.resolve_dispatch_config:
        detail["error"] = f"integration {integration_type} has no dispatch resolver"
        return
    dispatch_config = meta.resolve_dispatch_config(client_id)
    if not dispatch_config:
        detail["error"] = f"could not resolve dispatch config for {client_id}"
        return
    renderer = renderer_registry.get(integration_type)
    if renderer is None:
        detail["error"] = f"no renderer registered for integration_type={integration_type}"
        return

    typed_target = parse_dispatch_target({"type": integration_type, **dispatch_config})
    content = f"{payload.title}\n\n{payload.body}" if payload.title else payload.body
    event = ChannelEvent(
        channel_id=uuid.UUID(int=0),
        kind=ChannelEventKind.NEW_MESSAGE,
        payload=MessagePayload(
            message=DomainMessage(
                id=uuid.uuid4(),
                session_id=uuid.UUID(int=0),
                role="system",
                content=content,
                created_at=datetime.now(timezone.utc),
                actor=ActorRef.system("notification", actor_label),
                channel_id=None,
                metadata={"source": "notification", "severity": payload.severity, "tag": payload.tag},
            ),
        ),
    )
    receipt = await renderer.render(event, typed_target)
    detail["success"] = receipt.success
    if not receipt.success:
        detail["error"] = receipt.error or "renderer returned failure"


async def ensure_legacy_spike_targets_migrated(db: AsyncSession, config: UsageSpikeConfig) -> bool:
    if config.target_ids:
        return False
    legacy_targets = config.targets or []
    if not legacy_targets:
        return False

    target_ids: list[str] = []
    for legacy in legacy_targets:
        kind = "channel" if legacy.get("type") == "channel" else "integration_binding"
        label = legacy.get("label") or legacy.get("channel_id") or legacy.get("client_id") or "usage alert"
        config_payload = (
            {"channel_id": legacy.get("channel_id")}
            if kind == "channel"
            else {"integration_type": legacy.get("integration_type"), "client_id": legacy.get("client_id")}
        )
        slug = normalize_slug(f"usage-{kind}-{label}")
        existing = (await db.execute(select(NotificationTarget).where(NotificationTarget.slug == slug))).scalar_one_or_none()
        if existing is None:
            existing = NotificationTarget(
                slug=slug,
                label=f"Usage alert: {label}",
                kind=kind,
                config=config_payload,
                enabled=True,
                allowed_bot_ids=[],
                created_by="usage_spike_migration",
            )
            db.add(existing)
            await db.flush()
        target_ids.append(str(existing.id))

    config.target_ids = target_ids
    await db.commit()
    return True
