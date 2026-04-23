from __future__ import annotations

import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.agent.context import current_run_origin, current_session_id, current_user_id
from app.db.models import Session, User
from app.services import presence
from app.services.integration_settings import get_value, update_settings


INTEGRATION_ID = "local_companion"
TARGETS_KEY = "LOCAL_COMPANION_TARGETS_JSON"
LEASE_METADATA_KEY = "machine_target_lease"
DEFAULT_LEASE_TTL_SECONDS = 900
MAX_LEASE_TTL_SECONDS = 3600
_TARGETS_SETUP_VARS = [{"key": TARGETS_KEY, "secret": True}]
_AUTONOMOUS_ORIGINS = frozenset({"heartbeat", "task", "subagent", "hygiene"})


@dataclass
class ExecutionPolicyResolution:
    allowed: bool
    reason: str | None = None
    session: Session | None = None
    user: User | None = None
    lease: dict[str, Any] | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _parse_targets(raw: str) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        target_id = str(item.get("target_id") or "").strip()
        if not target_id:
            continue
        out.append({
            "target_id": target_id,
            "driver": str(item.get("driver") or "companion"),
            "label": str(item.get("label") or item.get("hostname") or target_id),
            "hostname": str(item.get("hostname") or ""),
            "platform": str(item.get("platform") or ""),
            "capabilities": [str(v) for v in (item.get("capabilities") or []) if str(v).strip()],
            "token": str(item.get("token") or ""),
            "enrolled_at": str(item.get("enrolled_at") or _utc_now_iso()),
            "last_seen_at": str(item.get("last_seen_at") or "") or None,
        })
    return out


def _dump_targets(targets: list[dict[str, Any]]) -> str:
    return json.dumps(targets, ensure_ascii=False)


def _bridge():
    from integrations.local_companion.bridge import bridge

    return bridge


def _public_target_payload(target: dict[str, Any], *, connection: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "target_id": target["target_id"],
        "driver": target.get("driver") or "companion",
        "label": target.get("label") or target["target_id"],
        "hostname": target.get("hostname") or "",
        "platform": target.get("platform") or "",
        "capabilities": list(target.get("capabilities") or []),
        "enrolled_at": target.get("enrolled_at"),
        "last_seen_at": target.get("last_seen_at"),
        "connected": connection is not None,
        "connection_id": connection.get("connection_id") if connection else None,
    }
    return payload


def get_registered_targets() -> list[dict[str, Any]]:
    return _parse_targets(get_value(INTEGRATION_ID, TARGETS_KEY, "[]"))


async def _save_targets(db: AsyncSession, targets: list[dict[str, Any]]) -> None:
    await update_settings(
        INTEGRATION_ID,
        {TARGETS_KEY: _dump_targets(targets)},
        _TARGETS_SETUP_VARS,
        db,
    )


async def create_enrollment(
    db: AsyncSession,
    *,
    label: str | None = None,
) -> dict[str, Any]:
    targets = get_registered_targets()
    target_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)
    target = {
        "target_id": target_id,
        "driver": "companion",
        "label": (label or f"Companion {len(targets) + 1}").strip() or f"Companion {len(targets) + 1}",
        "hostname": "",
        "platform": "",
        "capabilities": ["shell"],
        "token": token,
        "enrolled_at": _utc_now_iso(),
        "last_seen_at": None,
    }
    targets.append(target)
    await _save_targets(db, targets)
    return {
        **_public_target_payload(target),
        "token": token,
        "websocket_path": f"/integrations/{INTEGRATION_ID}/ws",
    }


async def register_connected_target(
    db: AsyncSession,
    *,
    target_id: str,
    label: str | None = None,
    hostname: str | None = None,
    platform: str | None = None,
    capabilities: list[str] | None = None,
) -> dict[str, Any] | None:
    targets = get_registered_targets()
    changed = False
    matched: dict[str, Any] | None = None
    for target in targets:
        if target.get("target_id") != target_id:
            continue
        matched = target
        if label:
            target["label"] = label
        if hostname:
            target["hostname"] = hostname
        if platform:
            target["platform"] = platform
        if capabilities is not None:
            target["capabilities"] = [str(v) for v in capabilities if str(v).strip()]
        target["last_seen_at"] = _utc_now_iso()
        changed = True
        break
    if changed:
        await _save_targets(db, targets)
    return matched


async def revoke_target(db: AsyncSession, target_id: str) -> bool:
    targets = get_registered_targets()
    kept = [target for target in targets if target.get("target_id") != target_id]
    if len(kept) == len(targets):
        return False
    await _save_targets(db, kept)
    result = await db.execute(select(Session))
    changed = False
    for session in result.scalars():
        lease = get_session_lease(session)
        if lease is None or lease["target_id"] != target_id:
            continue
        clear_session_lease(session)
        changed = True
    if changed:
        await db.commit()
    await _bridge().unregister_target(target_id)
    return True


def build_targets_status() -> list[dict[str, Any]]:
    conn_map = {row["target_id"]: row for row in _bridge().list_targets()}
    return [
        _public_target_payload(target, connection=conn_map.get(target["target_id"]))
        for target in get_registered_targets()
    ]


def get_target_by_id(target_id: str) -> dict[str, Any] | None:
    for target in get_registered_targets():
        if target.get("target_id") == target_id:
            return target
    return None


def get_session_lease(session: Session | None) -> dict[str, Any] | None:
    if session is None:
        return None
    meta = session.metadata_ or {}
    raw = meta.get(LEASE_METADATA_KEY)
    if not isinstance(raw, dict):
        return None
    target_id = str(raw.get("target_id") or "").strip()
    lease_id = str(raw.get("lease_id") or "").strip()
    user_id = str(raw.get("user_id") or "").strip()
    expires_at = str(raw.get("expires_at") or "").strip()
    granted_at = str(raw.get("granted_at") or "").strip()
    if not (target_id and lease_id and user_id and expires_at and granted_at):
        return None
    return {
        "lease_id": lease_id,
        "target_id": target_id,
        "user_id": user_id,
        "granted_at": granted_at,
        "expires_at": expires_at,
        "capabilities": [str(v) for v in (raw.get("capabilities") or []) if str(v).strip()],
        "connection_id": raw.get("connection_id"),
    }


def session_lease_payload(session: Session | None) -> dict[str, Any] | None:
    lease = get_session_lease(session)
    if lease is None:
        return None
    conn = _bridge().get_target_connection(lease["target_id"])
    target = get_target_by_id(lease["target_id"])
    return {
        **lease,
        "connected": conn is not None,
        "target_label": (target or {}).get("label") or lease["target_id"],
    }


def clear_session_lease(session: Session) -> None:
    meta = dict(session.metadata_ or {})
    if LEASE_METADATA_KEY in meta:
        meta.pop(LEASE_METADATA_KEY, None)
        session.metadata_ = meta
        flag_modified(session, "metadata_")


async def _find_conflicting_lease(
    db: AsyncSession,
    *,
    target_id: str,
    exclude_session_id: uuid.UUID | None = None,
) -> Session | None:
    result = await db.execute(select(Session))
    for session in result.scalars():
        if exclude_session_id is not None and session.id == exclude_session_id:
            continue
        lease = get_session_lease(session)
        if lease is None:
            continue
        expires_at = _parse_iso(lease["expires_at"])
        if expires_at is None or expires_at <= _utc_now():
            continue
        if lease["target_id"] == target_id:
            return session
    return None


async def grant_session_lease(
    db: AsyncSession,
    *,
    session: Session,
    user: User,
    target_id: str,
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
) -> dict[str, Any]:
    ttl_seconds = max(30, min(int(ttl_seconds), MAX_LEASE_TTL_SECONDS))
    target = get_target_by_id(target_id)
    if target is None:
        raise ValueError("Unknown machine target.")
    connection = _bridge().get_target_connection(target_id)
    if connection is None:
        raise ValueError("Selected machine target is not connected.")
    conflict = await _find_conflicting_lease(
        db,
        target_id=target_id,
        exclude_session_id=session.id,
    )
    if conflict is not None:
        raise RuntimeError(f"Machine target is already leased by session {conflict.id}.")
    meta = dict(session.metadata_ or {})
    lease = {
        "lease_id": str(uuid.uuid4()),
        "target_id": target_id,
        "user_id": str(user.id),
        "granted_at": _utc_now_iso(),
        "expires_at": (_utc_now() + timedelta(seconds=ttl_seconds)).isoformat(),
        "capabilities": list(target.get("capabilities") or []),
        "connection_id": connection.connection_id,
    }
    meta[LEASE_METADATA_KEY] = lease
    session.metadata_ = meta
    flag_modified(session, "metadata_")
    await db.commit()
    await db.refresh(session)
    return session_lease_payload(session) or lease


async def build_session_machine_target_payload(
    db: AsyncSession,
    *,
    session: Session,
) -> dict[str, Any]:
    lease = get_session_lease(session)
    if lease is not None:
        expires_at = _parse_iso(lease["expires_at"])
        if (
            expires_at is None
            or expires_at <= _utc_now()
            or get_target_by_id(lease["target_id"]) is None
        ):
            clear_session_lease(session)
            await db.commit()
            await db.refresh(session)
    return {
        "session_id": str(session.id),
        "lease": session_lease_payload(session),
        "targets": build_targets_status(),
    }


async def validate_current_execution_policy(
    execution_policy: str,
) -> ExecutionPolicyResolution:
    if execution_policy == "normal":
        return ExecutionPolicyResolution(allowed=True)

    origin_kind = current_run_origin.get(None)
    if origin_kind in _AUTONOMOUS_ORIGINS:
        return ExecutionPolicyResolution(
            allowed=False,
            reason=f"Machine-control tools are disabled for {origin_kind} runs.",
        )

    user_id = current_user_id.get()
    if user_id is None:
        return ExecutionPolicyResolution(
            allowed=False,
            reason="Machine-control tools require a live signed-in user session.",
        )

    from app.db.engine import async_session

    async with async_session() as db:
        user = await db.get(User, user_id)
        if user is None or not user.is_active:
            return ExecutionPolicyResolution(
                allowed=False,
                reason="Machine-control tools require an active signed-in user.",
            )
        if not user.is_admin:
            return ExecutionPolicyResolution(
                allowed=False,
                reason="Machine-control tools are admin-only in this build.",
            )
        if not presence.is_active(user.id):
            return ExecutionPolicyResolution(
                allowed=False,
                reason="Machine-control tools require a currently active user session in the web app.",
            )
        if execution_policy == "interactive_user":
            return ExecutionPolicyResolution(allowed=True, user=user)

        session_id = current_session_id.get()
        if session_id is None:
            return ExecutionPolicyResolution(
                allowed=False,
                reason="This machine-control tool requires a channel/session context with an active lease.",
            )
        session = await db.get(Session, session_id)
        if session is None:
            return ExecutionPolicyResolution(
                allowed=False,
                reason="The active session could not be resolved for machine control.",
            )
        lease = get_session_lease(session)
        if lease is None:
            return ExecutionPolicyResolution(
                allowed=False,
                reason="Grant machine control for this session before using that tool.",
            )
        if lease["user_id"] != str(user.id):
            return ExecutionPolicyResolution(
                allowed=False,
                reason="The active machine-control lease belongs to a different user.",
            )
        expires_at = _parse_iso(lease["expires_at"])
        if expires_at is None or expires_at <= _utc_now():
            return ExecutionPolicyResolution(
                allowed=False,
                reason="The machine-control lease for this session has expired. Grant it again.",
            )
        conn = _bridge().get_target_connection(lease["target_id"])
        if conn is None:
            return ExecutionPolicyResolution(
                allowed=False,
                reason="The leased machine target is not currently connected.",
            )
        return ExecutionPolicyResolution(
            allowed=True,
            session=session,
            user=user,
            lease=lease,
        )
