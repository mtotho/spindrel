from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.context import current_session_id, current_task_id
from app.db.engine import async_session
from app.db.models import MachineTargetLease, Session, Task, TaskMachineGrant

DEFAULT_TASK_LEASE_TTL_SECONDS = 900
DEFAULT_TASK_GRANT_CAPABILITIES = ("inspect", "exec")


@dataclass(frozen=True)
class ActiveTaskGrant:
    grant: TaskMachineGrant
    source_task_id: uuid.UUID


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_capabilities(
    values: list[str] | tuple[str, ...] | None,
    *,
    allowed_capabilities: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    allowed = tuple(allowed_capabilities or DEFAULT_TASK_GRANT_CAPABILITIES)
    caps = [str(value).strip() for value in (values or DEFAULT_TASK_GRANT_CAPABILITIES)]
    caps = [value for value in caps if value in allowed]
    return sorted(set(caps)) or list(allowed)


def _expires_at(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def is_grant_active(grant: TaskMachineGrant | None, *, now: datetime | None = None) -> bool:
    if grant is None:
        return False
    if grant.revoked_at is not None:
        return False
    expires_at = grant.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= (now or utc_now()):
            return False
    return True


async def _validate_task_machine_target(provider_id: str, target_id: str) -> tuple[dict[str, Any], list[str]]:
    from app.services.machine_control import (
        get_provider,
        get_provider_task_automation_capabilities,
        provider_supports_task_machine_automation,
    )

    if not provider_supports_task_machine_automation(provider_id):
        raise ValueError("Machine provider does not support scheduled task automation.")
    provider = get_provider(provider_id)
    target = provider.get_target(target_id)
    if target is None:
        raise ValueError("Unknown machine target.")
    return target, get_provider_task_automation_capabilities(provider_id)


async def upsert_task_machine_grant(
    db: AsyncSession,
    *,
    task: Task,
    provider_id: str,
    target_id: str,
    granted_by_user_id: uuid.UUID | None,
    capabilities: list[str] | None = None,
    allow_agent_tools: bool = True,
    expires_at: str | datetime | None = None,
) -> TaskMachineGrant:
    _target, allowed_capabilities = await _validate_task_machine_target(provider_id, target_id)
    now = utc_now()
    grant = (
        await db.execute(
            select(TaskMachineGrant).where(TaskMachineGrant.task_id == task.id)
        )
    ).scalar_one_or_none()
    if grant is None:
        grant = TaskMachineGrant(task_id=task.id)
        db.add(grant)
    grant.provider_id = provider_id
    grant.target_id = target_id
    grant.grant_id = str(uuid.uuid4())
    grant.granted_by_user_id = granted_by_user_id
    grant.capabilities = normalize_capabilities(capabilities, allowed_capabilities=allowed_capabilities)
    grant.allow_agent_tools = bool(allow_agent_tools)
    grant.expires_at = _expires_at(expires_at)
    grant.revoked_at = None
    grant.updated_at = now
    grant.metadata_ = {}
    await db.flush()
    return grant


async def revoke_task_machine_grant(db: AsyncSession, task_id: uuid.UUID) -> None:
    grant = (
        await db.execute(
            select(TaskMachineGrant).where(TaskMachineGrant.task_id == task_id)
        )
    ).scalar_one_or_none()
    if grant is None or grant.revoked_at is not None:
        return
    grant.revoked_at = utc_now()
    grant.updated_at = grant.revoked_at
    await db.flush()


async def get_active_task_machine_grant(
    db: AsyncSession,
    task_or_id: Task | uuid.UUID | None,
) -> ActiveTaskGrant | None:
    if task_or_id is None:
        return None
    task: Task | None
    if isinstance(task_or_id, Task):
        task = task_or_id
    else:
        task = await db.get(Task, task_or_id)
    if task is None:
        return None

    candidate_ids: list[uuid.UUID] = [task.id]
    if task.parent_task_id is not None:
        candidate_ids.append(task.parent_task_id)
    callback = task.callback_config if isinstance(task.callback_config, dict) else {}
    pipeline_task_id = callback.get("pipeline_task_id")
    if pipeline_task_id:
        try:
            candidate_ids.append(uuid.UUID(str(pipeline_task_id)))
        except ValueError:
            pass

    seen: set[uuid.UUID] = set()
    for task_id in candidate_ids:
        if task_id in seen:
            continue
        seen.add(task_id)
        grant = (
            await db.execute(
                select(TaskMachineGrant).where(TaskMachineGrant.task_id == task_id)
            )
        ).scalar_one_or_none()
        if is_grant_active(grant):
            return ActiveTaskGrant(grant=grant, source_task_id=task_id)
    return None


async def task_machine_grant_payload(
    db: AsyncSession,
    task: Task,
) -> dict[str, Any] | None:
    active = await get_active_task_machine_grant(db, task)
    if active is None:
        return None
    grant = active.grant
    from app.services.machine_control import get_provider

    provider = get_provider(grant.provider_id)
    target = provider.get_target(grant.target_id) or {}
    return {
        "provider_id": grant.provider_id,
        "target_id": grant.target_id,
        "grant_id": grant.grant_id,
        "grant_source_task_id": str(active.source_task_id),
        "granted_by_user_id": str(grant.granted_by_user_id) if grant.granted_by_user_id else None,
        "capabilities": list(grant.capabilities or []),
        "allow_agent_tools": bool(grant.allow_agent_tools),
        "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
        "created_at": grant.created_at.isoformat() if grant.created_at else None,
        "provider_label": getattr(provider, "label", None) or grant.provider_id,
        "target_label": target.get("label") or grant.target_id,
    }


async def probe_granted_target(db: AsyncSession, active: ActiveTaskGrant) -> dict[str, Any]:
    from app.services.machine_control import get_provider, provider_supports_task_machine_automation

    grant = active.grant
    if not provider_supports_task_machine_automation(grant.provider_id):
        raise ValueError("Machine provider does not support scheduled task automation.")
    provider = get_provider(grant.provider_id)
    target = provider.get_target(grant.target_id)
    if target is None:
        raise ValueError("The granted machine target no longer exists.")
    probed = await provider.probe_target(db, target_id=grant.target_id)
    if not bool(probed.get("ready")):
        reason = probed.get("reason") or "The granted machine target is not currently ready."
        raise ValueError(str(reason))
    return probed


def require_grant_capability(active: ActiveTaskGrant, capability: str) -> None:
    from app.services.machine_control import provider_supports_task_machine_automation

    if not provider_supports_task_machine_automation(active.grant.provider_id, capability=capability):
        raise PermissionError(f"Machine provider does not support scheduled '{capability}' automation.")
    if capability not in set(active.grant.capabilities or []):
        raise PermissionError(f"Task machine grant does not include '{capability}' capability.")


async def _user_id_for_lease(
    db: AsyncSession,
    grant: TaskMachineGrant,
    session: Session,
) -> uuid.UUID:
    if grant.granted_by_user_id is not None:
        return grant.granted_by_user_id
    if session.owner_user_id is not None:
        return session.owner_user_id
    raise PermissionError("Task machine grant has no user identity to attach to the runtime lease.")


async def ensure_task_machine_lease(
    db: AsyncSession,
    *,
    task: Task,
    session: Session,
    purpose: str,
    ttl_seconds: int = DEFAULT_TASK_LEASE_TTL_SECONDS,
) -> dict[str, Any] | None:
    active = await get_active_task_machine_grant(db, task)
    if active is None:
        return None
    grant = active.grant
    await probe_granted_target(db, active)
    user_id = await _user_id_for_lease(db, grant, session)
    now = utc_now()
    expires_at = now + timedelta(seconds=max(30, min(ttl_seconds, 3600)))

    existing = (
        await db.execute(
            select(MachineTargetLease).where(MachineTargetLease.session_id == session.id)
        )
    ).scalar_one_or_none()
    if (
        existing is not None
        and existing.provider_id == grant.provider_id
        and existing.target_id == grant.target_id
        and existing.expires_at > now
    ):
        existing.expires_at = expires_at
        existing.metadata_ = {
            **(existing.metadata_ or {}),
            "source": "task_machine_grant",
            "grant_id": grant.grant_id,
            "task_id": str(task.id),
            "grant_source_task_id": str(active.source_task_id),
            "purpose": purpose,
        }
        await db.flush()
        return _lease_payload(existing)

    await db.execute(delete(MachineTargetLease).where(MachineTargetLease.expires_at <= now))
    await db.execute(delete(MachineTargetLease).where(MachineTargetLease.session_id == session.id))
    lease = MachineTargetLease(
        session_id=session.id,
        user_id=user_id,
        provider_id=grant.provider_id,
        target_id=grant.target_id,
        lease_id=str(uuid.uuid4()),
        granted_at=now,
        expires_at=expires_at,
        capabilities=list(grant.capabilities or []),
        handle_id=None,
        connection_id=None,
        metadata_={
            "source": "task_machine_grant",
            "grant_id": grant.grant_id,
            "task_id": str(task.id),
            "grant_source_task_id": str(active.source_task_id),
            "purpose": purpose,
        },
    )
    db.add(lease)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise RuntimeError("The granted machine target is already leased by another session.") from exc
    return _lease_payload(lease)


def _lease_payload(row: MachineTargetLease) -> dict[str, Any]:
    return {
        "lease_id": row.lease_id,
        "provider_id": row.provider_id,
        "target_id": row.target_id,
        "user_id": str(row.user_id),
        "granted_at": row.granted_at.isoformat(),
        "expires_at": row.expires_at.isoformat(),
        "capabilities": list(row.capabilities or []),
        "handle_id": row.handle_id,
        "connection_id": row.connection_id,
    }


@asynccontextmanager
async def task_machine_lease_context(
    task: Task,
    *,
    session_id: uuid.UUID | None,
    purpose: str,
) -> AsyncIterator[None]:
    if session_id is None:
        yield
        return
    async with async_session() as db:
        session = await db.get(Session, session_id)
        fresh_task = await db.get(Task, task.id)
        if session is not None and fresh_task is not None:
            await ensure_task_machine_lease(
                db,
                task=fresh_task,
                session=session,
                purpose=purpose,
            )
            await db.commit()
    try:
        yield
    finally:
        pass


async def validate_current_automation_execution_policy(
    execution_policy: str,
) -> Any:
    from app.db.models import User
    from app.services.machine_control import ExecutionPolicyResolution, enrich_lease_payload

    task_id = current_task_id.get()
    if task_id is None:
        return ExecutionPolicyResolution(
            allowed=False,
            reason="Machine-control tools are disabled for autonomous runs without a task grant.",
        )
    session_id = current_session_id.get()
    if session_id is None:
        return ExecutionPolicyResolution(
            allowed=False,
            reason="Scheduled machine-control tools require a channel/session context.",
        )
    async with async_session() as db:
        task = await db.get(Task, task_id)
        session = await db.get(Session, session_id)
        if task is None or session is None:
            return ExecutionPolicyResolution(
                allowed=False,
                reason="Scheduled machine-control context could not be resolved.",
            )
        active = await get_active_task_machine_grant(db, task)
        if active is None:
            return ExecutionPolicyResolution(
                allowed=False,
                reason="Machine-control tools are disabled for task runs.",
            )
        if execution_policy == "live_target_lease" and not active.grant.allow_agent_tools:
            return ExecutionPolicyResolution(
                allowed=False,
                reason="This task grant does not allow LLM machine-control tools.",
            )
        try:
            lease = await ensure_task_machine_lease(db, task=task, session=session, purpose="agent_tool")
        except Exception as exc:
            return ExecutionPolicyResolution(allowed=False, reason=str(exc))
        await db.commit()
        user = await db.get(User, uuid.UUID(str(lease["user_id"]))) if lease else None
        return ExecutionPolicyResolution(
            allowed=True,
            session=session,
            user=user,
            lease=enrich_lease_payload(lease),
        )
