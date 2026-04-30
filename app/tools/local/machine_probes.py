from __future__ import annotations

import json
import re
import shlex
from typing import Any
from urllib.parse import urlparse

from app.services.machine_control import get_provider, validate_current_execution_policy
from app.tools.registry import register

_STATUS_VALUES = ("ok", "warning", "failed", "blocked", "unknown")
_CONFIDENCE_VALUES = ("low", "medium", "high")
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,252}$")
_MAX_EVIDENCE_LINES = 8
_DOCKER_APP_MAP_SECTION_RE = re.compile(r"^## app_map_(containers|networks|compose)$")


def _probe_catalog() -> list[dict[str, Any]]:
    return [
        {
            "probe_id": "network_basics",
            "label": "Network basics",
            "description": "Show hostname, OS, addresses, routes, and DNS resolver config on the leased machine.",
            "required_args": [],
            "optional_args": [],
            "requires_machine_lease": True,
            "next_probe_ids": ["dns_lookup", "tcp_port"],
        },
        {
            "probe_id": "dns_lookup",
            "label": "DNS lookup",
            "description": "Resolve one hostname from the leased machine.",
            "required_args": ["host"],
            "optional_args": [],
            "requires_machine_lease": True,
            "next_probe_ids": ["tcp_port", "http_probe"],
        },
        {
            "probe_id": "tcp_port",
            "label": "TCP port",
            "description": "Attempt a short TCP connection from the leased machine to a host and port.",
            "required_args": ["host", "port"],
            "optional_args": [],
            "requires_machine_lease": True,
            "next_probe_ids": ["dns_lookup", "http_probe"],
        },
        {
            "probe_id": "http_probe",
            "label": "HTTP probe",
            "description": "Attempt a basic HTTP HEAD request from the leased machine.",
            "required_args": ["url"],
            "optional_args": [],
            "requires_machine_lease": True,
            "next_probe_ids": ["dns_lookup", "tcp_port"],
        },
        {
            "probe_id": "docker_summary",
            "label": "Docker summary",
            "description": "List Docker containers, published ports, and compose projects when Docker is available.",
            "required_args": [],
            "optional_args": [],
            "requires_machine_lease": True,
            "next_probe_ids": ["docker_app_map", "docker_logs_tail", "tcp_port", "compose_summary"],
        },
        {
            "probe_id": "docker_app_map",
            "label": "Docker app map",
            "description": "Map Docker containers, published ports, networks, and Compose projects on the leased machine.",
            "required_args": [],
            "optional_args": [],
            "requires_machine_lease": True,
            "next_probe_ids": ["tcp_port", "http_probe", "docker_logs_tail", "compose_summary"],
        },
        {
            "probe_id": "compose_summary",
            "label": "Compose summary",
            "description": "List Docker Compose projects visible to the leased machine.",
            "required_args": [],
            "optional_args": [],
            "requires_machine_lease": True,
            "next_probe_ids": ["docker_summary"],
        },
        {
            "probe_id": "docker_logs_tail",
            "label": "Docker logs tail",
            "description": "Fetch a bounded log tail for one Docker container.",
            "required_args": ["container"],
            "optional_args": ["tail"],
            "requires_machine_lease": True,
            "next_probe_ids": ["docker_summary"],
        },
    ]


def _catalog_by_id() -> dict[str, dict[str, Any]]:
    return {entry["probe_id"]: entry for entry in _probe_catalog()}


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _failure(
    *,
    probe_id: str | None,
    status: str,
    message: str,
    error_code: str,
    next_probe_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "probe_id": probe_id,
        "status": status,
        "status_color": _status_color(status),
        "target": "",
        "evidence": [message],
        "blocked_reason": message if status == "blocked" else None,
        "next_probe_ids": next_probe_ids or [],
        "confidence": "low",
        "error": {"code": error_code, "message": message},
    }


def _safe_host(value: str, field: str) -> str:
    host = str(value or "").strip()
    if not host:
        raise ValueError(f"{field} is required")
    if any(ch.isspace() for ch in host) or not _HOST_RE.fullmatch(host):
        raise ValueError(f"{field} must be a hostname, IP address, or simple DNS name")
    return host


def _safe_container(value: str) -> str:
    container = str(value or "").strip()
    if not container:
        raise ValueError("container is required")
    if not _SAFE_NAME_RE.fullmatch(container):
        raise ValueError("container must be a simple Docker container name or id")
    return container


def _safe_port(value: Any) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise ValueError("port must be an integer") from None
    if port < 1 or port > 65535:
        raise ValueError("port must be between 1 and 65535")
    return port


def _safe_tail(value: Any) -> int:
    try:
        tail = int(value or 80)
    except (TypeError, ValueError):
        return 80
    return max(1, min(tail, 500))


def _safe_url(value: str) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url must be an http:// or https:// URL")
    return url


def _python_tcp_command(host: str, port: int) -> str:
    script = (
        "import socket,sys,time\n"
        "host=sys.argv[1]\n"
        "port=int(sys.argv[2])\n"
        "start=time.time()\n"
        "sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)\n"
        "sock.settimeout(5)\n"
        "try:\n"
        "    sock.connect((host,port))\n"
        "    print(f'tcp_connect ok host={host} port={port} elapsed_ms={int((time.time()-start)*1000)}')\n"
        "except Exception as exc:\n"
        "    print(f'tcp_connect failed host={host} port={port} error={exc}')\n"
        "    sys.exit(2)\n"
        "finally:\n"
        "    sock.close()\n"
    )
    return f"python3 -c {shlex.quote(script)} {shlex.quote(host)} {port}"


def _python_http_command(url: str) -> str:
    script = (
        "import sys,time,urllib.request\n"
        "url=sys.argv[1]\n"
        "start=time.time()\n"
        "req=urllib.request.Request(url,method='HEAD',headers={'User-Agent':'spindrel-machine-probe/1'})\n"
        "try:\n"
        "    with urllib.request.urlopen(req,timeout=8) as resp:\n"
        "        print(f'http_probe ok status={resp.status} url={url} elapsed_ms={int((time.time()-start)*1000)}')\n"
        "except Exception as exc:\n"
        "    print(f'http_probe failed url={url} error={exc}')\n"
        "    sys.exit(2)\n"
    )
    return f"python3 -c {shlex.quote(script)} {shlex.quote(url)}"


def _build_probe_command(
    probe_id: str,
    *,
    host: str = "",
    port: Any = None,
    url: str = "",
    container: str = "",
    tail: Any = 80,
) -> tuple[str, str]:
    if probe_id == "network_basics":
        return (
            "network_basics",
            "\n".join([
                "echo '## hostname'; hostname 2>/dev/null || true",
                "echo '## uname'; uname -srm 2>/dev/null || true",
                "echo '## addresses'; ip -brief addr 2>/dev/null || ifconfig 2>/dev/null || true",
                "echo '## routes'; ip route 2>/dev/null || route -n 2>/dev/null || netstat -rn 2>/dev/null || true",
                "echo '## dns'; cat /etc/resolv.conf 2>/dev/null || true",
            ]),
        )
    if probe_id == "dns_lookup":
        safe_host = _safe_host(host, "host")
        quoted = shlex.quote(safe_host)
        return (
            safe_host,
            f"getent hosts {quoted} 2>/dev/null || nslookup {quoted} 2>/dev/null || dig +short {quoted} 2>/dev/null",
        )
    if probe_id == "tcp_port":
        safe_host = _safe_host(host, "host")
        safe_port = _safe_port(port)
        return (f"{safe_host}:{safe_port}", _python_tcp_command(safe_host, safe_port))
    if probe_id == "http_probe":
        safe = _safe_url(url)
        return (safe, _python_http_command(safe))
    if probe_id == "docker_summary":
        return (
            "docker",
            "\n".join([
                "if ! command -v docker >/dev/null 2>&1; then echo 'docker_not_found'; exit 3; fi",
                "echo '## docker_version'; docker --version 2>/dev/null || true",
                "echo '## containers'; docker ps --format '{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || true",
                "echo '## networks'; docker network ls --format '{{.Name}}\t{{.Driver}}\t{{.Scope}}' 2>/dev/null || true",
                "echo '## compose_projects'; docker compose ls 2>/dev/null || docker-compose ls 2>/dev/null || true",
            ]),
        )
    if probe_id == "docker_app_map":
        return (
            "docker",
            "\n".join([
                "if ! command -v docker >/dev/null 2>&1; then echo 'docker_not_found'; exit 3; fi",
                "echo '## app_map_containers'",
                (
                    "app_map_containers=$(docker ps --format "
                    "'{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}\t{{.Networks}}\t"
                    "{{.Label \"com.docker.compose.project\"}}\t"
                    "{{.Label \"com.docker.compose.service\"}}' 2>&1); "
                    "app_map_rc=$?; "
                    "if [ $app_map_rc -ne 0 ]; then printf '%s\n' \"$app_map_containers\"; exit $app_map_rc; fi; "
                    "printf '%s\n' \"$app_map_containers\""
                ),
                "echo '## app_map_networks'",
                "docker network ls --format '{{.Name}}\t{{.Driver}}\t{{.Scope}}' 2>/dev/null || true",
                "echo '## app_map_compose'",
                "docker compose ls --format '{{.Name}}\t{{.Status}}' 2>/dev/null || docker-compose ls 2>/dev/null || true",
            ]),
        )
    if probe_id == "compose_summary":
        return ("docker compose", "docker compose ls 2>/dev/null || docker-compose ls 2>/dev/null")
    if probe_id == "docker_logs_tail":
        safe_container = _safe_container(container)
        safe_tail = _safe_tail(tail)
        return (safe_container, f"docker logs --tail {safe_tail} {shlex.quote(safe_container)}")
    raise ValueError(f"Unknown probe_id: {probe_id}")


def _evidence_from_result(result: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for label in ("stdout", "stderr"):
        value = str(result.get(label) or "")
        if not value.strip():
            continue
        for line in value.splitlines():
            text = line.strip()
            if text:
                lines.append(f"{label}: {text}")
            if len(lines) >= _MAX_EVIDENCE_LINES:
                break
        if len(lines) >= _MAX_EVIDENCE_LINES:
            break
    if not lines:
        lines.append("Command returned no output.")
    return lines


def _parse_published_ports(container_name: str, ports_text: str) -> list[dict[str, Any]]:
    ports: list[dict[str, Any]] = []
    for raw_part in str(ports_text or "").split(","):
        part = raw_part.strip()
        if not part or "->" not in part:
            continue
        host_side, container_side = part.split("->", 1)
        host_side = host_side.strip()
        container_side = container_side.strip()
        protocol = ""
        if "/" in container_side:
            container_port, protocol = container_side.rsplit("/", 1)
        else:
            container_port = container_side

        host_ip = ""
        host_port = host_side
        if host_side.startswith("[") and "]:" in host_side:
            host_ip, host_port = host_side[1:].split("]:", 1)
        elif ":" in host_side:
            host_ip, host_port = host_side.rsplit(":", 1)

        suggested_probe = None
        if host_port.isdigit():
            suggested_probe = {
                "probe_id": "tcp_port",
                "host": "127.0.0.1" if host_ip in {"", "0.0.0.0", "::"} else host_ip,
                "port": int(host_port),
            }

        ports.append({
            "container": container_name,
            "host_ip": host_ip,
            "host_port": host_port,
            "container_port": container_port,
            "protocol": protocol,
            "suggested_probe": suggested_probe,
        })
    return ports


def _parse_docker_app_map(stdout: str) -> dict[str, Any]:
    sections: dict[str, list[str]] = {"containers": [], "networks": [], "compose": []}
    current: str | None = None
    for raw_line in str(stdout or "").splitlines():
        line = raw_line.rstrip("\n")
        marker = _DOCKER_APP_MAP_SECTION_RE.match(line.strip())
        if marker:
            current = marker.group(1)
            continue
        if current and line.strip():
            sections[current].append(line)

    containers: list[dict[str, Any]] = []
    published_ports: list[dict[str, Any]] = []
    for line in sections["containers"]:
        parts = line.split("\t")
        while len(parts) < 7:
            parts.append("")
        name, image, status, ports_text, networks_text, compose_project, compose_service = parts[:7]
        networks = [item.strip() for item in networks_text.split(",") if item.strip()]
        ports = _parse_published_ports(name, ports_text)
        published_ports.extend(ports)
        containers.append({
            "name": name,
            "image": image,
            "status": status,
            "ports": ports_text,
            "networks": networks,
            "compose_project": compose_project,
            "compose_service": compose_service,
        })

    networks: list[dict[str, str]] = []
    for line in sections["networks"]:
        parts = line.split("\t")
        while len(parts) < 3:
            parts.append("")
        name, driver, scope = parts[:3]
        networks.append({"name": name, "driver": driver, "scope": scope})

    compose_projects: list[dict[str, str]] = []
    for line in sections["compose"]:
        if line.lower().startswith("name") or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            compose_projects.append({"name": parts[0], "status": parts[1]})
        elif parts:
            compose_projects.append({"name": parts[0], "status": ""})

    return {
        "summary": {
            "containers": len(containers),
            "published_ports": len(published_ports),
            "networks": len(networks),
            "compose_projects": len(compose_projects),
        },
        "containers": containers,
        "published_ports": published_ports,
        "networks": networks,
        "compose_projects": compose_projects,
    }


def _app_map_evidence(app_map: dict[str, Any]) -> list[str]:
    summary = app_map.get("summary") or {}
    lines = [
        (
            "Docker app map: "
            f"{summary.get('containers', 0)} containers, "
            f"{summary.get('published_ports', 0)} published ports, "
            f"{summary.get('networks', 0)} networks, "
            f"{summary.get('compose_projects', 0)} compose projects."
        )
    ]
    for port in (app_map.get("published_ports") or [])[:5]:
        host_ip = port.get("host_ip") or "*"
        lines.append(
            f"{port.get('container')}: {host_ip}:{port.get('host_port')} -> "
            f"{port.get('container_port')}/{port.get('protocol')}"
        )
    return lines[:_MAX_EVIDENCE_LINES]


def _status_from_result(result: dict[str, Any]) -> str:
    exit_code = int(result.get("exit_code") or 0)
    stdout = str(result.get("stdout") or "")
    stderr = str(result.get("stderr") or "")
    combined = f"{stdout}\n{stderr}".lower()
    if exit_code == 0:
        if "failed" in combined or "permission denied" in combined or "not found" in combined:
            return "warning"
        return "ok"
    return "failed"


def _confidence_for(status: str, result: dict[str, Any]) -> str:
    if status == "ok":
        return "high"
    if status == "warning":
        return "medium"
    if int(result.get("exit_code") or 0) != 0:
        return "high"
    return "low"


def _status_color(status: str) -> str:
    if status == "ok":
        return "success"
    if status == "warning":
        return "warning"
    if status in {"failed", "blocked"}:
        return "danger"
    return "muted"


_CATALOG_RETURNS = {
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "probes": {"type": "array", "items": {"type": "object"}},
        "error": {"type": "object"},
    },
    "required": ["status", "probes"],
}

_RUN_RETURNS = {
    "type": "object",
    "properties": {
        "probe_id": {"type": ["string", "null"]},
        "status": {"type": "string", "enum": list(_STATUS_VALUES)},
        "status_color": {"type": "string"},
        "target": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "blocked_reason": {"type": ["string", "null"]},
        "next_probe_ids": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": list(_CONFIDENCE_VALUES)},
        "result": {"type": "object"},
        "app_map": {"type": "object"},
        "error": {"type": "object"},
    },
    "required": ["probe_id", "status", "evidence", "next_probe_ids", "confidence"],
}


@register(
    {
        "type": "function",
        "function": {
            "name": "machine_probe_catalog",
            "description": (
                "List bounded read-only machine probes for progressive discovery. "
                "Use before machine_run_probe to see required arguments and next-probe suggestions."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    safety_tier="readonly",
    execution_policy="interactive_user",
    returns=_CATALOG_RETURNS,
)
async def machine_probe_catalog() -> str:
    resolution = await validate_current_execution_policy("interactive_user")
    if not resolution.allowed:
        return _json({
            "status": "blocked",
            "probes": _probe_catalog(),
            "error": {
                "code": "local_control_required",
                "message": resolution.reason or "Machine-control probes require a live user context.",
            },
        })
    return _json({"status": "ok", "probes": _probe_catalog()})


@register(
    {
        "type": "function",
        "function": {
            "name": "machine_run_probe",
            "description": (
                "Run one bounded read-only probe on the leased machine target. "
                "This uses fixed probe commands, returns structured evidence, and suggests the next probe."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "probe_id": {"type": "string", "description": "Probe id from machine_probe_catalog."},
                    "host": {"type": "string", "description": "Hostname or IP for dns_lookup and tcp_port."},
                    "port": {"type": "integer", "minimum": 1, "maximum": 65535},
                    "url": {"type": "string", "description": "HTTP or HTTPS URL for http_probe."},
                    "container": {"type": "string", "description": "Docker container name or id for docker_logs_tail."},
                    "tail": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 500,
                        "description": "Number of Docker log lines for docker_logs_tail. Defaults to 80.",
                    },
                },
                "required": ["probe_id"],
            },
        },
    },
    safety_tier="readonly",
    execution_policy="live_target_lease",
    returns=_RUN_RETURNS,
)
async def machine_run_probe(
    probe_id: str,
    host: str = "",
    port: int | None = None,
    url: str = "",
    container: str = "",
    tail: int = 80,
) -> str:
    catalog = _catalog_by_id()
    probe = catalog.get(str(probe_id or "").strip())
    if probe is None:
        return _json(_failure(
            probe_id=probe_id,
            status="unknown",
            message=f"Unknown probe_id: {probe_id}",
            error_code="unknown_probe",
            next_probe_ids=list(catalog.keys())[:5],
        ))

    resolution = await validate_current_execution_policy("live_target_lease")
    if not resolution.allowed or resolution.lease is None:
        return _json(_failure(
            probe_id=probe["probe_id"],
            status="blocked",
            message=resolution.reason or "A live machine target lease is required to run probes.",
            error_code="local_control_required",
        ))

    try:
        target, command = _build_probe_command(
            probe["probe_id"],
            host=host,
            port=port,
            url=url,
            container=container,
            tail=tail,
        )
    except ValueError as exc:
        return _json(_failure(
            probe_id=probe["probe_id"],
            status="failed",
            message=str(exc),
            error_code="invalid_probe_args",
            next_probe_ids=[probe["probe_id"]],
        ))

    lease = resolution.lease
    provider = get_provider(lease["provider_id"])
    try:
        result = await provider.exec_command(lease["target_id"], command, "")
    except Exception as exc:
        return _json(_failure(
            probe_id=probe["probe_id"],
            status="failed",
            message=str(exc),
            error_code="machine_probe_failed",
            next_probe_ids=probe.get("next_probe_ids") or [],
        ))

    status = _status_from_result(result)
    payload = {
        "probe_id": probe["probe_id"],
        "status": status,
        "status_color": _status_color(status),
        "target": target,
        "evidence": _evidence_from_result(result),
        "blocked_reason": None,
        "next_probe_ids": probe.get("next_probe_ids") or [],
        "confidence": _confidence_for(status, result),
        "result": {
            "stdout": str(result.get("stdout") or ""),
            "stderr": str(result.get("stderr") or ""),
            "exit_code": int(result.get("exit_code") or 0),
            "duration_ms": int(result.get("duration_ms") or 0),
            "truncated": bool(result.get("truncated")),
        },
    }
    if probe["probe_id"] == "docker_app_map" and status in {"ok", "warning"}:
        app_map = _parse_docker_app_map(str(result.get("stdout") or ""))
        payload["app_map"] = app_map
        payload["evidence"] = _app_map_evidence(app_map)
    return _json(payload)
