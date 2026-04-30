from __future__ import annotations

import logging
import re
import shlex
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.agent.context import current_run_origin, current_session_id, current_user_id
from app.db.models import MachineTargetLease, Session, User
from app.services import presence
from app.services.integration_manifests import get_manifest
from app.services.integration_settings import get_status, is_configured
from integrations.discovery import import_integration_module, iter_integration_candidates

logger = logging.getLogger(__name__)

LEASE_METADATA_KEY = "machine_target_lease"
DEFAULT_LEASE_TTL_SECONDS = 900
MAX_LEASE_TTL_SECONDS = 3600
LEGACY_PROVIDER_ID = "local_companion"
_AUTONOMOUS_ORIGINS = frozenset({"heartbeat", "task", "subagent", "hygiene"})
_PROVIDER_CACHE: dict[str, "MachineControlProvider"] = {}
DEFAULT_INSPECT_PREFIXES = ("pwd", "ls", "git", "cat", "head", "tail", "find", "rg", "ps", "which")
_INSPECT_COMPOSITION_RE = re.compile(r"[;&|><`$()]")


@runtime_checkable
class MachineControlProvider(Protocol):
    provider_id: str
    label: str
    driver: str
    supports_enroll: bool
    supports_remove_target: bool
    supports_profiles: bool

    def list_targets(self) -> list[dict[str, Any]]: ...

    def get_target(self, target_id: str) -> dict[str, Any] | None: ...

    def get_target_status(self, target_id: str) -> dict[str, Any] | None: ...

    def list_profiles(self) -> list[dict[str, Any]]: ...

    def get_profile(self, profile_id: str) -> dict[str, Any] | None: ...

    async def probe_target(
        self,
        db: AsyncSession,
        *,
        target_id: str,
    ) -> dict[str, Any]: ...

    async def enroll(
        self,
        db: AsyncSession,
        *,
        server_base_url: str,
        label: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    async def get_target_setup(
        self,
        db: AsyncSession,
        *,
        target_id: str,
        server_base_url: str,
    ) -> dict[str, Any] | None: ...

    async def create_profile(
        self,
        db: AsyncSession,
        *,
        label: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    async def update_profile(
        self,
        db: AsyncSession,
        *,
        profile_id: str,
        label: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    async def delete_profile(self, db: AsyncSession, profile_id: str) -> bool: ...

    async def remove_target(self, db: AsyncSession, target_id: str) -> bool: ...

    async def register_connected_target(
        self,
        db: AsyncSession,
        *,
        target_id: str,
        label: str | None = None,
        hostname: str | None = None,
        platform: str | None = None,
        capabilities: list[str] | None = None,
    ) -> dict[str, Any] | None: ...

    async def inspect_command(self, target_id: str, command: str) -> dict[str, Any]: ...

    async def exec_command(self, target_id: str, command: str, working_dir: str = "") -> dict[str, Any]: ...


@dataclass
class ExecutionPolicyResolution:
    allowed: bool
    reason: str | None = None
    session: Session | None = None
    user: User | None = None
    lease: dict[str, Any] | None = None


def validate_inspect_command(
    command: str,
    *,
    allowed_prefixes: tuple[str, ...] = DEFAULT_INSPECT_PREFIXES,
) -> None:
    stripped = command.strip()
    if not stripped:
        raise ValueError("inspect command cannot be empty")
    if _INSPECT_COMPOSITION_RE.search(stripped):
        raise ValueError("inspect command cannot use shell composition characters")
    parts = shlex.split(stripped)
    if not parts:
        raise ValueError("inspect command cannot be empty")
    binary = parts[0]
    if binary not in allowed_prefixes:
        raise ValueError(f"inspect command '{binary}' is not allowed")


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


def _provider_block(provider_id: str) -> dict[str, Any]:
    manifest = get_manifest(provider_id) or {}
    block = manifest.get("machine_control")
    return block if isinstance(block, dict) else {}


def _provider_label(provider_id: str, provider: MachineControlProvider | None = None) -> str:
    if provider is not None and getattr(provider, "label", None):
        return str(provider.label)
    block = _provider_block(provider_id)
    if block.get("label"):
        return str(block["label"])
    manifest = get_manifest(provider_id) or {}
    if manifest.get("name"):
        return str(manifest["name"])
    return provider_id.replace("_", " ").replace("-", " ").title()


def _provider_driver(provider_id: str, provider: MachineControlProvider | None = None) -> str:
    if provider is not None and getattr(provider, "driver", None):
        return str(provider.driver)
    block = _provider_block(provider_id)
    if block.get("driver"):
        return str(block["driver"])
    return "unknown"


def _provider_admin_href(provider_id: str) -> str:
    return f"/admin/integrations/{provider_id}"


def _provider_enroll_fields(provider_id: str) -> list[dict[str, Any]]:
    block = _provider_block(provider_id)
    fields = block.get("enroll_fields")
    if not isinstance(fields, list):
        return []
    return [field for field in fields if isinstance(field, dict)]


def _provider_profile_fields(provider_id: str) -> list[dict[str, Any]]:
    block = _provider_block(provider_id)
    fields = block.get("profile_fields")
    if not isinstance(fields, list):
        return []
    return [field for field in fields if isinstance(field, dict)]


def _provider_profile_setup_guide(provider_id: str) -> dict[str, Any] | None:
    block = _provider_block(provider_id)
    guide = block.get("profile_setup_guide")
    if not isinstance(guide, dict):
        return None
    raw_steps = guide.get("steps")
    if not isinstance(raw_steps, list):
        return None
    steps: list[dict[str, Any]] = []
    for raw_step in raw_steps:
        if not isinstance(raw_step, dict):
            continue
        title = raw_step.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        step: dict[str, Any] = {"title": title.strip()}
        run_on = raw_step.get("run_on")
        if isinstance(run_on, str) and run_on.strip():
            step["run_on"] = run_on.strip()
        description = raw_step.get("description")
        if isinstance(description, str) and description.strip():
            step["description"] = description.strip()
        raw_commands = raw_step.get("commands")
        if isinstance(raw_commands, list):
            commands: list[dict[str, str]] = []
            for raw_command in raw_commands:
                if not isinstance(raw_command, dict):
                    continue
                label = raw_command.get("label")
                value = raw_command.get("value")
                if not isinstance(label, str) or not isinstance(value, str):
                    continue
                if not label.strip() or not value.strip():
                    continue
                commands.append({"label": label.strip(), "value": value})
            if commands:
                step["commands"] = commands
        steps.append(step)
    if not steps:
        return None
    payload: dict[str, Any] = {"steps": steps}
    summary = guide.get("summary")
    if isinstance(summary, str) and summary.strip():
        payload["summary"] = summary.strip()
    return payload


def _normalize_target_status(
    status: dict[str, Any] | None,
    *,
    driver: str,
    last_seen_at: str | None = None,
) -> dict[str, Any]:
    raw = status if isinstance(status, dict) else {}
    ready = bool(raw.get("ready"))
    status_value = str(raw.get("status") or ("connected" if ready and driver == "companion" else "reachable" if ready else "unknown"))
    reason = raw.get("reason")
    checked_at = raw.get("checked_at") or last_seen_at
    handle_id = raw.get("handle_id") or raw.get("connection_id")

    if driver == "companion":
        if ready:
            status_label = "Connected"
        else:
            status_label = "Offline"
            if status_value == "unknown":
                status_value = "offline"
    else:
        if ready:
            status_label = "Reachable"
            if status_value == "unknown":
                status_value = "reachable"
        else:
            status_label = "Unreachable" if status_value in {"unreachable", "failed"} else "Unknown"

    return {
        "ready": ready,
        "status": status_value,
        "status_label": status_label,
        "reason": str(reason) if reason else None,
        "checked_at": checked_at,
        "handle_id": str(handle_id) if handle_id else None,
    }


def list_provider_ids() -> list[str]:
    provider_ids: list[str] = []
    for candidate, integration_id, _is_external, _source in iter_integration_candidates():
        manifest = get_manifest(integration_id) or {}
        block = manifest.get("machine_control")
        declared = "machine_control" in set(manifest.get("provides", []))
        if isinstance(block, dict) or declared or (candidate / "machine_control.py").exists():
            provider_ids.append(integration_id)
    return provider_ids


def _find_provider_candidate(provider_id: str) -> tuple[Path, bool, str] | None:
    for candidate, integration_id, is_external, source in iter_integration_candidates():
        if integration_id == provider_id:
            return candidate, is_external, source
    return None


def get_provider(provider_id: str) -> MachineControlProvider:
    cached = _PROVIDER_CACHE.get(provider_id)
    if cached is not None:
        return cached

    candidate = _find_provider_candidate(provider_id)
    if candidate is None:
        raise KeyError(f"Unknown machine-control provider '{provider_id}'.")
    integration_dir, is_external, source = candidate
    provider_file = integration_dir / "machine_control.py"
    if not provider_file.exists():
        raise RuntimeError(f"Machine-control provider '{provider_id}' has no machine_control.py module.")

    module = import_integration_module(provider_id, "machine_control", provider_file, is_external, source)
    provider = getattr(module, "provider", None)
    if provider is None and hasattr(module, "get_machine_control_provider"):
        provider = module.get_machine_control_provider()
    if provider is None:
        raise RuntimeError(f"Machine-control provider '{provider_id}' must export `provider` or `get_machine_control_provider()`.")
    if not isinstance(provider, MachineControlProvider):
        raise RuntimeError(f"Machine-control provider '{provider_id}' does not implement the required contract.")
    if getattr(provider, "provider_id", provider_id) != provider_id:
        raise RuntimeError(
            f"Machine-control provider '{provider_id}' reported provider_id={getattr(provider, 'provider_id', None)!r}.",
        )
    _PROVIDER_CACHE[provider_id] = provider
    return provider


def _public_target_payload(
    provider_id: str,
    target: dict[str, Any],
    *,
    provider: MachineControlProvider | None = None,
    runtime_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    driver = str(target.get("driver") or _provider_driver(provider_id, provider))
    profile_id = str(target.get("profile_id") or "").strip() or None
    profile_label = str(target.get("profile_label") or "").strip() or None
    if profile_id and profile_label is None and provider is not None and getattr(provider, "supports_profiles", False):
        profile = provider.get_profile(profile_id)
        if isinstance(profile, dict):
            profile_label = str(profile.get("label") or "").strip() or None
    normalized = _normalize_target_status(
        runtime_status,
        driver=driver,
        last_seen_at=target.get("last_seen_at"),
    )
    return {
        "provider_id": provider_id,
        "provider_label": _provider_label(provider_id, provider),
        "target_id": str(target.get("target_id") or ""),
        "driver": driver,
        "label": str(target.get("label") or target.get("hostname") or target.get("target_id") or ""),
        "hostname": str(target.get("hostname") or ""),
        "platform": str(target.get("platform") or ""),
        "capabilities": [str(v) for v in (target.get("capabilities") or []) if str(v).strip()],
        "enrolled_at": target.get("enrolled_at"),
        "last_seen_at": target.get("last_seen_at"),
        "ready": normalized["ready"],
        "status": normalized["status"],
        "status_label": normalized["status_label"],
        "reason": normalized["reason"],
        "checked_at": normalized["checked_at"],
        "handle_id": normalized["handle_id"],
        "connected": normalized["ready"],
        "connection_id": normalized["handle_id"],
        "profile_id": profile_id,
        "profile_label": profile_label,
        "metadata": target.get("metadata") if isinstance(target.get("metadata"), dict) else None,
    }


def _public_profile_payload(
    profile: dict[str, Any],
    *,
    target_count: int = 0,
) -> dict[str, Any]:
    return {
        "profile_id": str(profile.get("profile_id") or ""),
        "label": str(profile.get("label") or profile.get("profile_id") or ""),
        "summary": str(profile.get("summary") or "") or None,
        "created_at": profile.get("created_at"),
        "updated_at": profile.get("updated_at"),
        "target_count": int(target_count),
        "metadata": profile.get("metadata") if isinstance(profile.get("metadata"), dict) else None,
    }


def _provider_summary(provider_id: str, provider: MachineControlProvider) -> dict[str, Any]:
    manifest = get_manifest(provider_id) or {}
    block = _provider_block(provider_id)
    return {
        "provider_id": provider_id,
        "label": _provider_label(provider_id, provider),
        "driver": _provider_driver(provider_id, provider),
        "integration_id": provider_id,
        "integration_name": manifest.get("name") or provider_id,
        "integration_status": get_status(provider_id),
        "config_ready": is_configured(provider_id),
        "supports_enroll": bool(getattr(provider, "supports_enroll", False)),
        "supports_remove_target": bool(getattr(provider, "supports_remove_target", False)),
        "supports_profiles": bool(getattr(provider, "supports_profiles", False)),
        "integration_admin_href": _provider_admin_href(provider_id),
        "enroll_fields": _provider_enroll_fields(provider_id),
        "profile_fields": _provider_profile_fields(provider_id),
        "profile_setup_guide": _provider_profile_setup_guide(provider_id),
        "metadata": block.get("metadata") if isinstance(block.get("metadata"), dict) else None,
    }


def build_targets_status(*, provider_id: str | None = None) -> list[dict[str, Any]]:
    provider_ids = [provider_id] if provider_id else list_provider_ids()
    rows: list[dict[str, Any]] = []
    for current_provider_id in provider_ids:
        try:
            provider = get_provider(current_provider_id)
        except Exception:
            logger.exception("Failed to load machine-control provider %s", current_provider_id)
            continue
        for target in provider.list_targets():
            target_id = str(target.get("target_id") or "").strip()
            if not target_id:
                continue
            rows.append(
                _public_target_payload(
                    current_provider_id,
                    target,
                    provider=provider,
                    runtime_status=provider.get_target_status(target_id),
                ),
            )
    return rows


def build_providers_status() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for provider_id in list_provider_ids():
        try:
            provider = get_provider(provider_id)
        except Exception:
            logger.exception("Failed to load machine-control provider %s", provider_id)
            continue
        targets = build_targets_status(provider_id=provider_id)
        target_counts_by_profile: dict[str, int] = {}
        for target in targets:
            profile_id = str(target.get("profile_id") or "").strip()
            if not profile_id:
                continue
            target_counts_by_profile[profile_id] = target_counts_by_profile.get(profile_id, 0) + 1
        profiles = [
            _public_profile_payload(profile, target_count=target_counts_by_profile.get(str(profile.get("profile_id") or ""), 0))
            for profile in provider.list_profiles()
        ]
        rows.append({
            **_provider_summary(provider_id, provider),
            "profiles": profiles,
            "profile_count": len(profiles),
            "targets": targets,
            "target_count": len(targets),
            "ready_target_count": sum(1 for target in targets if target.get("ready")),
            "connected_target_count": sum(1 for target in targets if target.get("ready")),
        })
    return rows


def get_target_by_id(provider_id: str, target_id: str) -> dict[str, Any] | None:
    provider = get_provider(provider_id)
    target = provider.get_target(target_id)
    if target is None:
        return None
    return _public_target_payload(
        provider_id,
        target,
        provider=provider,
        runtime_status=provider.get_target_status(target_id),
    )


def get_session_lease(session: Session | None) -> dict[str, Any] | None:
    """Return a legacy metadata lease.

    New code should prefer ``get_active_session_lease`` so the DB lease table
    is the source of truth. This function remains for old metadata rows and
    lightweight unit fakes that do not model SQLAlchemy persistence.
    """
    if session is None:
        return None
    meta = session.metadata_ or {}
    raw = meta.get(LEASE_METADATA_KEY)
    if not isinstance(raw, dict):
        return None
    provider_id = str(raw.get("provider_id") or LEGACY_PROVIDER_ID).strip()
    target_id = str(raw.get("target_id") or "").strip()
    lease_id = str(raw.get("lease_id") or "").strip()
    user_id = str(raw.get("user_id") or "").strip()
    expires_at = str(raw.get("expires_at") or "").strip()
    granted_at = str(raw.get("granted_at") or "").strip()
    if not (provider_id and target_id and lease_id and user_id and expires_at and granted_at):
        return None
    return {
        "lease_id": lease_id,
        "provider_id": provider_id,
        "target_id": target_id,
        "user_id": user_id,
        "granted_at": granted_at,
        "expires_at": expires_at,
        "capabilities": [str(v) for v in (raw.get("capabilities") or []) if str(v).strip()],
        "handle_id": raw.get("handle_id") or raw.get("connection_id"),
        "connection_id": raw.get("connection_id"),
    }


def _db_supports_lease_table(db: AsyncSession) -> bool:
    return hasattr(db, "add") and hasattr(db, "flush") and hasattr(db, "rollback")


def _row_lease_payload(row: MachineTargetLease | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "lease_id": row.lease_id,
        "provider_id": row.provider_id,
        "target_id": row.target_id,
        "user_id": str(row.user_id),
        "granted_at": row.granted_at.isoformat(),
        "expires_at": row.expires_at.isoformat(),
        "capabilities": [str(v) for v in (row.capabilities or []) if str(v).strip()],
        "handle_id": row.handle_id,
        "connection_id": row.connection_id,
    }


async def get_active_session_lease(
    db: AsyncSession,
    session: Session | None,
) -> dict[str, Any] | None:
    if session is None:
        return None
    if not _db_supports_lease_table(db):
        return get_session_lease(session)
    now = _utc_now()
    row = (
        await db.execute(
            select(MachineTargetLease).where(MachineTargetLease.session_id == session.id)
        )
    ).scalar_one_or_none()
    if row is None:
        return get_session_lease(session)
    if row.expires_at <= now:
        await db.delete(row)
        await db.commit()
        return None
    return _row_lease_payload(row)


async def clear_session_lease_row(db: AsyncSession, session: Session) -> None:
    clear_session_lease(session)
    if _db_supports_lease_table(db):
        await db.execute(
            delete(MachineTargetLease).where(MachineTargetLease.session_id == session.id)
        )


def session_lease_payload(session: Session | None) -> dict[str, Any] | None:
    lease = get_session_lease(session)
    if lease is None:
        return None
    provider = get_provider(lease["provider_id"])
    target = get_target_by_id(lease["provider_id"], lease["target_id"]) or {}
    return {
        **lease,
        "ready": bool(target.get("ready")),
        "status": target.get("status"),
        "status_label": target.get("status_label"),
        "reason": target.get("reason"),
        "checked_at": target.get("checked_at"),
        "handle_id": target.get("handle_id") or lease.get("handle_id"),
        "connected": bool(target.get("ready")),
        "provider_label": _provider_label(lease["provider_id"], provider),
        "target_label": target.get("label") or lease["target_id"],
    }


def enrich_lease_payload(lease: dict[str, Any] | None) -> dict[str, Any] | None:
    if lease is None:
        return None
    provider = get_provider(lease["provider_id"])
    target = get_target_by_id(lease["provider_id"], lease["target_id"]) or {}
    return {
        **lease,
        "ready": bool(target.get("ready")),
        "status": target.get("status"),
        "status_label": target.get("status_label"),
        "reason": target.get("reason"),
        "checked_at": target.get("checked_at"),
        "handle_id": target.get("handle_id") or lease.get("handle_id"),
        "connected": bool(target.get("ready")),
        "provider_label": _provider_label(lease["provider_id"], provider),
        "target_label": target.get("label") or lease["target_id"],
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
    provider_id: str,
    target_id: str,
    exclude_session_id: uuid.UUID | None = None,
) -> Session | None:
    if _db_supports_lease_table(db):
        now = _utc_now()
        query = select(MachineTargetLease).where(
            MachineTargetLease.provider_id == provider_id,
            MachineTargetLease.target_id == target_id,
            MachineTargetLease.expires_at > now,
        )
        if exclude_session_id is not None:
            query = query.where(MachineTargetLease.session_id != exclude_session_id)
        row = (await db.execute(query)).scalar_one_or_none()
        if row is None:
            return None
        return await db.get(Session, row.session_id)

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
        if lease["provider_id"] == provider_id and lease["target_id"] == target_id:
            return session
    return None


async def _grant_session_lease_legacy(
    db: AsyncSession,
    *,
    session: Session,
    user: User,
    provider_id: str,
    target_id: str,
    ttl_seconds: int,
    probed: dict[str, Any],
    target: dict[str, Any],
) -> dict[str, Any]:
    conflict = await _find_conflicting_lease(
        db,
        provider_id=provider_id,
        target_id=target_id,
        exclude_session_id=session.id,
    )
    if conflict is not None:
        raise RuntimeError(f"Machine target is already leased by session {conflict.id}.")
    meta = dict(session.metadata_ or {})
    lease = {
        "lease_id": str(uuid.uuid4()),
        "provider_id": provider_id,
        "target_id": target_id,
        "user_id": str(user.id),
        "granted_at": _utc_now_iso(),
        "expires_at": (_utc_now() + timedelta(seconds=ttl_seconds)).isoformat(),
        "capabilities": [str(v) for v in (target.get("capabilities") or []) if str(v).strip()],
        "handle_id": probed.get("handle_id"),
        "connection_id": probed.get("handle_id"),
    }
    meta[LEASE_METADATA_KEY] = lease
    session.metadata_ = meta
    flag_modified(session, "metadata_")
    await db.commit()
    await db.refresh(session)
    return session_lease_payload(session) or lease


async def grant_session_lease(
    db: AsyncSession,
    *,
    session: Session,
    user: User,
    provider_id: str,
    target_id: str,
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
) -> dict[str, Any]:
    ttl_seconds = max(30, min(int(ttl_seconds), MAX_LEASE_TTL_SECONDS))
    provider = get_provider(provider_id)
    target = provider.get_target(target_id)
    if target is None:
        raise ValueError("Unknown machine target.")
    probed = _normalize_target_status(
        await provider.probe_target(db, target_id=target_id),
        driver=_provider_driver(provider_id, provider),
        last_seen_at=target.get("last_seen_at"),
    )
    if not probed["ready"]:
        raise ValueError(str(probed["reason"] or "Selected machine target is not ready."))

    if not _db_supports_lease_table(db):
        return await _grant_session_lease_legacy(
            db,
            session=session,
            user=user,
            provider_id=provider_id,
            target_id=target_id,
            ttl_seconds=ttl_seconds,
            probed=probed,
            target=target,
        )

    now = _utc_now()
    lease = MachineTargetLease(
        session_id=session.id,
        user_id=user.id,
        provider_id=provider_id,
        target_id=target_id,
        lease_id=str(uuid.uuid4()),
        granted_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
        capabilities=[str(v) for v in (target.get("capabilities") or []) if str(v).strip()],
        handle_id=probed.get("handle_id"),
        connection_id=probed.get("handle_id"),
        metadata_={},
    )
    await db.execute(delete(MachineTargetLease).where(MachineTargetLease.expires_at <= now))
    await db.execute(delete(MachineTargetLease).where(MachineTargetLease.session_id == session.id))
    clear_session_lease(session)
    db.add(lease)
    try:
        await db.flush()
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        conflict = await _find_conflicting_lease(
            db,
            provider_id=provider_id,
            target_id=target_id,
            exclude_session_id=session.id,
        )
        if conflict is not None:
            raise RuntimeError(f"Machine target is already leased by session {conflict.id}.") from exc
        raise RuntimeError("Machine target is already leased.") from exc
    await db.refresh(session)
    return enrich_lease_payload(_row_lease_payload(lease)) or _row_lease_payload(lease) or {}


async def build_session_machine_target_payload(
    db: AsyncSession,
    *,
    session: Session,
) -> dict[str, Any]:
    lease = await get_active_session_lease(db, session)
    if lease is not None:
        expires_at = _parse_iso(lease["expires_at"])
        target = get_target_by_id(lease["provider_id"], lease["target_id"])
        if expires_at is None or expires_at <= _utc_now() or target is None:
            await clear_session_lease_row(db, session)
            await db.commit()
            await db.refresh(session)
            lease = None
    targets = build_targets_status()
    ready_target_count = sum(1 for target in targets if target.get("ready"))
    return {
        "session_id": str(session.id),
        "lease": enrich_lease_payload(lease),
        "targets": targets,
        "ready_target_count": ready_target_count,
        "connected_target_count": ready_target_count,
    }


async def build_machine_access_required_payload(
    db: AsyncSession,
    *,
    session_id: uuid.UUID | None,
    reason: str,
    execution_policy: str,
    requested_tool: str | None = None,
) -> dict[str, Any]:
    session: Session | None = None
    if session_id is not None:
        session = await db.get(Session, session_id)

    if session is not None:
        session_payload = await build_session_machine_target_payload(db, session=session)
        lease = session_payload.get("lease")
        targets = list(session_payload.get("targets") or [])
        resolved_session_id = session_payload.get("session_id")
    else:
        lease = None
        targets = build_targets_status()
        resolved_session_id = str(session_id) if session_id else None

    ready_targets = [target for target in targets if target.get("ready")]
    return {
        "reason": reason,
        "execution_policy": execution_policy,
        "requested_tool": requested_tool,
        "session_id": resolved_session_id,
        "lease": lease,
        "targets": targets,
        "ready_targets": ready_targets,
        "ready_target_count": len(ready_targets),
        "connected_targets": ready_targets,
        "connected_target_count": len(ready_targets),
        "admin_machines_href": "/admin/machines",
        "integration_admin_href": "/admin/machines",
    }


async def validate_current_execution_policy(
    execution_policy: str,
) -> ExecutionPolicyResolution:
    if execution_policy == "normal":
        return ExecutionPolicyResolution(allowed=True)

    origin_kind = current_run_origin.get(None)
    if origin_kind in _AUTONOMOUS_ORIGINS:
        from app.services.machine_task_grants import validate_current_automation_execution_policy

        automated = await validate_current_automation_execution_policy(execution_policy)
        if automated.allowed:
            return automated
        return ExecutionPolicyResolution(
            allowed=False,
            reason=automated.reason or f"Machine-control tools are disabled for {origin_kind} runs.",
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
        lease = await get_active_session_lease(db, session)
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
        provider = get_provider(lease["provider_id"])
        target = provider.get_target(lease["target_id"])
        if target is None:
            return ExecutionPolicyResolution(
                allowed=False,
                reason="The leased machine target no longer exists.",
            )
        probed = _normalize_target_status(
            await provider.probe_target(db, target_id=lease["target_id"]),
            driver=_provider_driver(lease["provider_id"], provider),
            last_seen_at=target.get("last_seen_at"),
        )
        if not probed["ready"]:
            return ExecutionPolicyResolution(
                allowed=False,
                reason=str(probed["reason"] or "The leased machine target is not currently ready."),
            )
        return ExecutionPolicyResolution(
            allowed=True,
            session=session,
            user=user,
            lease=lease,
        )


async def enroll_machine_target(
    db: AsyncSession,
    *,
    provider_id: str,
    server_base_url: str,
    label: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider = get_provider(provider_id)
    if not provider.supports_enroll:
        raise ValueError(f"Provider '{provider_id}' does not support enrollment.")
    enrolled = await provider.enroll(db, server_base_url=server_base_url, label=label, config=config)
    target = enrolled.get("target")
    if not isinstance(target, dict):
        raise RuntimeError(f"Provider '{provider_id}' returned an invalid enrollment payload.")
    target_id = str(target.get("target_id") or "").strip()
    return {
        "provider": _provider_summary(provider_id, provider),
        "target": _public_target_payload(
            provider_id,
            target,
            provider=provider,
            runtime_status=provider.get_target_status(target_id) if target_id else None,
        ),
        "launch": enrolled.get("launch") if isinstance(enrolled.get("launch"), dict) else None,
        "metadata": enrolled.get("metadata") if isinstance(enrolled.get("metadata"), dict) else None,
    }


async def get_machine_target_setup(
    db: AsyncSession,
    *,
    provider_id: str,
    target_id: str,
    server_base_url: str,
) -> dict[str, Any]:
    provider = get_provider(provider_id)
    target = provider.get_target(target_id)
    if target is None:
        raise ValueError("Unknown machine target.")
    setup = await provider.get_target_setup(
        db,
        target_id=target_id,
        server_base_url=server_base_url,
    )
    return {
        "provider": _provider_summary(provider_id, provider),
        "target": _public_target_payload(
            provider_id,
            target,
            provider=provider,
            runtime_status=provider.get_target_status(target_id),
        ),
        "setup": setup,
    }


async def create_machine_profile(
    db: AsyncSession,
    *,
    provider_id: str,
    label: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider = get_provider(provider_id)
    if not getattr(provider, "supports_profiles", False):
        raise ValueError(f"Provider '{provider_id}' does not support profiles.")
    profile = await provider.create_profile(db, label=label, config=config)
    if not isinstance(profile, dict):
        raise RuntimeError(f"Provider '{provider_id}' returned an invalid profile payload.")
    return {
        "provider": _provider_summary(provider_id, provider),
        "profile": _public_profile_payload(profile),
    }


async def update_machine_profile(
    db: AsyncSession,
    *,
    provider_id: str,
    profile_id: str,
    label: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider = get_provider(provider_id)
    if not getattr(provider, "supports_profiles", False):
        raise ValueError(f"Provider '{provider_id}' does not support profiles.")
    profile = await provider.update_profile(db, profile_id=profile_id, label=label, config=config)
    if not isinstance(profile, dict):
        raise RuntimeError(f"Provider '{provider_id}' returned an invalid profile payload.")
    target_count = sum(
        1
        for target in build_targets_status(provider_id=provider_id)
        if str(target.get("profile_id") or "").strip() == profile_id
    )
    return {
        "provider": _provider_summary(provider_id, provider),
        "profile": _public_profile_payload(profile, target_count=target_count),
    }


async def delete_machine_profile(
    db: AsyncSession,
    *,
    provider_id: str,
    profile_id: str,
) -> bool:
    provider = get_provider(provider_id)
    if not getattr(provider, "supports_profiles", False):
        raise ValueError(f"Provider '{provider_id}' does not support profiles.")
    return await provider.delete_profile(db, profile_id)


async def probe_machine_target(
    db: AsyncSession,
    *,
    provider_id: str,
    target_id: str,
) -> dict[str, Any]:
    provider = get_provider(provider_id)
    target = provider.get_target(target_id)
    if target is None:
        raise ValueError("Unknown machine target.")
    runtime_status = await provider.probe_target(db, target_id=target_id)
    refreshed = provider.get_target(target_id) or target
    return {
        "provider": _provider_summary(provider_id, provider),
        "target": _public_target_payload(
            provider_id,
            refreshed,
            provider=provider,
            runtime_status=runtime_status,
        ),
    }


async def delete_machine_target(
    db: AsyncSession,
    *,
    provider_id: str,
    target_id: str,
) -> bool:
    provider = get_provider(provider_id)
    if not provider.supports_remove_target:
        raise ValueError(f"Provider '{provider_id}' does not support target removal.")
    removed = await provider.remove_target(db, target_id)
    if not removed:
        return False
    if _db_supports_lease_table(db):
        await db.execute(
            delete(MachineTargetLease).where(
                MachineTargetLease.provider_id == provider_id,
                MachineTargetLease.target_id == target_id,
            )
        )
    result = await db.execute(select(Session))
    changed = False
    for session in result.scalars():
        lease = get_session_lease(session)
        if lease is None:
            continue
        if lease["provider_id"] != provider_id or lease["target_id"] != target_id:
            continue
        clear_session_lease(session)
        changed = True
    if changed:
        await db.commit()
    return True
