"""Read-only UniFi Network tools."""
from __future__ import annotations

import json
import logging
from typing import Any

from integrations.sdk import register_tool as register
from integrations.unifi.client import (
    UniFiApiError,
    UniFiConfigurationError,
    UniFiConnectionError,
    redact_unifi_payload,
    unifi_client_from_settings,
    unifi_extract_items,
)

logger = logging.getLogger(__name__)

DEVICE_DOWN_STATES = {"offline", "disconnected", "isolated", "failed"}
WARNING_DEVICE_STATES = {"adopting", "pending", "updating", "restarting"}


def unifi_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def unifi_status_color(status: str) -> str:
    if status == "ok":
        return "success"
    if status in {"warning", "partial"}:
        return "warning"
    if status in {"error", "unavailable", "not_configured"}:
        return "danger"
    return "info"


def unifi_clamp_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def unifi_as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def unifi_error_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, UniFiConfigurationError):
        return {"error": str(exc), "status": "not_configured"}
    if isinstance(exc, UniFiConnectionError):
        return {"error": str(exc), "status": "unavailable", "diagnostics": unifi_exception_diagnostics(exc)}
    if isinstance(exc, UniFiApiError):
        return {
            "error": str(exc),
            "status": "error",
            "code": exc.status_code,
            "path": exc.path,
        }
    return {"error": "Failed to query UniFi", "status": "error", "detail": str(exc)}


def unifi_exception_diagnostics(exc: Exception) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "exception_type": type(exc).__name__,
        "message": str(exc),
    }
    attempts = getattr(exc, "attempts", None)
    if attempts:
        diagnostics["attempted_endpoints"] = redact_unifi_payload(attempts)
    return diagnostics


def unifi_connection_payload(client: Any) -> dict[str, Any]:
    summary = getattr(client, "connection_summary", None)
    if callable(summary):
        return summary()
    return {}


def unifi_widget_error_payload(exc: Exception, *, context: str) -> dict[str, Any]:
    base = unifi_error_payload(exc)
    message = str(base.get("error") or base.get("detail") or exc)
    status = str(base.get("status") or "error")
    diagnostics = unifi_exception_diagnostics(exc)
    attempts = diagnostics.get("attempted_endpoints", [])
    connection: dict[str, Any] = {"attempted_endpoints": attempts}
    if attempts and isinstance(attempts, list):
        last_attempt = attempts[-1]
        if isinstance(last_attempt, dict):
            connection["base_url"] = last_attempt.get("base_url")
            connection["api_base_path"] = last_attempt.get("api_base_path")
    return {
        "status": status,
        "status_color": unifi_status_color(status),
        "message": message,
        "context": context,
        "connection": connection,
        "diagnostics": diagnostics,
        "errors": {"connection": message},
        "tiles": [{
            "label": "Connection",
            "value": "Unavailable",
            "caption": message[:96],
            "status": "danger",
        }],
        "site": {},
        "sites": [],
        "devices": [],
        "clients": [],
        "networks": [],
        "wifi": [],
        "firewall_zones": [],
        "device_tiles": [],
        "client_tiles": [],
        "vlan_tiles": [],
        "wifi_tiles": [],
        "likely_causes": [],
        "evidence_from_tools": [],
        "missing_manual_checks": [],
        "safe_next_steps": [],
        "do_not_change_yet": [],
        "count": 0,
    }


async def unifi_run(call, *, widget_context: str | None = None) -> str:
    try:
        async with unifi_client_from_settings() as client:
            payload = await call(client)
            if isinstance(payload, dict):
                connection = unifi_connection_payload(client)
                if connection:
                    payload.setdefault("connection", connection)
    except Exception as exc:
        logger.warning("UniFi tool call failed: %s", exc, exc_info=True)
        payload = (
            unifi_widget_error_payload(exc, context=widget_context)
            if widget_context
            else unifi_error_payload(exc)
        )
    return unifi_json(payload)


async def unifi_site(client: Any) -> tuple[str, dict[str, Any]]:
    site_id = await client.selected_site_id()
    site: dict[str, Any] = {"id": site_id}
    for item in await client.sites():
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or item.get("siteId") or item.get("_id") or item.get("name") or "")
        if item_id == site_id:
            site = item
            break
    return site_id, site


async def unifi_devices_for_site(client: Any, site_id: str, limit: int = 500) -> list[Any]:
    return await client.list_paginated(f"/sites/{site_id}/devices", limit=200, max_items=limit)


async def unifi_clients_for_site(client: Any, site_id: str, limit: int = 500) -> list[Any]:
    return await client.list_paginated(f"/sites/{site_id}/clients", limit=200, max_items=limit)


async def unifi_networks_for_site(client: Any, site_id: str) -> list[Any]:
    return await client.list_paginated(f"/sites/{site_id}/networks", limit=200, max_items=500)


async def unifi_wifi_for_site(client: Any, site_id: str) -> list[Any]:
    payload = await client.get_first([
        f"/sites/{site_id}/wifi",
        f"/sites/{site_id}/wifis",
        f"/sites/{site_id}/wireless-networks",
    ])
    return unifi_extract_items(payload)


async def unifi_firewall_zones_for_site(client: Any, site_id: str) -> list[Any]:
    payload = await client.get_first([
        f"/sites/{site_id}/firewall/zones",
        f"/sites/{site_id}/firewall-zones",
        f"/sites/{site_id}/zones",
    ])
    return unifi_extract_items(payload)


def unifi_name(item: Any, *keys: str, default: str = "unknown") -> str:
    if not isinstance(item, dict):
        return default
    for key in keys:
        value = item.get(key)
        if value:
            return str(value)
    return default


def unifi_device_state(device: dict[str, Any]) -> str:
    return str(
        device.get("state")
        or device.get("status")
        or device.get("connectionState")
        or device.get("connectedState")
        or ("online" if device.get("online") is True else "offline" if device.get("online") is False else "unknown")
    ).lower()


def unifi_device_type(device: dict[str, Any]) -> str:
    return str(device.get("type") or device.get("deviceType") or device.get("model") or "device")


def unifi_client_network(client: dict[str, Any]) -> str:
    return unifi_name(client, "networkName", "network", "networkId", "vlanName", default="")


def unifi_vlan_id(item: dict[str, Any]) -> str:
    value = item.get("vlanId")
    if value is None:
        value = item.get("vlan")
    if value is None:
        value = item.get("vid")
    return "" if value is None else str(value)


def unifi_client_status(client: dict[str, Any]) -> str:
    if client.get("authorized") is False:
        return "unauthorized"
    if client.get("connected") is False or client.get("online") is False:
        return "offline"
    ip = str(client.get("ipAddress") or client.get("ip") or "")
    if ip.startswith("169.254."):
        return "dhcp_failed"
    return "online" if client.get("connected") is True or client.get("online") is True else "unknown"


def unifi_device_tiles(devices: list[Any]) -> list[dict[str, Any]]:
    tiles: list[dict[str, Any]] = []
    for device in devices[:24]:
        if not isinstance(device, dict):
            continue
        state = unifi_device_state(device)
        status = "danger" if state in DEVICE_DOWN_STATES else "warning" if state in WARNING_DEVICE_STATES else "success"
        tiles.append({
            "label": unifi_name(device, "name", "displayName", "macAddress", "mac", default="device"),
            "value": state,
            "caption": unifi_device_type(device),
            "status": status,
        })
    return tiles


def unifi_client_tiles(clients: list[Any]) -> list[dict[str, Any]]:
    tiles: list[dict[str, Any]] = []
    for client in clients[:24]:
        if not isinstance(client, dict):
            continue
        status = unifi_client_status(client)
        color = "danger" if status in {"dhcp_failed", "unauthorized"} else "warning" if status == "unknown" else "success"
        tiles.append({
            "label": unifi_name(client, "name", "hostname", "displayName", "macAddress", "mac", default="client"),
            "value": status,
            "caption": unifi_client_network(client) or str(client.get("ipAddress") or client.get("ip") or ""),
            "status": color,
        })
    return tiles


def unifi_vlan_tiles(networks: list[Any], wifi: list[Any]) -> list[dict[str, Any]]:
    ssid_by_vlan: dict[str, list[str]] = {}
    for item in wifi:
        if not isinstance(item, dict):
            continue
        vlan = unifi_vlan_id(item) or str(item.get("networkId") or item.get("networkName") or "")
        if not vlan:
            continue
        ssid_by_vlan.setdefault(vlan, []).append(unifi_name(item, "name", "ssid", default="SSID"))

    tiles: list[dict[str, Any]] = []
    for network in networks:
        if not isinstance(network, dict):
            continue
        vlan = unifi_vlan_id(network) or str(network.get("id") or network.get("networkId") or "")
        ssids = ssid_by_vlan.get(vlan, [])
        tiles.append({
            "label": unifi_name(network, "name", "displayName", default="network"),
            "value": vlan or "untagged",
            "caption": ", ".join(ssids[:3]) if ssids else str(network.get("subnet") or network.get("gatewayIp") or ""),
            "status": "info",
        })
    return tiles


def unifi_wifi_tiles(wifi: list[Any]) -> list[dict[str, Any]]:
    tiles: list[dict[str, Any]] = []
    for item in wifi:
        if not isinstance(item, dict):
            continue
        enabled = item.get("enabled")
        status = "success" if enabled is not False else "warning"
        tiles.append({
            "label": unifi_name(item, "name", "ssid", default="SSID"),
            "value": "enabled" if enabled is not False else "disabled",
            "caption": f"VLAN {unifi_vlan_id(item) or item.get('networkName') or 'default'}",
            "status": status,
        })
    return tiles


def unifi_network_status(devices: list[Any], clients: list[Any], errors: dict[str, str]) -> str:
    if any(isinstance(device, dict) and unifi_device_state(device) in DEVICE_DOWN_STATES for device in devices):
        return "warning"
    if any(isinstance(client, dict) and unifi_client_status(client) in {"dhcp_failed", "unauthorized"} for client in clients):
        return "warning"
    return "partial" if errors else "ok"


def unifi_find_clients(clients: list[Any], query: str) -> list[dict[str, Any]]:
    q = (query or "").strip().lower()
    if not q:
        return [item for item in clients if isinstance(item, dict)]
    matches = []
    for item in clients:
        if not isinstance(item, dict):
            continue
        haystack = " ".join(str(item.get(key) or "") for key in (
            "name", "hostname", "displayName", "macAddress", "mac", "ipAddress", "ip", "networkName", "network"
        )).lower()
        if q in haystack:
            matches.append(item)
    return matches


def unifi_vlan_advice(
    *,
    symptom: str,
    target_client: str,
    networks: list[Any],
    wifi: list[Any],
    clients: list[Any],
    devices: list[Any],
    firewall_zones: list[Any],
    errors: dict[str, str],
) -> dict[str, Any]:
    likely_causes: list[str] = []
    evidence: list[str] = []
    missing: list[str] = []
    steps: list[str] = []
    do_not_change: list[str] = [
        "Do not create or move VLANs until the failing client path is identified.",
        "Do not disable firewall or isolation rules globally as a first diagnostic step.",
    ]

    matched_clients = unifi_find_clients(clients, target_client)
    dhcp_failed = [c for c in matched_clients if unifi_client_status(c) == "dhcp_failed"]
    unauthorized = [c for c in matched_clients if unifi_client_status(c) == "unauthorized"]
    offline_devices = [d for d in devices if isinstance(d, dict) and unifi_device_state(d) in DEVICE_DOWN_STATES]

    if target_client and matched_clients:
        for client in matched_clients[:5]:
            evidence.append(
                "Client %s is %s on %s with IP %s"
                % (
                    unifi_name(client, "name", "hostname", "macAddress", "mac", default="client"),
                    unifi_client_status(client),
                    unifi_client_network(client) or "unknown network",
                    client.get("ipAddress") or client.get("ip") or "unknown",
                )
            )
    elif target_client:
        likely_causes.append("The target client was not found in the current UniFi client list.")
        missing.append("Confirm the client MAC/name and whether it is currently connected or recently seen.")

    if dhcp_failed:
        likely_causes.append("The client appears connected but is not receiving DHCP on the expected VLAN.")
        steps.append("Inspect the SSID/network VLAN and every switch/AP uplink in UniFi VLAN Viewer.")
    if unauthorized:
        likely_causes.append("The client is connected but not authorized, which points at captive portal or access policy state.")

    if offline_devices:
        likely_causes.append("At least one UniFi device is offline, isolated, or disconnected.")
        evidence.append(f"{len(offline_devices)} UniFi device(s) are not online.")

    if wifi and networks:
        vlan_values = {unifi_vlan_id(n) for n in networks if isinstance(n, dict)}
        for ssid in wifi:
            if not isinstance(ssid, dict):
                continue
            vlan = unifi_vlan_id(ssid)
            if vlan and vlan not in vlan_values:
                likely_causes.append(
                    f"SSID {unifi_name(ssid, 'name', 'ssid', default='SSID')} references VLAN {vlan}, but no matching network was returned."
                )
    else:
        missing.append("Use UniFi UI to confirm Settings > Networks and Settings > WiFi mappings if the API omitted them.")

    if "vlan" in symptom.lower() or "wrong" in symptom.lower() or "subnet" in symptom.lower():
        likely_causes.append("The SSID or access port may be mapped to the wrong VLAN/network.")
        steps.append("Check whether the SSID VLAN is accidentally set as the AP uplink port Primary/Native Network.")
        steps.append("Check whether the VLAN is allowed/tagged on every upstream switch port between client/AP and gateway.")
    if "internet" in symptom.lower():
        steps.append("Check WAN health first, then gateway firewall/zone rules from the client network to Internet.")
    if "reach" in symptom.lower() or "between" in symptom.lower() or "inter" in symptom.lower():
        steps.append("Check UniFi Firewall/Zones in both source-to-destination and destination-to-source directions.")
        if firewall_zones:
            evidence.append(f"{len(firewall_zones)} firewall zone(s) were returned by the API.")
        else:
            missing.append("Review Firewall/Zones manually; the API did not return zone details.")

    if errors:
        for key, value in errors.items():
            missing.append(f"{key} data unavailable from API: {value}")

    if not likely_causes:
        likely_causes.append("No single cause is proven from read-only API data; continue by narrowing DHCP vs tagging vs firewall.")
    if not steps:
        steps.extend([
            "Identify one failing client by MAC/name and rerun the advisor with target_client.",
            "Compare the client's IP/subnet against the intended UniFi network and SSID.",
            "Use UniFi VLAN Viewer to verify native/allowed VLANs along the full path.",
        ])

    return {
        "status": "ok" if not errors else "partial",
        "symptom": symptom,
        "target_client": target_client,
        "likely_causes": likely_causes,
        "evidence_from_tools": evidence,
        "missing_manual_checks": missing,
        "safe_next_steps": steps,
        "do_not_change_yet": do_not_change,
    }


async def unifi_collect_snapshot(client: Any, *, client_limit: int, device_limit: int) -> dict[str, Any]:
    site_id, site = await unifi_site(client)
    payload: dict[str, Any] = {"site_id": site_id, "site": site}
    errors: dict[str, str] = {}

    async def collect(key: str, call):
        try:
            payload[key] = await call()
        except Exception as exc:
            errors[key] = str(exc)

    await collect("devices", lambda: unifi_devices_for_site(client, site_id, device_limit))
    await collect("clients", lambda: unifi_clients_for_site(client, site_id, client_limit))
    await collect("networks", lambda: unifi_networks_for_site(client, site_id))
    await collect("wifi", lambda: unifi_wifi_for_site(client, site_id))
    await collect("firewall_zones", lambda: unifi_firewall_zones_for_site(client, site_id))

    devices = unifi_as_list(payload.get("devices"))
    clients = unifi_as_list(payload.get("clients"))
    networks = unifi_as_list(payload.get("networks"))
    wifi = unifi_as_list(payload.get("wifi"))
    status = unifi_network_status(devices, clients, errors)

    payload["status"] = status
    payload["status_color"] = unifi_status_color(status)
    payload["errors"] = errors
    payload["device_tiles"] = unifi_device_tiles(devices)
    payload["client_tiles"] = unifi_client_tiles(clients)
    payload["vlan_tiles"] = unifi_vlan_tiles(networks, wifi)
    payload["wifi_tiles"] = unifi_wifi_tiles(wifi)
    payload["tiles"] = [
        {"label": "Devices", "value": str(len(devices)), "caption": "UniFi", "status": "success" if status == "ok" else "warning"},
        {"label": "Clients", "value": str(len(clients)), "caption": "active/recent", "status": "info"},
        {"label": "Networks", "value": str(len(networks)), "caption": "VLANs", "status": "info"},
        {"label": "WiFi", "value": str(len(wifi)), "caption": "SSIDs", "status": "info"},
        {"label": "Zones", "value": str(len(unifi_as_list(payload.get("firewall_zones")))), "caption": "firewall", "status": "info"},
    ]
    payload["summary"] = [
        f"devices={len(devices)}",
        f"clients={len(clients)}",
        f"networks={len(networks)}",
        f"wifi={len(wifi)}",
    ]
    return payload


@register({
    "type": "function",
    "function": {
        "name": "unifi_test_connection",
        "description": "Check UniFi Network API connectivity and return site/API diagnostics.",
        "parameters": {"type": "object", "properties": {}},
    },
}, returns={"type": "object"})
async def unifi_test_connection() -> str:
    async def call(client):
        sites = await client.sites()
        site_id, site = await unifi_site(client)
        return {
            "status": "ok",
            "status_color": "success",
            "message": f"Connected to UniFi Network site {site.get('name') or site_id}.",
            "site_id": site_id,
            "site": site,
            "sites": sites,
            "count": len(sites),
        }

    return await unifi_run(call, widget_context="test_connection")


@register({
    "type": "function",
    "function": {
        "name": "unifi_sites",
        "description": "List UniFi Network sites available to the configured API key.",
        "parameters": {"type": "object", "properties": {}},
    },
}, returns={"type": "object"})
async def unifi_sites() -> str:
    async def call(client):
        sites = await client.sites()
        return {"status": "ok", "sites": sites, "count": len(sites)}

    return await unifi_run(call)


@register({
    "type": "function",
    "function": {
        "name": "unifi_network_snapshot",
        "description": "Read-only UniFi Network health snapshot for dashboards and troubleshooting.",
        "parameters": {
            "type": "object",
            "properties": {
                "client_limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 1000},
                "device_limit": {"type": "integer", "default": 200, "minimum": 1, "maximum": 1000},
            },
        },
    },
}, returns={"type": "object"})
async def unifi_network_snapshot(client_limit: int = 100, device_limit: int = 200) -> str:
    client_n = unifi_clamp_int(client_limit, default=100, minimum=1, maximum=1000)
    device_n = unifi_clamp_int(device_limit, default=200, minimum=1, maximum=1000)

    async def call(client):
        return await unifi_collect_snapshot(client, client_limit=client_n, device_limit=device_n)

    return await unifi_run(call, widget_context="network_snapshot")


@register({
    "type": "function",
    "function": {
        "name": "unifi_devices",
        "description": "List UniFi Network devices such as gateways, switches, and APs.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 200, "minimum": 1, "maximum": 1000},
            },
        },
    },
}, returns={"type": "object"})
async def unifi_devices(limit: int = 200) -> str:
    limit_n = unifi_clamp_int(limit, default=200, minimum=1, maximum=1000)

    async def call(client):
        site_id, site = await unifi_site(client)
        devices = await unifi_devices_for_site(client, site_id, limit_n)
        return {
            "status": "ok",
            "site_id": site_id,
            "site": site,
            "devices": devices,
            "count": len(devices),
            "device_tiles": unifi_device_tiles(devices),
        }

    return await unifi_run(call, widget_context="devices")


@register({
    "type": "function",
    "function": {
        "name": "unifi_clients",
        "description": "List UniFi Network clients with status, network, and IP details.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Optional client name, MAC, IP, or network search text."},
                "limit": {"type": "integer", "default": 200, "minimum": 1, "maximum": 1000},
            },
        },
    },
}, returns={"type": "object"})
async def unifi_clients(query: str | None = None, limit: int = 200) -> str:
    limit_n = unifi_clamp_int(limit, default=200, minimum=1, maximum=1000)

    async def call(client):
        site_id, site = await unifi_site(client)
        clients = await unifi_clients_for_site(client, site_id, limit_n)
        if query:
            clients = unifi_find_clients(clients, query)
        return {
            "status": "ok",
            "site_id": site_id,
            "site": site,
            "clients": clients,
            "count": len(clients),
            "client_tiles": unifi_client_tiles(clients),
        }

    return await unifi_run(call, widget_context="clients")


@register({
    "type": "function",
    "function": {
        "name": "unifi_networks",
        "description": "List UniFi networks/VLANs returned by the official Network API.",
        "parameters": {"type": "object", "properties": {}},
    },
}, returns={"type": "object"})
async def unifi_networks() -> str:
    async def call(client):
        site_id, site = await unifi_site(client)
        networks = await unifi_networks_for_site(client, site_id)
        wifi: list[Any] = []
        try:
            wifi = await unifi_wifi_for_site(client, site_id)
        except Exception:
            wifi = []
        return {
            "status": "ok",
            "site_id": site_id,
            "site": site,
            "networks": networks,
            "count": len(networks),
            "vlan_tiles": unifi_vlan_tiles(networks, wifi),
        }

    return await unifi_run(call, widget_context="networks")


@register({
    "type": "function",
    "function": {
        "name": "unifi_wifi",
        "description": "List UniFi WiFi/SSID configuration returned by the official Network API.",
        "parameters": {"type": "object", "properties": {}},
    },
}, returns={"type": "object"})
async def unifi_wifi() -> str:
    async def call(client):
        site_id, site = await unifi_site(client)
        wifi = await unifi_wifi_for_site(client, site_id)
        return {
            "status": "ok",
            "site_id": site_id,
            "site": site,
            "wifi": wifi,
            "count": len(wifi),
            "wifi_tiles": unifi_wifi_tiles(wifi),
        }

    return await unifi_run(call, widget_context="wifi")


@register({
    "type": "function",
    "function": {
        "name": "unifi_firewall_zones",
        "description": "List UniFi firewall zones when exposed by the official Network API.",
        "parameters": {"type": "object", "properties": {}},
    },
}, returns={"type": "object"})
async def unifi_firewall_zones() -> str:
    async def call(client):
        site_id, site = await unifi_site(client)
        zones = await unifi_firewall_zones_for_site(client, site_id)
        return {"status": "ok", "site_id": site_id, "site": site, "firewall_zones": zones, "count": len(zones)}

    return await unifi_run(call)


@register({
    "type": "function",
    "function": {
        "name": "unifi_vlan_advisor",
        "description": (
            "Read-only VLAN and connectivity troubleshooting advisor. "
            "Uses UniFi Network API data to separate DHCP, VLAN tagging, WiFi, and firewall-zone likely causes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symptom": {"type": "string", "description": "Connectivity symptom in plain language."},
                "target_client": {"type": "string", "description": "Optional client name, MAC, IP, or hostname."},
            },
        },
    },
}, returns={"type": "object"})
async def unifi_vlan_advisor(symptom: str = "", target_client: str = "") -> str:
    async def call(client):
        snapshot = await unifi_collect_snapshot(client, client_limit=500, device_limit=500)
        advice = unifi_vlan_advice(
            symptom=symptom or "",
            target_client=target_client or "",
            networks=unifi_as_list(snapshot.get("networks")),
            wifi=unifi_as_list(snapshot.get("wifi")),
            clients=unifi_as_list(snapshot.get("clients")),
            devices=unifi_as_list(snapshot.get("devices")),
            firewall_zones=unifi_as_list(snapshot.get("firewall_zones")),
            errors=snapshot.get("errors") if isinstance(snapshot.get("errors"), dict) else {},
        )
        return {**snapshot, **advice}

    return await unifi_run(call, widget_context="vlan_advisor")


@register({
    "type": "function",
    "function": {
        "name": "unifi_site_options",
        "description": "List UniFi site options for widget binding pickers.",
        "parameters": {"type": "object", "properties": {}},
    },
}, returns={"type": "object"})
async def unifi_site_options() -> str:
    async def call(client):
        sites = await client.sites()
        options = [
            {
                "site": unifi_name(site, "id", "siteId", "_id", "name", default=""),
                "label": unifi_name(site, "name", "displayName", "id", "siteId", default="site"),
            }
            for site in sites
            if isinstance(site, dict)
        ]
        return {"status": "ok", "sites": options, "count": len(options)}

    return await unifi_run(call)

