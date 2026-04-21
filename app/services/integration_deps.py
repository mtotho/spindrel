"""Auto-install missing integration dependencies on server startup.

Checks all integration manifests for declared Python, npm, and system
dependencies.  Missing Python/npm deps are installed automatically.
System deps are installed via apt-get and the package list is persisted
to the workspace volume so they survive Docker rebuilds.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Persistent file tracking apt-installed system packages.
# Lives on the workspace volume so it survives Docker rebuilds.
_SYSTEM_DEPS_FILE = Path(os.environ.get("WORKSPACE_DATA_DIR", "/workspace-data")) / ".installed-system-deps.json"


def _read_installed_system_packages() -> set[str]:
    """Read the set of previously apt-installed package names."""
    try:
        if _SYSTEM_DEPS_FILE.exists():
            return set(json.loads(_SYSTEM_DEPS_FILE.read_text()))
    except Exception:
        logger.debug("Could not read %s", _SYSTEM_DEPS_FILE, exc_info=True)
    return set()


def _persist_installed_system_packages(packages: set[str]) -> None:
    """Write the set of apt-installed package names to the workspace volume."""
    try:
        _SYSTEM_DEPS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SYSTEM_DEPS_FILE.write_text(json.dumps(sorted(packages)))
    except Exception:
        logger.warning("Could not persist system deps to %s", _SYSTEM_DEPS_FILE, exc_info=True)


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
        await _check_system_deps(integration_id, deps.get("system", []))


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

    t0 = time.monotonic()
    logger.info(
        "Auto-installing Python dependencies for '%s': %s",
        integration_id,
        ", ".join(missing),
    )

    # Always install the specific missing packages from the YAML declaration.
    # requirements.txt may be incomplete (e.g. wyoming had 2 of 3 packages).
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


def _is_system_dep_available(dep: dict) -> bool:
    """Check if a system dependency binary is available."""
    binary = dep.get("binary", "")
    alternatives = dep.get("alternatives", [])
    for candidate in [binary, *alternatives]:
        if candidate and shutil.which(candidate):
            return True
    return False


async def _check_system_deps(integration_id: str, system_deps: list[dict]) -> None:
    """Re-install previously-installed system packages if missing after rebuild."""
    if not system_deps:
        return

    previously_installed = _read_installed_system_packages()

    for dep in system_deps:
        binary = dep.get("binary")
        if not binary:
            continue

        if _is_system_dep_available(dep):
            continue

        # Check if we previously installed this — if so, re-install automatically
        apt_package = dep.get("apt_package", binary)
        if apt_package in previously_installed:
            logger.info(
                "Re-installing system dependency '%s' for '%s' (lost after rebuild)",
                apt_package,
                integration_id,
            )
            success = await install_system_package(apt_package)
            if not success:
                logger.error(
                    "Failed to re-install system dependency '%s' for '%s'",
                    apt_package,
                    integration_id,
                )
        else:
            hint = dep.get("install_hint", f"Use the Install button in the admin UI")
            logger.warning(
                "System dependency '%s' not found for integration '%s' — %s",
                binary,
                integration_id,
                hint,
            )


def _apt_prefix() -> list[str]:
    # Production runs as the non-root `spindrel` user; a narrow sudoers rule
    # (Dockerfile: /etc/sudoers.d/spindrel-apt) allows passwordless apt-get.
    # When already root (e.g. local shell), skip sudo so this still works
    # outside the container.
    if os.geteuid() == 0:
        return []
    return ["sudo", "-n"]


async def install_system_package(apt_package: str) -> bool:
    """Install a system package via apt-get and persist to the workspace volume.

    Returns True on success, False on failure.
    """
    t0 = time.monotonic()
    prefix = _apt_prefix()
    try:
        # apt-get update first (package lists may be cleared in slim images)
        update_proc = await asyncio.create_subprocess_exec(
            *prefix, "apt-get", "update", "-qq",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(update_proc.communicate(), timeout=60)

        proc = await asyncio.create_subprocess_exec(
            *prefix, "apt-get", "install", "-y", "-qq", "--no-install-recommends", apt_package,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

        if proc.returncode != 0:
            err = (stderr or b"").decode(errors="replace").strip()
            logger.error("apt-get install '%s' failed (exit %d): %s", apt_package, proc.returncode, err[:500])
            return False

        elapsed = time.monotonic() - t0
        logger.info("Installed system package '%s' in %.1fs", apt_package, elapsed)

        # Persist so it gets re-installed after future rebuilds
        installed = _read_installed_system_packages()
        installed.add(apt_package)
        _persist_installed_system_packages(installed)

        return True

    except asyncio.TimeoutError:
        logger.error("apt-get install '%s' timed out", apt_package)
        return False
    except Exception:
        logger.exception("Failed to install system package '%s'", apt_package)
        return False
