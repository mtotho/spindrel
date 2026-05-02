"""Build the temp dir and helper module that run_script executes.

The helper (``spindrel.py``) exposes a single ``tools`` object whose attribute
access proxies to ``POST /api/v1/internal/tools/exec`` against the agent
server. ``AGENT_SERVER_URL`` and ``AGENT_SERVER_API_KEY`` (the per-bot scoped
key) are already injected into every workspace exec by
``app/services/shared_workspace.py:230-233`` — the helper just reads them.

We deliberately do NOT pre-generate per-tool stub functions: the model already
sees signatures via ``list_tool_signatures`` / ``get_tool_info`` in its turn
context, the helper would have to be regenerated every time the registry
changes, and ``__getattr__`` proxying makes any tool callable as
``tools.tool_name(**kwargs)`` with no codegen.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import textwrap
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# Scratch root inside the bot's workspace. Lives under the workspace mount so
# the script can read sibling files (knowledge-base, attachments) if it needs
# to. Per-run UUID dir keeps concurrent script calls isolated.
SCRATCH_PARENT = ".run_script"

HELPER_FILENAME = "spindrel.py"
SCRIPT_FILENAME = "script.py"
EGRESS_GUARD_FILENAME = "sitecustomize.py"


def _helper_source() -> str:
    """Return the source of the spindrel.py helper module.

    The helper speaks HTTP to the agent server. In R2 Phase 2 the script
    subprocess runs inside an empty network namespace, so TCP loopback to the
    agent server is unreachable. When ``SPINDREL_SERVER_UDS`` is set in env,
    the helper switches to a unix-socket transport (the parent process serves
    a UDS-to-TCP bridge at that path); otherwise it falls back to the legacy
    TCP path via ``AGENT_SERVER_URL``.
    """
    return textwrap.dedent('''\
        """Spindrel programmatic-tool-call helper.

        Usage:
            from spindrel import tools
            result = tools.list_pipelines(source="user")
            for p in result["pipelines"]:
                print(p["title"])

        ``tools.NAME(**kwargs)`` POSTs to /api/v1/internal/tools/exec with the
        per-bot scoped API key already in this environment. Auth, policy, and
        tier checks all run on the server side — same gate the LLM-driven
        tool calls go through.
        """
        from __future__ import annotations
        import http.client
        import json
        import os
        import socket
        import urllib.request
        import urllib.error

        AGENT_SERVER_URL = os.environ.get("AGENT_SERVER_URL", "http://localhost:8000").rstrip("/")
        AGENT_SERVER_API_KEY = os.environ.get("AGENT_SERVER_API_KEY", "")
        PARENT_CORRELATION_ID = os.environ.get("SPINDREL_PARENT_CORRELATION_ID")
        CHANNEL_ID = os.environ.get("SPINDREL_CHANNEL_ID")
        DEFAULT_TIMEOUT = float(os.environ.get("SPINDREL_TOOL_TIMEOUT", "30"))
        # R2 Phase 2: when set, talk to the agent server over a UDS bridge
        # (path crosses the netns boundary; parent process forwards to TCP).
        SERVER_UDS = os.environ.get("SPINDREL_SERVER_UDS", "")


        class ToolError(RuntimeError):
            """Raised when a tool call hits a non-200 status (deny, approval-required, 5xx)."""

            def __init__(self, status: int, detail):
                self.status = status
                self.detail = detail
                super().__init__(f"[{status}] {detail}")


        class _UDSConnection(http.client.HTTPConnection):
            """HTTPConnection that targets a unix-domain socket path.

            host/port are placeholders — host header stays "localhost" so the
            FastAPI router matches the same as the TCP listener.
            """

            def __init__(self, uds_path: str, timeout: float):
                super().__init__("localhost", timeout=timeout)
                self._uds_path = uds_path

            def connect(self):  # type: ignore[override]
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.settimeout(self.timeout)
                self.sock.connect(self._uds_path)


        class _ToolsProxy:
            def __getattr__(self, name: str):
                if name.startswith("_"):
                    raise AttributeError(name)
                def _call(**kwargs):
                    return self.call(name, **kwargs)
                _call.__name__ = name
                return _call

            def call(self, name: str, **kwargs):
                """Invoke a tool by name. Returns the parsed JSON result.

                Raises ToolError on policy deny (403), approval-required (409),
                unknown tool (404), or any 5xx. The result is the same dict
                shape the LLM sees — top-level ``error`` keys surface as
                ToolError too so scripts can ``try/except`` instead of
                inspecting the body.

                Need catalog? Call the ``list_tool_signatures`` tool through
                this same proxy — there is no separate signatures endpoint.
                """
                body = json.dumps({
                    "name": name,
                    "arguments": kwargs,
                    "parent_correlation_id": PARENT_CORRELATION_ID,
                    "channel_id": CHANNEL_ID,
                }).encode("utf-8")
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {AGENT_SERVER_API_KEY}",
                }
                if SERVER_UDS:
                    return self._call_uds(body, headers)
                return self._call_tcp(body, headers)

            def _call_tcp(self, body, headers):
                req = urllib.request.Request(
                    f"{AGENT_SERVER_URL}/api/v1/internal/tools/exec",
                    data=body, headers=headers, method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
                        payload = json.loads(resp.read().decode("utf-8"))
                except urllib.error.HTTPError as e:
                    try:
                        detail = json.loads(e.read().decode("utf-8"))
                    except Exception:
                        detail = e.reason
                    raise ToolError(e.code, detail)
                except urllib.error.URLError as e:
                    raise ToolError(0, f"Network error reaching agent server: {e}")
                return self._handle_payload(payload)

            def _call_uds(self, body, headers):
                conn = _UDSConnection(SERVER_UDS, DEFAULT_TIMEOUT)
                try:
                    conn.request("POST", "/api/v1/internal/tools/exec", body=body, headers=headers)
                    resp = conn.getresponse()
                    raw = resp.read()
                    if 200 <= resp.status < 300:
                        payload = json.loads(raw.decode("utf-8"))
                        return self._handle_payload(payload)
                    try:
                        detail = json.loads(raw.decode("utf-8"))
                    except Exception:
                        detail = resp.reason
                    raise ToolError(resp.status, detail)
                except (OSError, ConnectionError) as e:
                    raise ToolError(0, f"Network error reaching agent server (uds): {e}")
                finally:
                    conn.close()

            def _handle_payload(self, payload):
                if not payload.get("ok"):
                    raise ToolError(200, payload.get("error") or payload.get("result"))
                return payload.get("result")


        tools = _ToolsProxy()
    ''')


def _egress_guard_source() -> str:
    """Return the source of the ``sitecustomize.py`` egress guard.

    Python imports ``sitecustomize`` from sys.path at startup (before any user
    code runs). When running ``python script.py`` with cwd set to the scratch
    dir, the scratch dir is sys.path[0], so this file gets imported automatically.

    The guard patches ``socket.socket.connect`` (the chokepoint underneath
    urllib / requests / http.client / asyncio) and only allows connections to
    the spindrel server (``AGENT_SERVER_URL``). Mode is read from
    ``SPINDREL_SCRIPT_EGRESS_MODE`` env: ``off`` / ``audit`` (default) / ``enforce``.

    Bypasses NOT covered (Phase 2 = OS-level netns):
      - Subprocess to a native binary that opens its own sockets
      - ``ctypes`` raw syscalls
      - Filesystem-level data exfil through synced workspace dirs
    """
    return textwrap.dedent('''\
        """Spindrel egress guard. Auto-imported via sitecustomize."""
        from __future__ import annotations
        import os
        import socket
        import sys
        import urllib.parse

        _MODE = os.environ.get("SPINDREL_SCRIPT_EGRESS_MODE", "audit").lower()

        if _MODE in ("audit", "enforce"):
            _allowed: set = set()
            _server = os.environ.get("AGENT_SERVER_URL", "")
            if _server:
                _parsed = urllib.parse.urlparse(_server)
                _host = (_parsed.hostname or "").lower()
                _port = _parsed.port or (443 if _parsed.scheme == "https" else 80)
                if _host:
                    _allowed.add((_host, _port))
                    # Loopback hostname forms — collapse them all together.
                    if _host in ("localhost", "127.0.0.1", "::1"):
                        _allowed.add(("127.0.0.1", _port))
                        _allowed.add(("::1", _port))
                        _allowed.add(("localhost", _port))
                    else:
                        # Pre-resolve so connections by IP literal still match.
                        try:
                            for info in socket.getaddrinfo(_host, _port, proto=socket.IPPROTO_TCP):
                                ip = info[4][0]
                                _allowed.add((ip.lower(), _port))
                        except Exception:
                            pass

            _orig_connect = socket.socket.connect

            def _addr_allowed(address) -> bool:
                if not isinstance(address, tuple) or len(address) < 2:
                    # AF_UNIX / AF_BLUETOOTH etc. — Phase 1 only guards INET; allow.
                    return True
                host = str(address[0]).lower()
                try:
                    port = int(address[1])
                except (TypeError, ValueError):
                    return False
                for ah, ap in _allowed:
                    if host == ah and port == ap:
                        return True
                return False

            def _guarded_connect(self, address):
                family = getattr(self, "family", None)
                if family in (socket.AF_INET, socket.AF_INET6) and not _addr_allowed(address):
                    msg = (
                        f"spindrel-egress: blocked connect to {address!r} "
                        f"(allowlist={sorted(_allowed)!r}, mode={_MODE})"
                    )
                    sys.stderr.write(msg + "\\n")
                    if _MODE == "enforce":
                        raise PermissionError(msg)
                return _orig_connect(self, address)

            socket.socket.connect = _guarded_connect  # type: ignore[assignment]
    ''')


def prepare_scratch_dir(workspace_root: str, parent_correlation_id: str | None) -> Path:
    """Create a per-run scratch dir under ``<workspace_root>/.run_script/<uuid>/``.

    Returns the dir path. Caller writes ``script.py`` and ``spindrel.py`` into
    it, then runs ``python script.py`` with cwd set to the dir.
    """
    base = Path(workspace_root) / SCRATCH_PARENT
    base.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex[:12]
    if parent_correlation_id:
        # Tag the dir with the correlation id prefix so trace inspection can
        # match a script call to its scratch dir.
        run_id = f"{parent_correlation_id[:8]}-{run_id}"
    scratch = base / run_id
    scratch.mkdir(parents=True, exist_ok=True)
    return scratch


def write_script_files(scratch_dir: Path, user_script: str) -> tuple[Path, Path]:
    """Write the user's script + the helper module into ``scratch_dir``.

    Also drops a ``sitecustomize.py`` next to them — Python auto-imports it at
    startup from sys.path[0] (the scratch dir) and it installs a socket-level
    egress allowlist so the bot's script can only reach the spindrel server.

    Returns ``(script_path, helper_path)``.
    """
    helper_path = scratch_dir / HELPER_FILENAME
    helper_path.write_text(_helper_source(), encoding="utf-8")

    guard_path = scratch_dir / EGRESS_GUARD_FILENAME
    guard_path.write_text(_egress_guard_source(), encoding="utf-8")

    script_path = scratch_dir / SCRIPT_FILENAME
    script_path.write_text(user_script, encoding="utf-8")
    return script_path, helper_path


def cleanup_scratch_dir(scratch_dir: Path) -> None:
    """Best-effort removal of the scratch dir. Swallows errors — the dir lives
    under the workspace and stale entries are harmless.
    """
    try:
        shutil.rmtree(scratch_dir, ignore_errors=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# R2 Phase 2 — OS-level netns sandbox helpers
# ---------------------------------------------------------------------------

# Cached probe result. None = not probed yet, (ok, reason) once probed.
_NETNS_PROBE_RESULT: tuple[bool, str] | None = None


def probe_netns_sandbox(force: bool = False) -> tuple[bool, str]:
    """Probe whether ``unshare --user --map-root-user --net`` works for the
    calling UID. Returns ``(ok, reason)``; cached after first call.

    A successful probe means the kernel and any active seccomp/AppArmor
    profile permit unprivileged user-namespace + network-namespace creation.
    Failure is fatal *only* in ``SCRIPT_NETNS_SANDBOX=on`` mode; in ``auto``
    we fall back to Phase 1 only with the audit signal flagging the gap.
    """
    global _NETNS_PROBE_RESULT
    if _NETNS_PROBE_RESULT is not None and not force:
        return _NETNS_PROBE_RESULT
    if shutil.which("unshare") is None:
        _NETNS_PROBE_RESULT = (False, "unshare binary not found on PATH")
        return _NETNS_PROBE_RESULT
    try:
        proc = subprocess.run(
            ["unshare", "--user", "--map-root-user", "--net", "--", "/bin/true"],
            capture_output=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _NETNS_PROBE_RESULT = (False, f"probe raised: {exc}")
        return _NETNS_PROBE_RESULT
    if proc.returncode == 0:
        _NETNS_PROBE_RESULT = (True, "ok")
        return _NETNS_PROBE_RESULT
    stderr = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
    detail = stderr[-1] if stderr else f"exit {proc.returncode}"
    _NETNS_PROBE_RESULT = (False, f"probe failed: {detail}")
    return _NETNS_PROBE_RESULT


def reset_netns_probe_cache() -> None:
    """Clear the cached probe result. Test-only — production callers rely on
    the cache so the probe runs once per process."""
    global _NETNS_PROBE_RESULT
    _NETNS_PROBE_RESULT = None


def netns_sandbox_enabled() -> tuple[bool, str]:
    """Return ``(enabled, reason)`` for the current process's sandbox decision.

    Reads ``SCRIPT_NETNS_SANDBOX`` setting — ``auto`` consults the probe,
    ``on`` requires the probe to pass (logs a warning if it doesn't but still
    returns enabled=True so the wrap is attempted — the operator chose ``on``
    deliberately), ``off`` skips the wrap entirely.
    """
    from app.config import settings

    mode = (settings.SCRIPT_NETNS_SANDBOX or "auto").lower()
    if mode == "off":
        return False, "SCRIPT_NETNS_SANDBOX=off"
    if mode == "on":
        ok, reason = probe_netns_sandbox()
        if not ok:
            logger.warning(
                "SCRIPT_NETNS_SANDBOX=on but probe failed: %s — wrap will likely fail",
                reason,
            )
        return True, f"forced on (probe: {reason})"
    # auto
    ok, reason = probe_netns_sandbox()
    return ok, reason


def wrap_command_for_sandbox(inner_shell_cmd: str) -> str:
    """Wrap a shell command (the ``sh -c`` payload) in an unshare invocation.

    Brings ``lo`` up inside the new netns so the script can talk to the UDS
    bridge mount and any localhost services *exposed inside its own ns*
    (currently none, but harmless). The unshare binary is exec-ed directly
    by the outer ``sh -c`` so PID/process tree shape stays simple.
    """
    import shlex as _shlex

    # Inside the unshared ns we run our own sh -c that brings lo up and execs
    # the original payload. ``exec`` replaces the inner sh with the script
    # so signals + exit code propagate cleanly.
    inner = f"ip link set lo up 2>/dev/null; exec sh -c {_shlex.quote(inner_shell_cmd)}"
    return (
        "unshare --user --map-root-user --net -- "
        f"sh -c {_shlex.quote(inner)}"
    )
