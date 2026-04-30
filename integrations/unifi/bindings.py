"""Widget preset binding transforms for UniFi Network."""
from __future__ import annotations

import json
from typing import Any


def _payload(raw_result: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_result)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def site_options(raw_result: str, _context: dict[str, Any]) -> list[dict[str, Any]]:
    payload = _payload(raw_result)
    sites = payload.get("sites")
    if not isinstance(sites, list):
        return []
    options: list[dict[str, Any]] = []
    for item in sites:
        if not isinstance(item, dict):
            continue
        value = item.get("site") or item.get("id") or item.get("siteId") or item.get("_id") or item.get("name")
        if not value:
            continue
        label = str(item.get("label") or item.get("name") or item.get("displayName") or value)
        options.append({
            "value": str(value),
            "label": label,
            "description": str(item.get("description") or item.get("role") or "UniFi site"),
            "group": "Sites",
            "meta": {"site_id": str(value)},
        })
    return options


def network_options(raw_result: str, _context: dict[str, Any]) -> list[dict[str, Any]]:
    payload = _payload(raw_result)
    networks = payload.get("networks")
    if not isinstance(networks, list):
        return []
    options: list[dict[str, Any]] = []
    for item in networks:
        if not isinstance(item, dict):
            continue
        value = item.get("id") or item.get("networkId") or item.get("name")
        label = item.get("name") or item.get("displayName") or value
        if not value or not label:
            continue
        vlan = item.get("vlanId")
        if vlan is None:
            vlan = item.get("vlan") or item.get("vid") or "untagged"
        options.append({
            "value": str(value),
            "label": str(label),
            "description": f"VLAN {vlan}",
            "group": "Networks",
            "meta": {"vlan": str(vlan)},
        })
    return options

