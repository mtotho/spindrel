"""Host-side integration admin lifecycle and settings operations."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import ConflictError, DomainError, NotFoundError, UnprocessableError, ValidationError
from app.services.integration_processes import process_manager

logger = logging.getLogger(__name__)


class GatewayTimeoutError(DomainError):
    http_status = 504


def get_setup_vars(integration_id: str) -> list[dict]:
    """Load the SETUP env_vars list for an integration."""
    from integrations import _get_setup, _iter_integration_candidates

    for candidate, iid, is_external, source in _iter_integration_candidates():
        if iid != integration_id:
            continue
        setup = _get_setup(candidate, iid, is_external, source)
        if not setup:
            return []
        env_vars = list(setup.get("env_vars", []))

        sidebar = setup.get("sidebar_section")
        if sidebar and isinstance(sidebar, dict) and sidebar.get("items"):
            existing_keys = {v["key"] for v in env_vars}
            if "SIDEBAR_ENABLED" not in existing_keys:
                env_vars.append({
                    "key": "SIDEBAR_ENABLED",
                    "required": False,
                    "type": "boolean",
                    "description": "Show this integration's sidebar section in the navigation",
                    "default": "true",
                })

        return env_vars
    return []


def get_api_permissions(integration_id: str) -> str | list[str] | None:
    """Load api_permissions from an integration manifest or setup.py."""
    from integrations import _get_setup, _iter_integration_candidates

    for candidate, iid, is_external, source in _iter_integration_candidates():
        if iid != integration_id:
            continue
        setup = _get_setup(candidate, iid, is_external, source)
        if not setup:
            return None
        return setup.get("api_permissions")
    return None


async def sync_docker_compose_stack(integration_id: str) -> None:
    """Apply this integration's docker_compose stack intent, if declared."""
    from app.services.docker_stacks import stack_service
    from app.services.integration_settings import get_value, is_active
    from integrations import discover_docker_compose_stacks

    for dc_info in discover_docker_compose_stacks():
        if dc_info["integration_id"] != integration_id:
            continue
        try:
            enabled = False
            if is_active(integration_id):
                enabled_callable = dc_info.get("enabled_callable")
                if enabled_callable is not None:
                    try:
                        enabled = bool(enabled_callable())
                    except Exception:
                        logger.exception("enabled_callable failed for %s", integration_id)
                        enabled = False
                elif dc_info["enabled_setting"]:
                    default = dc_info.get("enabled_default", "false")
                    val = get_value(integration_id, dc_info["enabled_setting"], default)
                    enabled = val.lower() in ("true", "1", "yes")
            await stack_service.apply_integration_stack(
                integration_id=integration_id,
                name=dc_info["description"] or integration_id,
                compose_definition=dc_info["compose_definition"],
                project_name=dc_info["project_name"],
                enabled=enabled,
                description=dc_info["description"],
                config_files=dc_info["config_files"],
            )
        except Exception:
            logger.exception("Failed to sync docker stack for %s", integration_id)
        break


async def _load_enabled_integration(integration_id: str) -> int:
    try:
        from app.services.integration_deps import ensure_one_integration_deps

        await ensure_one_integration_deps(integration_id)
    except Exception:
        logger.warning(
            "Dependency install on enable failed for %s; tools may not load",
            integration_id,
            exc_info=True,
        )

    from app.tools.loader import load_integration_tools
    from integrations import _iter_integration_candidates

    loaded: list[str] = []
    for candidate, iid, _is_external, _source in _iter_integration_candidates():
        if iid == integration_id:
            loaded = load_integration_tools(candidate)
            break
    await sync_docker_compose_stack(integration_id)
    return len(loaded)


async def set_integration_status(integration_id: str, status: str) -> dict:
    """Transition an integration between available and enabled."""
    from app.services.integration_settings import get_status, set_status

    target = status.strip().lower()
    if target not in ("available", "enabled"):
        raise ValidationError(f"Invalid status: {status!r}")

    previous = get_status(integration_id)
    if previous == target:
        return {"integration_id": integration_id, "status": target}

    await set_status(integration_id, target)  # type: ignore[arg-type]

    if target == "available":
        await _disable_integration(integration_id)
    else:
        await _enable_integration(integration_id)

    from app.services.mcp_servers import load_mcp_servers
    await load_mcp_servers()
    return {"integration_id": integration_id, "status": target}


async def _disable_integration(integration_id: str) -> None:
    try:
        await process_manager.stop(integration_id)
    except Exception:
        logger.debug("No process to stop for %s", integration_id, exc_info=True)

    from app.agent.tools import remove_integration_embeddings
    from app.tools.registry import unregister_integration_tools

    removed = unregister_integration_tools(integration_id)
    embed_count = await remove_integration_embeddings(integration_id)
    await sync_docker_compose_stack(integration_id)
    _unregister_integration_harness(integration_id)
    logger.info(
        "Integration %s -> available: removed %d tool(s), %d embedding(s)",
        integration_id,
        len(removed),
        embed_count,
    )


async def _enable_integration(integration_id: str) -> None:
    provider_loaded_count = 0
    try:
        from app.services.runtime_services import ensure_required_providers_enabled

        provider_ids = await ensure_required_providers_enabled(integration_id)
        for provider_id in provider_ids:
            provider_loaded_count += await _load_enabled_integration(provider_id)
    except Exception:
        logger.warning(
            "Runtime provider enablement failed for %s",
            integration_id,
            exc_info=True,
        )

    loaded_count = await _load_enabled_integration(integration_id)
    from app.agent.tools import index_local_tools
    await index_local_tools()

    from app.services import file_sync
    await file_sync.sync_all_files()
    try:
        from app.services.agent_harnesses import discover_and_load_harnesses

        discover_and_load_harnesses()
    except Exception:
        logger.debug("Harness discovery on enable failed for %s", integration_id, exc_info=True)
    logger.info(
        "Integration %s -> enabled: loaded %d tool(s), provider tools %d",
        integration_id,
        loaded_count,
        provider_loaded_count,
    )


def _unregister_integration_harness(integration_id: str) -> None:
    try:
        import inspect

        from app.services.agent_harnesses import HARNESS_REGISTRY, unregister_runtime
        from integrations import _iter_integration_candidates

        harness_path = None
        for candidate, iid, _is_external, _source in _iter_integration_candidates():
            if iid == integration_id:
                harness_path = candidate / "harness.py"
                break
        if not harness_path or not harness_path.is_file():
            return

        drop = []
        for runtime_name, runtime in list(HARNESS_REGISTRY.items()):
            try:
                src = inspect.getsourcefile(type(runtime))
            except Exception:
                src = None
            if src and str(harness_path) == src:
                drop.append(runtime_name)
        for runtime_name in drop:
            unregister_runtime(runtime_name)
    except Exception:
        logger.debug("Could not unregister harness for %s", integration_id, exc_info=True)


def get_integration_settings(integration_id: str) -> list[dict]:
    from app.services.integration_settings import get_all_for_integration

    return get_all_for_integration(integration_id, get_setup_vars(integration_id))


async def update_integration_settings(
    integration_id: str,
    updates: dict[str, str],
    db: AsyncSession,
) -> dict:
    from app.services.integration_settings import update_settings

    setup_vars = get_setup_vars(integration_id)
    valid_keys = {v["key"] for v in setup_vars}
    bad_keys = set(updates.keys()) - valid_keys
    if bad_keys:
        raise UnprocessableError(f"Unknown setting keys: {', '.join(sorted(bad_keys))}")

    applied = await update_settings(integration_id, updates, setup_vars, db)
    await _sync_runtime_providers_after_settings_update(integration_id)
    await sync_docker_compose_stack(integration_id)
    await _provision_api_key_if_needed(integration_id, db)
    await _refresh_mcp_after_settings_update()
    return {"applied": applied}


async def _sync_runtime_providers_after_settings_update(integration_id: str) -> None:
    try:
        from app.services.integration_settings import is_active
        from app.services.runtime_services import ensure_required_providers_enabled

        if is_active(integration_id):
            for provider_id in await ensure_required_providers_enabled(integration_id):
                await _load_enabled_integration(provider_id)
    except Exception:
        logger.warning("Runtime provider sync after settings update failed for %s", integration_id, exc_info=True)


async def _provision_api_key_if_needed(integration_id: str, db: AsyncSession) -> None:
    api_permissions = get_api_permissions(integration_id)
    if not api_permissions:
        return

    from app.services.api_keys import get_integration_api_key, provision_integration_api_key, resolve_scopes

    existing = await get_integration_api_key(db, integration_id)
    if existing:
        return
    try:
        scopes = resolve_scopes(api_permissions)
        await provision_integration_api_key(db, integration_id, scopes)
        logger.info("Auto-provisioned API key for integration %s", integration_id)
    except Exception:
        logger.warning("Failed to auto-provision API key for %s", integration_id, exc_info=True)


async def _refresh_mcp_after_settings_update() -> None:
    from app.services.mcp_servers import load_mcp_servers
    from app.tools.mcp import _cache as mcp_tools_cache

    await load_mcp_servers()
    mcp_tools_cache.clear()


def get_process_status(integration_id: str) -> dict:
    return process_manager.status(integration_id)


async def start_process(integration_id: str) -> dict:
    from app.services.integration_settings import get_status, is_configured

    if get_status(integration_id) != "enabled":
        raise ValidationError("Integration is not enabled")
    if not is_configured(integration_id):
        raise ValidationError("Integration is missing required settings")

    ok = await process_manager.start(integration_id)
    if not ok:
        status = process_manager.status(integration_id)
        if status["status"] == "running":
            raise ConflictError("Process is already running")
        missing = _missing_required_process_env(integration_id)
        if missing:
            raise ValidationError(f"Missing required settings: {', '.join(missing)}")
        raise ValidationError("Failed to start process (check server logs)")
    return process_manager.status(integration_id)


def _missing_required_process_env(integration_id: str) -> list[str]:
    state = process_manager._states.get(integration_id)
    if not state or not state.required_env:
        return []
    from app.services.integration_settings import get_value

    return [
        key
        for key in state.required_env
        if not os.environ.get(key) and not get_value(integration_id, key)
    ]


async def stop_process(integration_id: str) -> dict:
    ok = await process_manager.stop(integration_id)
    if not ok:
        raise ValidationError("Process is not running")
    return process_manager.status(integration_id)


async def restart_process(integration_id: str) -> dict:
    ok = await process_manager.restart(integration_id)
    if not ok:
        raise ValidationError("Failed to restart process")
    return process_manager.status(integration_id)


async def set_auto_start(integration_id: str, enabled: bool) -> dict:
    await process_manager.set_auto_start(integration_id, enabled)
    return {"integration_id": integration_id, "auto_start": enabled}


async def get_auto_start(integration_id: str) -> dict:
    enabled = await process_manager.get_auto_start(integration_id)
    return {"integration_id": integration_id, "auto_start": enabled}


def get_process_logs(integration_id: str, *, after: int = 0) -> dict:
    return process_manager.get_recent_logs(integration_id, after=after)


async def install_python_dependencies(integration_id: str) -> dict:
    from integrations import _get_setup, _iter_integration_candidates

    packages: list[str] = []
    req_path: str | None = None
    integration_path = None
    for candidate, iid, is_external, source in _iter_integration_candidates():
        if iid == integration_id:
            integration_path = candidate
            setup = _get_setup(candidate, iid, is_external, source)
            if setup:
                for dep in setup.get("python_dependencies", []):
                    packages.append(dep["package"])
            rp = candidate / "requirements.txt"
            if rp.exists():
                req_path = str(rp)
            break

    if not packages and req_path is None:
        raise NotFoundError(f"No Python dependencies found for integration {integration_id!r}")

    cmd = (
        [sys.executable, "-m", "pip", "install", "-q", "-U", *packages]
        if packages
        else [sys.executable, "-m", "pip", "install", "-q", "-U", "-r", req_path]
    )
    await _run_install_command(cmd, timeout=120, error_prefix="pip install failed")
    logger.info("Installed dependencies for integration %s: %s", integration_id, packages or req_path)
    harness_loaded = _reload_harness_after_dependency_install(integration_id, integration_path)
    return {
        "integration_id": integration_id,
        "installed": True,
        "harness_reloaded": harness_loaded,
        "message": (
            "Dependencies installed. Harness reloaded - ready to use."
            if harness_loaded
            else "Dependencies installed. Restart the server to activate new tools."
        ),
    }


async def install_npm_dependencies(integration_id: str) -> dict:
    from integrations import _get_setup, _iter_integration_candidates

    npm_deps = None
    integration_path = None
    for candidate, iid, is_external, source in _iter_integration_candidates():
        if iid == integration_id:
            integration_path = candidate
            setup = _get_setup(candidate, iid, is_external, source)
            if setup:
                npm_deps = setup.get("npm_dependencies", [])
            break

    if not npm_deps or integration_path is None:
        raise NotFoundError(f"No npm_dependencies found for integration {integration_id!r}")

    local_install_dir = None
    for dep in npm_deps:
        if dep.get("local_install_dir"):
            dep_dir = dep["local_install_dir"]
            if not os.path.isabs(dep_dir):
                dep_dir = os.path.join(str(integration_path), dep_dir)
            local_install_dir = dep_dir
            break

    packages = [dep["package"] for dep in npm_deps]
    if local_install_dir:
        cmd = ["npm", "install", "--no-audit", "--no-fund"]
        cwd = local_install_dir
    else:
        npm_prefix = os.path.expanduser("~/.local")
        cmd = ["npm", "install", "-g", f"--prefix={npm_prefix}", *packages]
        cwd = None

    await _run_install_command(cmd, cwd=cwd, timeout=120, error_prefix="npm install failed")
    logger.info("Installed npm dependencies for integration %s: %s", integration_id, packages)
    return {
        "integration_id": integration_id,
        "installed": True,
        "message": "npm packages installed. Restart the server if needed.",
    }


async def _run_install_command(
    cmd: list[str],
    *,
    cwd: str | None = None,
    timeout: int,
    error_prefix: str,
) -> None:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise GatewayTimeoutError(f"{error_prefix} timed out after {timeout}s") from exc

    if proc.returncode != 0:
        err = (stderr or stdout or b"").decode(errors="replace").strip()
        logger.error("%s: %s", error_prefix, err)
        raise DomainError(f"{error_prefix}: {err[:500]}")


def _reload_harness_after_dependency_install(integration_id: str, integration_path) -> bool:
    if integration_path is None:
        return False
    try:
        from app.services.agent_harnesses import _import_harness_module

        harness_file = integration_path / "harness.py"
        if harness_file.is_file():
            _import_harness_module(harness_file, integration_id)
            return True
    except Exception:
        logger.exception("post-install harness reload failed for %s", integration_id)
    return False


async def install_system_dependency(integration_id: str, apt_package: str) -> dict:
    from app.services.integration_deps import install_system_package

    if not apt_package or not isinstance(apt_package, str):
        raise ValidationError("apt_package is required")
    if not re.match(r"^[a-z0-9][a-z0-9.+\-]+$", apt_package):
        raise ValidationError(f"Invalid package name: {apt_package!r}")

    success = await install_system_package(apt_package)
    if not success:
        raise DomainError(f"Failed to install {apt_package}")

    return {
        "integration_id": integration_id,
        "apt_package": apt_package,
        "installed": True,
        "message": f"System package '{apt_package}' installed successfully.",
    }


async def get_integration_api_key(integration_id: str, db: AsyncSession) -> dict:
    from app.services.api_keys import get_integration_api_key as get_key

    api_key = await get_key(db, integration_id)
    if not api_key:
        return {"provisioned": False}
    return {
        "provisioned": True,
        "key_prefix": api_key.key_prefix,
        "scopes": api_key.scopes,
        "created_at": api_key.created_at.isoformat() if api_key.created_at else None,
        "last_used_at": api_key.last_used_at.isoformat() if api_key.last_used_at else None,
    }


async def provision_or_regenerate_integration_api_key(integration_id: str, db: AsyncSession) -> dict:
    from app.services.api_keys import provision_integration_api_key, resolve_scopes, revoke_integration_api_key

    api_permissions = get_api_permissions(integration_id)
    if not api_permissions:
        raise ValidationError(f"Integration {integration_id!r} does not declare api_permissions")

    scopes = resolve_scopes(api_permissions)
    await revoke_integration_api_key(db, integration_id)
    key, full_value = await provision_integration_api_key(db, integration_id, scopes)
    return {
        "key_prefix": key.key_prefix,
        "key_value": full_value,
        "scopes": key.scopes,
        "created_at": key.created_at.isoformat() if key.created_at else None,
    }


async def revoke_integration_api_key(integration_id: str, db: AsyncSession) -> dict:
    from app.services.api_keys import revoke_integration_api_key as revoke_key

    revoked = await revoke_key(db, integration_id)
    if not revoked:
        raise NotFoundError("No API key found for this integration")
    return {"revoked": True}

