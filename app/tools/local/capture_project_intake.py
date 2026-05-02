"""Capture a Project intake note to the user's chosen substrate.

Phase 4BD.3 of the Project Factory issue substrate. Replaces the bespoke
``publish_issue_intake`` write path (which created an Attention/IssueWorkPack
DB row) with a write to whatever the user configured at setup time:

- ``repo_file``      -> append to ``<canonical_repo>/<intake_target>``.
- ``repo_folder``    -> write a new file under ``<canonical_repo>/<intake_target>/``.
- ``external_tracker`` -> emit a hand-off message; do not call any external API.
- ``unset``          -> warn the user and echo the captured note so it is not lost.

Repo-local ``.agents/skills/<repo>-issues/SKILL.md`` always wins over this
tool's defaults: when a repo names a different schema or commit cadence, the
calling skill should follow that and use ``file_ops`` directly.
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
        "kind": {"type": "string"},
        "wrote": {"type": "object"},
        "handoff": {"type": "object"},
        "warning": {"type": "string"},
        "captured_note": {"type": "object"},
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
        "name": "capture_project_intake",
        "description": (
            "Capture a Project intake note (rough bug, idea, future investigation, "
            "tech-debt observation) to the substrate the user configured at setup "
            "time. Reads `intake_config` from the Project to decide where to write. "
            "Always returns the captured note so the user sees the durable record. "
            "When `intake_kind = unset`, warns the user that no convention is "
            "configured and points at `project/setup/init` to fix it. When "
            "`intake_kind = external_tracker`, returns a hand-off message instead "
            "of calling any API."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short headline (kebab-able). Becomes the inbox heading slug.",
                },
                "kind": {
                    "type": "string",
                    "enum": ["bug", "idea", "tech-debt", "question"],
                    "description": "Coarse classification used in the entry's tag line.",
                },
                "area": {
                    "type": ["string", "null"],
                    "description": "Subsystem/module/path the note is about (free-form, e.g. 'ui/chat').",
                },
                "body": {
                    "type": ["string", "null"],
                    "description": "1-10 lines of free-form context. Repro steps, links, observations.",
                },
                "project_id": {
                    "type": "string",
                    "description": "Optional Project UUID. Inferred from the current Project-bound channel or run when omitted.",
                },
            },
            "required": ["title"],
        },
    },
}, safety_tier="mutating", requires_bot_context=True, returns=_RETURNS)
async def capture_project_intake_tool(
    title: str,
    kind: str = "idea",
    area: str | None = None,
    body: str | None = None,
    project_id: str | None = None,
) -> str:
    from app.db.engine import async_session
    from app.db.models import Project
    from app.services.project_intake_writer import (
        CapturedIntakeNote,
        append_to_repo_file,
        write_to_repo_folder,
    )
    from app.services.projects import project_intake_config

    note = CapturedIntakeNote(title=title, kind=kind, area=area, body=body)
    rendered = note.normalized()
    captured_payload = {
        "title": rendered.title,
        "kind": rendered.kind,
        "area": rendered.area,
        "body": rendered.body,
        "captured_at": rendered.captured_at.isoformat(),
    }

    try:
        async with async_session() as db:
            resolved_project_id = await _infer_project_id(db, project_id)
            project = await db.get(Project, resolved_project_id)
            if project is None:
                return json.dumps({"ok": False, "error": "project not found"}, ensure_ascii=False)
            config = project_intake_config(project)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc), "captured_note": captured_payload}, ensure_ascii=False)

    intake_kind = config["kind"]

    if intake_kind == "unset":
        return json.dumps(
            {
                "ok": True,
                "kind": "unset",
                "warning": (
                    "Project has no intake convention configured. Run `project/setup/init` "
                    "(or ask the user 'where should issues live for this Project?') to set "
                    "intake_kind. Note shown below was NOT persisted."
                ),
                "captured_note": captured_payload,
            },
            ensure_ascii=False,
        )

    if intake_kind == "external_tracker":
        target = config.get("target") or ""
        tracker = (config.get("metadata") or {}).get("tracker") or "external tracker"
        return json.dumps(
            {
                "ok": True,
                "kind": "external_tracker",
                "handoff": {
                    "tracker": tracker,
                    "target": target,
                    "instructions": (
                        f"Open {target} and create a new {tracker} issue with the captured note "
                        "below. Spindrel does not write to external trackers automatically."
                    ),
                },
                "captured_note": captured_payload,
            },
            ensure_ascii=False,
        )

    # File / folder kinds need a resolvable canonical repo on disk.
    host_target_dir_or_file = config.get("host_target")
    canonical_host = None
    target_relative = config.get("target") or ""
    if host_target_dir_or_file:
        # host_target is the joined absolute path; we still need the canonical
        # repo root for the helpers, which they derive from canonical_repo_host_path.
        # The writer takes (canonical_repo_host_path, intake_target_relative) so we
        # split host_target back into its parts for clarity.
        from app.services.projects import project_canonical_repo_host_path

        canonical_host = project_canonical_repo_host_path(project)

    if not canonical_host or not target_relative:
        return json.dumps(
            {
                "ok": False,
                "error": (
                    "Cannot resolve canonical repo path for this Project. Configure a canonical "
                    "repo entry on the Blueprint (canonical: true) or set intake_kind=external_tracker."
                ),
                "captured_note": captured_payload,
            },
            ensure_ascii=False,
        )

    try:
        if intake_kind == "repo_file":
            result = append_to_repo_file(canonical_host, target_relative, note)
        elif intake_kind == "repo_folder":
            result = write_to_repo_folder(canonical_host, target_relative, note)
        else:
            return json.dumps(
                {
                    "ok": False,
                    "error": f"Unsupported intake_kind: {intake_kind}",
                    "captured_note": captured_payload,
                },
                ensure_ascii=False,
            )
    except Exception as exc:
        return json.dumps(
            {"ok": False, "error": str(exc), "captured_note": captured_payload},
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "ok": True,
            "kind": intake_kind,
            "wrote": {
                "host_path": result.host_path,
                "relative_path": result.relative_path,
                "appended": result.appended,
                "created_file": result.created_file,
                "slug": result.slug,
                "timestamp": result.timestamp,
            },
            "captured_note": captured_payload,
        },
        ensure_ascii=False,
    )
