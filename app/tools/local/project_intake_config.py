"""Set the Project's intake convention - where issues should be captured.

Single tool. Persists the chosen convention so the generic intake skill knows
which write path to use (a file in the canonical repo, a folder in the canonical
repo, an external tracker URL, or unset). Idempotency is the caller's job: the
project/setup/init skill checks `intake_kind != "unset"` before prompting and
only re-asks when the user explicitly says "reconfigure intake."
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.agent.context import (
    current_channel_id,
    current_project_instance_id,
)
from app.tools.registry import register


_RETURNS = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "intake_config": {"type": "object"},
        "previous_kind": {"type": "string"},
        "error": {"type": "string"},
    },
    "required": ["ok"],
}


async def _infer_project_id(db, explicit_project_id: str | None) -> uuid.UUID:
    from app.db.models import Channel, ProjectInstance

    if explicit_project_id:
        return uuid.UUID(str(explicit_project_id))

    instance_id = current_project_instance_id.get()
    if instance_id:
        instance = await db.get(ProjectInstance, uuid.UUID(str(instance_id)))
        if instance is not None:
            return instance.project_id

    channel_id = current_channel_id.get()
    if channel_id is not None:
        channel = await db.get(Channel, uuid.UUID(str(channel_id)))
        if channel is not None and channel.project_id is not None:
            return channel.project_id

    raise ValueError("project_id is required when the current channel is not Project-bound")


@register({
    "type": "function",
    "function": {
        "name": "update_project_intake_config",
        "description": (
            "Persist the Project's chosen issue-intake convention. `kind` is one of "
            "'unset', 'repo_file', 'repo_folder', 'external_tracker'. For repo kinds, "
            "`target` is a path relative to the canonical repo (e.g. 'docs/inbox.md' or "
            "'docs/inbox/'). For external_tracker, `target` is the canonical URL. `metadata` "
            "is free-form per-kind config (e.g. {tracker: 'github', label: 'inbox'}). "
            "Returns the resolved intake_config (kind/target/metadata/host_target/configured) "
            "after the write so callers can verify the canonical-repo path resolved correctly."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["unset", "repo_file", "repo_folder", "external_tracker"],
                    "description": "Where issues should be captured.",
                },
                "target": {
                    "type": ["string", "null"],
                    "description": (
                        "Repo-relative path for repo_file/repo_folder; URL for external_tracker; "
                        "null/omitted for unset."
                    ),
                },
                "metadata": {
                    "type": "object",
                    "description": "Free-form per-kind config. Replaces existing metadata when provided.",
                },
                "project_id": {
                    "type": "string",
                    "description": "Optional Project UUID. Inferred from the current Project-bound channel or run when omitted.",
                },
            },
            "required": ["kind"],
        },
    },
}, safety_tier="mutating", requires_bot_context=True, returns=_RETURNS)
async def update_project_intake_config_tool(
    kind: str,
    target: str | None = None,
    metadata: dict[str, Any] | None = None,
    project_id: str | None = None,
) -> str:
    from app.db.engine import async_session
    from app.db.models import Project
    from app.services.projects import (
        normalize_project_intake_kind,
        project_intake_config,
    )

    try:
        normalized_kind = normalize_project_intake_kind(kind)
    except ValueError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    try:
        async with async_session() as db:
            resolved_project_id = await _infer_project_id(db, project_id)
            project = await db.get(Project, resolved_project_id)
            if project is None:
                return json.dumps({"ok": False, "error": "project not found"}, ensure_ascii=False)

            previous_kind = project.intake_kind or "unset"
            project.intake_kind = normalized_kind
            project.intake_target = (target or None) if normalized_kind != "unset" else None
            if metadata is not None:
                project.intake_metadata = dict(metadata)
            elif normalized_kind == "unset":
                project.intake_metadata = {}
            await db.commit()
            await db.refresh(project)
            config = project_intake_config(project)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    return json.dumps(
        {"ok": True, "intake_config": config, "previous_kind": previous_kind},
        ensure_ascii=False,
    )
