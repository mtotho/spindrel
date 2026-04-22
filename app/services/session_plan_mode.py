from __future__ import annotations

import copy
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm.attributes import flag_modified

from app.agent.bots import get_bot
from app.db.models import Session
from app.services.channel_workspace import ensure_channel_workspace

PLAN_MODE_METADATA_KEY = "plan_mode"
PLAN_PATH_METADATA_KEY = "plan_active_path"
PLAN_SLUG_METADATA_KEY = "plan_task_slug"
PLAN_REVISION_METADATA_KEY = "plan_revision"
PLAN_ACCEPTED_REVISION_METADATA_KEY = "plan_accepted_revision"
PLAN_STATUS_METADATA_KEY = "plan_status"

PLAN_MODE_CHAT = "chat"
PLAN_MODE_PLANNING = "planning"
PLAN_MODE_EXECUTING = "executing"
PLAN_MODE_BLOCKED = "blocked"
PLAN_MODE_DONE = "done"

PLAN_STATUS_DRAFT = "draft"
PLAN_STATUS_APPROVED = "approved"
PLAN_STATUS_EXECUTING = "executing"
PLAN_STATUS_BLOCKED = "blocked"
PLAN_STATUS_DONE = "done"

STEP_STATUS_PENDING = "pending"
STEP_STATUS_IN_PROGRESS = "in_progress"
STEP_STATUS_DONE = "done"
STEP_STATUS_BLOCKED = "blocked"

_VALID_PLAN_MODES = {
    PLAN_MODE_CHAT,
    PLAN_MODE_PLANNING,
    PLAN_MODE_EXECUTING,
    PLAN_MODE_BLOCKED,
    PLAN_MODE_DONE,
}
_VALID_PLAN_STATUSES = {
    PLAN_STATUS_DRAFT,
    PLAN_STATUS_APPROVED,
    PLAN_STATUS_EXECUTING,
    PLAN_STATUS_BLOCKED,
    PLAN_STATUS_DONE,
}
_VALID_STEP_STATUSES = {
    STEP_STATUS_PENDING,
    STEP_STATUS_IN_PROGRESS,
    STEP_STATUS_DONE,
    STEP_STATUS_BLOCKED,
}

_SECTION_ORDER = (
    "summary",
    "scope",
    "assumptions",
    "open_questions",
    "steps",
    "artifacts",
    "acceptance_criteria",
    "outcome",
)
_SECTION_LABELS = {
    "summary": "Summary",
    "scope": "Scope",
    "assumptions": "Assumptions",
    "open_questions": "Open Questions",
    "steps": "Execution Checklist",
    "artifacts": "Artifacts",
    "acceptance_criteria": "Acceptance Criteria",
    "outcome": "Outcome",
}
_SECTION_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$", re.MULTILINE)
_STEP_RE = re.compile(
    r"^- \[(?P<status>pending|in_progress|done|blocked)\]\s+"
    r"(?P<id>[a-z0-9][a-z0-9_-]*)\s+\|\s+(?P<label>.+?)"
    r"(?:\s+--\s+(?P<note>.+))?$",
    re.MULTILINE,
)
_STATUS_LINE_RE = re.compile(r"^Status:\s*(.+)$", re.MULTILINE)
_REVISION_LINE_RE = re.compile(r"^Revision:\s*(\d+)$", re.MULTILINE)
_SESSION_LINE_RE = re.compile(r"^Session:\s*([0-9a-fA-F-]+)$", re.MULTILINE)
_TASK_LINE_RE = re.compile(r"^Task:\s*([a-z0-9][a-z0-9_-]*)$", re.MULTILINE)


def slugify_task(value: str) -> str:
    raw = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return raw[:80] or f"task-{uuid.uuid4().hex[:8]}"


def _clean_list(lines: list[str]) -> list[str]:
    items: list[str] = []
    for line in lines:
        text = line.strip()
        if text.startswith("- "):
            text = text[2:].strip()
        if text and text.lower() != "none":
            items.append(text)
    return items


def _format_list(items: list[str]) -> str:
    if not items:
        return "- None"
    return "\n".join(f"- {item}" for item in items)


def _normalize_free_text(value: str | None, fallback: str) -> str:
    text = (value or "").strip()
    return text or fallback


@dataclass
class PlanStep:
    id: str
    label: str
    status: str = STEP_STATUS_PENDING
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "note": self.note,
        }


@dataclass
class PlanArtifact:
    kind: str
    label: str
    ref: str | None = None
    created_at: str | None = None
    metadata: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "ref": self.ref,
            "created_at": self.created_at,
            "metadata": copy.deepcopy(self.metadata or {}),
        }


@dataclass
class SessionPlan:
    title: str
    status: str
    revision: int
    session_id: uuid.UUID
    task_slug: str
    summary: str
    scope: str
    assumptions: list[str]
    open_questions: list[str]
    steps: list[PlanStep]
    artifacts: list[PlanArtifact]
    acceptance_criteria: list[str]
    outcome: str
    path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "status": self.status,
            "revision": self.revision,
            "session_id": str(self.session_id),
            "task_slug": self.task_slug,
            "summary": self.summary,
            "scope": self.scope,
            "assumptions": list(self.assumptions),
            "open_questions": list(self.open_questions),
            "steps": [step.as_dict() for step in self.steps],
            "artifacts": [artifact.as_dict() for artifact in self.artifacts],
            "acceptance_criteria": list(self.acceptance_criteria),
            "outcome": self.outcome,
            "path": self.path,
        }


def _default_steps(title: str) -> list[PlanStep]:
    return [
        PlanStep(id="clarify-scope", label=f"Clarify scope and constraints for {title}"),
        PlanStep(id="implementation", label="Implement the agreed changes"),
        PlanStep(id="verify", label="Verify the result and summarize any follow-up"),
    ]


def render_plan_markdown(plan: SessionPlan) -> str:
    step_lines = []
    for step in plan.steps:
        note_suffix = f" -- {step.note}" if step.note else ""
        step_lines.append(f"- [{step.status}] {step.id} | {step.label}{note_suffix}")
    steps_block = "\n".join(step_lines) if step_lines else "- [pending] step-1 | Add at least one step"
    artifact_lines = []
    for artifact in plan.artifacts:
        line = artifact.label
        line += f" | kind={artifact.kind}"
        if artifact.ref:
            line += f" | ref={artifact.ref}"
        if artifact.created_at:
            line += f" | created_at={artifact.created_at}"
        if artifact.metadata:
            line += f" | metadata={json.dumps(artifact.metadata, sort_keys=True)}"
        artifact_lines.append(f"- {line}")
    artifacts_block = "\n".join(artifact_lines) if artifact_lines else "- None"
    return (
        f"# {plan.title}\n\n"
        f"Status: {plan.status}\n"
        f"Revision: {plan.revision}\n"
        f"Session: {plan.session_id}\n"
        f"Task: {plan.task_slug}\n\n"
        f"## Summary\n"
        f"{_normalize_free_text(plan.summary, 'Pending summary.')}\n\n"
        f"## Scope\n"
        f"{_normalize_free_text(plan.scope, 'Pending scope.')}\n\n"
        f"## Assumptions\n"
        f"{_format_list(plan.assumptions)}\n\n"
        f"## Open Questions\n"
        f"{_format_list(plan.open_questions)}\n\n"
        f"## Execution Checklist\n"
        f"{steps_block}\n\n"
        f"## Artifacts\n"
        f"{artifacts_block}\n\n"
        f"## Acceptance Criteria\n"
        f"{_format_list(plan.acceptance_criteria)}\n\n"
        f"## Outcome\n"
        f"{_normalize_free_text(plan.outcome, 'Pending execution.')}\n"
    )


def _extract_sections(markdown: str) -> dict[str, str]:
    matches = list(_SECTION_RE.finditer(markdown))
    sections: dict[str, str] = {}
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown)
        title = match.group("title").strip().lower()
        key = next((k for k, label in _SECTION_LABELS.items() if label.lower() == title), None)
        if key:
            sections[key] = markdown[start:end].strip()
    return sections


def parse_plan_markdown(markdown: str, *, path: str | None = None) -> SessionPlan:
    title_line = markdown.splitlines()[0].strip() if markdown.strip() else ""
    if not title_line.startswith("# "):
        raise ValueError("Plan markdown must start with a '# <title>' heading.")
    title = title_line[2:].strip()
    status_match = _STATUS_LINE_RE.search(markdown)
    revision_match = _REVISION_LINE_RE.search(markdown)
    session_match = _SESSION_LINE_RE.search(markdown)
    task_match = _TASK_LINE_RE.search(markdown)
    if not status_match or not revision_match or not session_match or not task_match:
        raise ValueError("Plan markdown is missing required metadata lines.")
    status = status_match.group(1).strip()
    if status not in _VALID_PLAN_STATUSES:
        raise ValueError(f"Invalid plan status: {status}")
    revision = int(revision_match.group(1))
    session_id = uuid.UUID(session_match.group(1))
    task_slug = task_match.group(1).strip()
    sections = _extract_sections(markdown)
    missing = [name for name in _SECTION_ORDER if name != "artifacts" and name not in sections]
    if missing:
        raise ValueError(f"Plan markdown is missing required sections: {missing}")
    sections.setdefault("artifacts", "- None")
    steps: list[PlanStep] = []
    for match in _STEP_RE.finditer(sections["steps"]):
        steps.append(
            PlanStep(
                id=match.group("id"),
                label=match.group("label").strip(),
                status=match.group("status"),
                note=(match.group("note") or "").strip() or None,
            )
        )
    artifacts: list[PlanArtifact] = []
    for line in sections["artifacts"].splitlines():
        text = line.strip()
        if not text or text.lower() == "- none":
            continue
        if text.startswith("- "):
            text = text[2:].strip()
        parts = [part.strip() for part in text.split("|")]
        label = parts[0]
        kind = "artifact"
        ref = None
        created_at = None
        metadata: dict[str, Any] | None = None
        for part in parts[1:]:
            if part.startswith("kind="):
                kind = part[len("kind="):].strip() or "artifact"
            elif part.startswith("ref="):
                ref = part[len("ref="):].strip() or None
            elif part.startswith("created_at="):
                created_at = part[len("created_at="):].strip() or None
            elif part.startswith("metadata="):
                raw = part[len("metadata="):].strip()
                if raw:
                    try:
                        parsed = json.loads(raw)
                        metadata = parsed if isinstance(parsed, dict) else {"value": parsed}
                    except json.JSONDecodeError:
                        metadata = {"raw": raw}
        artifacts.append(
            PlanArtifact(
                kind=kind,
                label=label,
                ref=ref,
                created_at=created_at,
                metadata=metadata or {},
            )
        )
    return SessionPlan(
        title=title,
        status=status,
        revision=revision,
        session_id=session_id,
        task_slug=task_slug,
        summary=sections["summary"].strip(),
        scope=sections["scope"].strip(),
        assumptions=_clean_list(sections["assumptions"].splitlines()),
        open_questions=_clean_list(sections["open_questions"].splitlines()),
        steps=steps,
        artifacts=artifacts,
        acceptance_criteria=_clean_list(sections["acceptance_criteria"].splitlines()),
        outcome=sections["outcome"].strip(),
        path=path,
    )


def _session_plan_meta(session: Session) -> dict[str, Any]:
    return copy.deepcopy(session.metadata_ or {})


def get_session_plan_mode(session: Session) -> str:
    mode = (session.metadata_ or {}).get(PLAN_MODE_METADATA_KEY) or PLAN_MODE_CHAT
    return mode if mode in _VALID_PLAN_MODES else PLAN_MODE_CHAT


def get_session_active_plan_path(session: Session) -> str | None:
    path = (session.metadata_ or {}).get(PLAN_PATH_METADATA_KEY)
    return str(path) if path else None


def get_session_plan_state(session: Session) -> dict[str, Any]:
    meta = session.metadata_ or {}
    return {
        "mode": get_session_plan_mode(session),
        "has_plan": bool(get_session_active_plan_path(session)),
        "path": get_session_active_plan_path(session),
        "task_slug": meta.get(PLAN_SLUG_METADATA_KEY),
        "revision": meta.get(PLAN_REVISION_METADATA_KEY),
        "accepted_revision": meta.get(PLAN_ACCEPTED_REVISION_METADATA_KEY),
        "status": meta.get(PLAN_STATUS_METADATA_KEY),
    }


def _plan_channel_id(session: Session) -> uuid.UUID | None:
    return session.channel_id or session.parent_channel_id


def build_plan_path(session: Session, task_slug: str) -> str:
    channel_id = _plan_channel_id(session)
    if channel_id is None:
        raise HTTPException(status_code=400, detail="Plan mode requires a channel-backed session.")
    bot = get_bot(session.bot_id)
    ws_root = ensure_channel_workspace(str(channel_id), bot)
    plan_dir = os.path.join(ws_root, ".sessions", str(session.id), "plans")
    os.makedirs(plan_dir, exist_ok=True)
    return os.path.join(plan_dir, f"{task_slug}.md")


def write_session_plan_metadata(
    session: Session,
    *,
    mode: str | None = None,
    plan_path: str | None = None,
    task_slug: str | None = None,
    revision: int | None = None,
    accepted_revision: int | None = None,
    plan_status: str | None = None,
    clear_plan: bool = False,
) -> None:
    meta = _session_plan_meta(session)
    if clear_plan:
        meta.pop(PLAN_MODE_METADATA_KEY, None)
        meta.pop(PLAN_PATH_METADATA_KEY, None)
        meta.pop(PLAN_SLUG_METADATA_KEY, None)
        meta.pop(PLAN_REVISION_METADATA_KEY, None)
        meta.pop(PLAN_ACCEPTED_REVISION_METADATA_KEY, None)
        meta.pop(PLAN_STATUS_METADATA_KEY, None)
    else:
        if mode is not None:
            meta[PLAN_MODE_METADATA_KEY] = mode
        if plan_path is not None:
            meta[PLAN_PATH_METADATA_KEY] = plan_path
        if task_slug is not None:
            meta[PLAN_SLUG_METADATA_KEY] = task_slug
        if revision is not None:
            meta[PLAN_REVISION_METADATA_KEY] = revision
        if accepted_revision is not None:
            meta[PLAN_ACCEPTED_REVISION_METADATA_KEY] = accepted_revision
        if plan_status is not None:
            meta[PLAN_STATUS_METADATA_KEY] = plan_status
    session.metadata_ = meta
    flag_modified(session, "metadata_")


def load_session_plan(session: Session, *, required: bool = False) -> SessionPlan | None:
    path = get_session_active_plan_path(session)
    if not path:
        if required:
            raise HTTPException(status_code=404, detail="Session has no active plan.")
        return None
    if not os.path.isfile(path):
        if required:
            raise HTTPException(status_code=404, detail="Active plan file is missing.")
        return None
    try:
        return parse_plan_markdown(Path(path).read_text(), path=path)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=f"Invalid active plan file: {exc}")


def save_session_plan(session: Session, plan: SessionPlan, *, mode: str | None = None, accepted_revision: int | None = None) -> SessionPlan:
    plan_path = plan.path or build_plan_path(session, plan.task_slug)
    Path(plan_path).parent.mkdir(parents=True, exist_ok=True)
    Path(plan_path).write_text(render_plan_markdown(plan))
    write_session_plan_metadata(
        session,
        mode=mode,
        plan_path=plan_path,
        task_slug=plan.task_slug,
        revision=plan.revision,
        accepted_revision=accepted_revision,
        plan_status=plan.status,
    )
    plan.path = plan_path
    return plan


def enter_session_plan_mode(session: Session) -> dict[str, Any]:
    write_session_plan_metadata(session, mode=PLAN_MODE_PLANNING)
    return get_session_plan_state(session)


def create_session_plan(
    session: Session,
    *,
    title: str,
    summary: str | None = None,
    scope: str | None = None,
    assumptions: list[str] | None = None,
    open_questions: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    steps: list[dict[str, Any]] | None = None,
) -> SessionPlan:
    task_slug = slugify_task(title)
    plan_steps = [
        PlanStep(
            id=str(item.get("id") or slugify_task(str(item.get("label") or f"step-{idx + 1}"))),
            label=str(item.get("label") or f"Step {idx + 1}"),
            status=str(item.get("status") or STEP_STATUS_PENDING),
            note=(str(item.get("note")).strip() if item.get("note") is not None else None),
        )
        for idx, item in enumerate(steps or [])
    ]
    if not plan_steps:
        plan_steps = _default_steps(title)
    plan = SessionPlan(
        title=title.strip(),
        status=PLAN_STATUS_DRAFT,
        revision=1,
        session_id=session.id,
        task_slug=task_slug,
        summary=_normalize_free_text(summary, "Pending summary."),
        scope=_normalize_free_text(scope, "Pending scope."),
        assumptions=[item.strip() for item in (assumptions or []) if item.strip()],
        open_questions=[item.strip() for item in (open_questions or []) if item.strip()],
        steps=plan_steps,
        artifacts=[],
        acceptance_criteria=[item.strip() for item in (acceptance_criteria or []) if item.strip()],
        outcome="Pending execution.",
    )
    return save_session_plan(session, plan, mode=PLAN_MODE_PLANNING)


def publish_session_plan(
    session: Session,
    *,
    title: str,
    summary: str | None = None,
    scope: str | None = None,
    assumptions: list[str] | None = None,
    open_questions: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    steps: list[dict[str, Any]] | None = None,
    outcome: str | None = None,
) -> SessionPlan:
    existing = load_session_plan(session, required=False)
    if existing is None:
        return create_session_plan(
            session,
            title=title,
            summary=summary,
            scope=scope,
            assumptions=assumptions,
            open_questions=open_questions,
            acceptance_criteria=acceptance_criteria,
            steps=steps,
        )

    existing.title = title.strip() or existing.title
    existing.summary = _normalize_free_text(summary, existing.summary)
    existing.scope = _normalize_free_text(scope, existing.scope)
    if assumptions is not None:
        existing.assumptions = [item.strip() for item in assumptions if item.strip()]
    if open_questions is not None:
        existing.open_questions = [item.strip() for item in open_questions if item.strip()]
    if acceptance_criteria is not None:
        existing.acceptance_criteria = [item.strip() for item in acceptance_criteria if item.strip()]
    if outcome is not None:
        existing.outcome = outcome.strip() or existing.outcome
    if steps is not None:
        existing.steps = [
            PlanStep(
                id=str(item.get("id") or slugify_task(str(item.get("label") or f"step-{idx + 1}"))),
                label=str(item.get("label") or f"Step {idx + 1}"),
                status=str(item.get("status") or STEP_STATUS_PENDING),
                note=(str(item.get("note")).strip() if item.get("note") is not None else None),
            )
            for idx, item in enumerate(steps)
        ]
    existing.revision += 1
    existing.status = PLAN_STATUS_DRAFT
    return save_session_plan(session, existing, mode=PLAN_MODE_PLANNING, accepted_revision=0)


def update_session_plan(
    session: Session,
    *,
    revision: int,
    title: str | None = None,
    summary: str | None = None,
    scope: str | None = None,
    assumptions: list[str] | None = None,
    open_questions: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    outcome: str | None = None,
) -> SessionPlan:
    plan = load_session_plan(session, required=True)
    assert plan is not None
    if revision != plan.revision:
        raise HTTPException(status_code=409, detail=f"Revision mismatch. Expected {plan.revision}.")
    if title is not None and title.strip():
        plan.title = title.strip()
    if summary is not None:
        plan.summary = _normalize_free_text(summary, plan.summary)
    if scope is not None:
        plan.scope = _normalize_free_text(scope, plan.scope)
    if assumptions is not None:
        plan.assumptions = [item.strip() for item in assumptions if item.strip()]
    if open_questions is not None:
        plan.open_questions = [item.strip() for item in open_questions if item.strip()]
    if acceptance_criteria is not None:
        plan.acceptance_criteria = [item.strip() for item in acceptance_criteria if item.strip()]
    if outcome is not None:
        plan.outcome = outcome.strip() or plan.outcome
    plan.revision += 1
    plan.status = PLAN_STATUS_DRAFT
    return save_session_plan(session, plan, mode=PLAN_MODE_PLANNING)


def _validate_plan_for_execution(plan: SessionPlan) -> None:
    if not plan.steps:
        raise HTTPException(status_code=422, detail="Plan must have at least one step.")
    if plan.open_questions:
        raise HTTPException(status_code=422, detail="Resolve open questions before execution.")
    if any(step.status not in _VALID_STEP_STATUSES for step in plan.steps):
        raise HTTPException(status_code=422, detail="Plan contains invalid step statuses.")


def _find_next_pending_step(plan: SessionPlan) -> PlanStep | None:
    for step in plan.steps:
        if step.status == STEP_STATUS_PENDING:
            return step
    return None


def approve_session_plan(session: Session) -> SessionPlan:
    plan = load_session_plan(session, required=True)
    assert plan is not None
    _validate_plan_for_execution(plan)
    accepted_revision = plan.revision
    active_step = next((step for step in plan.steps if step.status == STEP_STATUS_IN_PROGRESS), None)
    if active_step is None:
        next_step = _find_next_pending_step(plan)
        if next_step is not None:
            next_step.status = STEP_STATUS_IN_PROGRESS
    plan.status = PLAN_STATUS_EXECUTING
    if plan.outcome.strip().lower() == "pending execution.":
        plan.outcome = "Execution started."
    return save_session_plan(
        session,
        plan,
        mode=PLAN_MODE_EXECUTING,
        accepted_revision=accepted_revision,
    )


def exit_session_plan_mode(session: Session) -> None:
    if load_session_plan(session, required=False) is None:
        write_session_plan_metadata(session, mode=PLAN_MODE_CHAT)
        return
    plan = load_session_plan(session, required=True)
    assert plan is not None
    write_session_plan_metadata(session, mode=PLAN_MODE_CHAT, plan_status=plan.status)


def resume_session_plan_mode(session: Session) -> SessionPlan:
    plan = load_session_plan(session, required=True)
    assert plan is not None
    mode = PLAN_MODE_PLANNING
    if plan.status == PLAN_STATUS_EXECUTING:
        mode = PLAN_MODE_EXECUTING
    elif plan.status == PLAN_STATUS_BLOCKED:
        mode = PLAN_MODE_BLOCKED
    elif plan.status == PLAN_STATUS_DONE:
        mode = PLAN_MODE_DONE
    save_session_plan(
        session,
        plan,
        mode=mode,
        accepted_revision=(session.metadata_ or {}).get(PLAN_ACCEPTED_REVISION_METADATA_KEY),
    )
    return plan


def update_plan_step_status(
    session: Session,
    *,
    step_id: str,
    status: str,
    note: str | None = None,
) -> SessionPlan:
    if status not in _VALID_STEP_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid step status: {status}")
    plan = load_session_plan(session, required=True)
    assert plan is not None
    step = next((item for item in plan.steps if item.id == step_id), None)
    if step is None:
        raise HTTPException(status_code=404, detail="Plan step not found.")
    step.status = status
    if note is not None:
        step.note = note.strip() or None
    if status == STEP_STATUS_BLOCKED:
        plan.status = PLAN_STATUS_BLOCKED
        if note:
            plan.outcome = note.strip()
        return save_session_plan(session, plan, mode=PLAN_MODE_BLOCKED)
    if status == STEP_STATUS_DONE:
        next_step = _find_next_pending_step(plan)
        if next_step is not None:
            next_step.status = STEP_STATUS_IN_PROGRESS
            plan.status = PLAN_STATUS_EXECUTING
            if note:
                plan.outcome = note.strip()
            return save_session_plan(session, plan, mode=PLAN_MODE_EXECUTING)
        plan.status = PLAN_STATUS_DONE
        plan.outcome = note.strip() if note and note.strip() else "Execution complete."
        return save_session_plan(session, plan, mode=PLAN_MODE_DONE)
    if status == STEP_STATUS_IN_PROGRESS:
        for other in plan.steps:
            if other.id != step.id and other.status == STEP_STATUS_IN_PROGRESS:
                other.status = STEP_STATUS_PENDING
        plan.status = PLAN_STATUS_EXECUTING
        return save_session_plan(session, plan, mode=PLAN_MODE_EXECUTING)
    plan.status = PLAN_STATUS_APPROVED if (session.metadata_ or {}).get(PLAN_ACCEPTED_REVISION_METADATA_KEY) else PLAN_STATUS_DRAFT
    return save_session_plan(session, plan, mode=PLAN_MODE_PLANNING if plan.status == PLAN_STATUS_DRAFT else PLAN_MODE_EXECUTING)


def list_session_plans(session: Session, *, status: str | None = None) -> list[dict[str, Any]]:
    plan = load_session_plan(session, required=False)
    if plan is None:
        return []
    if status and status != "all" and plan.status != status:
        return []
    return [plan.as_dict()]


def append_plan_artifact(
    session: Session,
    *,
    kind: str,
    label: str,
    ref: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> SessionPlan:
    plan = load_session_plan(session, required=True)
    assert plan is not None
    plan.artifacts.append(
            PlanArtifact(
                kind=kind,
                label=label,
                ref=ref,
                created_at=datetime.now(timezone.utc).isoformat(),
                metadata=copy.deepcopy(metadata or {}),
            )
    )
    return save_session_plan(session, plan, mode=get_session_plan_mode(session))


def build_plan_mode_system_context(session: Session) -> list[str]:
    plan = load_session_plan(session, required=False)
    mode = get_session_plan_mode(session)
    if mode not in _VALID_PLAN_MODES or mode == PLAN_MODE_CHAT:
        return []
    lines: list[str] = []
    if plan is None:
        if mode == PLAN_MODE_PLANNING:
            return [
                "Plan mode is active. Stay in planning mode: ask clarifying questions, narrow scope, do not edit non-plan files, and do not execute implementation changes yet.",
                "When you have enough information to propose a concrete plan, publish it as the session plan artifact instead of editing application files.",
            ]
        return []
    path = plan.path or get_session_active_plan_path(session) or "<unknown>"
    if mode == PLAN_MODE_PLANNING:
        lines.append(
            "Plan mode is active. Stay in planning mode: ask clarifying questions, refine the canonical plan file, "
            "and do not edit non-plan files or execute implementation changes."
        )
        lines.append(f"Canonical plan file: {path}")
        lines.append(f"Current revision: {plan.revision} ({plan.status})")
        if plan.open_questions:
            lines.append("Outstanding questions:\n" + "\n".join(f"- {item}" for item in plan.open_questions))
    elif mode in {PLAN_MODE_EXECUTING, PLAN_MODE_BLOCKED, PLAN_MODE_DONE}:
        accepted_revision = (session.metadata_ or {}).get(PLAN_ACCEPTED_REVISION_METADATA_KEY) or plan.revision
        active_step = next((step for step in plan.steps if step.status == STEP_STATUS_IN_PROGRESS), None)
        next_step = active_step or _find_next_pending_step(plan)
        lines.append(
            "An approved plan is active. Follow the accepted plan revision, work one step at a time, "
            "and keep the plan file current as progress changes."
        )
        lines.append(f"Canonical plan file: {path}")
        lines.append(f"Accepted revision: {accepted_revision}; plan status: {plan.status}")
        if next_step is not None:
            lines.append(
                f"Current step: {next_step.id} | {next_step.label} [{next_step.status}]"
            )
        completed = [step for step in plan.steps if step.status == STEP_STATUS_DONE]
        if completed:
            lines.append("Completed steps:\n" + "\n".join(f"- {step.id} | {step.label}" for step in completed[-5:]))
    return lines


def path_allowed_for_plan_write(session: Session, resolved_path: str) -> bool:
    if get_session_plan_mode(session) != PLAN_MODE_PLANNING:
        return True
    active_plan_path = get_session_active_plan_path(session)
    if not active_plan_path:
        return False
    return os.path.realpath(active_plan_path) == os.path.realpath(resolved_path)
