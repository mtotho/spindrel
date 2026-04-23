from __future__ import annotations

import json
import secrets
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.integration_settings import get_status, get_value, set_status, update_settings

from .bridge import bridge

TARGETS_KEY = "LOCAL_COMPANION_TARGETS_JSON"
_TARGETS_SETUP_VARS = [{"key": TARGETS_KEY, "secret": True}]


def _utc_now_iso() -> str:
    from app.services.machine_control import _utc_now_iso as _shared_utc_now_iso

    return _shared_utc_now_iso()


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
            "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else None,
        })
    return out


def _dump_targets(targets: list[dict[str, Any]]) -> str:
    return json.dumps(targets, ensure_ascii=False)


def get_registered_targets() -> list[dict[str, Any]]:
    return _parse_targets(get_value("local_companion", TARGETS_KEY, "[]"))


async def _save_targets(db: AsyncSession, targets: list[dict[str, Any]]) -> None:
    await update_settings(
        "local_companion",
        {TARGETS_KEY: _dump_targets(targets)},
        _TARGETS_SETUP_VARS,
        db,
    )


class LocalCompanionMachineControlProvider:
    provider_id = "local_companion"
    label = "Local Companion"
    driver = "companion"
    supports_enroll = True
    supports_remove_target = True

    def list_targets(self) -> list[dict[str, Any]]:
        return get_registered_targets()

    def get_target(self, target_id: str) -> dict[str, Any] | None:
        for target in get_registered_targets():
            if target.get("target_id") == target_id:
                return target
        return None

    def get_target_connection(self, target_id: str) -> dict[str, Any] | None:
        conn = bridge.get_target_connection(target_id)
        if conn is None:
            return None
        return {
            "target_id": conn.target_id,
            "connection_id": conn.connection_id,
            "label": conn.label,
            "hostname": conn.hostname,
            "platform": conn.platform,
            "capabilities": list(conn.capabilities),
            "pending": len(conn.pending),
        }

    async def enroll(
        self,
        db: AsyncSession,
        request: Request,
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
            "metadata": None,
        }
        targets.append(target)
        await _save_targets(db, targets)

        if get_status("local_companion") != "enabled":
            await set_status("local_companion", "enabled")

        server_url = str(request.base_url).rstrip("/")
        return {
            "target": {k: v for k, v in target.items() if k != "token"},
            "launch": {
                "token": token,
                "websocket_path": "/integrations/local_companion/ws",
                "example_command": (
                    "python -m integrations.local_companion.client "
                    f"--server-url {server_url} --target-id {target_id} --token {token}"
                ),
            },
        }

    async def remove_target(self, db: AsyncSession, target_id: str) -> bool:
        targets = get_registered_targets()
        kept = [target for target in targets if target.get("target_id") != target_id]
        if len(kept) == len(targets):
            return False
        await _save_targets(db, kept)
        await bridge.unregister_target(target_id)
        return True

    async def register_connected_target(
        self,
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

    async def inspect_command(self, target_id: str, command: str) -> dict[str, Any]:
        return await bridge.request(target_id, "inspect_command", {"command": command})

    async def exec_command(self, target_id: str, command: str, working_dir: str = "") -> dict[str, Any]:
        return await bridge.request(
            target_id,
            "exec_command",
            {"command": command, "working_dir": working_dir},
        )


provider = LocalCompanionMachineControlProvider()
