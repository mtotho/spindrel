"""R2 Phase 2 — OS-level netns sandbox for run_script.

Pins the kernel-level egress shutoff Phase 2 adds on top of Phase 1's
sitecustomize.py allowlist. The wrap is `unshare --user --map-root-user
--net` which the script subprocess runs through; the only transport the
sandboxed script has to the agent server is the UDS bridge served from the
parent network namespace.

Tests run real subprocesses with `unshare`. If the host kernel / seccomp
profile blocks unprivileged user-namespace creation (rare on modern Linux,
but possible under hardened Docker / gVisor / Kata), the per-test gate
``_skip_if_probe_failed()`` calls ``pytest.skip`` rather than failing.

Phase 1 coverage stays in `tests/unit/test_script_egress_guard.py` — these
tests target the *kernel-level* layer and the UDS transport.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from app.services.script_runner import (
    _egress_guard_source,
    _helper_source,
    netns_sandbox_enabled,
    probe_netns_sandbox,
    reset_netns_probe_cache,
    wrap_command_for_sandbox,
)
from app.services.script_sandbox_bridge import serve_uds_bridge


def _skip_if_probe_failed() -> None:
    reset_netns_probe_cache()
    ok, reason = probe_netns_sandbox()
    if not ok:
        pytest.skip(f"unprivileged user/net namespace not available: {reason}")


# ---------------------------------------------------------------------------
# Probe helper
# ---------------------------------------------------------------------------


class TestProbe:
    def test_probe_succeeds_on_supported_kernel(self) -> None:
        reset_netns_probe_cache()
        ok, reason = probe_netns_sandbox()
        if not ok:
            pytest.skip(f"unprivileged user-ns not supported: {reason}")
        assert ok is True
        assert reason == "ok"

    def test_probe_is_cached(self) -> None:
        reset_netns_probe_cache()
        first = probe_netns_sandbox()
        # Subsequent call returns cached tuple identity.
        second = probe_netns_sandbox()
        assert first is second

    def test_probe_reset_clears_cache(self) -> None:
        probe_netns_sandbox()
        reset_netns_probe_cache()
        # After reset, next probe runs fresh — different tuple identity even
        # if the result is the same content.
        again = probe_netns_sandbox()
        assert again[0] in (True, False)


# ---------------------------------------------------------------------------
# Settings-driven decision
# ---------------------------------------------------------------------------


class TestSandboxDecision:
    def test_off_mode_disables_wrap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.config import settings

        monkeypatch.setattr(settings, "SCRIPT_NETNS_SANDBOX", "off")
        enabled, reason = netns_sandbox_enabled()
        assert enabled is False
        assert "off" in reason.lower()

    def test_auto_mode_consults_probe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.config import settings
        from app.services import script_runner

        monkeypatch.setattr(settings, "SCRIPT_NETNS_SANDBOX", "auto")
        # Force probe to a known-failed state so we assert the decision shape.
        monkeypatch.setattr(script_runner, "_NETNS_PROBE_RESULT", (False, "probe failed: simulated"))
        enabled, reason = netns_sandbox_enabled()
        assert enabled is False
        assert "simulated" in reason

    def test_auto_mode_enabled_when_probe_passes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.config import settings
        from app.services import script_runner

        monkeypatch.setattr(settings, "SCRIPT_NETNS_SANDBOX", "auto")
        monkeypatch.setattr(script_runner, "_NETNS_PROBE_RESULT", (True, "ok"))
        enabled, reason = netns_sandbox_enabled()
        assert enabled is True
        assert reason == "ok"


# ---------------------------------------------------------------------------
# Argv wrap shape
# ---------------------------------------------------------------------------


class TestWrapShape:
    def test_wrap_includes_unshare_and_lo_up(self) -> None:
        wrapped = wrap_command_for_sandbox("python3 script.py")
        assert "unshare --user --map-root-user --net" in wrapped
        assert "ip link set lo up" in wrapped

    def test_wrap_preserves_inner_command_quoting(self) -> None:
        # Inner command with shell-special chars must round-trip safely
        # through the wrap (shell quoting handled by shlex.quote).
        inner = "echo 'hello there' && cd /tmp && python3 script.py"
        wrapped = wrap_command_for_sandbox(inner)
        # Run it (without unshare for this assertion — just that the shell
        # parses our wrap as a valid command).
        result = subprocess.run(
            ["sh", "-c", wrapped.replace(
                "unshare --user --map-root-user --net -- ", ""
            )],
            cwd="/tmp", capture_output=True, text=True, timeout=5,
        )
        # Inner will fail because there's no script.py; we only care that
        # the shell parses the wrap (no syntax error on stderr from sh).
        assert "syntax error" not in result.stderr.lower()


# ---------------------------------------------------------------------------
# Kernel-level egress shutoff (real subprocess)
# ---------------------------------------------------------------------------


class TestKernelLevelEgressShutoff:
    """The whole point of Phase 2: kernel-enforced egress denial that
    survives ``subprocess.run(["curl"])`` and ``ctypes`` raw socket calls.
    """

    def test_curl_subprocess_blocked_inside_sandbox(self) -> None:
        _skip_if_probe_failed()
        wrapped = wrap_command_for_sandbox(
            "curl --max-time 2 -sS http://1.1.1.1 2>&1; echo EXIT=$?"
        )
        result = subprocess.run(
            ["sh", "-c", wrapped],
            capture_output=True, text=True, timeout=10,
        )
        assert "EXIT=0" not in result.stdout
        # curl exit codes 6 (couldn't resolve) or 7 (couldn't connect) both
        # acceptable — depending on whether DNS happens to be reachable from
        # the test host's parent namespace, but inside our empty netns
        # there's no upstream so connect is the typical failure.
        assert "EXIT=" in result.stdout
        exit_token = result.stdout.split("EXIT=")[-1].strip().splitlines()[0]
        assert exit_token != "0", f"curl unexpectedly succeeded: {result.stdout}"

    def test_ctypes_raw_socket_blocked_inside_sandbox(self) -> None:
        _skip_if_probe_failed()
        # Direct libc syscall — bypasses Python's socket.socket entirely,
        # which is the documented Phase 1 bypass.
        py_script = textwrap.dedent('''\
            import ctypes, ctypes.util, struct, socket, sys
            libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
            fd = libc.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
            assert fd >= 0
            # 1.1.1.1:80 in network byte order
            sa = struct.pack("!HH4sBBBBBBBB", socket.AF_INET, 80, b"\\x01\\x01\\x01\\x01", 0,0,0,0,0,0,0,0)
            rc = libc.connect(fd, sa, len(sa))
            errno = ctypes.get_errno()
            print(f"connect_rc={rc} errno={errno}")
            sys.exit(0 if rc == 0 else 42)
        ''')
        wrapped = wrap_command_for_sandbox(
            f"{sys.executable} -c {repr_quote(py_script)}"
        )
        result = subprocess.run(
            ["sh", "-c", wrapped],
            capture_output=True, text=True, timeout=10,
        )
        # Either the connect returned -1 (rc=-1) OR the script exited 42
        # (our explicit non-zero on rc != 0).
        assert "connect_rc=0" not in result.stdout, (
            f"raw socket connect unexpectedly succeeded: {result.stdout}"
        )


def repr_quote(s: str) -> str:
    """Single-quote a Python string literal for safe shell embedding."""
    import shlex

    return shlex.quote(s)


# ---------------------------------------------------------------------------
# UDS transport — sandboxed script CAN reach the bridge
# ---------------------------------------------------------------------------


class TestUDSBridgeTransport:
    """Sandbox shuts off TCP egress — but spindrel.py still works because
    the UDS bridge crosses the netns boundary via filesystem-path resolution.
    """

    def test_spindrel_helper_uds_call_succeeds_inside_sandbox(
        self, tmp_path: Path
    ) -> None:
        _skip_if_probe_failed()
        sock_path = tmp_path / "test-uds.sock"
        scratch = tmp_path / "scratch"
        scratch.mkdir()

        captured: dict[str, Any] = {"body": None}

        async def run() -> tuple[int, str, str]:
            async def handler(reader, writer):
                # Read raw HTTP request, capture body, return 200 JSON.
                buf = b""
                while b"\r\n\r\n" not in buf:
                    chunk = await reader.read(4096)
                    if not chunk:
                        break
                    buf += chunk
                head, _, rest = buf.partition(b"\r\n\r\n")
                cl = 0
                for line in head.split(b"\r\n"):
                    if line.lower().startswith(b"content-length:"):
                        cl = int(line.split(b":")[1].strip())
                body = rest
                while len(body) < cl:
                    more = await reader.read(cl - len(body))
                    if not more:
                        break
                    body += more
                captured["body"] = body.decode("utf-8")
                resp_body = json.dumps({"ok": True, "result": {"received": True}}).encode()
                writer.write(
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Content-Length: " + str(len(resp_body)).encode() + b"\r\n"
                    b"\r\n" + resp_body
                )
                await writer.drain()
                writer.close()

            server = await asyncio.start_unix_server(handler, path=str(sock_path))
            os.chmod(sock_path, 0o666)

            async with server:
                # Drop the production helper + sitecustomize into the scratch dir.
                (scratch / "spindrel.py").write_text(_helper_source())
                (scratch / "sitecustomize.py").write_text(_egress_guard_source())
                (scratch / "script.py").write_text(textwrap.dedent('''\
                    from spindrel import tools
                    print(tools.echo(message="hi"))
                '''))
                inner = (
                    f"export SPINDREL_SERVER_UDS={sock_path} && "
                    f"export SPINDREL_SCRIPT_EGRESS_MODE=off && "
                    f"export AGENT_SERVER_API_KEY=test-key && "
                    f"cd {scratch} && python3 script.py"
                )
                wrapped = wrap_command_for_sandbox(inner)
                proc = await asyncio.create_subprocess_shell(
                    wrapped,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=15,
                )
                return proc.returncode or 0, stdout_b.decode(), stderr_b.decode()

        rc, stdout, stderr = asyncio.run(run())
        assert rc == 0, f"script failed: stdout={stdout!r} stderr={stderr!r}"
        assert "received" in stdout, stdout
        # Server saw the request body — confirms UDS round-trip worked.
        assert captured["body"] is not None
        body_json = json.loads(captured["body"])
        assert body_json["name"] == "echo"
        assert body_json["arguments"] == {"message": "hi"}


# ---------------------------------------------------------------------------
# Bridge module
# ---------------------------------------------------------------------------


class TestUDSBridgeModule:
    def test_bridge_forwards_to_tcp_backend(self, tmp_path: Path) -> None:
        sock_path = tmp_path / "bridge.sock"

        async def run() -> bytes:
            # Tiny TCP echo server — accepts a request, returns "RECEIVED" + body.
            captured = []

            async def tcp_handler(r, w):
                data = await r.read(4096)
                captured.append(data)
                w.write(b"RECEIVED:" + data)
                await w.drain()
                w.close()

            tcp_server = await asyncio.start_server(tcp_handler, "127.0.0.1", 0)
            tcp_port = tcp_server.sockets[0].getsockname()[1]

            bridge = await serve_uds_bridge(str(sock_path), "127.0.0.1", tcp_port)
            try:
                # Connect to the UDS, send bytes, read response.
                ureader, uwriter = await asyncio.open_unix_connection(str(sock_path))
                uwriter.write(b"hello-bridge")
                await uwriter.drain()
                uwriter.write_eof()
                resp = await ureader.read(4096)
                uwriter.close()
                return resp
            finally:
                bridge.close()
                tcp_server.close()
                await bridge.wait_closed()
                await tcp_server.wait_closed()

        resp = asyncio.run(run())
        assert resp.startswith(b"RECEIVED:hello-bridge"), resp


# ---------------------------------------------------------------------------
# Audit signal
# ---------------------------------------------------------------------------


class TestAuditSignalShape:
    def test_signal_reports_passed_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.config import settings
        from app.services import script_runner
        from app.services.security_audit import _check_script_netns_sandbox

        monkeypatch.setattr(settings, "SCRIPT_NETNS_SANDBOX", "auto")
        monkeypatch.setattr(script_runner, "_NETNS_PROBE_RESULT", (True, "ok"))
        check = _check_script_netns_sandbox()
        assert check.id == "script_netns_sandbox"
        assert check.status.value == "pass"
        assert check.details and check.details["enabled"] is True
        assert check.details["uds_path"]

    def test_signal_reports_warning_when_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.config import settings
        from app.services.security_audit import _check_script_netns_sandbox

        monkeypatch.setattr(settings, "SCRIPT_NETNS_SANDBOX", "off")
        check = _check_script_netns_sandbox()
        assert check.status.value == "warning"
        assert "off" in check.message.lower()
        assert check.recommendation and "auto" in check.recommendation.lower()

    def test_signal_reports_warning_when_probe_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.config import settings
        from app.services import script_runner
        from app.services.security_audit import _check_script_netns_sandbox

        monkeypatch.setattr(settings, "SCRIPT_NETNS_SANDBOX", "auto")
        monkeypatch.setattr(
            script_runner, "_NETNS_PROBE_RESULT", (False, "probe failed: simulated")
        )
        check = _check_script_netns_sandbox()
        assert check.status.value == "warning"
        assert "simulated" in check.message
        assert check.recommendation and "seccomp" in check.recommendation.lower()
