"""R2 Phase 1 — run_script egress guard.

Pins the Python-level egress allowlist injected via ``sitecustomize.py`` next
to ``script.py`` / ``spindrel.py`` in the run_script scratch dir. The guard
patches ``socket.socket.connect`` so the bot's script can only reach the
spindrel server (``AGENT_SERVER_URL``); all other outbound destinations are
logged (``audit`` mode) or refused (``enforce`` mode).

Bypasses NOT covered by Phase 1 — Phase 2 (OS-level netns) closes them:
- subprocess to a native binary (curl / wget) that opens its own sockets
- ``ctypes`` raw syscalls
- Filesystem-level data exfil through synced workspace dirs
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app.services.script_runner import (
    EGRESS_GUARD_FILENAME,
    _egress_guard_source,
    write_script_files,
)


# ---------------------------------------------------------------------------
# write_script_files emits the guard alongside script.py + spindrel.py
# ---------------------------------------------------------------------------


def test_write_script_files_drops_sitecustomize(tmp_path: Path) -> None:
    script_path, helper_path = write_script_files(tmp_path, "print('hi')")
    guard = tmp_path / EGRESS_GUARD_FILENAME
    assert guard.exists()
    assert guard.name == "sitecustomize.py"
    body = guard.read_text(encoding="utf-8")
    assert "SPINDREL_SCRIPT_EGRESS_MODE" in body
    assert "socket.socket.connect" in body
    assert "AGENT_SERVER_URL" in body


def test_egress_guard_source_compiles() -> None:
    """The injected sitecustomize must be syntactically valid Python."""
    src = _egress_guard_source()
    compile(src, "<sitecustomize>", "exec")


# ---------------------------------------------------------------------------
# End-to-end: run a real subprocess with the guard installed and verify it
# blocks/audits/permits as configured. These exercise the actual Python
# import-of-sitecustomize path, not a mock.
# ---------------------------------------------------------------------------


def _run_with_guard(
    tmp_path: Path,
    user_script: str,
    *,
    mode: str,
    server_url: str = "http://127.0.0.1:8000",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    write_script_files(tmp_path, user_script)
    env = {
        **os.environ,
        "SPINDREL_SCRIPT_EGRESS_MODE": mode,
        "AGENT_SERVER_URL": server_url,
        **(extra_env or {}),
    }
    return subprocess.run(
        [sys.executable, "script.py"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_enforce_blocks_disallowed_destination(tmp_path: Path) -> None:
    """An attempt to connect to a non-allowlisted host must raise PermissionError."""
    user_script = textwrap.dedent('''
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect(("198.51.100.7", 9999))  # TEST-NET-2 — never reachable
            print("NOT_BLOCKED")
        except PermissionError as e:
            print("BLOCKED")
        except OSError:
            # If the guard didn't fire, the connect itself fails — that's
            # not what we want to assert here.
            print("OS_ERROR_NOT_BLOCKED")
    ''')
    res = _run_with_guard(tmp_path, user_script, mode="enforce")
    assert res.returncode == 0, res.stderr
    assert "BLOCKED" in res.stdout
    assert "spindrel-egress: blocked" in res.stderr


def test_enforce_permits_allowlisted_server(tmp_path: Path) -> None:
    """A connect to the AGENT_SERVER_URL host:port must pass the guard
    (the connect itself may still fail because nothing is listening — we
    only care that the guard doesn't fire)."""
    user_script = textwrap.dedent('''
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            s.connect(("127.0.0.1", 8000))
            print("CONNECTED")
        except PermissionError:
            print("BLOCKED_BY_GUARD")
        except OSError:
            print("OS_ERROR_OK")  # connect refused / timeout — guard didn't fire
    ''')
    res = _run_with_guard(
        tmp_path, user_script, mode="enforce",
        server_url="http://127.0.0.1:8000",
    )
    assert res.returncode == 0, res.stderr
    assert "BLOCKED_BY_GUARD" not in res.stdout
    assert "spindrel-egress: blocked" not in res.stderr


def test_audit_logs_but_does_not_block(tmp_path: Path) -> None:
    """In audit mode the guard logs to stderr but does NOT raise."""
    user_script = textwrap.dedent('''
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        try:
            s.connect(("198.51.100.7", 9999))
        except (PermissionError, OSError) as e:
            # OS-level failure is fine; guard must NOT have raised PermissionError.
            print("RAISED:" + type(e).__name__)
        else:
            print("NO_RAISE")
    ''')
    res = _run_with_guard(tmp_path, user_script, mode="audit")
    assert res.returncode == 0, res.stderr
    assert "PermissionError" not in res.stdout
    assert "spindrel-egress: blocked" in res.stderr


def test_off_mode_does_not_install_guard(tmp_path: Path) -> None:
    """``mode=off`` must leave socket.connect untouched — no log, no block."""
    user_script = textwrap.dedent('''
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        try:
            s.connect(("198.51.100.7", 9999))
        except OSError:
            pass
        print("DONE")
    ''')
    res = _run_with_guard(tmp_path, user_script, mode="off")
    assert res.returncode == 0, res.stderr
    assert "spindrel-egress" not in res.stderr


def test_enforce_blocks_urllib_to_disallowed_host(tmp_path: Path) -> None:
    """Defense-in-depth: urllib.request goes through socket underneath, so
    the guard catches it even though the user never imports socket."""
    user_script = textwrap.dedent('''
        import urllib.request
        try:
            urllib.request.urlopen("http://198.51.100.7:9999/", timeout=2)
            print("NOT_BLOCKED")
        except PermissionError:
            print("BLOCKED_BY_GUARD")
        except Exception as e:
            print("OTHER:" + type(e).__name__)
    ''')
    res = _run_with_guard(tmp_path, user_script, mode="enforce")
    assert res.returncode == 0, res.stderr
    # urllib wraps PermissionError in URLError — accept either signal as long
    # as the guard fired (stderr line) and the connect did not succeed.
    assert "NOT_BLOCKED" not in res.stdout
    assert "spindrel-egress: blocked" in res.stderr


def test_unix_socket_passes_through(tmp_path: Path) -> None:
    """AF_UNIX sockets are never INET — guard must not interfere."""
    user_script = textwrap.dedent('''
        import socket
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.connect("/tmp/this-does-not-exist-spindrel-test.sock")
            print("CONNECTED")
        except PermissionError:
            print("GUARD_BLOCKED")
        except OSError:
            print("OS_OK")  # ENOENT — guard did not fire
    ''')
    res = _run_with_guard(tmp_path, user_script, mode="enforce")
    assert res.returncode == 0, res.stderr
    assert "GUARD_BLOCKED" not in res.stdout


# ---------------------------------------------------------------------------
# Config wiring — settings.SCRIPT_EGRESS_MODE flows through to the env var
# ---------------------------------------------------------------------------


def test_config_default_is_audit() -> None:
    """Default mode is ``audit`` — log violations, don't break existing scripts."""
    from app.config import settings

    assert settings.SCRIPT_EGRESS_MODE == "audit"
