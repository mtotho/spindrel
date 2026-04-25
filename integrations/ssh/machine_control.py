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

from integrations.sdk import (
    get_status,
    get_value,
    machine_utc_now_iso,
    set_status,
    update_settings,
)

TARGETS_KEY = "SSH_TARGETS_JSON"
PROFILES_KEY = "SSH_PROFILES_JSON"
_TARGETS_SETUP_VARS = [{"key": TARGETS_KEY, "secret": False}]
_PROFILES_SETUP_VARS = [{"key": PROFILES_KEY, "secret": True}]


def _utc_now_iso() -> str:
    return machine_utc_now_iso()


def _parse_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _load_runtime_settings() -> dict[str, Any]:
    return {
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
        profile_id = str(item.get("profile_id") or metadata.get("profile_id") or "").strip()
        out.append({
            "target_id": target_id,
            "driver": "ssh",
            "label": str(item.get("label") or metadata.get("host") or target_id),
            "hostname": str(item.get("hostname") or metadata.get("host") or ""),
            "platform": str(item.get("platform") or ""),
            "capabilities": [str(v) for v in (item.get("capabilities") or ["shell"]) if str(v).strip()],
            "profile_id": profile_id or None,
            "profile_label": str(item.get("profile_label") or "").strip() or None,
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


def _parse_profiles(raw: str) -> list[dict[str, Any]]:
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
        profile_id = str(item.get("profile_id") or "").strip()
        if not profile_id:
            continue
        config = item.get("config") if isinstance(item.get("config"), dict) else {}
        out.append({
            "profile_id": profile_id,
            "label": str(item.get("label") or profile_id),
            "created_at": str(item.get("created_at") or _utc_now_iso()),
            "updated_at": str(item.get("updated_at") or item.get("created_at") or _utc_now_iso()),
            "config": {
                "private_key": str(config.get("private_key") or ""),
                "known_hosts": str(config.get("known_hosts") or ""),
            },
        })
    return out


def _dump_profiles(profiles: list[dict[str, Any]]) -> str:
    return json.dumps(profiles, ensure_ascii=False)


def get_registered_targets() -> list[dict[str, Any]]:
    return _parse_targets(get_value("ssh", TARGETS_KEY, "[]"))


def _get_stored_profiles() -> list[dict[str, Any]]:
    return _parse_profiles(get_value("ssh", PROFILES_KEY, "[]"))


def _public_profile(profile: dict[str, Any]) -> dict[str, Any]:
    config = profile.get("config") if isinstance(profile.get("config"), dict) else {}
    configured = [key for key in ("private_key", "known_hosts") if str(config.get(key) or "").strip()]
    return {
        "profile_id": str(profile.get("profile_id") or ""),
        "label": str(profile.get("label") or profile.get("profile_id") or ""),
        "created_at": profile.get("created_at"),
        "updated_at": profile.get("updated_at"),
        "summary": f"{len(configured)} secret{'s' if len(configured) != 1 else ''} configured" if configured else "No secrets configured",
        "metadata": {
            "configured_secrets": configured,
        },
    }


async def _save_targets(db: AsyncSession, targets: list[dict[str, Any]]) -> None:
    await update_settings("ssh", {TARGETS_KEY: _dump_targets(targets)}, _TARGETS_SETUP_VARS, db)


async def _save_profiles(db: AsyncSession, profiles: list[dict[str, Any]]) -> None:
    await update_settings("ssh", {PROFILES_KEY: _dump_profiles(profiles)}, _PROFILES_SETUP_VARS, db)


def _require_profile(profile_id: str) -> dict[str, Any]:
    for profile in _get_stored_profiles():
        if profile.get("profile_id") != profile_id:
            continue
        config = profile.get("config") if isinstance(profile.get("config"), dict) else {}
        private_key = str(config.get("private_key") or "")
        known_hosts = str(config.get("known_hosts") or "")
        if not private_key.strip():
            raise ValueError(f"SSH profile '{profile_id}' is missing a private key.")
        if not known_hosts.strip():
            raise ValueError(f"SSH profile '{profile_id}' is missing known_hosts.")
        return profile
    raise ValueError(f"Unknown SSH profile '{profile_id}'.")


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
    auth: dict[str, Any],
    remote_command: str,
    timeout_seconds: int,
    connect_timeout_seconds: int,
    max_output_bytes: int,
) -> dict[str, Any]:
    metadata = target.get("metadata") if isinstance(target.get("metadata"), dict) else {}
    host = str(metadata.get("host") or target.get("hostname") or "").strip()
    username = str(metadata.get("username") or "").strip()
    port = _parse_int(metadata.get("port"), 22)
    if not host or not username:
        raise ValueError("SSH target is missing host or username.")

    config = auth.get("config") if isinstance(auth.get("config"), dict) else {}
    private_key = str(config.get("private_key") or "")
    known_hosts = str(config.get("known_hosts") or "")
    if not private_key.strip():
        raise ValueError("SSH profile is missing a private key.")
    if not known_hosts.strip():
        raise ValueError("SSH profile is missing known_hosts.")

    key_fd, key_path = tempfile.mkstemp(prefix="spindrel-ssh-key-", text=True)
    hosts_fd, hosts_path = tempfile.mkstemp(prefix="spindrel-known-hosts-", text=True)
    try:
        os.write(key_fd, private_key.encode())
        os.write(hosts_fd, known_hosts.encode())
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
    supports_profiles = True

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

    def list_profiles(self) -> list[dict[str, Any]]:
        return [_public_profile(profile) for profile in _get_stored_profiles()]

    def get_profile(self, profile_id: str) -> dict[str, Any] | None:
        for profile in self.list_profiles():
            if profile.get("profile_id") == profile_id:
                return profile
        return None

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
        profile_id = str(payload.get("profile_id") or "").strip()
        if not host:
            raise ValueError("SSH target enrollment requires a host.")
        if not username:
            raise ValueError("SSH target enrollment requires a username.")
        if not profile_id:
            raise ValueError("SSH target enrollment requires a profile_id.")
        profile = self.get_profile(profile_id)
        if profile is None:
            raise ValueError("Unknown SSH profile.")

        targets = get_registered_targets()
        target_id = str(uuid.uuid4())
        target = {
            "target_id": target_id,
            "driver": "ssh",
            "label": (label or host).strip() or host,
            "hostname": host,
            "platform": "",
            "capabilities": ["shell"],
            "profile_id": profile_id,
            "profile_label": profile.get("label"),
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

    async def create_profile(
        self,
        db: AsyncSession,
        *,
        label: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = config if isinstance(config, dict) else {}
        private_key = str(payload.get("private_key") or "")
        known_hosts = str(payload.get("known_hosts") or "")
        if not private_key.strip():
            raise ValueError("SSH profile creation requires a private_key.")
        if not known_hosts.strip():
            raise ValueError("SSH profile creation requires known_hosts.")
        profiles = _get_stored_profiles()
        profile = {
            "profile_id": str(uuid.uuid4()),
            "label": (label or f"SSH Profile {len(profiles) + 1}").strip() or f"SSH Profile {len(profiles) + 1}",
            "created_at": _utc_now_iso(),
            "updated_at": _utc_now_iso(),
            "config": {
                "private_key": private_key,
                "known_hosts": known_hosts,
            },
        }
        profiles.append(profile)
        await _save_profiles(db, profiles)
        if get_status("ssh") != "enabled":
            await set_status("ssh", "enabled")
        return _public_profile(profile)

    async def update_profile(
        self,
        db: AsyncSession,
        *,
        profile_id: str,
        label: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        profiles = _get_stored_profiles()
        payload = config if isinstance(config, dict) else {}
        updated: dict[str, Any] | None = None
        for profile in profiles:
            if profile.get("profile_id") != profile_id:
                continue
            if label is not None:
                next_label = label.strip()
                if not next_label:
                    raise ValueError("SSH profile label cannot be empty.")
                profile["label"] = next_label
            existing_config = profile.get("config") if isinstance(profile.get("config"), dict) else {}
            next_config = dict(existing_config)
            for key in ("private_key", "known_hosts"):
                if key not in payload:
                    continue
                value = payload.get(key)
                next_config[key] = "" if value is None else str(value)
            if not str(next_config.get("private_key") or "").strip():
                raise ValueError("SSH profile must keep a private_key.")
            if not str(next_config.get("known_hosts") or "").strip():
                raise ValueError("SSH profile must keep known_hosts.")
            profile["config"] = next_config
            profile["updated_at"] = _utc_now_iso()
            updated = profile
            break
        if updated is None:
            raise ValueError("Unknown SSH profile.")
        await _save_profiles(db, profiles)
        return _public_profile(updated)

    async def delete_profile(self, db: AsyncSession, profile_id: str) -> bool:
        targets = get_registered_targets()
        if any(str(target.get("profile_id") or "").strip() == profile_id for target in targets):
            raise RuntimeError("Machine profile is still in use by one or more targets.")
        profiles = _get_stored_profiles()
        kept = [profile for profile in profiles if profile.get("profile_id") != profile_id]
        if len(kept) == len(profiles):
            return False
        await _save_profiles(db, kept)
        return True

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
            profile = self.get_profile(str(target.get("profile_id") or "").strip())
            target["profile_label"] = profile.get("label") if isinstance(profile, dict) else target.get("profile_label")
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
        profile_id = str(target.get("profile_id") or "").strip()
        checked_at = _utc_now_iso()
        try:
            auth = _require_profile(profile_id)
            result = await _run_ssh(
                target,
                auth=auth,
                remote_command=_probe_remote_command(),
                timeout_seconds=_load_runtime_settings()["probe_timeout_seconds"],
                connect_timeout_seconds=_load_runtime_settings()["connect_timeout_seconds"],
                max_output_bytes=_load_runtime_settings()["max_output_bytes"],
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
        auth = _require_profile(str(target.get("profile_id") or "").strip())
        runtime = _load_runtime_settings()
        return await _run_ssh(
            target,
            auth=auth,
            remote_command=_command_remote_script(command),
            timeout_seconds=runtime["command_timeout_seconds"],
            connect_timeout_seconds=runtime["connect_timeout_seconds"],
            max_output_bytes=runtime["max_output_bytes"],
        )

    async def exec_command(self, target_id: str, command: str, working_dir: str = "") -> dict[str, Any]:
        target = self.get_target(target_id)
        if target is None:
            raise ValueError("Unknown machine target.")
        auth = _require_profile(str(target.get("profile_id") or "").strip())
        runtime = _load_runtime_settings()
        metadata = target.get("metadata") if isinstance(target.get("metadata"), dict) else {}
        effective_dir = working_dir.strip() or str(metadata.get("working_dir") or "").strip()
        return await _run_ssh(
            target,
            auth=auth,
            remote_command=_command_remote_script(command, effective_dir),
            timeout_seconds=runtime["command_timeout_seconds"],
            connect_timeout_seconds=runtime["connect_timeout_seconds"],
            max_output_bytes=runtime["max_output_bytes"],
        )


provider = SSHMachineControlProvider()
