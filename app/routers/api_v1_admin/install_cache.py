"""Persistent install-cache inspection + reset — /admin/install-cache.

Two named Docker volumes persist across `spindrel pull` rebuilds so
integration dependencies (chromium via apt, npm-global binaries like the
claude CLI, pip caches, playwright browsers) don't get wiped on every
container rebuild:

- ``/home/spindrel``          — user-home writes: ``.local/bin``, ``.cache/pip``,
                                ``.cache/ms-playwright``, ``.npm``, ``.claude``,
                                and any ad-hoc files agents install into home.
- ``/var/cache/apt/archives`` — downloaded ``.deb`` files. Apt binaries in
                                ``/usr/bin`` still vanish on rebuild; the
                                existing ``integration_deps`` reinstall loop
                                then pulls from this cache instead of the
                                network (typically 5–10× faster).

This router exposes a GET for sizes and a POST to wipe the caches when
something gets wedged (stale package, corrupted cache).
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies import require_scopes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/install-cache", tags=["Install Cache"])

HOME_PATH = Path("/home/spindrel")
APT_PATH = Path("/var/cache/apt/archives")


class InstallCacheStats(BaseModel):
    home_path: str
    home_bytes: int
    home_exists: bool
    apt_path: str
    apt_bytes: int
    apt_exists: bool


class ClearRequest(BaseModel):
    target: Literal["home", "apt", "all"] = "all"


class ClearResult(BaseModel):
    cleared: list[str]
    freed_bytes: int
    errors: list[str]


def _dir_size(path: Path) -> int:
    total = 0
    try:
        for dirpath, _dirnames, filenames in os.walk(path, followlinks=False):
            for name in filenames:
                try:
                    total += os.lstat(os.path.join(dirpath, name)).st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


@router.get("", response_model=InstallCacheStats)
async def install_cache_stats(_auth=Depends(require_scopes("admin"))):
    """Report on-disk size of both install-cache volumes."""
    return InstallCacheStats(
        home_path=str(HOME_PATH),
        home_bytes=_dir_size(HOME_PATH) if HOME_PATH.exists() else 0,
        home_exists=HOME_PATH.exists(),
        apt_path=str(APT_PATH),
        apt_bytes=_dir_size(APT_PATH) if APT_PATH.exists() else 0,
        apt_exists=APT_PATH.exists(),
    )


def _clear_home() -> tuple[int, list[str]]:
    """Wipe contents of /home/spindrel but not the directory itself.

    Runs as the spindrel user (we *are* spindrel in the container), so
    no sudo needed — everything here is owned by us.
    """
    errors: list[str] = []
    freed = 0
    if not HOME_PATH.exists():
        return 0, errors

    for entry in HOME_PATH.iterdir():
        try:
            if entry.is_symlink() or entry.is_file():
                try:
                    freed += entry.stat().st_size
                except OSError:
                    pass
                entry.unlink()
            elif entry.is_dir():
                freed += _dir_size(entry)
                shutil.rmtree(entry)
        except OSError as e:
            errors.append(f"{entry}: {e}")

    # Recreate the skeleton so the next install doesn't have to.
    for sub in (".local/bin", ".cache", ".npm", ".config"):
        try:
            (HOME_PATH / sub).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            errors.append(f"mkdir {sub}: {e}")

    return freed, errors


async def _clear_apt() -> tuple[int, list[str]]:
    """Run `sudo apt-get clean` to wipe /var/cache/apt/archives.

    The Dockerfile grants spindrel passwordless sudo specifically for
    apt-get; `apt-get clean` removes archives but leaves the directory
    structure (including `partial/` and the lock file) intact.
    """
    errors: list[str] = []
    freed_before = _dir_size(APT_PATH) if APT_PATH.exists() else 0

    prefix: list[str] = [] if os.geteuid() == 0 else ["sudo", "-n"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *prefix, "apt-get", "clean",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _out, err = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode != 0:
            errors.append(
                f"apt-get clean exit {proc.returncode}: "
                f"{(err or b'').decode(errors='replace').strip()[:500]}"
            )
    except asyncio.TimeoutError:
        errors.append("apt-get clean timed out")
    except Exception as e:  # pragma: no cover — subprocess failures
        errors.append(f"apt-get clean failed: {e}")

    freed_after = _dir_size(APT_PATH) if APT_PATH.exists() else 0
    return max(0, freed_before - freed_after), errors


@router.post("/clear", response_model=ClearResult)
async def install_cache_clear(
    body: ClearRequest | None = None,
    _auth=Depends(require_scopes("admin")),
):
    """Wipe one or both install caches in-place.

    Never removes the mount points themselves (that would break the
    volumes until container restart).
    """
    target = (body or ClearRequest()).target
    cleared: list[str] = []
    freed_total = 0
    errors: list[str] = []

    if target in ("home", "all"):
        logger.info("install-cache clear: wiping /home/spindrel")
        # Offload sync file ops to a thread so we don't block the event loop.
        freed, errs = await asyncio.to_thread(_clear_home)
        freed_total += freed
        errors.extend(errs)
        cleared.append("home")

    if target in ("apt", "all"):
        logger.info("install-cache clear: running apt-get clean")
        freed, errs = await _clear_apt()
        freed_total += freed
        errors.extend(errs)
        cleared.append("apt")

    if not cleared:
        raise HTTPException(status_code=400, detail=f"Unknown target: {target}")

    return ClearResult(cleared=cleared, freed_bytes=freed_total, errors=errors)
