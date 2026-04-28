from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import platform as py_platform
import re
import shlex
import socket
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Spindrel local companion")
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--label", default=socket.gethostname())
    parser.add_argument("--hostname", default=socket.gethostname())
    parser.add_argument("--platform", default=py_platform.platform())
    parser.add_argument("--inspect-prefix", action="append", default=["pwd", "ls", "git", "cat", "head", "tail", "find", "rg", "ps", "which"])
    parser.add_argument("--allowed-root", action="append", default=[os.getcwd()])
    parser.add_argument("--blocked-pattern", action="append", default=[])
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--max-output-bytes", type=int, default=65536)
    parser.add_argument("--once", action="store_true", help="Exit instead of reconnecting when the websocket closes.")
    parser.add_argument("--reconnect-initial-seconds", type=float, default=1.0)
    parser.add_argument("--reconnect-max-seconds", type=float, default=30.0)
    parser.add_argument("--install-systemd-user", action="store_true", help="Install and start a reconnecting systemd user service.")
    parser.add_argument("--service-name", default="spindrel-local-companion")
    return parser.parse_args()


def _validate_inspect_command(command: str, prefixes: list[str]) -> None:
    stripped = command.strip()
    if not stripped:
        raise ValueError("inspect command cannot be empty")
    if re.search(r"[;&|><`$()]", stripped):
        raise ValueError("inspect command cannot use shell composition characters")
    parts = shlex.split(stripped)
    if not parts:
        raise ValueError("inspect command cannot be empty")
    binary = parts[0]
    if binary not in prefixes:
        raise ValueError(f"inspect command '{binary}' is not allowed")


def _validate_working_dir(working_dir: str, allowed_roots: list[str]) -> str:
    candidate = os.path.realpath(working_dir or os.getcwd())
    if not os.path.isdir(candidate):
        raise ValueError(f"working directory does not exist: {candidate}")
    roots = [os.path.realpath(root) for root in allowed_roots]
    if not any(candidate == root or candidate.startswith(root.rstrip(os.sep) + os.sep) for root in roots):
        raise ValueError(f"working directory is outside the allowed roots: {candidate}")
    return candidate


def _check_blocked_patterns(command: str, patterns: list[str]) -> None:
    for raw in patterns:
        if raw and re.search(raw, command, re.IGNORECASE):
            raise ValueError(f"command blocked by companion policy: {raw}")


def _trim(data: bytes, max_output_bytes: int) -> tuple[str, bool]:
    truncated = len(data) > max_output_bytes
    if truncated:
        data = data[:max_output_bytes]
    return data.decode(errors="replace"), truncated


def _build_ws_url(server_url: str, *, target_id: str, token: str) -> str:
    _ = token
    parsed = urlsplit(server_url.rstrip("/"))
    scheme_map = {"http": "ws", "https": "wss", "ws": "ws", "wss": "wss"}
    scheme = scheme_map.get(parsed.scheme)
    if scheme is None:
        raise ValueError("--server-url must use http, https, ws, or wss")
    path = f"{parsed.path.rstrip('/')}/integrations/local_companion/ws"
    query = urlencode({"target_id": target_id})
    return urlunsplit((scheme, parsed.netloc, path, query, ""))


async def _run_exec_command(
    command: str,
    *,
    working_dir: str,
    timeout_seconds: int,
    max_output_bytes: int,
) -> dict[str, Any]:
    start = time.monotonic()
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=working_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_raw, stderr_raw = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"command timed out after {timeout_seconds}s")
    stdout, stdout_truncated = _trim(stdout_raw, max_output_bytes)
    stderr, stderr_truncated = _trim(stderr_raw, max_output_bytes)
    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": proc.returncode or 0,
        "duration_ms": int((time.monotonic() - start) * 1000),
        "truncated": stdout_truncated or stderr_truncated,
    }


async def _run_inspect_command(
    command: str,
    *,
    timeout_seconds: int,
    max_output_bytes: int,
) -> dict[str, Any]:
    start = time.monotonic()
    parts = shlex.split(command)
    proc = await asyncio.create_subprocess_exec(
        *parts,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_raw, stderr_raw = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"inspect command timed out after {timeout_seconds}s")
    stdout, stdout_truncated = _trim(stdout_raw, max_output_bytes)
    stderr, stderr_truncated = _trim(stderr_raw, max_output_bytes)
    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": proc.returncode or 0,
        "duration_ms": int((time.monotonic() - start) * 1000),
        "truncated": stdout_truncated or stderr_truncated,
    }


async def _handle_request(payload: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    op = payload.get("op")
    request_id = payload.get("request_id")
    req_args = payload.get("args") or {}
    if op == "inspect_command":
        command = str(req_args.get("command") or "")
        _check_blocked_patterns(command, args.blocked_pattern)
        _validate_inspect_command(command, args.inspect_prefix)
        result = await _run_inspect_command(
            command,
            timeout_seconds=args.timeout_seconds,
            max_output_bytes=args.max_output_bytes,
        )
        return {"request_id": request_id, "result": result}
    if op == "exec_command":
        command = str(req_args.get("command") or "")
        working_dir = _validate_working_dir(str(req_args.get("working_dir") or os.getcwd()), args.allowed_root)
        _check_blocked_patterns(command, args.blocked_pattern)
        result = await _run_exec_command(
            command,
            working_dir=working_dir,
            timeout_seconds=args.timeout_seconds,
            max_output_bytes=args.max_output_bytes,
        )
        return {"request_id": request_id, "result": result}
    return {"request_id": request_id, "error": f"unknown op: {op}"}


async def _run_client(args: argparse.Namespace) -> int:
    ws_url = _build_ws_url(args.server_url, target_id=args.target_id, token=args.token)
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError(
            "Python package 'websockets' is required. Install it with `python -m pip install websockets`, "
            "or rerun this script with --install-systemd-user to create an isolated service environment.",
        ) from exc

    async with websockets.connect(ws_url, max_size=2**22) as ws:
        challenge = json.loads(await ws.recv())
        if challenge.get("type") != "challenge" or challenge.get("target_id") != args.target_id:
            raise RuntimeError("server did not issue a valid challenge")
        nonce = str(challenge.get("nonce") or "")
        signature = hmac.new(
            args.token.encode("utf-8"),
            f"{args.target_id}.{nonce}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        await ws.send(json.dumps({"type": "auth", "signature": f"sha256={signature}"}))
        await ws.send(json.dumps({
            "type": "hello",
            "label": args.label,
            "hostname": args.hostname,
            "platform": args.platform,
            "capabilities": ["shell"],
        }))
        async for raw in ws:
            payload = json.loads(raw)
            if payload.get("type") == "hello":
                print(
                    f"Connected target={payload.get('target_id')} connection_id={payload.get('connection_id')}",
                    file=sys.stderr,
                    flush=True,
                )
                continue
            try:
                response = await _handle_request(payload, args)
            except Exception as exc:
                response = {"request_id": payload.get("request_id"), "error": str(exc)}
            await ws.send(json.dumps(response))
    return 0


async def _run_reconnecting_client(args: argparse.Namespace) -> int:
    delay = max(0.25, float(args.reconnect_initial_seconds))
    max_delay = max(delay, float(args.reconnect_max_seconds))
    while True:
        try:
            await _run_client(args)
            if args.once:
                return 0
            print("Disconnected; reconnecting...", file=sys.stderr, flush=True)
            delay = max(0.25, float(args.reconnect_initial_seconds))
        except Exception as exc:
            if args.once:
                print(f"Companion exited: {exc}", file=sys.stderr, flush=True)
                return 1
            print(f"Connection failed: {exc}; retrying in {delay:.1f}s", file=sys.stderr, flush=True)
        await asyncio.sleep(delay)
        delay = min(max_delay, delay * 2)


def _service_args(args: argparse.Namespace, client_path: Path, python_path: Path) -> list[str]:
    out = [
        str(python_path),
        str(client_path),
        "--server-url",
        args.server_url,
        "--target-id",
        args.target_id,
        "--token",
        args.token,
        "--label",
        args.label,
        "--hostname",
        args.hostname,
        "--platform",
        args.platform,
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--max-output-bytes",
        str(args.max_output_bytes),
        "--reconnect-initial-seconds",
        str(args.reconnect_initial_seconds),
        "--reconnect-max-seconds",
        str(args.reconnect_max_seconds),
    ]
    for value in args.inspect_prefix:
        out.extend(["--inspect-prefix", value])
    for value in args.allowed_root:
        out.extend(["--allowed-root", value])
    for value in args.blocked_pattern:
        out.extend(["--blocked-pattern", value])
    return out


def _systemd_exec_start(argv: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in argv)


def _install_systemd_user(args: argparse.Namespace) -> int:
    home = Path.home()
    app_dir = home / ".local" / "share" / "spindrel-local-companion"
    venv_dir = app_dir / ".venv"
    client_path = app_dir / "client.py"
    service_dir = home / ".config" / "systemd" / "user"
    service_path = service_dir / f"{args.service_name}.service"

    app_dir.mkdir(parents=True, exist_ok=True)
    service_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).resolve(), client_path)

    if not venv_dir.exists():
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    python_path = venv_dir / "bin" / "python"
    subprocess.run([str(python_path), "-m", "pip", "install", "--upgrade", "pip", "websockets"], check=True)

    service_path.write_text(
        "\n".join([
            "[Unit]",
            "Description=Spindrel Local Companion",
            "After=network-online.target",
            "Wants=network-online.target",
            "",
            "[Service]",
            "Type=simple",
            f"WorkingDirectory={shlex.quote(os.getcwd())}",
            f"ExecStart={_systemd_exec_start(_service_args(args, client_path, python_path))}",
            "Restart=always",
            "RestartSec=5",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]),
        encoding="utf-8",
    )
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", f"{args.service_name}.service"], check=True)
    print(f"Installed and started {args.service_name}.service", file=sys.stderr, flush=True)
    print("Optional: run `loginctl enable-linger $USER` to keep it running after logout.", file=sys.stderr, flush=True)
    return 0


def main() -> int:
    args = _parse_args()
    if args.install_systemd_user:
        return _install_systemd_user(args)
    try:
        return asyncio.run(_run_reconnecting_client(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
