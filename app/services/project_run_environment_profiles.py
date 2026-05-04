"""Pre-agent run environment profiles for Project coding runs."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import signal
import tomllib
from pathlib import Path
from typing import Any, Mapping

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, Project, ProjectRunReceipt, Task
from app.services.project_coding_run_lib import WORK_SURFACE_SHARED_REPO, normalize_work_surface_mode
from app.services.project_runtime import ProjectRuntimeEnvironment, load_project_runtime_environment_for_id
from app.services.projects import normalize_project_path, project_canonical_repo_host_path, project_repo_host_path
from app.services.secret_registry import redact
from app.services.session_execution_environments import (
    get_session_execution_environment,
    session_execution_environment_out,
)


DEFAULT_PROFILE_TIMEOUT_SECONDS = 600
MAX_CAPTURE_CHARS = 6000
MAX_PROFILE_BYTES = 64 * 1024
ENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
PROFILE_SUFFIXES = (".yaml", ".yml", ".toml")
ALLOWED_PROFILE_FIELDS = {
    "name",
    "env",
    "setup_commands",
    "background_processes",
    "readiness_checks",
    "required_artifacts",
    "timeout_seconds",
    "work_surface_modes",
    # Backward-compatible aliases while early callers migrate to the V1 names.
    "preflight_commands",
    "commands",
    "artifacts",
}


def _utcnow():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _snapshot(project: Project) -> dict[str, Any]:
    metadata = project.metadata_ if isinstance(project.metadata_, dict) else {}
    snapshot = metadata.get("blueprint_snapshot")
    return dict(snapshot) if isinstance(snapshot, dict) else {}


def _project_metadata(project: Project) -> dict[str, Any]:
    return dict(project.metadata_ or {}) if isinstance(project.metadata_, dict) else {}


def _blueprint_profiles_source(project: Project) -> dict[str, Any]:
    raw = _snapshot(project).get("run_environment_profiles")
    return raw if isinstance(raw, dict) else {}


def default_run_environment_profile_id(project: Project) -> str | None:
    metadata = _project_metadata(project)
    value = metadata.get("default_run_environment_profile")
    if not isinstance(value, str) or not value.strip():
        value = _snapshot(project).get("default_run_environment_profile")
    return value.strip() if isinstance(value, str) and value.strip() else None


def resolve_run_environment_profile(project: Project, profile_id: str | None) -> tuple[str | None, dict[str, Any] | None]:
    """Resolve Blueprint-snapshot profiles only.

    Repo-file profile resolution is async because it reads the run worktree and
    is handled by ``prepare_project_run_environment_profile``.
    """
    resolved_id = (profile_id or "").strip() or default_run_environment_profile_id(project)
    if not resolved_id:
        return None, None
    raw = _blueprint_profiles_source(project).get(resolved_id)
    if not isinstance(raw, dict):
        return resolved_id, None
    return resolved_id, dict(raw)


def _redactor_for(runtime: ProjectRuntimeEnvironment | None):
    def _redact_text(value: Any) -> str:
        text = str(value or "")
        if runtime is not None:
            return runtime.redact_text(text)
        return redact(text)

    return _redact_text


def _truncate(value: Any, *, redactor=None) -> str:
    redact_text = redactor or redact
    text = redact_text(value or "")
    if len(text) <= MAX_CAPTURE_CHARS:
        return text
    return text[:MAX_CAPTURE_CHARS] + "\n...[truncated]"


def _is_sensitive_env_key(key: str) -> bool:
    upper = key.upper()
    return any(marker in upper for marker in ("SECRET", "TOKEN", "PASSWORD", "PASS", "KEY"))


def _render_env_refs(value: str, env: Mapping[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1) or match.group(2) or ""
        return str(env.get(key, match.group(0)))

    return ENV_REF_RE.sub(repl, value)


def _profile_commands(profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = profile.get("setup_commands") or profile.get("preflight_commands") or profile.get("commands") or []
    if not isinstance(raw, list):
        return []
    commands: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if isinstance(item, str):
            command = item.strip()
            if command:
                commands.append({"name": f"step-{index}", "command": command})
            continue
        if not isinstance(item, dict):
            continue
        command = str(item.get("command") or "").strip()
        if not command:
            continue
        commands.append({
            "name": str(item.get("name") or f"step-{index}"),
            "command": command,
            "cwd": str(item.get("cwd") or "").strip() or None,
            "timeout_seconds": item.get("timeout_seconds"),
            "env": item.get("env") if isinstance(item.get("env"), dict) else {},
        })
    return commands


def _profile_readiness_checks(profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = profile.get("readiness_checks") or []
    if not isinstance(raw, list):
        return []
    checks: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if isinstance(item, str):
            command = item.strip()
            if command:
                checks.append({"name": f"check-{index}", "type": "command", "command": command})
            continue
        if not isinstance(item, dict):
            continue
        check_type = str(item.get("type") or ("http" if item.get("url") else "command")).strip() or "command"
        checks.append({
            "name": str(item.get("name") or f"check-{index}"),
            "type": check_type,
            "command": str(item.get("command") or "").strip(),
            "url": str(item.get("url") or "").strip(),
            "method": str(item.get("method") or "GET").strip().upper(),
            "expected_status": item.get("expected_status"),
            "timeout_seconds": item.get("timeout_seconds"),
            "interval_seconds": item.get("interval_seconds"),
            "cwd": str(item.get("cwd") or "").strip() or None,
            "env": item.get("env") if isinstance(item.get("env"), dict) else {},
        })
    return checks


def _profile_background_processes(profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = profile.get("background_processes") or []
    if not isinstance(raw, list):
        return []
    processes: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if isinstance(item, str):
            command = item.strip()
            if command:
                processes.append({"name": f"process-{index}", "command": command})
            continue
        if isinstance(item, dict) and str(item.get("command") or "").strip():
            processes.append({
                "name": str(item.get("name") or f"process-{index}"),
                "command": str(item["command"]).strip(),
                "cwd": str(item.get("cwd") or "").strip() or None,
                "env": item.get("env") if isinstance(item.get("env"), dict) else {},
            })
    return processes


def _command_cwd(base_cwd: str, command: Mapping[str, Any]) -> str:
    raw = command.get("cwd")
    if not raw:
        return base_cwd
    rel = normalize_project_path(str(raw))
    target = (Path(base_cwd) / rel).resolve()
    root = Path(base_cwd).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"run environment command cwd escapes run root: {raw}")
    return str(target)


def _visible_env_keys(*envs: Mapping[str, str]) -> list[str]:
    keys: set[str] = set()
    for env in envs:
        keys.update(str(key) for key in env.keys())
    return sorted(keys)


def _interpolation_env(env: Mapping[str, str], allowed_keys: set[str]) -> dict[str, str]:
    return {key: str(env[key]) for key in allowed_keys if key in env and not _is_sensitive_env_key(str(key))}


def _profile_artifacts(profile: Mapping[str, Any]) -> list[Any]:
    raw = profile.get("required_artifacts")
    if not isinstance(raw, list):
        raw = profile.get("artifacts")
    return raw if isinstance(raw, list) else []


def _profile_modes(profile: Mapping[str, Any]) -> list[str]:
    raw = profile.get("work_surface_modes")
    if raw is None:
        return ["isolated_worktree"]
    if not isinstance(raw, list):
        return []
    return [normalize_work_surface_mode(item) for item in raw if isinstance(item, str) and item.strip()]


def _profile_validation_error(
    *,
    profile_id: str,
    profile: Mapping[str, Any],
    source_layer: str,
    work_surface_mode: str,
) -> str | None:
    unknown = sorted(set(profile.keys()) - ALLOWED_PROFILE_FIELDS)
    if unknown:
        return f"run environment profile has unknown fields: {', '.join(unknown)}"
    if "env" in profile and not isinstance(profile.get("env"), dict):
        return "run environment profile field env must be an object"
    for key in ("setup_commands", "background_processes", "readiness_checks", "required_artifacts"):
        if key in profile and not isinstance(profile.get(key), list):
            return f"run environment profile field {key} must be a list"
    try:
        modes = _profile_modes(profile)
    except ValueError as exc:
        return str(exc)
    if not modes:
        return "run environment profile field work_surface_modes must list at least one supported mode"
    mutates_checkout = bool(_profile_commands(profile) or _profile_background_processes(profile))
    if work_surface_mode == WORK_SURFACE_SHARED_REPO and mutates_checkout and WORK_SURFACE_SHARED_REPO not in modes:
        return "shared_repo profiles with setup commands or background processes must opt into shared_repo"
    if not (work_surface_mode == WORK_SURFACE_SHARED_REPO and not mutates_checkout) and work_surface_mode not in modes:
        return f"run environment profile {profile_id} does not allow work surface mode {work_surface_mode}"
    timeout = profile.get("timeout_seconds")
    if timeout is not None:
        try:
            if int(timeout) <= 0:
                return "run environment profile timeout_seconds must be positive"
        except (TypeError, ValueError):
            return "run environment profile timeout_seconds must be an integer"
    if source_layer not in {"repo_file", "blueprint_snapshot"}:
        return "run environment profile source is invalid"
    return None


def _approved_profile_hash(project: Project, profile_id: str) -> tuple[str | None, str | None]:
    metadata = _project_metadata(project)
    approvals = metadata.get("run_environment_profile_approvals")
    if isinstance(approvals, dict):
        entry = approvals.get(profile_id)
        if isinstance(entry, dict):
            return str(entry.get("sha256") or "") or None, str(entry.get("approved_by") or "") or None
        if isinstance(entry, str):
            return entry, None
    hashes = metadata.get("approved_run_environment_profile_hashes")
    if isinstance(hashes, dict) and isinstance(hashes.get(profile_id), str):
        return str(hashes[profile_id]), None
    return None, None


def _repo_profile_candidates(cwd: str, profile_id: str) -> list[Path]:
    return [Path(cwd) / ".spindrel" / "profiles" / f"{profile_id}{suffix}" for suffix in PROFILE_SUFFIXES]


async def _read_profile_bytes(path: Path) -> bytes:
    return await asyncio.to_thread(path.read_bytes)


def _parse_profile_bytes(path: Path, raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8")
    if path.suffix == ".toml":
        parsed = tomllib.loads(text)
    else:
        parsed = yaml.safe_load(text) or {}
    if not isinstance(parsed, dict):
        raise ValueError("profile file must contain an object")
    return dict(parsed)


async def _load_repo_file_profile(
    *,
    project: Project,
    profile_id: str,
    cwd: str | None,
    work_surface_mode: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    metadata = _project_metadata(project)
    if not bool(metadata.get("trust_repo_environment_profiles")) or not cwd:
        return None, None
    if not PROFILE_ID_RE.match(profile_id):
        return None, {
            "status": "failed",
            "error": "run environment profile id may contain only letters, numbers, dot, underscore, and dash",
            "source_layer": "repo_file",
        }
    root = Path(cwd).resolve()
    for path in _repo_profile_candidates(cwd, profile_id):
        if not await asyncio.to_thread(path.exists):
            continue
        resolved = path.resolve()
        if resolved != root and root not in resolved.parents:
            return None, {
                "status": "failed",
                "error": f"run environment profile path escapes run root: {path}",
                "source_layer": "repo_file",
            }
        try:
            size = (await asyncio.to_thread(path.stat)).st_size
        except OSError as exc:
            return None, {"status": "failed", "error": str(exc), "source_layer": "repo_file"}
        if size > MAX_PROFILE_BYTES:
            return None, {
                "status": "failed",
                "error": f"run environment profile exceeds {MAX_PROFILE_BYTES} bytes",
                "source_layer": "repo_file",
            }
        try:
            raw = await _read_profile_bytes(path)
            current_hash = hashlib.sha256(raw).hexdigest()
            approved_hash, approved_by = _approved_profile_hash(project, profile_id)
            if approved_hash != current_hash:
                return None, {
                    "status": "needs_review",
                    "error": "run environment repo-file profile changed and needs operator approval",
                    "source_layer": "repo_file",
                    "profile_path": str(path.relative_to(root)),
                    "current_hash": current_hash,
                    "approved_hash": approved_hash,
                    "approved_by": approved_by,
                }
            profile = _parse_profile_bytes(path, raw)
            validation_error = _profile_validation_error(
                profile_id=profile_id,
                profile=profile,
                source_layer="repo_file",
                work_surface_mode=work_surface_mode,
            )
            if validation_error:
                return None, {
                    "status": "failed",
                    "error": validation_error,
                    "source_layer": "repo_file",
                    "profile_path": str(path.relative_to(root)),
                    "current_hash": current_hash,
                    "approved_hash": approved_hash,
                    "approved_by": approved_by,
                }
            return profile, {
                "source_layer": "repo_file",
                "profile_path": str(path.relative_to(root)),
                "current_hash": current_hash,
                "approved_hash": approved_hash,
                "approved_by": approved_by,
            }
        except Exception as exc:
            return None, {
                "status": "failed",
                "error": f"run environment profile file could not be loaded: {exc}",
                "source_layer": "repo_file",
                "profile_path": str(path.relative_to(root)),
            }
    return None, None


async def _resolve_profile_definition(
    *,
    project: Project,
    profile_id: str | None,
    cwd: str | None,
    work_surface_mode: str,
) -> tuple[str | None, dict[str, Any] | None, dict[str, Any]]:
    resolved_id = (profile_id or "").strip() or default_run_environment_profile_id(project)
    if not resolved_id:
        return None, None, {"source_layer": None}
    repo_profile, repo_source = await _load_repo_file_profile(
        project=project,
        profile_id=resolved_id,
        cwd=cwd,
        work_surface_mode=work_surface_mode,
    )
    if repo_source is not None:
        if repo_profile is None:
            return resolved_id, None, repo_source
        return resolved_id, repo_profile, repo_source
    raw = _blueprint_profiles_source(project).get(resolved_id)
    if not isinstance(raw, dict):
        return resolved_id, None, {"source_layer": "blueprint_snapshot"}
    profile = dict(raw)
    validation_error = _profile_validation_error(
        profile_id=resolved_id,
        profile=profile,
        source_layer="blueprint_snapshot",
        work_surface_mode=work_surface_mode,
    )
    if validation_error:
        return resolved_id, None, {"source_layer": "blueprint_snapshot", "status": "failed", "error": validation_error}
    return resolved_id, profile, {"source_layer": "blueprint_snapshot"}


async def _run_shell_command(
    *,
    command: str,
    cwd: str,
    env: Mapping[str, str],
    timeout: int,
    redactor,
) -> dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(
        "/bin/sh",
        "-lc",
        command,
        cwd=cwd,
        env=dict(env),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        await _terminate_process_group(os.getpgid(proc.pid))
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        except asyncio.TimeoutError:
            stdout, stderr = b"", b""
        return {
            "exit_code": None,
            "timed_out": True,
            "stdout": _truncate(stdout.decode("utf-8", "replace"), redactor=redactor),
            "stderr": _truncate(stderr.decode("utf-8", "replace"), redactor=redactor),
        }
    return {
        "exit_code": proc.returncode,
        "timed_out": False,
        "stdout": _truncate(stdout.decode("utf-8", "replace"), redactor=redactor),
        "stderr": _truncate(stderr.decode("utf-8", "replace"), redactor=redactor),
    }


async def _start_background_process(
    *,
    command: str,
    cwd: str,
    env: Mapping[str, str],
    stdout_path: Path,
    stderr_path: Path,
) -> dict[str, Any]:
    stdout_handle = await asyncio.to_thread(stdout_path.open, "ab")
    stderr_handle = await asyncio.to_thread(stderr_path.open, "ab")
    try:
        proc = await asyncio.create_subprocess_exec(
            "/bin/sh",
            "-lc",
            command,
            cwd=cwd,
            env=dict(env),
            stdout=stdout_handle,
            stderr=stderr_handle,
            start_new_session=True,
        )
    finally:
        stdout_handle.close()
        stderr_handle.close()
    return {"pid": proc.pid, "pgid": os.getpgid(proc.pid)}


async def _terminate_process_group(pgid: int | str | None) -> bool:
    if pgid is None:
        return False
    try:
        pgid_int = int(pgid)
    except (TypeError, ValueError):
        return False
    try:
        os.killpg(pgid_int, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    await asyncio.sleep(0.2)
    try:
        os.killpg(pgid_int, 0)
    except ProcessLookupError:
        return True
    try:
        os.killpg(pgid_int, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return True


async def _cleanup_started_processes(process_results: list[dict[str, Any]]) -> dict[str, Any]:
    terminated = []
    for item in process_results:
        if not isinstance(item, dict) or not item.get("pgid"):
            continue
        ok = await _terminate_process_group(item.get("pgid"))
        item["terminated"] = ok
        terminated.append({"name": item.get("name"), "pid": item.get("pid"), "pgid": item.get("pgid"), "terminated": ok})
    return {"terminated": terminated}


async def _persist_background_processes(
    db: AsyncSession,
    *,
    task: Task,
    process_results: list[dict[str, Any]],
) -> None:
    if task.session_id is None or not process_results:
        return
    env_row = await get_session_execution_environment(db, task.session_id)
    if env_row is None:
        return
    metadata = dict(env_row.metadata_ or {})
    existing = list(metadata.get("run_environment_background_processes") or [])
    for item in process_results:
        if isinstance(item, dict) and item.get("pgid"):
            existing.append({
                "task_id": str(task.id),
                "name": item.get("name"),
                "pid": item.get("pid"),
                "pgid": item.get("pgid"),
                "started_at": _utcnow().isoformat(),
            })
    metadata["run_environment_background_processes"] = existing
    env_row.metadata_ = metadata


async def _run_http_readiness_check(
    *,
    check: Mapping[str, Any],
    env: Mapping[str, str],
    timeout: int,
    redactor,
) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    method = str(check.get("method") or "GET").upper()
    url = _render_env_refs(str(check.get("url") or ""), env)
    expected_status = check.get("expected_status")
    expected = {int(expected_status)} if expected_status is not None else set(range(200, 300))

    def _request_once() -> tuple[int | None, str | None]:
        try:
            request = urllib.request.Request(url, method=method)
            with urllib.request.urlopen(request, timeout=min(5, max(1, timeout))) as response:
                return int(getattr(response, "status", 0) or 0), None
        except urllib.error.HTTPError as exc:
            return int(exc.code), None
        except Exception as exc:  # pragma: no cover - exception type varies by platform
            return None, str(exc)

    status, error = await asyncio.to_thread(_request_once)
    result: dict[str, Any] = {
        "name": check.get("name") or "check",
        "type": "http",
        "ok": False,
        "url": _truncate(url, redactor=redactor),
        "method": method,
        "expected_status": sorted(expected),
    }
    if status is not None:
        result["status_code"] = status
        result["ok"] = status in expected
    if error:
        result["error"] = _truncate(error, redactor=redactor)
    return result


async def _run_readiness_check(
    *,
    check: Mapping[str, Any],
    cwd: str,
    env: Mapping[str, str],
    render_env: Mapping[str, str],
    timeout_default: int,
    redactor,
) -> dict[str, Any]:
    timeout = int(check.get("timeout_seconds") or timeout_default)
    interval = max(1.0, float(check.get("interval_seconds") or 2))
    deadline = asyncio.get_running_loop().time() + timeout
    result: dict[str, Any] = {
        "name": check.get("name") or "check",
        "type": check.get("type") or "command",
        "ok": False,
        "attempts": 0,
    }
    while True:
        result["attempts"] = int(result["attempts"]) + 1
        if check.get("type") == "http":
            result.update(await _run_http_readiness_check(
                check=check,
                env=render_env,
                timeout=timeout,
                redactor=redactor,
            ))
        else:
            command = _render_env_refs(str(check.get("command") or ""), render_env)
            result["command"] = _truncate(command, redactor=redactor)
            try:
                command_result = await _run_shell_command(
                    command=command,
                    cwd=_command_cwd(cwd, check),
                    env=env,
                    timeout=min(30, max(1, timeout)),
                    redactor=redactor,
                )
                result.update(command_result)
                result["ok"] = command_result.get("exit_code") == 0
            except Exception as exc:
                result["error"] = _truncate(str(exc), redactor=redactor)
        if result.get("ok"):
            return result
        if asyncio.get_running_loop().time() >= deadline:
            result["error"] = result.get("error") or f"readiness check timed out after {timeout}s"
            return result
        await asyncio.sleep(interval)


async def _execution_cwd(
    db: AsyncSession,
    *,
    task: Task,
    project: Project,
    work_surface_mode: str,
) -> tuple[str, dict[str, Any]]:
    env_payload: dict[str, Any] = {}
    if task.session_id is not None:
        env_row = await get_session_execution_environment(db, task.session_id)
        env_payload = session_execution_environment_out(env_row, session_id=task.session_id)
        if env_payload.get("cwd"):
            return str(env_payload["cwd"]), env_payload
    if work_surface_mode == WORK_SURFACE_SHARED_REPO:
        cwd = project_canonical_repo_host_path(project)
        if cwd:
            return str(cwd), env_payload
    return "", env_payload


async def prepare_project_run_environment_profile(
    db: AsyncSession,
    *,
    task: Task,
    project: Project,
    profile_id: str | None,
) -> dict[str, Any]:
    """Run Project-declared setup before the model receives the task."""
    run_cfg = (task.execution_config or {}).get("project_coding_run") if isinstance(task.execution_config, dict) else {}
    work_surface_mode = normalize_work_surface_mode((run_cfg or {}).get("work_surface_mode"))
    cwd, env_payload = await _execution_cwd(db, task=task, project=project, work_surface_mode=work_surface_mode)
    if not cwd:
        return {
            "configured": True,
            "ok": False,
            "status": "failed",
            "profile_id": profile_id,
            "error": "run environment profile requires a prepared execution cwd",
            "commands": [],
            "env_keys": [],
        }

    resolved_id, profile, source = await _resolve_profile_definition(
        project=project,
        profile_id=profile_id,
        cwd=cwd,
        work_surface_mode=work_surface_mode,
    )
    source_layer = source.get("source_layer")
    if resolved_id and profile is None:
        return {
            "configured": True,
            "ok": False,
            "status": source.get("status") or "failed",
            "profile_id": resolved_id,
            "source_layer": source_layer,
            "profile_path": source.get("profile_path"),
            "current_hash": source.get("current_hash"),
            "approved_hash": source.get("approved_hash"),
            "approved_by": source.get("approved_by"),
            "error": source.get("error") or f"run environment profile not found: {resolved_id}",
            "commands": [],
            "env_keys": [],
        }
    if profile is None:
        return {"configured": False, "ok": True, "status": "not_configured", "profile_id": None, "commands": [], "env_keys": []}

    runtime = await load_project_runtime_environment_for_id(db, project.id, task_id=task.id)
    redact_text = _redactor_for(runtime)
    raw_profile_env = profile.get("env") if isinstance(profile.get("env"), dict) else {}
    runtime_env = dict(runtime.env) if runtime is not None else {}
    env_payload_runtime = dict(env_payload.get("runtime_env") or {})
    interpolation_keys = set(env_payload_runtime.keys()) | {key for key in runtime_env if key.startswith("PROJECT_DEPENDENCY_")}
    interpolation_keys.update({"DOCKER_HOST", "COMPOSE_PROJECT_NAME"})
    base_render_env = _interpolation_env({**runtime_env, **env_payload_runtime}, interpolation_keys)
    profile_env = {str(key): _render_env_refs(str(value), base_render_env) for key, value in raw_profile_env.items()}
    env = {
        **os.environ,
        **runtime_env,
        **env_payload_runtime,
        **profile_env,
    }
    render_env = {
        **base_render_env,
        **_interpolation_env(profile_env, set(profile_env.keys())),
    }
    visible_keys = _visible_env_keys(runtime_env, env_payload_runtime, profile_env)

    timeout_default = int(profile.get("timeout_seconds") or DEFAULT_PROFILE_TIMEOUT_SECONDS)
    process_results: list[dict[str, Any]] = []
    log_dir = Path(cwd) / ".spindrel" / "runs" / str(task.id) / "preflight"

    try:
        for process in _profile_background_processes(profile):
            cwd_for_process = _command_cwd(cwd, process)
            process_env = {**env, **{str(key): _render_env_refs(str(value), render_env) for key, value in (process.get("env") or {}).items()}}
            rendered_command = _render_env_refs(str(process["command"]), render_env)
            try:
                await asyncio.to_thread(log_dir.mkdir, parents=True, exist_ok=True)
                stdout_path = log_dir / f"{process['name']}.stdout.log"
                stderr_path = log_dir / f"{process['name']}.stderr.log"
                started = await _start_background_process(
                    command=rendered_command,
                    cwd=cwd_for_process,
                    env=process_env,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                )
                process_results.append({
                    "name": process["name"],
                    "command": _truncate(rendered_command, redactor=redact_text),
                    "cwd": cwd_for_process,
                    "pid": started["pid"],
                    "pgid": started["pgid"],
                    "stdout_log": str(stdout_path.relative_to(Path(cwd))),
                    "stderr_log": str(stderr_path.relative_to(Path(cwd))),
                })
            except Exception as exc:
                process_results.append({
                    "name": process["name"],
                    "command": _truncate(rendered_command, redactor=redact_text),
                    "cwd": cwd_for_process,
                    "error": _truncate(str(exc), redactor=redact_text),
                })
                cleanup = await _cleanup_started_processes(process_results)
                return {
                    "configured": True,
                    "ok": False,
                    "status": "failed",
                    "profile_id": resolved_id,
                    "name": profile.get("name") or resolved_id,
                    "source_layer": source_layer,
                    "cwd": cwd,
                    "error": f"run environment background process failed to start: {process['name']}",
                    "commands": [],
                    "background_processes": process_results,
                    "background_cleanup": cleanup,
                    "env_keys": visible_keys,
                }
        await _persist_background_processes(db, task=task, process_results=process_results)

        results: list[dict[str, Any]] = []
        for command in _profile_commands(profile):
            timeout = int(command.get("timeout_seconds") or timeout_default)
            cwd_for_command = _command_cwd(cwd, command)
            command_env = {**env, **{str(key): _render_env_refs(str(value), render_env) for key, value in (command.get("env") or {}).items()}}
            rendered_command = _render_env_refs(str(command["command"]), render_env)
            command_result = await _run_shell_command(
                command=rendered_command,
                cwd=cwd_for_command,
                env=command_env,
                timeout=timeout,
                redactor=redact_text,
            )
            result = {
                "name": command["name"],
                "command": _truncate(rendered_command, redactor=redact_text),
                "cwd": cwd_for_command,
                **command_result,
            }
            results.append(result)
            if result.get("timed_out"):
                cleanup = await _cleanup_started_processes(process_results)
                return {
                    "configured": True,
                    "ok": False,
                    "status": "failed",
                    "profile_id": resolved_id,
                    "name": profile.get("name") or resolved_id,
                    "source_layer": source_layer,
                    "cwd": cwd,
                    "error": f"run environment command timed out: {command['name']}",
                    "commands": results,
                    "background_processes": process_results,
                    "background_cleanup": cleanup,
                    "env_keys": visible_keys,
                }
            if result.get("exit_code") != 0:
                cleanup = await _cleanup_started_processes(process_results)
                return {
                    "configured": True,
                    "ok": False,
                    "status": "failed",
                    "profile_id": resolved_id,
                    "name": profile.get("name") or resolved_id,
                    "source_layer": source_layer,
                    "cwd": cwd,
                    "error": f"run environment command failed: {command['name']} exited {result.get('exit_code')}",
                    "commands": results,
                    "background_processes": process_results,
                    "background_cleanup": cleanup,
                    "env_keys": visible_keys,
                }

        readiness_results = []
        for check in _profile_readiness_checks(profile):
            result = await _run_readiness_check(
                check=check,
                cwd=cwd,
                env=env,
                render_env=render_env,
                timeout_default=timeout_default,
                redactor=redact_text,
            )
            readiness_results.append(result)
            if not result.get("ok"):
                cleanup = await _cleanup_started_processes(process_results)
                return {
                    "configured": True,
                    "ok": False,
                    "status": "failed",
                    "profile_id": resolved_id,
                    "name": profile.get("name") or resolved_id,
                    "source_layer": source_layer,
                    "cwd": cwd,
                    "error": f"run environment readiness check failed: {result.get('name')}",
                    "commands": results,
                    "background_processes": process_results,
                    "background_cleanup": cleanup,
                    "readiness_checks": readiness_results,
                    "env_keys": visible_keys,
                }

        artifacts = _profile_artifacts(profile)
        artifact_status = []
        for raw_path in artifacts:
            raw_text = raw_path.get("path") if isinstance(raw_path, dict) else raw_path
            rel = normalize_project_path(_render_env_refs(str(raw_text), render_env))
            path = (Path(cwd) / rel).resolve()
            root = Path(cwd).resolve()
            if path == root:
                artifact_status.append({"path": str(raw_path), "exists": False, "error": "path must name a file or directory under the run root"})
            elif root not in path.parents:
                artifact_status.append({"path": str(raw_path), "exists": False, "error": "path escapes run root"})
            else:
                artifact_status.append({"path": rel, "exists": path.exists()})
        missing_artifacts = [item for item in artifact_status if not item.get("exists")]
        if missing_artifacts:
            cleanup = await _cleanup_started_processes(process_results)
            return {
                "configured": True,
                "ok": False,
                "status": "failed",
                "profile_id": resolved_id,
                "name": profile.get("name") or resolved_id,
                "source_layer": source_layer,
                "cwd": cwd,
                "error": "run environment required artifacts are missing",
                "commands": results,
                "background_processes": process_results,
                "background_cleanup": cleanup,
                "readiness_checks": readiness_results,
                "artifacts": artifact_status,
                "env_keys": visible_keys,
            }

        return {
            "configured": True,
            "ok": True,
            "status": "ready",
            "profile_id": resolved_id,
            "name": profile.get("name") or resolved_id,
            "source_layer": source_layer,
            "profile_path": source.get("profile_path"),
            "current_hash": source.get("current_hash"),
            "approved_hash": source.get("approved_hash"),
            "approved_by": source.get("approved_by"),
            "cwd": cwd,
            "commands": results,
            "background_processes": process_results,
            "readiness_checks": readiness_results,
            "artifacts": artifact_status,
            "env_keys": visible_keys,
        }
    except asyncio.CancelledError:
        await _cleanup_started_processes(process_results)
        raise


async def cleanup_project_run_environment_background_processes(db: AsyncSession, *, task: Task) -> dict[str, Any]:
    if not isinstance(task.execution_config, dict):
        return {"terminated": []}
    run_cfg = task.execution_config.get("project_coding_run")
    if not isinstance(run_cfg, dict):
        return {"terminated": []}
    preflight = run_cfg.get("run_environment_preflight")
    if not isinstance(preflight, dict):
        return {"terminated": []}
    processes = [item for item in (preflight.get("background_processes") or []) if isinstance(item, dict) and item.get("pgid")]
    if not processes:
        return {"terminated": []}
    cleanup = await _cleanup_started_processes(processes)
    preflight["background_cleanup"] = cleanup
    run_cfg["run_environment_preflight"] = preflight
    task.execution_config = {**task.execution_config, "project_coding_run": run_cfg}
    db_task = await db.get(Task, task.id)
    if db_task is not None:
        db_task.execution_config = task.execution_config
    return cleanup


def _preflight_log_hash(*parts: Any) -> str | None:
    text = "\n".join(str(part or "") for part in parts).strip()
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def preflight_blocker_identity(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Return the stable identity used to stop repeated schedule preflight loops."""
    base: dict[str, Any] = {
        "profile_id": summary.get("profile_id") or None,
        "source_layer": summary.get("source_layer") or None,
        "status": summary.get("status") or "failed",
    }
    if summary.get("status") == "needs_review":
        return {
            **base,
            "step_type": "profile_hash",
            "step_name": summary.get("profile_path") or summary.get("profile_id") or "profile",
            "command_or_check_id": summary.get("current_hash") or summary.get("profile_path") or summary.get("profile_id"),
            "exit_code_or_status": "needs_review",
            "error": summary.get("error") or None,
        }
    for item in summary.get("background_processes") or []:
        if isinstance(item, dict) and item.get("error"):
            return {
                **base,
                "step_type": "background_process",
                "step_name": item.get("name") or "background_process",
                "command_or_check_id": item.get("name") or item.get("command"),
                "exit_code_or_status": "start_failed",
                "error": summary.get("error") or item.get("error"),
                "log_hash": _preflight_log_hash(item.get("error")),
            }
    for item in summary.get("commands") or []:
        if not isinstance(item, dict):
            continue
        if item.get("timed_out") or item.get("exit_code") not in (0, "0", None):
            status = "timeout" if item.get("timed_out") else f"exit:{item.get('exit_code')}"
            return {
                **base,
                "step_type": "command",
                "step_name": item.get("name") or "command",
                "command_or_check_id": item.get("name") or item.get("command"),
                "exit_code_or_status": status,
                "error": summary.get("error") or None,
                "log_hash": _preflight_log_hash(item.get("stdout"), item.get("stderr")),
            }
    for item in summary.get("readiness_checks") or []:
        if not isinstance(item, dict) or item.get("ok"):
            continue
        status = item.get("status_code")
        if status is None:
            status = "timeout" if item.get("timed_out") else item.get("exit_code")
        if status is None:
            status = item.get("error") or "failed"
        return {
            **base,
            "step_type": "readiness_check",
            "step_name": item.get("name") or "readiness_check",
            "command_or_check_id": item.get("name") or item.get("url") or item.get("command"),
            "exit_code_or_status": str(status),
            "error": summary.get("error") or item.get("error"),
            "log_hash": _preflight_log_hash(item.get("stdout"), item.get("stderr"), item.get("error")),
        }
    for item in summary.get("artifacts") or []:
        if isinstance(item, dict) and not item.get("exists"):
            return {
                **base,
                "step_type": "artifact",
                "step_name": item.get("path") or "artifact",
                "command_or_check_id": item.get("path"),
                "exit_code_or_status": item.get("error") or "missing",
                "error": summary.get("error") or item.get("error"),
            }
    return {
        **base,
        "step_type": "preflight",
        "step_name": "preflight",
        "command_or_check_id": summary.get("error") or "unknown",
        "exit_code_or_status": summary.get("status") or "failed",
        "error": summary.get("error") or None,
    }


def _identity_digest(identity: Mapping[str, Any]) -> str:
    raw = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _maybe_downgrade_repeated_preflight_blocker(
    db: AsyncSession,
    *,
    task: Task,
    project: Project,
    summary: dict[str, Any],
    branch: str | None,
    base_branch: str | None,
) -> None:
    if task.parent_task_id is None:
        return
    schedule = await db.get(Task, task.parent_task_id)
    if schedule is None or schedule.status != "active":
        return
    current_identity = preflight_blocker_identity(summary)
    previous_tasks = list((await db.execute(
        select(Task)
        .where(Task.parent_task_id == schedule.id)
        .where(Task.id != task.id)
        .order_by(Task.created_at.desc())
        .limit(3)
    )).scalars().all())
    previous_receipt: ProjectRunReceipt | None = None
    previous_preflight: dict[str, Any] | None = None
    for previous_task in previous_tasks:
        receipts = list((await db.execute(
            select(ProjectRunReceipt)
            .where(ProjectRunReceipt.task_id == previous_task.id)
            .order_by(ProjectRunReceipt.created_at.desc())
        )).scalars().all())
        for receipt in receipts:
            metadata = receipt.metadata_ if isinstance(receipt.metadata_, dict) else {}
            if metadata.get("category") != "run_environment_preflight":
                continue
            preflight = metadata.get("preflight")
            if isinstance(preflight, dict):
                previous_receipt = receipt
                previous_preflight = preflight
                break
        if previous_receipt is not None:
            break
    if previous_receipt is None or previous_preflight is None:
        return
    previous_identity = preflight_blocker_identity(previous_preflight)
    if previous_identity != current_identity:
        return

    identity_hash = _identity_digest(current_identity)
    loop_stop_key = f"project-run-preflight-loop-stop:{schedule.id}:{task.id}:{identity_hash}"
    existing = (await db.execute(
        select(ProjectRunReceipt.id)
        .where(ProjectRunReceipt.project_id == project.id)
        .where(ProjectRunReceipt.idempotency_key == loop_stop_key)
        .limit(1)
    )).scalar_one_or_none()
    if existing is None:
        db.add(ProjectRunReceipt(
            project_id=project.id,
            task_id=task.id,
            session_id=task.session_id,
            bot_id=task.bot_id,
            idempotency_key=loop_stop_key,
            status="needs_review",
            summary="Project coding-run schedule stopped after repeated identical preflight blocker.",
            branch=str(branch) if branch else None,
            base_branch=str(base_branch) if base_branch else None,
            metadata_={
                "category": "run_environment_loop_stop",
                "reason": "repeated_preflight_blocker",
                "blocker_identity": current_identity,
                "blocker_identity_hash": identity_hash,
                "current_task_id": str(task.id),
                "previous_task_id": str(previous_receipt.task_id) if previous_receipt.task_id else None,
                "previous_receipt_id": str(previous_receipt.id),
                "schedule_task_id": str(schedule.id),
            },
        ))

    cfg = dict(schedule.execution_config or {})
    schedule_cfg = dict(cfg.get("project_coding_run_schedule") or {})
    schedule_cfg["review_state"] = "needs_review"
    schedule_cfg["review_reason"] = "repeated_preflight_blocker"
    schedule_cfg["latest_preflight_blocker"] = {
        "identity": current_identity,
        "identity_hash": identity_hash,
        "current_task_id": str(task.id),
        "previous_task_id": str(previous_receipt.task_id) if previous_receipt.task_id else None,
        "updated_at": _utcnow().isoformat(),
    }
    cfg["project_coding_run_schedule"] = schedule_cfg
    schedule.execution_config = cfg
    schedule.status = "needs_review"
    schedule.error = "Repeated identical Project run environment preflight blocker; operator review required."


async def record_project_run_preflight_failure(
    db: AsyncSession,
    *,
    task: Task,
    project: Project,
    summary: dict[str, Any],
) -> None:
    error = str(summary.get("error") or "Project run preflight failed.")
    profile_id = summary.get("profile_id")
    receipt_key = f"project-run-preflight-failure:{task.id}:{profile_id or 'dependency'}"
    run_cfg = (task.execution_config or {}).get("project_coding_run") if isinstance(task.execution_config, dict) else {}
    branch = run_cfg.get("branch") if isinstance(run_cfg, dict) else None
    base_branch = run_cfg.get("base_branch") if isinstance(run_cfg, dict) else None
    receipt_status = "needs_review" if summary.get("status") == "needs_review" else "blocked"

    existing = (await db.execute(
        select(ProjectRunReceipt.id)
        .where(ProjectRunReceipt.task_id == task.id)
        .where(ProjectRunReceipt.idempotency_key == receipt_key)
        .limit(1)
    )).scalar_one_or_none()
    if existing is None:
        db.add(ProjectRunReceipt(
            project_id=project.id,
            task_id=task.id,
            session_id=task.session_id,
            bot_id=task.bot_id,
            idempotency_key=receipt_key,
            status=receipt_status,
            summary=f"Project coding run blocked before agent start: {error}",
            branch=str(branch) if branch else None,
            base_branch=str(base_branch) if base_branch else None,
            metadata_={
                "category": "run_environment_preflight",
                "preflight": summary,
                "loop": {
                    "decision": "blocked",
                    "reason": error,
                    "remaining_work": "Repair the Project run environment profile or dependency preflight, then re-run the Project task.",
                },
            },
        ))
        if task.session_id is not None:
            lines = []
            for item in summary.get("commands") or []:
                if isinstance(item, dict):
                    lines.append(f"- {item.get('name') or 'command'}: exit {item.get('exit_code')} in `{item.get('cwd') or ''}`")
            for item in summary.get("readiness_checks") or []:
                if isinstance(item, dict):
                    lines.append(f"- readiness {item.get('name') or 'check'}: {'ok' if item.get('ok') else 'failed'}")
            for item in summary.get("artifacts") or []:
                if isinstance(item, dict) and not item.get("exists"):
                    lines.append(f"- missing artifact: `{item.get('path')}`")
            command_block = "\n".join(lines) if lines else "- No profile commands completed."
            db.add(Message(
                session_id=task.session_id,
                role="assistant",
                content=(
                    "Project coding run blocked before the agent started.\n\n"
                    f"Run environment preflight failed: {error}\n\n"
                    f"- Profile: `{profile_id or 'default'}`\n"
                    f"- Status: {summary.get('status') or 'failed'}\n"
                    f"- Source: {summary.get('source_layer') or 'dependency'}\n"
                    f"{command_block}\n\n"
                    "No files were edited by the agent. Repair the Project run environment profile or dependency preflight, then re-run the Project task."
                ),
                metadata_={
                    "source": "project_run_environment",
                    "sender_type": "project_run_launcher",
                    "sender_display_name": "Project run launcher",
                    "task_id": str(task.id),
                    "project_id": str(project.id),
                    "context_visibility": "session",
                    "result_kind": "blocked",
                },
                created_at=_utcnow(),
            ))

    task.status = "failed"
    task.error = error[:4000]
    task.completed_at = _utcnow()
    if isinstance(task.execution_config, dict):
        run_cfg = dict(task.execution_config.get("project_coding_run") or {})
        loop_state = dict(run_cfg.get("loop_state") or {})
        if loop_state:
            loop_state.update({
                "state": "blocked",
                "stop_reason": "preflight_failed",
                "latest_decision": "blocked",
                "latest_reason": error,
                "remaining_work": "Repair the Project run environment profile or dependency preflight, then re-run the Project task.",
                "updated_at": _utcnow().isoformat(),
            })
            run_cfg["loop_state"] = loop_state
        task.execution_config = {**task.execution_config, "project_coding_run": run_cfg}
    await _maybe_downgrade_repeated_preflight_blocker(
        db,
        task=task,
        project=project,
        summary=summary,
        branch=branch,
        base_branch=base_branch,
    )


async def record_project_run_preflight_success(
    db: AsyncSession,
    *,
    task: Task,
    project: Project,
    summary: dict[str, Any],
) -> None:
    if task.session_id is None or not summary.get("configured"):
        return
    lines = []
    for item in summary.get("commands") or []:
        if isinstance(item, dict):
            lines.append(f"- {item.get('name') or 'command'}: exit {item.get('exit_code')}")
    for item in summary.get("readiness_checks") or []:
        if isinstance(item, dict):
            lines.append(f"- readiness {item.get('name') or 'check'}: {'ok' if item.get('ok') else 'failed'}")
    command_block = "\n".join(lines) if lines else "- No profile setup commands were configured."
    db.add(Message(
        session_id=task.session_id,
        role="assistant",
        content=(
            "Project run environment prepared before agent start.\n\n"
            f"- Profile: `{summary.get('profile_id') or 'default'}`\n"
            f"- Status: {summary.get('status') or 'ready'}\n"
            f"- Source: {summary.get('source_layer') or 'blueprint_snapshot'}\n"
            f"- CWD: `{summary.get('cwd') or ''}`\n"
            f"{command_block}"
        ),
        metadata_={
            "source": "project_run_environment",
            "sender_type": "project_run_launcher",
            "sender_display_name": "Project run launcher",
            "task_id": str(task.id),
            "project_id": str(project.id),
            "context_visibility": "session",
            "result_kind": "ready",
        },
        created_at=_utcnow(),
    ))


async def validate_run_environment_profile(
    project: Project,
    profile_id: str | None,
    *,
    cwd: str | None,
    work_surface_mode: str = "isolated_worktree",
) -> dict[str, Any]:
    resolved_id, profile, source = await _resolve_profile_definition(
        project=project,
        profile_id=profile_id,
        cwd=cwd,
        work_surface_mode=normalize_work_surface_mode(work_surface_mode),
    )
    return {
        "ok": bool(profile is not None),
        "profile_id": resolved_id,
        "source_layer": source.get("source_layer"),
        "profile_path": source.get("profile_path"),
        "status": source.get("status") if profile is None else "ready",
        "current_hash": source.get("current_hash"),
        "approved_hash": source.get("approved_hash"),
        "approved_by": source.get("approved_by"),
        "error": None if profile is not None else source.get("error") or f"run environment profile not found: {resolved_id}",
        "fields": sorted(profile.keys()) if isinstance(profile, dict) else [],
    }


async def validate_project_run_environment_profile_selection(
    project: Project,
    *,
    profile_id: str | None,
    repo_path: str | None = None,
    work_surface_mode: str = "isolated_worktree",
) -> dict[str, Any]:
    metadata = _project_metadata(project)
    cwd = project_repo_host_path(project, repo_path=repo_path)
    resolved_id = (profile_id or "").strip() or default_run_environment_profile_id(project)
    if not resolved_id:
        return {
            "ok": True,
            "configured": False,
            "profile_id": None,
            "work_surface_mode": normalize_work_surface_mode(work_surface_mode),
            "trust_repo_environment_profiles": bool(metadata.get("trust_repo_environment_profiles")),
            "cwd": cwd,
        }
    result = await validate_run_environment_profile(
        project,
        resolved_id,
        cwd=cwd,
        work_surface_mode=work_surface_mode,
    )
    result.update({
        "configured": True,
        "trust_repo_environment_profiles": bool(metadata.get("trust_repo_environment_profiles")),
        "cwd": cwd,
        "work_surface_mode": normalize_work_surface_mode(work_surface_mode),
    })
    if not result.get("ok"):
        result["status"] = str(result.get("status") or "blocked")
        if not result.get("error"):
            result["error"] = f"run environment profile is not valid: {resolved_id}"
    else:
        result["status"] = "ready"
    return result


async def validate_project_run_environment_profile_or_raise(
    project: Project,
    *,
    profile_id: str | None,
    repo_path: str | None = None,
    work_surface_mode: str = "isolated_worktree",
) -> dict[str, Any]:
    result = await validate_project_run_environment_profile_selection(
        project,
        profile_id=profile_id,
        repo_path=repo_path,
        work_surface_mode=work_surface_mode,
    )
    if result.get("ok") is False:
        raise ValueError(str(result.get("error") or "run environment profile is invalid"))
    return result


def approve_run_environment_profile_hash(
    project: Project,
    *,
    profile_id: str,
    sha256: str,
    approved_by: str | None,
) -> dict[str, Any]:
    profile_id = profile_id.strip()
    digest = sha256.strip().lower()
    if not PROFILE_ID_RE.match(profile_id):
        raise ValueError("run environment profile id may contain only letters, numbers, dot, underscore, and dash")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("sha256 must be a 64-character lowercase hexadecimal digest")
    metadata = _project_metadata(project)
    approvals = dict(metadata.get("run_environment_profile_approvals") or {})
    entry = {
        "sha256": digest,
        "approved_by": approved_by,
        "approved_at": _utcnow().isoformat(),
    }
    approvals[profile_id] = entry
    metadata["run_environment_profile_approvals"] = approvals
    project.metadata_ = metadata
    return {"profile_id": profile_id, **entry}
