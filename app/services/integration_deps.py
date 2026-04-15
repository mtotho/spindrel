"""Auto-install missing integration dependencies on server startup.

Checks all integration manifests for declared Python, npm, and system
dependencies.  Missing Python/npm deps are installed automatically;
missing system deps produce a warning log.
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import os
import shutil
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)


async def ensure_integration_deps() -> None:
    """Install missing dependencies for all discovered integrations."""
    from app.services.integration_manifests import get_all_manifests
    from integrations import _iter_integration_candidates

    manifests = get_all_manifests()
    if not manifests:
        return

    # Build a map of integration_id → directory path
    id_to_dir: dict[str, Path] = {}
    for candidate, iid, _is_external, _source in _iter_integration_candidates():
        id_to_dir[iid] = candidate

    for integration_id, manifest in manifests.items():
        deps = manifest.get("dependencies", {})
        if not isinstance(deps, dict):
            continue

        int_dir = id_to_dir.get(integration_id)
        if not int_dir:
            continue

        await _check_python_deps(integration_id, deps.get("python", []), int_dir)
        await _check_npm_deps(integration_id, deps.get("npm", []), int_dir)
        _check_system_deps(integration_id, deps.get("system", []))


async def _check_python_deps(
    integration_id: str,
    py_deps: list[dict],
    int_dir: Path,
) -> None:
    """Install missing Python packages via pip."""
    if not py_deps:
        return

    missing = []
    for dep in py_deps:
        import_name = dep.get("import_name", dep.get("package", "").replace("-", "_"))
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(dep["package"])

    if not missing:
        return

    # Prefer requirements.txt if it exists, otherwise install packages directly
    req_path = int_dir / "requirements.txt"
    t0 = time.monotonic()
    logger.info(
        "Auto-installing Python dependencies for '%s': %s",
        integration_id,
        ", ".join(missing),
    )

    if req_path.exists():
        cmd = [sys.executable, "-m", "pip", "install", "-q", "-r", str(req_path)]
    else:
        cmd = [sys.executable, "-m", "pip", "install", "-q", *missing]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            err = (stderr or b"").decode(errors="replace").strip()
            logger.error(
                "pip install failed for '%s' (exit %d): %s",
                integration_id,
                proc.returncode,
                err[:500],
            )
        else:
            elapsed = time.monotonic() - t0
            logger.info(
                "Auto-installed Python deps for '%s' in %.1fs",
                integration_id,
                elapsed,
            )
    except asyncio.TimeoutError:
        logger.error("pip install timed out for '%s'", integration_id)
    except Exception:
        logger.exception("Failed to auto-install Python deps for '%s'", integration_id)


async def _check_npm_deps(
    integration_id: str,
    npm_deps: list[dict],
    int_dir: Path,
) -> None:
    """Install missing npm packages."""
    if not npm_deps:
        return

    npm_bin = os.path.expanduser("~/.local/bin")

    for dep in npm_deps:
        # Check if already installed
        check_path = dep.get("check_path")
        if check_path:
            if not os.path.isabs(check_path):
                check_path = os.path.join(str(int_dir), check_path)
            if os.path.exists(check_path):
                continue
        else:
            binary = dep.get("binary_name", dep["package"])
            if shutil.which(binary) or os.path.isfile(os.path.join(npm_bin, binary)):
                continue

        # Missing — install
        local_install_dir = dep.get("local_install_dir")
        t0 = time.monotonic()
        logger.info(
            "Auto-installing npm dependencies for '%s': %s",
            integration_id,
            dep["package"],
        )

        try:
            if local_install_dir:
                cwd = local_install_dir
                if not os.path.isabs(cwd):
                    cwd = os.path.join(str(int_dir), cwd)
                proc = await asyncio.create_subprocess_exec(
                    "npm", "install", "--no-audit", "--no-fund",
                    cwd=cwd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            else:
                npm_prefix = os.path.expanduser("~/.local")
                packages = [dep["package"]]
                proc = await asyncio.create_subprocess_exec(
                    "npm", "install", "-g", f"--prefix={npm_prefix}", *packages,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

            _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode != 0:
                err = (stderr or b"").decode(errors="replace").strip()
                logger.error(
                    "npm install failed for '%s' (exit %d): %s",
                    integration_id,
                    proc.returncode,
                    err[:500],
                )
            else:
                elapsed = time.monotonic() - t0
                logger.info(
                    "Auto-installed npm deps for '%s' in %.1fs",
                    integration_id,
                    elapsed,
                )
        except asyncio.TimeoutError:
            logger.error("npm install timed out for '%s'", integration_id)
        except Exception:
            logger.exception("Failed to auto-install npm deps for '%s'", integration_id)


def _check_system_deps(integration_id: str, system_deps: list[dict]) -> None:
    """Check system dependencies and log warnings for missing ones."""
    if not system_deps:
        return

    for dep in system_deps:
        binary = dep.get("binary")
        if not binary:
            continue

        # Check the primary binary and alternatives
        alternatives = dep.get("alternatives", [])
        found = False
        for candidate in [binary, *alternatives]:
            if shutil.which(candidate):
                found = True
                break

        if not found:
            hint = dep.get("install_hint", f"Install '{binary}' in the Dockerfile")
            logger.warning(
                "System dependency '%s' not found for integration '%s' — %s",
                binary,
                integration_id,
                hint,
            )
