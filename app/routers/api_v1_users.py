"""Admin user management API — /api/v1/admin/users."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, ConversationSection, Message, Session, User
from app.dependencies import get_db, require_scopes
from app.services.auth import create_local_user, get_user_by_id, hash_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    avatar_url: str | None
    integration_config: dict
    is_admin: bool
    is_active: bool
    auth_method: str
    created_at: str


class CreateUserRequest(BaseModel):
    email: str
    display_name: str
    password: str


class UpdateUserRequest(BaseModel):
    display_name: str | None = None
    avatar_url: str | None = None
    integration_config: dict | None = None
    is_admin: bool | None = None
    is_active: bool | None = None
    password: str | None = None  # reset password (local only)


class UserActivityLatestSessionOut(BaseModel):
    session_id: str
    channel_id: str
    channel_name: str
    label: str | None
    preview: str | None
    last_active: str | None
    message_count: int
    section_count: int


class UserActivitySummaryOut(BaseModel):
    id: str
    email: str
    display_name: str
    avatar_url: str | None
    is_admin: bool
    is_active: bool
    today_message_count: int
    today_session_count: int
    today_channel_count: int
    latest_activity_at: str | None
    latest_session: UserActivityLatestSessionOut | None


class UserActivitySummaryListOut(BaseModel):
    users: list[UserActivitySummaryOut]


def _user_out(u: User) -> UserOut:
    return UserOut(
        id=str(u.id),
        email=u.email,
        display_name=u.display_name,
        avatar_url=u.avatar_url,
        integration_config=u.integration_config or {},
        is_admin=u.is_admin,
        is_active=u.is_active,
        auth_method=u.auth_method,
        created_at=u.created_at.isoformat() if u.created_at else "",
    )


def _truncate_preview(content: str | None, limit: int = 140) -> str | None:
    if not content:
        return None
    normalized = " ".join(content.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1].rstrip()}…"


def _sender_ids_for_user(user: User) -> list[str]:
    sender_ids = [f"user:{user.id}"]
    integration_config = user.integration_config or {}
    if isinstance(integration_config, dict):
        for integration, config in integration_config.items():
            if isinstance(config, dict):
                external_id = config.get("user_id")
                if external_id:
                    sender_ids.append(f"{integration}:{external_id}")
    return sender_ids


@router.get("", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("users:read")),
):
    result = await db.execute(select(User).order_by(User.created_at))
    return [_user_out(u) for u in result.scalars().all()]


@router.get("/activity-summary", response_model=UserActivitySummaryListOut)
async def user_activity_summary(
    limit: int = Query(6, ge=1, le=25),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("users:read")),
):
    users = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    if not users:
        return UserActivitySummaryListOut(users=[])

    sender_to_user: dict[str, uuid.UUID] = {}
    for user in users:
        for sender_id in _sender_ids_for_user(user):
            sender_to_user.setdefault(sender_id, user.id)
    sender_ids = list(sender_to_user)

    today_message_counts: dict[uuid.UUID, int] = {user.id: 0 for user in users}
    today_session_ids: dict[uuid.UUID, set[uuid.UUID]] = {user.id: set() for user in users}
    today_channel_ids: dict[uuid.UUID, set[uuid.UUID]] = {user.id: set() for user in users}
    latest_message_by_user: dict[uuid.UUID, Message] = {}
    session_by_id: dict[uuid.UUID, Session] = {}
    channel_by_id: dict[uuid.UUID, Channel] = {}

    if sender_ids:
        sender_expr = Message.metadata_["sender_id"].astext
        today_start = datetime.combine(
            datetime.now(timezone.utc).date(),
            time.min,
            tzinfo=timezone.utc,
        )

        today_rows = await db.execute(
            select(sender_expr, Message.session_id, Session.channel_id, Session.parent_channel_id)
            .join(Session, Session.id == Message.session_id)
            .where(
                Message.role == "user",
                sender_expr.in_(sender_ids),
                Message.created_at >= today_start,
            )
        )
        for sender_id, session_id, channel_id, parent_channel_id in today_rows.all():
            user_id = sender_to_user.get(sender_id)
            if user_id is None:
                continue
            today_message_counts[user_id] += 1
            today_session_ids[user_id].add(session_id)
            visible_channel_id = parent_channel_id or channel_id
            if visible_channel_id:
                today_channel_ids[user_id].add(visible_channel_id)

        latest_rows = await db.execute(
            select(Message, Session, Channel)
            .join(Session, Session.id == Message.session_id)
            .outerjoin(Channel, Channel.id == func.coalesce(Session.parent_channel_id, Session.channel_id))
            .where(
                Message.role == "user",
                sender_expr.in_(sender_ids),
            )
            .order_by(Message.created_at.desc())
            .limit(max(100, len(sender_ids) * 20))
        )
        for message, session, channel in latest_rows.all():
            sender_id = (message.metadata_ or {}).get("sender_id")
            user_id = sender_to_user.get(sender_id)
            if user_id is None or user_id in latest_message_by_user:
                continue
            latest_message_by_user[user_id] = message
            session_by_id[session.id] = session
            if channel is not None:
                channel_by_id[channel.id] = channel

    latest_session_ids = {message.session_id for message in latest_message_by_user.values()}
    message_counts_by_session: dict[uuid.UUID, int] = {}
    section_counts_by_session: dict[uuid.UUID, int] = {}
    if latest_session_ids:
        message_count_rows = await db.execute(
            select(Message.session_id, func.count(Message.id))
            .where(Message.session_id.in_(latest_session_ids))
            .group_by(Message.session_id)
        )
        message_counts_by_session = {session_id: count for session_id, count in message_count_rows.all()}

        section_count_rows = await db.execute(
            select(ConversationSection.session_id, func.count(ConversationSection.id))
            .where(ConversationSection.session_id.in_(latest_session_ids))
            .group_by(ConversationSection.session_id)
        )
        section_counts_by_session = {
            session_id: count
            for session_id, count in section_count_rows.all()
            if session_id is not None
        }

    rows: list[UserActivitySummaryOut] = []
    for user in users:
        latest_message = latest_message_by_user.get(user.id)
        latest_session = None
        if latest_message is not None:
            session = session_by_id.get(latest_message.session_id)
            visible_channel_id = session.parent_channel_id or session.channel_id if session else None
            channel = channel_by_id.get(visible_channel_id) if visible_channel_id else None
            preview = _truncate_preview(latest_message.content)
            if session is not None and visible_channel_id is not None:
                latest_session = UserActivityLatestSessionOut(
                    session_id=str(session.id),
                    channel_id=str(visible_channel_id),
                    channel_name=channel.name if channel is not None else "Unknown channel",
                    label=session.title or session.summary or preview,
                    preview=preview,
                    last_active=session.last_active.isoformat() if session.last_active else None,
                    message_count=message_counts_by_session.get(session.id, 0),
                    section_count=section_counts_by_session.get(session.id, 0),
                )

        rows.append(UserActivitySummaryOut(
            id=str(user.id),
            email=user.email,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            is_admin=user.is_admin,
            is_active=user.is_active,
            today_message_count=today_message_counts.get(user.id, 0),
            today_session_count=len(today_session_ids.get(user.id, set())),
            today_channel_count=len(today_channel_ids.get(user.id, set())),
            latest_activity_at=latest_message.created_at.isoformat() if latest_message else None,
            latest_session=latest_session,
        ))

    rows.sort(
        key=lambda row: (
            not row.is_active,
            -(datetime.fromisoformat(row.latest_activity_at).timestamp() if row.latest_activity_at else 0),
            row.display_name.lower(),
        )
    )
    return UserActivitySummaryListOut(users=rows[:limit])


@router.post("", response_model=UserOut)
async def create_user(
    req: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("users:write")),
):
    user = await create_local_user(db, req.email, req.display_name, req.password)
    return _user_out(user)


@router.put("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    req: UpdateUserRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("users:write")),
):
    from uuid import UUID
    user = await get_user_by_id(db, UUID(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if req.display_name is not None:
        user.display_name = req.display_name
    if req.avatar_url is not None:
        user.avatar_url = req.avatar_url
    if req.integration_config is not None:
        user.integration_config = req.integration_config
    if req.is_admin is not None:
        role_changed = req.is_admin != user.is_admin
        user.is_admin = req.is_admin
    else:
        role_changed = False
    if req.is_active is not None:
        user.is_active = req.is_active
    if req.password is not None and user.auth_method == "local":
        user.password_hash = hash_password(req.password)
    await db.commit()
    await db.refresh(user)

    # Sync API key scopes when role changes
    if role_changed and user.api_key_id:
        from app.services.api_keys import ensure_entity_api_key, SCOPE_PRESETS
        preset_name = "admin_user" if user.is_admin else "member_user"
        scopes = SCOPE_PRESETS[preset_name]["scopes"]
        await ensure_entity_api_key(
            db, name=f"user:{user.email}", scopes=scopes,
            existing_key_id=user.api_key_id,
        )
        await db.commit()

    return _user_out(user)


@router.delete("/{user_id}")
async def deactivate_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("users:write")),
):
    from uuid import UUID
    user = await get_user_by_id(db, UUID(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = False
    await db.commit()
    return {"status": "deactivated"}


@router.get("/identity-suggestions/{integration}")
async def identity_suggestions(
    integration: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("users:read")),
):
    """Return distinct sender IDs for an integration, excluding already-claimed ones."""
    prefix = f"{integration}:"
    stmt = select(distinct(Message.metadata_["sender_id"].astext)).where(
        Message.metadata_["sender_id"].astext.like(f"{prefix}%"),
        Message.metadata_["sender_type"].astext == "human",
    )
    result = await db.execute(stmt)
    all_ids = [row[0].removeprefix(prefix) for row in result.all()]

    # Filter out claimed
    users_result = await db.execute(select(User))
    users = users_result.scalars().all()
    claimed = {
        u.integration_config.get(integration, {}).get("user_id")
        for u in users if u.integration_config
    }
    return [uid for uid in all_ids if uid not in claimed]
