"""Auto-install missing integration dependencies on server startup.

Checks all integration manifests for declared Python, npm, and system
dependencies. Missing Python/npm deps are installed automatically into
the spindrel user's home (persisted via the ``spindrel-home`` volume).

System (apt) deps are installed via ``apt-get download`` + ``dpkg -x``
into ``/opt/spindrel-pkg/`` — a named Docker volume that survives
``spindrel pull`` rebuilds. The entrypoint prepends
``/opt/spindrel-pkg/usr/bin`` to ``PATH`` and
``/opt/spindrel-pkg/usr/lib{,/x86_64-linux-gnu}`` to
``LD_LIBRARY_PATH`` so the extracted binaries + shared libs are
discoverable by ``shutil.which()`` and the dynamic linker just like
normal system-installed packages.

Why not ``apt-get install``: apt writes into /usr/bin and /usr/lib,
which are part of the Docker image layer and are wiped on every
rebuild. Extracting into a volume-backed prefix is what gets us
persistence without baking packages into the image.

Known caveat: ``dpkg -x`` does not run the package's ``postinst``
script. For most CLIs (gh, jq, ripgrep) this is fine — they're a
single static binary. Chromium pulls in ~20 transitive deps,
including pulseaudio whose ``libpulsecommon-*.so`` lives in a
versioned subdir that's normally registered with ``ldconfig`` by
postinst. ``scripts/entrypoint.sh`` runs ``ldconfig`` against
``/opt/spindrel-pkg/usr/lib/x86_64-linux-gnu/*/`` at boot to cover
that gap. Separately, the chromium wrapper at ``…/usr/bin/chromium``
is a shell script with hardcoded ``/usr/`` and ``/etc/`` paths that
break under dpkg-extract; ``integrations.sdk.find_chrome_path``
bypasses the wrapper and returns the underlying ELF binary
(``…/usr/lib/chromium/chromium``) for the spindrel-pkg layout.
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
    from integrations.discovery import iter_integration_candidates

    manifests = get_all_manifests()
    if not manifests:
        return

    # Build a map of integration_id → directory path
    id_to_dir: dict[str, Path] = {}
    for candidate, iid, _is_external, _source in iter_integration_candidates():
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


async def ensure_one_integration_deps(integration_id: str) -> None:
    """Install missing dependencies for a single integration on demand.

    Called from the admin enable handler so freshly added or freshly enabled
    integrations don't have to wait for the next process restart to get
    their npm / pip / apt deps installed.
    """
    from app.services.integration_manifests import get_manifest
    from integrations.discovery import iter_integration_candidates

    manifest = get_manifest(integration_id)
    if not manifest:
        return
    deps = manifest.get("dependencies", {})
    if not isinstance(deps, dict):
        return

    int_dir: Path | None = None
    for candidate, iid, _is_external, _source in iter_integration_candidates():
        if iid == integration_id:
            int_dir = candidate
            break
    if int_dir is None:
        return

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


# Persistent package tree — apt packages are `dpkg -x`'d here so their
# binaries + libs survive container rebuilds. Volume mounted at this path
# via docker-compose.yml. Entrypoint prepends the subpaths to PATH and
# LD_LIBRARY_PATH so binaries installed here are discoverable by
# ``shutil.which()`` (which is what ``_is_system_dep_available`` uses).
_PKG_ROOT = Path(os.environ.get("SPINDREL_PKG_ROOT", "/opt/spindrel-pkg"))


def _package_already_extracted(apt_package: str) -> bool:
    """Does /opt/spindrel-pkg already contain files from this package?

    We check the manifest we persist after each successful extraction
    (``.extracted-manifest/<pkg>.list``) instead of re-probing dpkg state,
    because dpkg itself knows nothing about extracted-only packages.
    """
    manifest = _PKG_ROOT / ".extracted-manifest" / f"{apt_package}.list"
    return manifest.is_file() and manifest.stat().st_size > 0


async def _apt_get_update_if_stale() -> None:
    """Refresh apt lists if the cached metadata is old or missing.

    The lists live on the persistent ``spindrel-apt-archives`` volume
    (mounted at /var/cache/apt/archives). We only run update when no list
    has been fetched in the last 6 hours to avoid re-downloading on every
    install call.
    """
    lists_dir = Path("/var/lib/apt/lists")
    stale = True
    try:
        if lists_dir.is_dir():
            newest = max(
                (p.stat().st_mtime for p in lists_dir.glob("*_Packages*") if p.is_file()),
                default=0,
            )
            if newest and (time.time() - newest) < 6 * 3600:
                stale = False
    except OSError:
        pass
    if not stale:
        return
    proc = await asyncio.create_subprocess_exec(
        *_apt_prefix(), "apt-get", "update", "-qq",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    await asyncio.wait_for(proc.communicate(), timeout=60)


async def _resolve_missing_runtime_deps(apt_package: str) -> list[str]:
    """Return the transitive runtime deps of ``apt_package`` that aren't
    already satisfied by the base image.

    Uses ``apt-cache depends --recurse --no-recommends --no-suggests``
    and filters to real packages whose binaries aren't already on PATH.
    Conservative: if dep resolution fails we return just [apt_package]
    and let the install proceed (single-package extract may still work
    for self-contained tools like ``gh``).
    """
    proc = await asyncio.create_subprocess_exec(
        "apt-cache", "depends",
        "--recurse", "--no-recommends", "--no-suggests",
        "--no-conflicts", "--no-breaks", "--no-replaces", "--no-enhances",
        "--no-pre-depends", apt_package,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, _err = await asyncio.wait_for(proc.communicate(), timeout=30)
    if proc.returncode != 0:
        return [apt_package]

    pkgs: list[str] = []
    for raw in out.decode(errors="replace").splitlines():
        line = raw.strip()
        # apt-cache depends output: package names at column 0, deps indented.
        if not line or line.startswith("|") or line.startswith("<"):
            continue
        if raw.startswith(" "):
            # Dependency entry, e.g. "  Depends: libxrandr2"
            _, _, name = line.partition(": ")
            name = name.strip()
            if name and not name.startswith("<"):
                pkgs.append(name)
        else:
            # Root package line
            pkgs.append(line)

    # Dedupe, preserve order.
    seen: set[str] = set()
    ordered: list[str] = []
    for p in pkgs:
        if p in seen:
            continue
        seen.add(p)
        ordered.append(p)

    # Filter out things already present in the base image. dpkg-query
    # returns 0 for installed packages — those we skip because they're
    # part of python:3.12-slim or our Dockerfile-installed baseline.
    missing: list[str] = []
    for p in ordered:
        check = await asyncio.create_subprocess_exec(
            "dpkg-query", "-W", "-f=${Status}", p,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        status_out, _ = await check.communicate()
        status = status_out.decode(errors="replace").strip()
        if check.returncode == 0 and "install ok installed" in status:
            continue
        missing.append(p)

    return missing


async def _download_deb(apt_package: str) -> Path | None:
    """Download ``apt_package``'s .deb into /var/cache/apt/archives (a
    persistent volume). Returns the path to the resulting .deb, or None."""
    archives = Path("/var/cache/apt/archives")
    archives.mkdir(parents=True, exist_ok=True)
    # apt-get download writes to CWD, not /var/cache/apt/archives — run it
    # there so the .deb ends up on the persistent volume.
    proc = await asyncio.create_subprocess_exec(
        *_apt_prefix(), "apt-get", "download", apt_package,
        cwd=str(archives),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _out, err = await asyncio.wait_for(proc.communicate(), timeout=300)
    if proc.returncode != 0:
        logger.error(
            "apt-get download '%s' failed (exit %d): %s",
            apt_package, proc.returncode,
            (err or b"").decode(errors="replace").strip()[:500],
        )
        return None
    # apt-get download names files as <pkg>_<version>_<arch>.deb.
    candidates = sorted(
        archives.glob(f"{apt_package}_*.deb"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


async def _dpkg_extract(deb_path: Path, apt_package: str) -> tuple[bool, list[str]]:
    """Extract .deb contents into /opt/spindrel-pkg and record the file
    manifest so we know what this package owns for later lookups."""
    _PKG_ROOT.mkdir(parents=True, exist_ok=True)

    # 1. Get the file list so we can persist it before extraction.
    list_proc = await asyncio.create_subprocess_exec(
        "dpkg-deb", "--contents", str(deb_path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    list_out, list_err = await asyncio.wait_for(list_proc.communicate(), timeout=30)
    if list_proc.returncode != 0:
        logger.error(
            "dpkg-deb --contents '%s' failed: %s",
            deb_path.name, (list_err or b"").decode(errors="replace")[:300],
        )
        return False, []

    files: list[str] = []
    for raw in list_out.decode(errors="replace").splitlines():
        # Last column is the path, prefixed with "./" ; skip dirs (trailing /).
        parts = raw.split()
        if not parts:
            continue
        path = parts[-1]
        if path.endswith("/"):
            continue
        files.append(path.lstrip("./"))

    # 2. Extract. dpkg -x runs unprivileged — /opt/spindrel-pkg is
    # chowned to spindrel in the entrypoint. No sudo needed. Also means
    # postinst doesn't run (known tradeoff, see module docstring).
    extract_proc = await asyncio.create_subprocess_exec(
        "dpkg", "-x", str(deb_path), str(_PKG_ROOT),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _out, err = await asyncio.wait_for(extract_proc.communicate(), timeout=300)
    if extract_proc.returncode != 0:
        logger.error(
            "dpkg -x '%s' -> %s failed: %s",
            deb_path.name, _PKG_ROOT,
            (err or b"").decode(errors="replace")[:300],
        )
        return False, []

    # 3. Persist manifest for idempotent skip on future boots.
    manifest_dir = _PKG_ROOT / ".extracted-manifest"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / f"{apt_package}.list").write_text("\n".join(files) + "\n")

    return True, files


async def install_system_package(apt_package: str) -> bool:
    """Install an apt package into /opt/spindrel-pkg so it survives rebuilds.

    Uses ``apt-get download`` + ``dpkg -x`` instead of ``apt-get install`` so
    files land on the persistent ``spindrel-pkg`` volume (mounted at
    /opt/spindrel-pkg) rather than in the container's /usr/* image layer.
    The entrypoint prepends /opt/spindrel-pkg/usr/{bin,lib,...} to PATH and
    LD_LIBRARY_PATH so the binaries and their shared libs are discoverable
    just like normal system-installed packages.

    Returns True on success, False on failure. Idempotent: calling twice
    with the same package is a no-op on the second call.
    """
    t0 = time.monotonic()

    if _package_already_extracted(apt_package):
        logger.info("System package '%s' already extracted — skipping", apt_package)
        # Still re-record in the installed set in case we're recovering
        # from a mangled persistence file.
        installed = _read_installed_system_packages()
        if apt_package not in installed:
            installed.add(apt_package)
            _persist_installed_system_packages(installed)
        return True

    try:
        await _apt_get_update_if_stale()

        # Resolve and fetch + extract the package + any runtime deps the
        # base image doesn't already carry. For most tools (gh, jq, etc.)
        # this is a list of one. For chromium it's ~20 packages.
        pkgs = await _resolve_missing_runtime_deps(apt_package)
        logger.info(
            "Installing system package '%s' (+ %d transitive runtime deps) into %s",
            apt_package, max(0, len(pkgs) - 1), _PKG_ROOT,
        )

        for pkg in pkgs:
            if _package_already_extracted(pkg):
                continue
            deb = await _download_deb(pkg)
            if deb is None:
                logger.error("Could not download .deb for '%s' — aborting '%s'", pkg, apt_package)
                return False
            ok, _files = await _dpkg_extract(deb, pkg)
            if not ok:
                logger.error("dpkg -x failed for '%s' — aborting '%s'", pkg, apt_package)
                return False

        elapsed = time.monotonic() - t0
        logger.info("Installed system package '%s' in %.1fs", apt_package, elapsed)

        installed = _read_installed_system_packages()
        installed.add(apt_package)
        _persist_installed_system_packages(installed)
        return True

    except asyncio.TimeoutError:
        logger.error("install_system_package('%s') timed out", apt_package)
        return False
    except Exception:
        logger.exception("Failed to install system package '%s'", apt_package)
        return False
