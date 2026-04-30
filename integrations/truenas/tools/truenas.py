"""Read-mostly TrueNAS operations via JSON-RPC."""
from __future__ import annotations

import json
from typing import Any

from integrations.sdk import register_tool as register
from integrations.truenas.client import (
    TrueNASApiError,
    TrueNASConfigurationError,
    TrueNASConnectionError,
    truenas_client_from_settings,
)

CRITICAL_ALERT_LEVELS = {"CRITICAL", "ERROR"}
WARNING_ALERT_LEVELS = {"WARNING", "WARN"}
UNHEALTHY_POOL_STATES = {"DEGRADED", "FAULTED", "OFFLINE", "REMOVED", "UNAVAIL"}
HIGH_DISK_TEMP_C = 55.0


def truenas_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def truenas_error_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, TrueNASConfigurationError):
        return {"error": str(exc), "status": "not_configured"}
    if isinstance(exc, TrueNASConnectionError):
        return {"error": str(exc), "status": "unavailable"}
    if isinstance(exc, TrueNASApiError):
        payload: dict[str, Any] = {"error": str(exc), "status": "error"}
        if exc.code is not None:
            payload["code"] = exc.code
        return payload
    return {"error": "Failed to query TrueNAS", "status": "error", "detail": str(exc)}


def truenas_as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def truenas_count(value: Any) -> int:
    if isinstance(value, (list, dict, tuple, set)):
        return len(value)
    return 0


def truenas_clamp_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def truenas_pool_name(pool: dict[str, Any]) -> str:
    return str(pool.get("name") or pool.get("pool_name") or pool.get("id") or "unknown")


def truenas_pool_state(pool: dict[str, Any]) -> str:
    return str(pool.get("status") or pool.get("healthy") or pool.get("state") or "unknown")


def truenas_status_color(status: str) -> str:
    if status == "ok":
        return "success"
    if status == "warning":
        return "warning"
    if status in {"partial", "unavailable", "error", "not_configured"}:
        return "danger"
    return "info"


def truenas_alert_level(alert: dict[str, Any]) -> str:
    return str(alert.get("level") or alert.get("klass") or alert.get("category") or "").upper()


def truenas_alert_status(alerts: list[Any]) -> str:
    levels = {
        truenas_alert_level(item)
        for item in alerts
        if isinstance(item, dict)
    }
    if levels & CRITICAL_ALERT_LEVELS:
        return "critical"
    if levels & WARNING_ALERT_LEVELS:
        return "warning"
    return "ok"


def truenas_pool_status(pools: list[Any]) -> str:
    if not pools:
        return "unknown"
    for pool in pools:
        if not isinstance(pool, dict):
            continue
        state = truenas_pool_state(pool).upper()
        healthy = pool.get("healthy")
        if healthy is False or state in UNHEALTHY_POOL_STATES:
            return "warning"
    return "ok"


def truenas_disk_temp_rows(temperatures: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(temperatures, dict):
        iterable = temperatures.items()
    elif isinstance(temperatures, list):
        iterable = [
            (item.get("name") or item.get("disk") or item.get("identifier"), item)
            for item in temperatures
            if isinstance(item, dict)
        ]
    else:
        iterable = []

    for disk, value in iterable:
        temp = value
        if isinstance(value, dict):
            temp = value.get("temperature") or value.get("temp") or value.get("value")
        try:
            temp_c = float(temp)
        except (TypeError, ValueError):
            temp_c = None
        rows.append({
            "disk": str(disk or "unknown"),
            "temperature_c": temp_c,
            "status": "warning" if temp_c is not None and temp_c >= HIGH_DISK_TEMP_C else "ok",
        })
    return rows


def truenas_disk_status(rows: list[dict[str, Any]]) -> str:
    if any(row.get("status") == "warning" for row in rows):
        return "warning"
    return "ok" if rows else "unknown"


def truenas_tiles(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    pools = truenas_as_list(snapshot.get("pools"))
    alerts = truenas_as_list(snapshot.get("alerts"))
    jobs = truenas_as_list(snapshot.get("jobs"))
    disk_rows = truenas_as_list(snapshot.get("disk_temperatures"))
    update_status = snapshot.get("update_status") if isinstance(snapshot.get("update_status"), dict) else {}
    version = (snapshot.get("system") or {}).get("version") if isinstance(snapshot.get("system"), dict) else None
    return [
        {
            "label": "Pools",
            "value": str(len(pools)),
            "caption": truenas_pool_status(pools),
            "status": truenas_status_color("ok" if truenas_pool_status(pools) == "ok" else "warning"),
        },
        {
            "label": "Alerts",
            "value": str(len(alerts)),
            "caption": truenas_alert_status(alerts),
            "status": truenas_status_color("ok" if not alerts else "warning"),
        },
        {
            "label": "Disks",
            "value": str(len(disk_rows)),
            "caption": truenas_disk_status([row for row in disk_rows if isinstance(row, dict)]),
            "status": truenas_status_color(
                "ok" if truenas_disk_status([row for row in disk_rows if isinstance(row, dict)]) == "ok" else "warning"
            ),
        },
        {
            "label": "Jobs",
            "value": str(len(jobs)),
            "caption": "recent",
            "status": "info",
        },
        {
            "label": "Version",
            "value": str(version or "unknown"),
            "caption": str(update_status.get("status") or "update status unknown"),
            "status": "info",
        },
    ]


def truenas_pool_tiles(pools: list[Any]) -> list[dict[str, Any]]:
    tiles: list[dict[str, Any]] = []
    for item in pools:
        if not isinstance(item, dict):
            continue
        state = truenas_pool_state(item)
        free = item.get("free") or item.get("free_str")
        size = item.get("size") or item.get("size_str")
        caption = state
        if free is not None and size is not None:
            caption = f"{free} free of {size}"
        status = "success" if truenas_pool_status([item]) == "ok" else "warning"
        tiles.append({
            "label": truenas_pool_name(item),
            "value": state,
            "caption": caption,
            "status": status,
        })
    return tiles


def truenas_alert_tiles(alerts: list[Any]) -> list[dict[str, Any]]:
    tiles: list[dict[str, Any]] = []
    for item in alerts:
        if not isinstance(item, dict):
            continue
        level = truenas_alert_level(item) or "INFO"
        text = item.get("formatted") or item.get("text") or item.get("message") or item.get("klass") or "Alert"
        color = "danger" if level in CRITICAL_ALERT_LEVELS else "warning" if level in WARNING_ALERT_LEVELS else "info"
        tiles.append({
            "label": level,
            "value": str(text)[:96],
            "caption": str(item.get("datetime") or item.get("last_occurrence") or ""),
            "status": color,
        })
    return tiles


def truenas_job_tiles(jobs: list[Any]) -> list[dict[str, Any]]:
    tiles: list[dict[str, Any]] = []
    for item in jobs:
        if not isinstance(item, dict):
            continue
        state = str(item.get("state") or "unknown")
        method = str(item.get("method") or item.get("description") or "job")
        status = "success" if state.upper() == "SUCCESS" else "warning" if state.upper() in {"FAILED", "ABORTED"} else "info"
        tiles.append({
            "label": method,
            "value": state,
            "caption": str(item.get("time_finished") or item.get("time_started") or item.get("id") or ""),
            "status": status,
        })
    return tiles


async def truenas_query(client: Any, method: str, filters: list[Any] | None = None, options: dict[str, Any] | None = None) -> Any:
    return await client.call(method, [filters or [], options or {}])


async def truenas_collect_health(
    client: Any,
    *,
    alerts_limit: int,
    jobs_limit: int,
    include_shares: bool,
    include_snapshots: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    errors: dict[str, str] = {}

    async def collect(key: str, call):
        try:
            payload[key] = await call()
        except Exception as exc:
            errors[key] = str(exc)

    await collect("system", lambda: client.call("system.info"))
    await collect("pools", lambda: truenas_query(client, "pool.query"))
    await collect("alerts", lambda: client.call("alert.list"))
    await collect("jobs", lambda: truenas_query(
        client,
        "core.get_jobs",
        [],
        {"limit": jobs_limit, "order_by": ["-id"]},
    ))
    await collect("services", lambda: truenas_query(client, "service.query"))
    await collect("disk_temperatures", lambda: client.call("disk.temperatures"))
    await collect("update_status", lambda: client.call("update.status"))
    if include_shares:
        await collect("shares", lambda: truenas_fetch_shares(client))
    if include_snapshots:
        await collect("snapshots", lambda: truenas_query(client, "zfs.resource.snapshot.query", [], {"limit": 20, "order_by": ["-name"]}))

    alerts = truenas_as_list(payload.get("alerts"))[:alerts_limit]
    jobs = truenas_as_list(payload.get("jobs"))[:jobs_limit]
    disk_rows = truenas_disk_temp_rows(payload.get("disk_temperatures"))
    payload["alerts"] = alerts
    payload["jobs"] = jobs
    payload["disk_temperatures"] = disk_rows
    payload["pool_tiles"] = truenas_pool_tiles(truenas_as_list(payload.get("pools")))
    payload["alert_tiles"] = truenas_alert_tiles(alerts)
    payload["job_tiles"] = truenas_job_tiles(jobs)

    pool_state = truenas_pool_status(truenas_as_list(payload.get("pools")))
    alert_state = truenas_alert_status(alerts)
    disk_state = truenas_disk_status(disk_rows)
    status = "ok"
    if errors:
        status = "partial"
    if pool_state == "warning" or alert_state in {"critical", "warning"} or disk_state == "warning":
        status = "warning"
    if payload.keys() <= {"alerts", "jobs", "disk_temperatures", "pool_tiles", "alert_tiles", "job_tiles"} and errors:
        status = "unavailable"

    payload["status"] = status
    payload["status_color"] = truenas_status_color(status)
    payload["errors"] = errors
    payload["tiles"] = truenas_tiles(payload)
    payload["summary"] = [
        f"pools={pool_state}",
        f"alerts={len(alerts)}",
        f"disks={disk_state}",
        f"jobs={len(jobs)}",
    ]
    return payload


async def truenas_fetch_shares(client: Any) -> dict[str, Any]:
    smb = await truenas_query(client, "sharing.smb.query")
    nfs = await truenas_query(client, "sharing.nfs.query")
    return {
        "smb": truenas_as_list(smb),
        "nfs": truenas_as_list(nfs),
        "count": truenas_count(smb) + truenas_count(nfs),
    }


async def truenas_run(call) -> str:
    try:
        async with truenas_client_from_settings() as client:
            payload = await call(client)
    except Exception as exc:
        payload = truenas_error_payload(exc)
    return truenas_json(payload)


@register({
    "type": "function",
    "function": {
        "name": "truenas_test_connection",
        "description": "Check TrueNAS API connectivity and return basic system identity.",
        "parameters": {"type": "object", "properties": {}},
    },
}, returns={"type": "object"})
async def truenas_test_connection() -> str:
    async def call(client):
        system = await client.call("system.info")
        return {"status": "ok", "system": system}

    return await truenas_run(call)


@register({
    "type": "function",
    "function": {
        "name": "truenas_health_snapshot",
        "description": (
            "Read-only TrueNAS health snapshot for dashboards and heartbeats. "
            "Collects system info, pools, alerts, recent jobs, services, disk temperatures, and update status. "
            "Partial API failures are returned per section instead of failing the whole snapshot."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "alerts_limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                "jobs_limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100},
                "include_shares": {"type": "boolean", "default": False},
                "include_snapshots": {"type": "boolean", "default": False},
            },
        },
    },
}, returns={"type": "object"})
async def truenas_health_snapshot(
    alerts_limit: int = 20,
    jobs_limit: int = 10,
    include_shares: bool = False,
    include_snapshots: bool = False,
) -> str:
    alerts_n = truenas_clamp_int(alerts_limit, default=20, minimum=1, maximum=100)
    jobs_n = truenas_clamp_int(jobs_limit, default=10, minimum=1, maximum=100)

    async def call(client):
        return await truenas_collect_health(
            client,
            alerts_limit=alerts_n,
            jobs_limit=jobs_n,
            include_shares=bool(include_shares),
            include_snapshots=bool(include_snapshots),
        )

    return await truenas_run(call)


@register({
    "type": "function",
    "function": {
        "name": "truenas_pool_status",
        "description": "List TrueNAS storage pools with health/status details and scrub schedules.",
        "parameters": {
            "type": "object",
            "properties": {
                "pool_name": {"type": "string", "description": "Optional pool name to inspect."},
                "include_scrub_schedules": {"type": "boolean", "default": True},
            },
        },
    },
}, returns={"type": "object"})
async def truenas_pool_status_tool(pool_name: str | None = None, include_scrub_schedules: bool = True) -> str:
    async def call(client):
        filters = [["name", "=", pool_name]] if pool_name else []
        pools = truenas_as_list(await truenas_query(client, "pool.query", filters))
        payload = {
            "status": truenas_pool_status(pools),
            "pools": pools,
            "pool_tiles": truenas_pool_tiles(pools),
            "pool_name": pool_name or "",
        }
        if include_scrub_schedules:
            scrub_filters = [["pool_name", "=", pool_name]] if pool_name else []
            payload["scrub_schedules"] = truenas_as_list(await truenas_query(client, "pool.scrub.query", scrub_filters))
        return payload

    return await truenas_run(call)


@register({
    "type": "function",
    "function": {
        "name": "truenas_alerts",
        "description": "List active TrueNAS alerts with level, message, and timestamps.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
            },
        },
    },
}, returns={"type": "object"})
async def truenas_alerts(limit: int = 50) -> str:
    limit_n = truenas_clamp_int(limit, default=50, minimum=1, maximum=200)

    async def call(client):
        alerts = truenas_as_list(await client.call("alert.list"))[:limit_n]
        return {
            "status": truenas_alert_status(alerts),
            "count": len(alerts),
            "alerts": alerts,
            "alert_tiles": truenas_alert_tiles(alerts),
        }

    return await truenas_run(call)


@register({
    "type": "function",
    "function": {
        "name": "truenas_jobs",
        "description": "List recent TrueNAS jobs, optionally filtered by state.",
        "parameters": {
            "type": "object",
            "properties": {
                "state": {
                    "type": "string",
                    "description": "Optional job state filter, e.g. RUNNING, FAILED, SUCCESS.",
                },
                "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
            },
        },
    },
}, returns={"type": "object"})
async def truenas_jobs(state: str | None = None, limit: int = 20) -> str:
    limit_n = truenas_clamp_int(limit, default=20, minimum=1, maximum=100)
    filters = [["state", "=", state.upper()]] if state else []

    async def call(client):
        jobs = truenas_as_list(await truenas_query(client, "core.get_jobs", filters, {"limit": limit_n, "order_by": ["-id"]}))
        return {"status": "ok", "count": len(jobs), "jobs": jobs, "job_tiles": truenas_job_tiles(jobs)}

    return await truenas_run(call)


@register({
    "type": "function",
    "function": {
        "name": "truenas_services",
        "description": "List TrueNAS services and whether they are enabled/running.",
        "parameters": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Optional service name filter, e.g. smb or nfs."},
            },
        },
    },
}, returns={"type": "object"})
async def truenas_services(service: str | None = None) -> str:
    filters = [["service", "=", service]] if service else []

    async def call(client):
        services = truenas_as_list(await truenas_query(client, "service.query", filters))
        return {"status": "ok", "count": len(services), "services": services}

    return await truenas_run(call)


@register({
    "type": "function",
    "function": {
        "name": "truenas_disk_temperatures",
        "description": "Read TrueNAS disk temperatures and flag disks at or above the warning threshold.",
        "parameters": {"type": "object", "properties": {}},
    },
}, returns={"type": "object"})
async def truenas_disk_temperatures() -> str:
    async def call(client):
        rows = truenas_disk_temp_rows(await client.call("disk.temperatures"))
        return {"status": truenas_disk_status(rows), "disk_temperatures": rows, "count": len(rows)}

    return await truenas_run(call)


@register({
    "type": "function",
    "function": {
        "name": "truenas_shares",
        "description": "List configured TrueNAS SMB and NFS shares.",
        "parameters": {"type": "object", "properties": {}},
    },
}, returns={"type": "object"})
async def truenas_shares() -> str:
    async def call(client):
        shares = await truenas_fetch_shares(client)
        return {"status": "ok", **shares}

    return await truenas_run(call)


@register({
    "type": "function",
    "function": {
        "name": "truenas_snapshots",
        "description": "List recent TrueNAS ZFS snapshots, optionally scoped to a dataset prefix.",
        "parameters": {
            "type": "object",
            "properties": {
                "dataset": {"type": "string", "description": "Optional dataset prefix to filter snapshots."},
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
            },
        },
    },
}, returns={"type": "object"})
async def truenas_snapshots(dataset: str | None = None, limit: int = 50) -> str:
    limit_n = truenas_clamp_int(limit, default=50, minimum=1, maximum=200)
    filters = [["name", "^", f"{dataset}@"]] if dataset else []

    async def call(client):
        snapshots = truenas_as_list(await truenas_query(
            client,
            "zfs.resource.snapshot.query",
            filters,
            {"limit": limit_n, "order_by": ["-name"]},
        ))
        return {"status": "ok", "count": len(snapshots), "snapshots": snapshots}

    return await truenas_run(call)


@register({
    "type": "function",
    "function": {
        "name": "truenas_pool_options",
        "description": "List TrueNAS pool names for widget binding pickers and scrub targets.",
        "parameters": {"type": "object", "properties": {}},
    },
}, returns={"type": "object"})
async def truenas_pool_options() -> str:
    async def call(client):
        pools = truenas_as_list(await truenas_query(client, "pool.query"))
        options = [
            {
                "pool": truenas_pool_name(pool),
                "label": truenas_pool_name(pool),
                "state": truenas_pool_state(pool),
            }
            for pool in pools
            if isinstance(pool, dict)
        ]
        return {"status": "ok", "pools": options}

    return await truenas_run(call)


@register({
    "type": "function",
    "function": {
        "name": "truenas_start_scrub",
        "description": "Start a TrueNAS pool scrub. Requires confirmed=true because this is a state-changing operation.",
        "parameters": {
            "type": "object",
            "properties": {
                "pool_name": {"type": "string", "description": "Pool name to scrub."},
                "threshold": {"type": "integer", "default": 35, "minimum": 0, "maximum": 365},
                "confirmed": {"type": "boolean", "description": "Must be true to start the scrub."},
            },
            "required": ["pool_name", "confirmed"],
        },
    },
}, safety_tier="requires_confirmation", returns={"type": "object"})
async def truenas_start_scrub(pool_name: str, threshold: int = 35, confirmed: bool = False) -> str:
    if not confirmed:
        return truenas_json({
            "status": "confirmation_required",
            "error": "Set confirmed=true to start a TrueNAS scrub.",
        })
    threshold_n = truenas_clamp_int(threshold, default=35, minimum=0, maximum=365)

    async def call(client):
        result = await client.call("pool.scrub.run", [pool_name, threshold_n])
        return {"status": "ok", "pool_name": pool_name, "result": result}

    return await truenas_run(call)


@register({
    "type": "function",
    "function": {
        "name": "truenas_control_service",
        "description": "Start, stop, restart, or reload a TrueNAS service. Requires confirmed=true.",
        "parameters": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "TrueNAS service name, e.g. smb, nfs, ssh."},
                "action": {"type": "string", "enum": ["START", "STOP", "RESTART", "RELOAD"]},
                "confirmed": {"type": "boolean", "description": "Must be true to control the service."},
            },
            "required": ["service", "action", "confirmed"],
        },
    },
}, safety_tier="requires_confirmation", returns={"type": "object"})
async def truenas_control_service(service: str, action: str, confirmed: bool = False) -> str:
    verb = (action or "").upper()
    if verb not in {"START", "STOP", "RESTART", "RELOAD"}:
        return truenas_json({"status": "error", "error": "action must be START, STOP, RESTART, or RELOAD"})
    if not confirmed:
        return truenas_json({
            "status": "confirmation_required",
            "error": "Set confirmed=true to control a TrueNAS service.",
        })

    async def call(client):
        result = await client.call("service.control", [verb, service, {"ha_propagate": True, "silent": False, "timeout": 120}])
        return {"status": "ok", "service": service, "action": verb, "result": result}

    return await truenas_run(call)
