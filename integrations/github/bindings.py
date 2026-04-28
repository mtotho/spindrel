"""Widget preset binding transforms for GitHub."""
from __future__ import annotations

import json
from typing import Any


def repo_options(raw_result: str, _context: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw_result)
    except json.JSONDecodeError:
        return []
    repos = payload.get("repositories")
    if not isinstance(repos, list):
        return []
    options: list[dict[str, Any]] = []
    for item in repos:
        if not isinstance(item, dict):
            continue
        repo = item.get("repository")
        if not isinstance(repo, str) or "/" not in repo:
            continue
        options.append({
            "value": repo,
            "label": str(item.get("label") or repo),
            "description": "GitHub repository",
            "group": str(item.get("group") or "GitHub bindings"),
            "meta": {
                "channel_id": item.get("channel_id"),
                "current_channel": bool(item.get("current_channel")),
            },
        })
    return options
