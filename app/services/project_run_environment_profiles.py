"""Pre-agent run environment profiles for Project coding runs."""
from __future__ import annotations

import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, Project, ProjectRunReceipt, Task
from app.services.project_runtime import load_project_runtime_environment_for_id
from app.services.projects import normalize_project_path
from app.services.secret_registry import redact
from app.services.session_execution_environments import (
    get_session_execution_environment,
    session_execution_environment_out,
)


DEFAULT_PROFILE_TIMEOUT_SECONDS = 600
MAX_CAPTURE_CHARS = 6000
ENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")


def _snapshot(project: Project) -> dict[str, Any]:
    metadata = project.metadata_ if isinstance(project.metadata_, dict) else {}
    snapshot = metadata.get("blueprint_snapshot")
    return dict(snapshot) if isinstance(snapshot, dict) else {}


def _profiles_source(project: Project) -> dict[str, Any]:
    metadata = project.metadata_ if isinstance(project.metadata_, dict) else {}
    raw = metadata.get("run_environment_profiles")
    if not isinstance(raw, dict):
        raw = _snapshot(project).get("run_environment_profiles")
    return raw if isinstance(raw, dict) else {}


def default_run_environment_profile_id(project: Project) -> str | None:
    metadata = project.metadata_ if isinstance(project.metadata_, dict) else {}
    value = metadata.get("default_run_environment_profile")
    if not isinstance(value, str) or not value.strip():
        value = _snapshot(project).get("default_run_environment_profile")
    return value.strip() if isinstance(value, str) and value.strip() else None


def resolve_run_environment_profile(project: Project, profile_id: str | None) -> tuple[str | None, dict[str, Any] | None]:
    resolved_id = (profile_id or "").strip() or default_run_environment_profile_id(project)
    if not resolved_id:
        return None, None
    profiles = _profiles_source(project)
    raw = profiles.get(resolved_id)
    if not isinstance(raw, dict):
        return resolved_id, None
    return resolved_id, dict(raw)


def _truncate(value: str) -> str:
    text = redact(value or "")
    if len(text) <= MAX_CAPTURE_CHARS:
        return text
    return text[:MAX_CAPTURE_CHARS] + "\n...[truncated]"


def _utcnow():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _render_env_refs(value: str, env: Mapping[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1) or match.group(2) or ""
        return str(env.get(key, match.group(0)))

    return ENV_REF_RE.sub(repl, value)


def _profile_commands(profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = profile.get("preflight_commands") or profile.get("setup_commands") or profile.get("commands") or []
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
        check = {
            "name": str(item.get("name") or f"check-{index}"),
            "type": check_type,
            "command": str(item.get("command") or "").strip(),
            "url": str(item.get("url") or "").strip(),
            "timeout_seconds": item.get("timeout_seconds"),
            "interval_seconds": item.get("interval_seconds"),
            "cwd": str(item.get("cwd") or "").strip() or None,
            "env": item.get("env") if isinstance(item.get("env"), dict) else {},
        }
        checks.append(check)
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


def _env_keys(env: Mapping[str, str]) -> list[str]:
    prefixes = ("SPINDREL_", "PROJECT_DEPENDENCY_", "DOCKER_HOST", "COMPOSE_PROJECT_NAME")
    return sorted(key for key in env if str(key).startswith(prefixes))


def _profile_artifacts(profile: Mapping[str, Any]) -> list[Any]:
    raw = profile.get("required_artifacts")
    if not isinstance(raw, list):
        raw = profile.get("artifacts")
    return raw if isinstance(raw, list) else []


def _run_readiness_check(
    *,
    check: Mapping[str, Any],
    cwd: str,
    env: Mapping[str, str],
    timeout_default: int,
) -> dict[str, Any]:
    timeout = int(check.get("timeout_seconds") or timeout_default)
    interval = max(1.0, float(check.get("interval_seconds") or 2))
    deadline = time.monotonic() + timeout
    result: dict[str, Any] = {
        "name": check.get("name") or "check",
        "type": check.get("type") or "command",
        "ok": False,
        "attempts": 0,
    }
    while True:
        result["attempts"] = int(result["attempts"]) + 1
        if check.get("type") == "http":
            url = _render_env_refs(str(check.get("url") or ""), env)
            result["url"] = url
            try:
                with urllib.request.urlopen(url, timeout=min(5, max(1, timeout))) as response:
                    status = int(getattr(response, "status", 0) or 0)
                result["status_code"] = status
                if 200 <= status < 500:
                    result["ok"] = True
                    return result
            except Exception as exc:
                result["error"] = _truncate(str(exc))
        else:
            command = _render_env_refs(str(check.get("command") or ""), env)
            result["command"] = command
            try:
                proc = subprocess.run(
                    command,
                    cwd=_command_cwd(cwd, check),
                    env=dict(env),
                    shell=True,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=min(30, max(1, timeout)),
                )
                result.update({
                    "exit_code": proc.returncode,
                    "stdout": _truncate(proc.stdout),
                    "stderr": _truncate(proc.stderr),
                })
                if proc.returncode == 0:
                    result["ok"] = True
                    return result
            except subprocess.TimeoutExpired as exc:
                result.update({
                    "exit_code": None,
                    "timed_out": True,
                    "stdout": _truncate(exc.stdout or ""),
                    "stderr": _truncate(exc.stderr or ""),
                })
        if time.monotonic() >= deadline:
            result["error"] = result.get("error") or f"readiness check timed out after {timeout}s"
            return result
        time.sleep(interval)


async def prepare_project_run_environment_profile(
    db: AsyncSession,
    *,
    task: Task,
    project: Project,
    profile_id: str | None,
) -> dict[str, Any]:
    """Run Project-declared setup commands before the model receives the task."""
    resolved_id, profile = resolve_run_environment_profile(project, profile_id)
    if resolved_id and profile is None:
        return {
            "configured": True,
            "ok": False,
            "status": "failed",
            "profile_id": resolved_id,
            "error": f"run environment profile not found: {resolved_id}",
            "commands": [],
            "env_keys": [],
        }
    if profile is None:
        return {"configured": False, "ok": True, "status": "not_configured", "profile_id": None, "commands": [], "env_keys": []}
    if task.session_id is None:
        return {
            "configured": True,
            "ok": False,
            "status": "failed",
            "profile_id": resolved_id,
            "error": "run environment profile requires a run session",
            "commands": [],
            "env_keys": [],
        }

    env_row = await get_session_execution_environment(db, task.session_id)
    env_payload = session_execution_environment_out(env_row, session_id=task.session_id)
    cwd = str(env_payload.get("cwd") or "")
    if not cwd:
        return {
            "configured": True,
            "ok": False,
            "status": "failed",
            "profile_id": resolved_id,
            "error": "run environment profile requires a prepared execution cwd",
            "commands": [],
            "env_keys": [],
        }

    runtime = await load_project_runtime_environment_for_id(db, project.id, task_id=task.id)
    raw_profile_env = profile.get("env") if isinstance(profile.get("env"), dict) else {}
    env = {
        **os.environ,
        **(dict(runtime.env) if runtime is not None else {}),
        **dict(env_payload.get("runtime_env") or {}),
    }
    profile_env = {str(key): _render_env_refs(str(value), env) for key, value in raw_profile_env.items()}
    env.update(profile_env)

    timeout_default = int(profile.get("timeout_seconds") or DEFAULT_PROFILE_TIMEOUT_SECONDS)
    process_results: list[dict[str, Any]] = []
    log_dir = Path(cwd) / ".spindrel" / "runs" / str(task.id) / "preflight"
    for process in _profile_background_processes(profile):
        cwd_for_process = _command_cwd(cwd, process)
        process_env = {**env, **{str(key): _render_env_refs(str(value), env) for key, value in (process.get("env") or {}).items()}}
        command = _render_env_refs(str(process["command"]), process_env)
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            stdout_path = log_dir / f"{process['name']}.stdout.log"
            stderr_path = log_dir / f"{process['name']}.stderr.log"
            stdout_handle = stdout_path.open("ab")
            stderr_handle = stderr_path.open("ab")
            proc = subprocess.Popen(
                command,
                cwd=cwd_for_process,
                env=process_env,
                shell=True,
                stdout=stdout_handle,
                stderr=stderr_handle,
                start_new_session=True,
            )
            stdout_handle.close()
            stderr_handle.close()
            process_results.append({
                "name": process["name"],
                "command": command,
                "cwd": cwd_for_process,
                "pid": proc.pid,
                "stdout_log": str(stdout_path.relative_to(Path(cwd))),
                "stderr_log": str(stderr_path.relative_to(Path(cwd))),
            })
        except Exception as exc:
            process_results.append({
                "name": process["name"],
                "command": command,
                "cwd": cwd_for_process,
                "error": _truncate(str(exc)),
            })
            return {
                "configured": True,
                "ok": False,
                "status": "failed",
                "profile_id": resolved_id,
                "name": profile.get("name") or resolved_id,
                "cwd": cwd,
                "error": f"run environment background process failed to start: {process['name']}",
                "commands": [],
                "background_processes": process_results,
                "env_keys": _env_keys(env),
            }

    results: list[dict[str, Any]] = []
    for command in _profile_commands(profile):
        timeout = int(command.get("timeout_seconds") or timeout_default)
        cwd_for_command = _command_cwd(cwd, command)
        command_env = {**env, **{str(key): _render_env_refs(str(value), env) for key, value in (command.get("env") or {}).items()}}
        rendered_command = _render_env_refs(str(command["command"]), command_env)
        try:
            proc = subprocess.run(
                rendered_command,
                cwd=cwd_for_command,
                env=command_env,
                shell=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            results.append({
                "name": command["name"],
                "command": rendered_command,
                "cwd": cwd_for_command,
                "exit_code": None,
                "timed_out": True,
                "stdout": _truncate(exc.stdout or ""),
                "stderr": _truncate(exc.stderr or ""),
            })
            return {
                "configured": True,
                "ok": False,
                "status": "failed",
                "profile_id": resolved_id,
                "name": profile.get("name") or resolved_id,
                "cwd": cwd,
                "error": f"run environment command timed out: {command['name']}",
                "commands": results,
                "background_processes": process_results,
                "env_keys": _env_keys(env),
            }
        result = {
            "name": command["name"],
            "command": rendered_command,
            "cwd": cwd_for_command,
            "exit_code": proc.returncode,
            "timed_out": False,
            "stdout": _truncate(proc.stdout),
            "stderr": _truncate(proc.stderr),
        }
        results.append(result)
        if proc.returncode != 0:
            return {
                "configured": True,
                "ok": False,
                "status": "failed",
                "profile_id": resolved_id,
                "name": profile.get("name") or resolved_id,
                "cwd": cwd,
                "error": f"run environment command failed: {command['name']} exited {proc.returncode}",
                "commands": results,
                "background_processes": process_results,
                "env_keys": _env_keys(env),
            }

    readiness_results = []
    for check in _profile_readiness_checks(profile):
        result = _run_readiness_check(check=check, cwd=cwd, env=env, timeout_default=timeout_default)
        readiness_results.append(result)
        if not result.get("ok"):
            return {
                "configured": True,
                "ok": False,
                "status": "failed",
                "profile_id": resolved_id,
                "name": profile.get("name") or resolved_id,
                "cwd": cwd,
                "error": f"run environment readiness check failed: {result.get('name')}",
                "commands": results,
                "background_processes": process_results,
                "readiness_checks": readiness_results,
                "env_keys": _env_keys(env),
            }

    artifacts = _profile_artifacts(profile)
    artifact_status = []
    for raw_path in artifacts:
        raw_text = raw_path.get("path") if isinstance(raw_path, dict) else raw_path
        rel = normalize_project_path(_render_env_refs(str(raw_text), env))
        path = (Path(cwd) / rel).resolve()
        root = Path(cwd).resolve()
        if path == root or root not in path.parents:
            artifact_status.append({"path": str(raw_path), "exists": False, "error": "path escapes run root"})
        else:
            artifact_status.append({"path": rel, "exists": path.exists()})
    missing_artifacts = [item for item in artifact_status if not item.get("exists")]
    if missing_artifacts:
        return {
            "configured": True,
            "ok": False,
            "status": "failed",
            "profile_id": resolved_id,
            "name": profile.get("name") or resolved_id,
            "cwd": cwd,
            "error": "run environment required artifacts are missing",
            "commands": results,
            "background_processes": process_results,
            "readiness_checks": readiness_results,
            "artifacts": artifact_status,
            "env_keys": _env_keys(env),
        }

    return {
        "configured": True,
        "ok": True,
        "status": "ready",
        "profile_id": resolved_id,
        "name": profile.get("name") or resolved_id,
        "cwd": cwd,
        "commands": results,
        "background_processes": process_results,
        "readiness_checks": readiness_results,
        "artifacts": artifact_status,
        "env_keys": _env_keys(env),
    }


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
            status="blocked",
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
