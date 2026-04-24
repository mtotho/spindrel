from __future__ import annotations

import asyncio
import json
import os
import shlex
import tempfile
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.integration_settings import get_status, get_value, set_status, update_settings

TARGETS_KEY = "SSH_TARGETS_JSON"
_TARGETS_SETUP_VARS = [{"key": TARGETS_KEY, "secret": False}]


def _utc_now_iso() -> str:
    from app.services.machine_control import _utc_now_iso as _shared_utc_now_iso

    return _shared_utc_now_iso()


def _parse_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _load_runtime_settings() -> dict[str, Any]:
    return {
        "private_key": get_value("ssh", "SSH_PRIVATE_KEY", ""),
        "known_hosts": get_value("ssh", "SSH_KNOWN_HOSTS", ""),
        "connect_timeout_seconds": max(1, _parse_int(get_value("ssh", "SSH_CONNECT_TIMEOUT_SECONDS", "10"), 10)),
        "probe_timeout_seconds": max(1, _parse_int(get_value("ssh", "SSH_PROBE_TIMEOUT_SECONDS", "10"), 10)),
        "command_timeout_seconds": max(1, _parse_int(get_value("ssh", "SSH_COMMAND_TIMEOUT_SECONDS", "120"), 120)),
        "max_output_bytes": max(1024, _parse_int(get_value("ssh", "SSH_MAX_OUTPUT_BYTES", "65536"), 65536)),
    }


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
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        out.append({
            "target_id": target_id,
            "driver": "ssh",
            "label": str(item.get("label") or metadata.get("host") or target_id),
            "hostname": str(item.get("hostname") or metadata.get("host") or ""),
            "platform": str(item.get("platform") or ""),
            "capabilities": [str(v) for v in (item.get("capabilities") or ["shell"]) if str(v).strip()],
            "enrolled_at": str(item.get("enrolled_at") or _utc_now_iso()),
            "last_seen_at": str(item.get("last_seen_at") or "") or None,
            "metadata": {
                "host": str(metadata.get("host") or item.get("hostname") or ""),
                "username": str(metadata.get("username") or ""),
                "port": _parse_int(metadata.get("port"), 22),
                "working_dir": str(metadata.get("working_dir") or ""),
                "status": str(metadata.get("status") or "unknown"),
                "reason": str(metadata.get("reason") or "") or None,
                "checked_at": str(metadata.get("checked_at") or "") or None,
                "handle_id": str(metadata.get("handle_id") or "") or None,
            },
        })
    return out


def _dump_targets(targets: list[dict[str, Any]]) -> str:
    return json.dumps(targets, ensure_ascii=False)


def get_registered_targets() -> list[dict[str, Any]]:
    return _parse_targets(get_value("ssh", TARGETS_KEY, "[]"))


async def _save_targets(db: AsyncSession, targets: list[dict[str, Any]]) -> None:
    await update_settings("ssh", {TARGETS_KEY: _dump_targets(targets)}, _TARGETS_SETUP_VARS, db)


def _require_secret_settings() -> dict[str, Any]:
    config = _load_runtime_settings()
    if not config["private_key"].strip():
        raise ValueError("SSH provider requires SSH_PRIVATE_KEY to be configured.")
    if not config["known_hosts"].strip():
        raise ValueError("SSH provider requires SSH_KNOWN_HOSTS to be configured.")
    return config


def _target_handle_id(target: dict[str, Any]) -> str:
    metadata = target.get("metadata") if isinstance(target.get("metadata"), dict) else {}
    username = str(metadata.get("username") or "")
    host = str(metadata.get("host") or target.get("hostname") or "")
    port = _parse_int(metadata.get("port"), 22)
    return f"ssh://{username}@{host}:{port}"


def _trim(data: bytes, max_output_bytes: int) -> tuple[str, bool]:
    truncated = len(data) > max_output_bytes
    if truncated:
        data = data[:max_output_bytes]
    return data.decode(errors="replace"), truncated


async def _run_ssh(
    target: dict[str, Any],
    *,
    remote_command: str,
    timeout_seconds: int,
    connect_timeout_seconds: int,
    max_output_bytes: int,
) -> dict[str, Any]:
    config = _require_secret_settings()
    metadata = target.get("metadata") if isinstance(target.get("metadata"), dict) else {}
    host = str(metadata.get("host") or target.get("hostname") or "").strip()
    username = str(metadata.get("username") or "").strip()
    port = _parse_int(metadata.get("port"), 22)
    if not host or not username:
        raise ValueError("SSH target is missing host or username.")

    key_fd, key_path = tempfile.mkstemp(prefix="spindrel-ssh-key-", text=True)
    hosts_fd, hosts_path = tempfile.mkstemp(prefix="spindrel-known-hosts-", text=True)
    try:
        os.write(key_fd, config["private_key"].encode())
        os.write(hosts_fd, config["known_hosts"].encode())
    finally:
        os.close(key_fd)
        os.close(hosts_fd)
    os.chmod(key_path, 0o600)
    os.chmod(hosts_path, 0o600)

    args = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={hosts_path}",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "PasswordAuthentication=no",
        "-o",
        "KbdInteractiveAuthentication=no",
        "-o",
        "PubkeyAuthentication=yes",
        "-o",
        "ForwardAgent=no",
        "-o",
        "ClearAllForwardings=yes",
        "-o",
        "RequestTTY=no",
        "-o",
        f"ConnectTimeout={connect_timeout_seconds}",
        "-i",
        key_path,
        "-p",
        str(port),
        f"{username}@{host}",
        remote_command,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("OpenSSH client binary 'ssh' is not installed on the server.") from exc

    try:
        stdout_raw, stderr_raw = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"SSH command timed out after {timeout_seconds}s") from exc
    finally:
        Path(key_path).unlink(missing_ok=True)
        Path(hosts_path).unlink(missing_ok=True)

    stdout, stdout_truncated = _trim(stdout_raw or b"", max_output_bytes)
    stderr, stderr_truncated = _trim(stderr_raw or b"", max_output_bytes)
    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": int(proc.returncode or 0),
        "duration_ms": 0,
        "truncated": stdout_truncated or stderr_truncated,
    }


def _probe_remote_command() -> str:
    return "sh -lc " + shlex.quote("hostname && uname -srm")


def _command_remote_script(command: str, working_dir: str = "") -> str:
    script = command
    if working_dir.strip():
        script = f"cd {shlex.quote(working_dir.strip())} && {command}"
    return "sh -lc " + shlex.quote(script)


class SSHMachineControlProvider:
    provider_id = "ssh"
    label = "SSH"
    driver = "ssh"
    supports_enroll = True
    supports_remove_target = True

    def list_targets(self) -> list[dict[str, Any]]:
        return get_registered_targets()

    def get_target(self, target_id: str) -> dict[str, Any] | None:
        for target in get_registered_targets():
            if target.get("target_id") == target_id:
                return target
        return None

    def get_target_status(self, target_id: str) -> dict[str, Any] | None:
        target = self.get_target(target_id)
        if target is None:
            return None
        metadata = target.get("metadata") if isinstance(target.get("metadata"), dict) else {}
        status = str(metadata.get("status") or "unknown")
        ready = status == "reachable"
        return {
            "ready": ready,
            "status": status,
            "reason": metadata.get("reason"),
            "checked_at": metadata.get("checked_at") or target.get("last_seen_at"),
            "handle_id": metadata.get("handle_id") or _target_handle_id(target),
        }

    async def enroll(
        self,
        db: AsyncSession,
        *,
        server_base_url: str,
        label: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _ = server_base_url
        payload = config if isinstance(config, dict) else {}
        host = str(payload.get("host") or "").strip()
        username = str(payload.get("username") or "").strip()
        port = _parse_int(payload.get("port"), 22)
        working_dir = str(payload.get("working_dir") or "").strip()
        if not host:
            raise ValueError("SSH target enrollment requires a host.")
        if not username:
            raise ValueError("SSH target enrollment requires a username.")

        targets = get_registered_targets()
        target_id = str(uuid.uuid4())
        target = {
            "target_id": target_id,
            "driver": "ssh",
            "label": (label or host).strip() or host,
            "hostname": host,
            "platform": "",
            "capabilities": ["shell"],
            "enrolled_at": _utc_now_iso(),
            "last_seen_at": None,
            "metadata": {
                "host": host,
                "username": username,
                "port": port,
                "working_dir": working_dir,
                "status": "unknown",
                "reason": "Probe this target to verify SSH reachability.",
                "checked_at": None,
                "handle_id": f"ssh://{username}@{host}:{port}",
            },
        }
        targets.append(target)
        await _save_targets(db, targets)
        if get_status("ssh") != "enabled":
            await set_status("ssh", "enabled")
        return {"target": target}

    async def remove_target(self, db: AsyncSession, target_id: str) -> bool:
        targets = get_registered_targets()
        kept = [target for target in targets if target.get("target_id") != target_id]
        if len(kept) == len(targets):
            return False
        await _save_targets(db, kept)
        return True

    async def register_connected_target(self, db: AsyncSession, **_kwargs) -> dict[str, Any] | None:
        _ = db
        raise NotImplementedError

    async def _update_probe_state(
        self,
        db: AsyncSession,
        *,
        target_id: str,
        ready: bool,
        status: str,
        reason: str | None,
        checked_at: str,
        hostname: str | None = None,
        platform: str | None = None,
    ) -> dict[str, Any]:
        targets = get_registered_targets()
        updated: dict[str, Any] | None = None
        for target in targets:
            if target.get("target_id") != target_id:
                continue
            metadata = target.get("metadata") if isinstance(target.get("metadata"), dict) else {}
            metadata["status"] = status
            metadata["reason"] = reason
            metadata["checked_at"] = checked_at
            metadata["handle_id"] = _target_handle_id(target)
            target["metadata"] = metadata
            if ready:
                target["last_seen_at"] = checked_at
            if hostname:
                target["hostname"] = hostname
            if platform:
                target["platform"] = platform
            updated = target
            break
        if updated is None:
            raise ValueError("Unknown machine target.")
        await _save_targets(db, targets)
        return updated

    async def probe_target(
        self,
        db: AsyncSession,
        *,
        target_id: str,
    ) -> dict[str, Any]:
        target = self.get_target(target_id)
        if target is None:
            raise ValueError("Unknown machine target.")
        config = _require_secret_settings()
        checked_at = _utc_now_iso()
        try:
            result = await _run_ssh(
                target,
                remote_command=_probe_remote_command(),
                timeout_seconds=config["probe_timeout_seconds"],
                connect_timeout_seconds=config["connect_timeout_seconds"],
                max_output_bytes=config["max_output_bytes"],
            )
        except Exception as exc:
            await self._update_probe_state(
                db,
                target_id=target_id,
                ready=False,
                status="unreachable",
                reason=str(exc),
                checked_at=checked_at,
            )
            return {
                "ready": False,
                "status": "unreachable",
                "reason": str(exc),
                "checked_at": checked_at,
                "handle_id": _target_handle_id(target),
            }

        lines = [line.strip() for line in (result.get("stdout") or "").splitlines() if line.strip()]
        hostname = lines[0] if lines else target.get("hostname") or ""
        platform = lines[1] if len(lines) > 1 else target.get("platform") or ""
        if result["exit_code"] == 0:
            await self._update_probe_state(
                db,
                target_id=target_id,
                ready=True,
                status="reachable",
                reason=None,
                checked_at=checked_at,
                hostname=hostname,
                platform=platform,
            )
            return {
                "ready": True,
                "status": "reachable",
                "reason": None,
                "checked_at": checked_at,
                "handle_id": _target_handle_id(target),
            }

        reason = (result.get("stderr") or "").strip() or "SSH probe failed."
        await self._update_probe_state(
            db,
            target_id=target_id,
            ready=False,
            status="unreachable",
            reason=reason,
            checked_at=checked_at,
        )
        return {
            "ready": False,
            "status": "unreachable",
            "reason": reason,
            "checked_at": checked_at,
            "handle_id": _target_handle_id(target),
        }

    async def inspect_command(self, target_id: str, command: str) -> dict[str, Any]:
        target = self.get_target(target_id)
        if target is None:
            raise ValueError("Unknown machine target.")
        config = _require_secret_settings()
        return await _run_ssh(
            target,
            remote_command=_command_remote_script(command),
            timeout_seconds=config["command_timeout_seconds"],
            connect_timeout_seconds=config["connect_timeout_seconds"],
            max_output_bytes=config["max_output_bytes"],
        )

    async def exec_command(self, target_id: str, command: str, working_dir: str = "") -> dict[str, Any]:
        target = self.get_target(target_id)
        if target is None:
            raise ValueError("Unknown machine target.")
        config = _require_secret_settings()
        metadata = target.get("metadata") if isinstance(target.get("metadata"), dict) else {}
        effective_dir = working_dir.strip() or str(metadata.get("working_dir") or "").strip()
        return await _run_ssh(
            target,
            remote_command=_command_remote_script(command, effective_dir),
            timeout_seconds=config["command_timeout_seconds"],
            connect_timeout_seconds=config["connect_timeout_seconds"],
            max_output_bytes=config["max_output_bytes"],
        )


provider = SSHMachineControlProvider()
