"""Widget preset binding transforms for TrueNAS."""
from __future__ import annotations

import json
from typing import Any


def pool_options(raw_result: str, _context: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw_result)
    except json.JSONDecodeError:
        return []

    pools = payload.get("pools")
    if not isinstance(pools, list):
        return []

    options: list[dict[str, Any]] = []
    for item in pools:
        if not isinstance(item, dict):
            continue
        pool = item.get("pool") or item.get("name") or item.get("label")
        if not isinstance(pool, str) or not pool:
            continue
        state = str(item.get("state") or "unknown")
        options.append({
            "value": pool,
            "label": str(item.get("label") or pool),
            "description": state,
            "group": "Pools",
            "meta": {"state": state},
        })
    return options

