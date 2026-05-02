"""Propose Run Packs into a repo-resident markdown artifact.

Phase 4BD.4 of the Project Factory issue substrate. Replaces the bespoke
``create_issue_work_packs`` tool (which wrote to the ``issue_work_packs`` DB
table). Pack proposals are now appended to a markdown section under the
Project's canonical repo so they version with the rest of the codebase and
can be reviewed by humans / agents through normal text tools.
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
        "wrote": {"type": "object"},
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
        "name": "propose_run_packs",
        "description": (
            "Propose one or more Run Packs (launchable Project coding-run units) by "
            "writing them into a markdown section in a repo-resident artifact. The "
            "artifact lives under the Project's canonical repo (typically a Track, "
            "PRD, or audit document). Each pack becomes a `### <title>` block under "
            "the named section. Idempotent: re-running this tool against the same "
            "section replaces its contents, so revising a proposal is safe. Use after "
            "a planning conversation when the user has decided which units of work "
            "should be launchable."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "packs": {
                    "type": "array",
                    "description": "One or more pack proposals.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "summary": {"type": "string"},
                            "category": {
                                "type": "string",
                                "enum": [
                                    "code_bug", "test_failure", "config_issue",
                                    "environment_issue", "user_decision",
                                    "not_code_work", "needs_info", "other",
                                ],
                            },
                            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                            "launch_prompt": {"type": "string"},
                            "blueprint_impact": {"type": "boolean"},
                            "source_item_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["title", "summary", "category", "confidence"],
                    },
                },
                "source_artifact_path": {
                    "type": "string",
                    "description": (
                        "Repo-relative path of the markdown file to write into "
                        "(e.g. `docs/tracks/<slug>.md`, `.spindrel/audits/<slug>.md`)."
                    ),
                },
                "section": {
                    "type": "string",
                    "description": (
                        "Markdown ## heading under which packs are rendered. "
                        "Defaults to 'Proposed Run Packs'. Re-running with the "
                        "same section replaces its contents."
                    ),
                },
                "project_id": {
                    "type": "string",
                    "description": "Optional Project UUID. Inferred from the current Project-bound channel/run when omitted.",
                },
            },
            "required": ["packs", "source_artifact_path"],
        },
    },
}, safety_tier="mutating", requires_bot_context=True, returns=_RETURNS)
async def propose_run_packs_tool(
    packs: list[dict],
    source_artifact_path: str,
    section: str | None = None,
    project_id: str | None = None,
) -> str:
    from app.db.engine import async_session
    from app.db.models import Project
    from app.services.project_run_pack_writer import (
        DEFAULT_SECTION,
        write_run_pack_proposals,
    )
    from app.services.projects import project_canonical_repo_host_path

    if not isinstance(packs, list) or not packs:
        return json.dumps({"ok": False, "error": "packs must be a non-empty list"}, ensure_ascii=False)
    if not source_artifact_path or not str(source_artifact_path).strip():
        return json.dumps({"ok": False, "error": "source_artifact_path is required"}, ensure_ascii=False)
    target_section = (section or DEFAULT_SECTION).strip() or DEFAULT_SECTION

    try:
        async with async_session() as db:
            resolved_project_id = await _infer_project_id(db, project_id)
            project = await db.get(Project, resolved_project_id)
            if project is None:
                return json.dumps({"ok": False, "error": "project not found"}, ensure_ascii=False)
            canonical_host = project_canonical_repo_host_path(project)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    if not canonical_host:
        return json.dumps(
            {
                "ok": False,
                "error": (
                    "Cannot resolve canonical repo path for this Project. Configure a "
                    "canonical repo entry on the Blueprint (canonical: true) before "
                    "proposing Run Packs."
                ),
            },
            ensure_ascii=False,
        )

    try:
        result = write_run_pack_proposals(
            canonical_host,
            str(source_artifact_path).strip(),
            target_section,
            packs,
        )
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    return json.dumps(
        {
            "ok": True,
            "wrote": {
                "host_path": result.host_path,
                "relative_path": result.relative_path,
                "section": result.section,
                "pack_count": result.pack_count,
                "created_file": result.created_file,
            },
        },
        ensure_ascii=False,
    )
