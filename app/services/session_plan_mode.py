from __future__ import annotations

import copy
import difflib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.domain.errors import ConflictError, NotFoundError, UnprocessableError, ValidationError
from sqlalchemy.orm.attributes import flag_modified

from app.agent.bots import get_bot
from app.config import settings
from app.db.models import Session
from app.services.channel_workspace import ensure_channel_workspace

PLAN_MODE_METADATA_KEY = "plan_mode"
PLAN_PATH_METADATA_KEY = "plan_active_path"
PLAN_SLUG_METADATA_KEY = "plan_task_slug"
PLAN_REVISION_METADATA_KEY = "plan_revision"
PLAN_ACCEPTED_REVISION_METADATA_KEY = "plan_accepted_revision"
PLAN_STATUS_METADATA_KEY = "plan_status"
PLAN_RUNTIME_METADATA_KEY = "plan_runtime"
PLAN_PLANNING_STATE_METADATA_KEY = "planning_state"
PLAN_ADHERENCE_METADATA_KEY = "plan_adherence"

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

PLAN_VALIDATION_ERROR = "error"
PLAN_VALIDATION_WARNING = "warning"

PLAN_MUTATING_TOOL_ALLOWLIST = frozenset({"publish_plan"})
PLAN_EXECUTION_OUTCOME_TOOL_ALLOWLIST = frozenset({"record_plan_progress", "request_plan_replan"})
PLAN_GUIDED_SUBAGENT_TOOL = "spawn_subagents"
_PLANNING_STATE_LIST_LIMIT = 12
_ADHERENCE_EVIDENCE_LIMIT = 20
_ADHERENCE_OUTCOME_LIMIT = 20
_ADHERENCE_SEMANTIC_REVIEW_LIMIT = 12
_INCOMPLETE_STEP_DONE_NOTE_RE = re.compile(
    r"\b(awaiting|pending|unverified|not verified|needs verification|needs review|todo|not done)\b",
    re.I,
)

PLAN_PROGRESS_OUTCOME_PROGRESS = "progress"
PLAN_PROGRESS_OUTCOME_VERIFICATION = "verification"
PLAN_PROGRESS_OUTCOME_STEP_DONE = "step_done"
PLAN_PROGRESS_OUTCOME_BLOCKED = "blocked"
PLAN_PROGRESS_OUTCOME_NO_PROGRESS = "no_progress"
_VALID_PLAN_PROGRESS_OUTCOMES = {
    PLAN_PROGRESS_OUTCOME_PROGRESS,
    PLAN_PROGRESS_OUTCOME_VERIFICATION,
    PLAN_PROGRESS_OUTCOME_STEP_DONE,
    PLAN_PROGRESS_OUTCOME_BLOCKED,
    PLAN_PROGRESS_OUTCOME_NO_PROGRESS,
}

PLAN_SEMANTIC_REVIEW_SUPPORTED = "supported"
PLAN_SEMANTIC_REVIEW_WEAK_SUPPORT = "weak_support"
PLAN_SEMANTIC_REVIEW_UNSUPPORTED = "unsupported"
PLAN_SEMANTIC_REVIEW_NEEDS_REPLAN = "needs_replan"
_VALID_PLAN_SEMANTIC_VERDICTS = {
    PLAN_SEMANTIC_REVIEW_SUPPORTED,
    PLAN_SEMANTIC_REVIEW_WEAK_SUPPORT,
    PLAN_SEMANTIC_REVIEW_UNSUPPORTED,
    PLAN_SEMANTIC_REVIEW_NEEDS_REPLAN,
}

PLAN_SEMANTIC_STATUS_OK = "ok"
PLAN_SEMANTIC_STATUS_WARNING = "warning"
PLAN_SEMANTIC_STATUS_NEEDS_REPLAN = "needs_replan"
PLAN_SEMANTIC_STATUS_UNKNOWN = "unknown"
_VALID_PLAN_SEMANTIC_STATUSES = {
    PLAN_SEMANTIC_STATUS_OK,
    PLAN_SEMANTIC_STATUS_WARNING,
    PLAN_SEMANTIC_STATUS_NEEDS_REPLAN,
    PLAN_SEMANTIC_STATUS_UNKNOWN,
}

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
    "key_changes",
    "interfaces",
    "assumptions",
    "assumptions_and_defaults",
    "open_questions",
    "steps",
    "test_plan",
    "artifacts",
    "acceptance_criteria",
    "risks",
    "outcome",
)
_OPTIONAL_SECTION_KEYS = {
    "key_changes",
    "interfaces",
    "assumptions_and_defaults",
    "test_plan",
    "artifacts",
    "risks",
}
_SECTION_LABELS = {
    "summary": "Summary",
    "scope": "Scope",
    "key_changes": "Key Changes",
    "interfaces": "Interfaces",
    "assumptions": "Assumptions",
    "assumptions_and_defaults": "Assumptions And Defaults",
    "open_questions": "Open Questions",
    "steps": "Execution Checklist",
    "test_plan": "Test Plan",
    "artifacts": "Artifacts",
    "acceptance_criteria": "Acceptance Criteria",
    "risks": "Risks",
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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _dedupe_recent_items(items: list[dict[str, Any]], *, key: str = "text", limit: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in reversed(items):
        # Prefer the canonical key, then the human label. Falling through to
        # ``item`` itself would stringify the whole dict (e.g. ``{"text": ""}``
        # becomes a non-empty unique key and bypasses the empty-value filter).
        value = str(item.get(key) or item.get("label") or "").strip().lower()
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(copy.deepcopy(item))
    deduped.reverse()
    return deduped[-limit:]


def _planning_match_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _planning_state_default() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "decisions": [],
        "open_questions": [],
        "assumptions": [],
        "constraints": [],
        "non_goals": [],
        "evidence": [],
        "preference_changes": [],
        "last_updated_at": None,
        "last_update_reason": None,
    }


def _normalize_planning_state(raw: Any) -> dict[str, Any]:
    state = _planning_state_default()
    if isinstance(raw, dict):
        for key in state:
            if key in raw:
                state[key] = copy.deepcopy(raw[key])
    for key in ("decisions", "open_questions", "assumptions", "constraints", "non_goals", "evidence", "preference_changes"):
        value = state.get(key)
        state[key] = value if isinstance(value, list) else []
    return state


def get_planning_state(session: Session) -> dict[str, Any]:
    return _normalize_planning_state((session.metadata_ or {}).get(PLAN_PLANNING_STATE_METADATA_KEY))


def _planning_state_context_lines(state: dict[str, Any]) -> list[str]:
    lines = ["Planning state capsule (visible durable planning notes):"]
    sections = (
        ("Confirmed decisions", "decisions"),
        ("Open questions", "open_questions"),
        ("Assumptions", "assumptions"),
        ("Constraints", "constraints"),
        ("Non-goals", "non_goals"),
        ("Relevant evidence", "evidence"),
        ("Preference changes", "preference_changes"),
    )
    for label, key in sections:
        items = state.get(key) or []
        if not items:
            continue
        lines.append(
            f"{label}:\n"
            + "\n".join(
                f"- {_clip_plan_context(str(item.get('text') or item.get('label') or item), 220)}"
                for item in items[-6:]
                if isinstance(item, dict)
            )
        )
    if state.get("last_updated_at"):
        lines.append(f"Last planning-state update: {state['last_updated_at']} ({state.get('last_update_reason') or 'update'})")
    return lines


def update_planning_state(
    session: Session,
    *,
    decisions: list[str | dict[str, Any]] | None = None,
    open_questions: list[str | dict[str, Any]] | None = None,
    assumptions: list[str | dict[str, Any]] | None = None,
    constraints: list[str | dict[str, Any]] | None = None,
    non_goals: list[str | dict[str, Any]] | None = None,
    evidence: list[str | dict[str, Any]] | None = None,
    preference_changes: list[str | dict[str, Any]] | None = None,
    reason: str = "planning_state_update",
) -> dict[str, Any]:
    meta = _session_plan_meta(session)
    state = _normalize_planning_state(meta.get(PLAN_PLANNING_STATE_METADATA_KEY))
    now = _utc_now_iso()

    def append_items(field: str, values: list[str | dict[str, Any]] | None) -> None:
        if not values:
            return
        for raw in values:
            if isinstance(raw, dict):
                text = str(raw.get("text") or raw.get("label") or raw.get("answer") or "").strip()
                if not text:
                    continue
                item = copy.deepcopy(raw)
                item.setdefault("text", text)
            else:
                text = str(raw).strip()
                if not text:
                    continue
                item = {"text": text}
            item.setdefault("created_at", now)
            item.setdefault("source", reason)
            state[field].append(item)
        state[field] = _dedupe_recent_items(state[field], limit=_PLANNING_STATE_LIST_LIMIT)

    append_items("decisions", decisions)
    append_items("open_questions", open_questions)
    append_items("assumptions", assumptions)
    append_items("constraints", constraints)
    append_items("non_goals", non_goals)
    append_items("evidence", evidence)
    append_items("preference_changes", preference_changes)
    state["last_updated_at"] = now
    state["last_update_reason"] = reason
    meta[PLAN_PLANNING_STATE_METADATA_KEY] = state
    session.metadata_ = meta
    flag_modified(session, "metadata_")
    return state


def record_plan_question_answers(
    session: Session,
    *,
    title: str,
    answers: list[dict[str, Any]],
    source_message_id: str | None = None,
) -> dict[str, Any]:
    decisions: list[dict[str, Any]] = []
    answered_keys: set[str] = set()
    for answer in answers:
        value = str(answer.get("answer") or "").strip()
        if not value:
            continue
        label = str(answer.get("label") or answer.get("question_id") or "Plan question").strip()
        answered_keys.update(
            key
            for key in (
                _planning_match_key(answer.get("question_id")),
                _planning_match_key(label),
            )
            if key
        )
        decisions.append({
            "text": f"{label}: {value}",
            "question_id": answer.get("question_id"),
            "label": label,
            "answer": value,
            "source_message_id": source_message_id,
            "source": "plan_question_answer",
        })
    evidence = [{
        "text": f"Answered plan question card: {title.strip() or 'Plan questions'}",
        "source_message_id": source_message_id,
        "source": "plan_question_answer",
    }] if decisions else []
    state = update_planning_state(session, decisions=decisions, evidence=evidence, reason="plan_question_answers")
    if answered_keys:
        unresolved_questions = []
        for question in state.get("open_questions") or []:
            if not isinstance(question, dict):
                unresolved_questions.append(question)
                continue
            question_keys = {
                key
                for key in (
                    _planning_match_key(question.get("question_id")),
                    _planning_match_key(question.get("label")),
                    _planning_match_key(question.get("text")),
                )
                if key
            }
            if not question_keys.intersection(answered_keys):
                unresolved_questions.append(question)
        if len(unresolved_questions) != len(state.get("open_questions") or []):
            state["open_questions"] = unresolved_questions
            meta = _session_plan_meta(session)
            meta[PLAN_PLANNING_STATE_METADATA_KEY] = state
            session.metadata_ = meta
            flag_modified(session, "metadata_")
    return state


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
    key_changes: list[str]
    interfaces: list[str]
    assumptions: list[str]
    assumptions_and_defaults: list[str]
    open_questions: list[str]
    steps: list[PlanStep]
    test_plan: list[str]
    artifacts: list[PlanArtifact]
    acceptance_criteria: list[str]
    risks: list[str]
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
            "key_changes": list(self.key_changes),
            "interfaces": list(self.interfaces),
            "assumptions": list(self.assumptions),
            "assumptions_and_defaults": list(self.assumptions_and_defaults),
            "open_questions": list(self.open_questions),
            "steps": [step.as_dict() for step in self.steps],
            "test_plan": list(self.test_plan),
            "artifacts": [artifact.as_dict() for artifact in self.artifacts],
            "acceptance_criteria": list(self.acceptance_criteria),
            "risks": list(self.risks),
            "outcome": self.outcome,
            "path": self.path,
        }


def _default_steps(title: str) -> list[PlanStep]:
    return [
        PlanStep(id="clarify-scope", label=f"Clarify scope and constraints for {title}"),
        PlanStep(id="apply-changes", label="Apply the planned implementation changes"),
        PlanStep(id="verify-result", label="Run verification and summarize any follow-up"),
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
        f"## Key Changes\n"
        f"{_format_list(plan.key_changes)}\n\n"
        f"## Interfaces\n"
        f"{_format_list(plan.interfaces)}\n\n"
        f"## Assumptions\n"
        f"{_format_list(plan.assumptions)}\n\n"
        f"## Assumptions And Defaults\n"
        f"{_format_list(plan.assumptions_and_defaults)}\n\n"
        f"## Open Questions\n"
        f"{_format_list(plan.open_questions)}\n\n"
        f"## Execution Checklist\n"
        f"{steps_block}\n\n"
        f"## Test Plan\n"
        f"{_format_list(plan.test_plan)}\n\n"
        f"## Artifacts\n"
        f"{artifacts_block}\n\n"
        f"## Acceptance Criteria\n"
        f"{_format_list(plan.acceptance_criteria)}\n\n"
        f"## Risks\n"
        f"{_format_list(plan.risks)}\n\n"
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
    missing = [name for name in _SECTION_ORDER if name not in _OPTIONAL_SECTION_KEYS and name not in sections]
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
        key_changes=_clean_list(sections.get("key_changes", "").splitlines()),
        interfaces=_clean_list(sections.get("interfaces", "").splitlines()),
        assumptions=_clean_list(sections["assumptions"].splitlines()),
        assumptions_and_defaults=_clean_list(sections.get("assumptions_and_defaults", "").splitlines()),
        open_questions=_clean_list(sections["open_questions"].splitlines()),
        steps=steps,
        test_plan=_clean_list(sections.get("test_plan", "").splitlines()),
        artifacts=artifacts,
        acceptance_criteria=_clean_list(sections["acceptance_criteria"].splitlines()),
        risks=_clean_list(sections.get("risks", "").splitlines()),
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
    plan = load_session_plan(session, required=False)
    return {
        "mode": get_session_plan_mode(session),
        "has_plan": bool(get_session_active_plan_path(session)),
        "path": get_session_active_plan_path(session),
        "task_slug": meta.get(PLAN_SLUG_METADATA_KEY),
        "revision": meta.get(PLAN_REVISION_METADATA_KEY),
        "accepted_revision": meta.get(PLAN_ACCEPTED_REVISION_METADATA_KEY),
        "status": meta.get(PLAN_STATUS_METADATA_KEY),
        "revision_count": len(list_session_plan_revisions(session)),
        "planning_state": get_planning_state(session),
        "adherence": build_plan_adherence_state(session, plan),
        "runtime": build_plan_runtime_capsule(session, plan),
        "validation": validate_plan_for_approval(plan, planning_state=get_planning_state(session)) if plan is not None else None,
    }


def _runtime_step_ids(plan: SessionPlan | None) -> tuple[str | None, str | None, str | None]:
    if plan is None:
        return None, None, None
    active = next((step for step in plan.steps if step.status == STEP_STATUS_IN_PROGRESS), None)
    pending = _find_next_pending_step(plan)
    completed = [step for step in plan.steps if step.status == STEP_STATUS_DONE]
    return (
        active.id if active else None,
        (active or pending).id if (active or pending) else None,
        completed[-1].id if completed else None,
    )


def _runtime_next_action(mode: str, plan: SessionPlan | None, validation: dict[str, Any] | None) -> str:
    if mode == PLAN_MODE_PLANNING:
        if plan is None:
            return "clarify_scope"
        if plan.open_questions:
            return "resolve_open_questions"
        if validation and not validation.get("ok"):
            return "fix_plan_validation"
        return "publish_or_approve_plan"
    if mode == PLAN_MODE_EXECUTING:
        return "execute_current_step"
    if mode == PLAN_MODE_BLOCKED:
        return "resolve_blocker_or_replan"
    if mode == PLAN_MODE_DONE:
        return "complete"
    return "chat"


def _semantic_status_from_review(review: dict[str, Any] | None) -> str:
    if not isinstance(review, dict):
        return PLAN_SEMANTIC_STATUS_UNKNOWN
    semantic_status = str(review.get("semantic_status") or "").strip()
    if semantic_status in _VALID_PLAN_SEMANTIC_STATUSES:
        return semantic_status
    verdict = str(review.get("verdict") or "").strip()
    if verdict == PLAN_SEMANTIC_REVIEW_SUPPORTED:
        return PLAN_SEMANTIC_STATUS_OK
    if verdict == PLAN_SEMANTIC_REVIEW_NEEDS_REPLAN:
        return PLAN_SEMANTIC_STATUS_NEEDS_REPLAN
    if verdict in {PLAN_SEMANTIC_REVIEW_WEAK_SUPPORT, PLAN_SEMANTIC_REVIEW_UNSUPPORTED}:
        return PLAN_SEMANTIC_STATUS_WARNING
    return PLAN_SEMANTIC_STATUS_UNKNOWN


def _runtime_semantic_needs_replan(runtime: dict[str, Any], session: Session) -> bool:
    review = _runtime_latest_semantic_review(runtime, session)
    return _semantic_status_from_review(review) == PLAN_SEMANTIC_STATUS_NEEDS_REPLAN


def _runtime_latest_semantic_review(runtime: dict[str, Any], session: Session) -> dict[str, Any] | None:
    review = runtime.get("latest_semantic_review")
    if isinstance(review, dict):
        return review
    adherence = _normalize_adherence((session.metadata_ or {}).get(PLAN_ADHERENCE_METADATA_KEY))
    review = adherence.get("latest_semantic_review")
    return review if isinstance(review, dict) else None


def _runtime_semantic_blocks_mutation(runtime: dict[str, Any], session: Session) -> bool:
    review = _runtime_latest_semantic_review(runtime, session)
    if _semantic_status_from_review(review) == PLAN_SEMANTIC_STATUS_NEEDS_REPLAN:
        return True
    return str((review or {}).get("verdict") or "").strip() == PLAN_SEMANTIC_REVIEW_UNSUPPORTED


def build_plan_runtime_capsule(session: Session, plan: SessionPlan | None = None) -> dict[str, Any]:
    """Build the compact durable execution state separate from plan prose."""
    meta = session.metadata_ or {}
    existing_raw = meta.get(PLAN_RUNTIME_METADATA_KEY)
    existing = copy.deepcopy(existing_raw if isinstance(existing_raw, dict) else {})
    mode = get_session_plan_mode(session)
    current_step_id, next_step_id, last_completed_step_id = _runtime_step_ids(plan)
    validation = validate_plan_for_approval(plan, planning_state=get_planning_state(session)) if plan is not None else None
    blockers: list[str] = []
    if plan is not None:
        blockers.extend(
            step.note or step.label
            for step in plan.steps
            if step.status == STEP_STATUS_BLOCKED
        )
    for blocker in existing.get("blockers") or []:
        if blocker and blocker not in blockers:
            blockers.append(str(blocker))

    adherence = build_plan_adherence_state(session, plan)
    runtime = {
        "schema_version": 1,
        "mode": mode,
        "plan_revision": plan.revision if plan is not None else meta.get(PLAN_REVISION_METADATA_KEY),
        "accepted_revision": meta.get(PLAN_ACCEPTED_REVISION_METADATA_KEY),
        "plan_status": plan.status if plan is not None else meta.get(PLAN_STATUS_METADATA_KEY),
        "current_step_id": current_step_id,
        "next_step_id": next_step_id,
        "last_completed_step_id": last_completed_step_id,
        "next_action": _runtime_next_action(mode, plan, validation),
        "unresolved_questions": list(plan.open_questions if plan is not None else existing.get("unresolved_questions") or []),
        "blockers": blockers,
        "replan": copy.deepcopy(existing.get("replan")),
        "pending_turn_outcome": copy.deepcopy(existing.get("pending_turn_outcome")),
        "latest_outcome": adherence.get("latest_outcome"),
        "adherence_status": adherence.get("status"),
        "semantic_status": _semantic_status_from_review(adherence.get("latest_semantic_review")),
        "latest_semantic_review": copy.deepcopy(adherence.get("latest_semantic_review")),
        "latest_evidence": adherence.get("latest_evidence"),
        "compaction_watermark_message_id": (
            str(session.summary_message_id) if getattr(session, "summary_message_id", None) else None
        ),
        "last_updated_at": existing.get("last_updated_at"),
        "last_update_reason": existing.get("last_update_reason"),
    }
    return runtime


def _adherence_default() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "unknown",
        "evidence": [],
        "outcomes": [],
        "semantic_reviews": [],
        "latest_evidence": None,
        "latest_outcome": None,
        "latest_semantic_review": None,
        "last_transition": None,
        "last_updated_at": None,
    }


def _normalize_adherence(raw: Any) -> dict[str, Any]:
    state = _adherence_default()
    if isinstance(raw, dict):
        for key in state:
            if key in raw:
                state[key] = copy.deepcopy(raw[key])
    evidence = state.get("evidence")
    state["evidence"] = evidence if isinstance(evidence, list) else []
    outcomes = state.get("outcomes")
    state["outcomes"] = outcomes if isinstance(outcomes, list) else []
    semantic_reviews = state.get("semantic_reviews")
    state["semantic_reviews"] = semantic_reviews if isinstance(semantic_reviews, list) else []
    return state


def build_plan_adherence_state(session: Session, plan: SessionPlan | None = None) -> dict[str, Any]:
    state = _normalize_adherence((session.metadata_ or {}).get(PLAN_ADHERENCE_METADATA_KEY))
    mode = get_session_plan_mode(session)
    if mode == PLAN_MODE_PLANNING:
        state["status"] = "planning"
    elif mode == PLAN_MODE_BLOCKED:
        state["status"] = "blocked"
    elif mode == PLAN_MODE_DONE:
        state["status"] = "ok"
    elif mode == PLAN_MODE_EXECUTING:
        accepted = _accepted_plan_revision(session)
        if accepted <= 0 or plan is None or plan.revision != accepted:
            state["status"] = "blocked"
        else:
            runtime_raw = (session.metadata_ or {}).get(PLAN_RUNTIME_METADATA_KEY)
            runtime = runtime_raw if isinstance(runtime_raw, dict) else {}
            if runtime.get("pending_turn_outcome"):
                state["status"] = "warning"
            elif runtime.get("replan"):
                state["status"] = "blocked"
            elif state.get("latest_outcome"):
                latest_outcome = state["latest_outcome"] if isinstance(state["latest_outcome"], dict) else {}
                if latest_outcome.get("outcome") == PLAN_PROGRESS_OUTCOME_NO_PROGRESS:
                    state["status"] = "warning"
                elif latest_outcome.get("outcome") == PLAN_PROGRESS_OUTCOME_BLOCKED:
                    state["status"] = "blocked"
                else:
                    state["status"] = "ok"
            elif state.get("latest_evidence"):
                state["status"] = "ok"
            else:
                state["status"] = "unknown"
    else:
        state["status"] = "unknown"
    return state


def record_plan_execution_evidence(
    session: Session,
    *,
    tool_name: str,
    tool_kind: str,
    status: str,
    error: str | None = None,
    tool_call_id: str | None = None,
    record_id: str | None = None,
    arguments: dict[str, Any] | None = None,
    result_summary: str | None = None,
    turn_id: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any] | None:
    plan = load_session_plan(session, required=False)
    mode = get_session_plan_mode(session)
    if mode not in {PLAN_MODE_EXECUTING, PLAN_MODE_BLOCKED, PLAN_MODE_DONE} or plan is None:
        return None
    runtime = build_plan_runtime_capsule(session, plan)
    now = _utc_now_iso()
    evidence = {
        "created_at": now,
        "plan_revision": plan.revision,
        "accepted_revision": _accepted_plan_revision(session) or None,
        "step_id": runtime.get("current_step_id") or runtime.get("next_step_id"),
        "turn_id": turn_id,
        "correlation_id": correlation_id,
        "tool_name": tool_name,
        "tool_kind": tool_kind,
        "status": status,
        "error": error,
        "tool_call_id": tool_call_id,
        "record_id": record_id,
        "arguments": copy.deepcopy(arguments or {}),
        "summary": _clip_plan_context(result_summary or error or f"{tool_name} completed", 500),
    }
    meta = _session_plan_meta(session)
    adherence = _normalize_adherence(meta.get(PLAN_ADHERENCE_METADATA_KEY))
    adherence["evidence"].append(evidence)
    adherence["evidence"] = adherence["evidence"][-_ADHERENCE_EVIDENCE_LIMIT:]
    adherence["latest_evidence"] = evidence
    adherence["last_updated_at"] = now
    adherence["last_transition"] = "tool_error" if error else "tool_evidence"
    adherence["status"] = "warning" if error else "ok"
    meta[PLAN_ADHERENCE_METADATA_KEY] = adherence
    meta[PLAN_RUNTIME_METADATA_KEY] = {
        **copy.deepcopy(meta.get(PLAN_RUNTIME_METADATA_KEY) if isinstance(meta.get(PLAN_RUNTIME_METADATA_KEY), dict) else {}),
        "adherence_status": adherence["status"],
        "latest_evidence": evidence,
        "last_updated_at": now,
        "last_update_reason": "tool_evidence",
    }
    session.metadata_ = meta
    flag_modified(session, "metadata_")
    return adherence


def record_plan_semantic_review(
    session: Session,
    review: dict[str, Any],
    *,
    plan: SessionPlan | None = None,
) -> dict[str, Any]:
    review_copy = copy.deepcopy(review if isinstance(review, dict) else {})
    verdict = str(review_copy.get("verdict") or "").strip()
    if verdict not in _VALID_PLAN_SEMANTIC_VERDICTS:
        raise UnprocessableError(f"Invalid semantic review verdict: {verdict or 'missing'}")

    review_copy["semantic_status"] = _semantic_status_from_review(review_copy)
    review_copy["created_at"] = str(review_copy.get("created_at") or _utc_now_iso())

    meta = _session_plan_meta(session)
    adherence = _normalize_adherence(meta.get(PLAN_ADHERENCE_METADATA_KEY))
    adherence["semantic_reviews"].append(review_copy)
    adherence["semantic_reviews"] = adherence["semantic_reviews"][-_ADHERENCE_SEMANTIC_REVIEW_LIMIT:]
    adherence["latest_semantic_review"] = review_copy
    adherence["last_transition"] = "semantic_review"
    adherence["last_updated_at"] = review_copy["created_at"]
    meta[PLAN_ADHERENCE_METADATA_KEY] = adherence

    runtime_raw = meta.get(PLAN_RUNTIME_METADATA_KEY)
    runtime = copy.deepcopy(runtime_raw if isinstance(runtime_raw, dict) else {})
    runtime["semantic_status"] = review_copy["semantic_status"]
    runtime["latest_semantic_review"] = review_copy
    runtime["last_updated_at"] = review_copy["created_at"]
    runtime["last_update_reason"] = "semantic_review"
    meta[PLAN_RUNTIME_METADATA_KEY] = runtime

    session.metadata_ = meta
    flag_modified(session, "metadata_")
    sync_plan_runtime_capsule(session, plan, reason="semantic_review")
    return review_copy


def _current_or_next_step_id(plan: SessionPlan | None) -> str | None:
    _current_step_id, next_step_id, _last_completed = _runtime_step_ids(plan)
    return _current_step_id or next_step_id


def _turn_ids_match(item: dict[str, Any], *, turn_id: str | None, correlation_id: str | None) -> bool:
    if turn_id and str(item.get("turn_id") or "") == turn_id:
        return True
    if correlation_id and str(item.get("correlation_id") or "") == correlation_id:
        return True
    return False


def _has_outcome_for_turn(adherence: dict[str, Any], *, turn_id: str | None, correlation_id: str | None) -> bool:
    return any(
        isinstance(item, dict) and _turn_ids_match(item, turn_id=turn_id, correlation_id=correlation_id)
        for item in adherence.get("outcomes", [])
    )


def _clear_pending_turn_outcome(runtime: dict[str, Any], *, turn_id: str | None, correlation_id: str | None) -> None:
    pending = runtime.get("pending_turn_outcome")
    if not isinstance(pending, dict):
        runtime.pop("pending_turn_outcome", None)
        return
    if not pending.get("turn_id") and not pending.get("correlation_id"):
        runtime.pop("pending_turn_outcome", None)
        return
    if _turn_ids_match(pending, turn_id=turn_id, correlation_id=correlation_id):
        runtime.pop("pending_turn_outcome", None)


def record_plan_progress_outcome(
    session: Session,
    *,
    outcome: str,
    summary: str,
    step_id: str | None = None,
    evidence: str | None = None,
    status_note: str | None = None,
    turn_id: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    outcome = str(outcome or "").strip()
    if outcome not in _VALID_PLAN_PROGRESS_OUTCOMES:
        raise UnprocessableError(f"Invalid plan progress outcome: {outcome}")
    summary_text = (summary or "").strip()
    if not summary_text:
        raise UnprocessableError("Plan progress summary is required.")

    plan = load_session_plan(session, required=True)
    assert plan is not None
    mode = get_session_plan_mode(session)
    if mode not in {PLAN_MODE_EXECUTING, PLAN_MODE_BLOCKED}:
        raise ConflictError("Plan progress can only be recorded while executing or blocked.")
    _ensure_plan_is_approved_for_execution(session, plan)

    resolved_step_id = (step_id or "").strip() or _current_or_next_step_id(plan)
    if resolved_step_id and all(step.id != resolved_step_id for step in plan.steps):
        raise NotFoundError(f"Plan step not found: {resolved_step_id}")
    if outcome in {PLAN_PROGRESS_OUTCOME_STEP_DONE, PLAN_PROGRESS_OUTCOME_BLOCKED} and not resolved_step_id:
        raise UnprocessableError(f"{outcome} requires a plan step.")
    if outcome == PLAN_PROGRESS_OUTCOME_NO_PROGRESS and not (evidence or status_note):
        raise UnprocessableError("no_progress requires evidence or a status note.")
    if outcome == PLAN_PROGRESS_OUTCOME_STEP_DONE:
        if not str(evidence or "").strip():
            raise UnprocessableError("step_done requires concrete evidence for the completed step.")
        completion_note = " ".join(part for part in [summary_text, status_note or ""] if part).strip()
        if _INCOMPLETE_STEP_DONE_NOTE_RE.search(completion_note):
            raise UnprocessableError(
                "step_done cannot describe pending, awaiting, or unverified work. "
                "Use progress, verification, blocked, or no_progress until the step is actually complete."
            )

    if outcome == PLAN_PROGRESS_OUTCOME_STEP_DONE:
        plan = update_plan_step_status(
            session,
            step_id=resolved_step_id or "",
            status=STEP_STATUS_DONE,
            note=status_note or summary_text,
        )
    elif outcome == PLAN_PROGRESS_OUTCOME_BLOCKED:
        plan = update_plan_step_status(
            session,
            step_id=resolved_step_id or "",
            status=STEP_STATUS_BLOCKED,
            note=status_note or summary_text,
        )

    now = _utc_now_iso()
    meta = _session_plan_meta(session)
    adherence = _normalize_adherence(meta.get(PLAN_ADHERENCE_METADATA_KEY))
    runtime_raw = meta.get(PLAN_RUNTIME_METADATA_KEY)
    runtime = copy.deepcopy(runtime_raw if isinstance(runtime_raw, dict) else {})
    pending = runtime.get("pending_turn_outcome")
    record_turn_id = turn_id
    record_correlation_id = correlation_id
    if isinstance(pending, dict):
        record_turn_id = str(pending.get("turn_id") or record_turn_id or "") or None
        record_correlation_id = str(pending.get("correlation_id") or record_correlation_id or "") or None
    outcome_record = {
        "created_at": now,
        "outcome": outcome,
        "summary": _clip_plan_context(summary_text, 500),
        "evidence": _clip_plan_context(evidence, 500) if evidence else None,
        "status_note": _clip_plan_context(status_note, 500) if status_note else None,
        "plan_revision": plan.revision,
        "accepted_revision": _accepted_plan_revision(session) or None,
        "step_id": resolved_step_id,
        "turn_id": record_turn_id,
        "correlation_id": record_correlation_id,
    }
    adherence["outcomes"].append(outcome_record)
    adherence["outcomes"] = adherence["outcomes"][-_ADHERENCE_OUTCOME_LIMIT:]
    adherence["latest_outcome"] = outcome_record
    adherence["last_updated_at"] = now
    adherence["last_transition"] = f"outcome_{outcome}"
    if outcome == PLAN_PROGRESS_OUTCOME_BLOCKED:
        adherence["status"] = "blocked"
    elif outcome == PLAN_PROGRESS_OUTCOME_NO_PROGRESS:
        adherence["status"] = "warning"
    else:
        adherence["status"] = "ok"

    _clear_pending_turn_outcome(runtime, turn_id=record_turn_id, correlation_id=record_correlation_id)
    runtime.update({
        "latest_outcome": outcome_record,
        "adherence_status": adherence["status"],
        "last_updated_at": now,
        "last_update_reason": f"plan_progress_{outcome}",
    })
    meta[PLAN_ADHERENCE_METADATA_KEY] = adherence
    meta[PLAN_RUNTIME_METADATA_KEY] = runtime
    session.metadata_ = meta
    flag_modified(session, "metadata_")
    sync_plan_runtime_capsule(session, plan, reason=f"plan_progress_{outcome}")
    return outcome_record


def mark_plan_turn_outcome_pending(
    session: Session,
    *,
    turn_id: str | None,
    correlation_id: str | None,
    reason: str = "missing_turn_outcome",
    assistant_summary: str | None = None,
) -> dict[str, Any] | None:
    mode = get_session_plan_mode(session)
    if mode not in {PLAN_MODE_EXECUTING, PLAN_MODE_BLOCKED}:
        return None
    plan = load_session_plan(session, required=False)
    if plan is None or _accepted_plan_revision(session) <= 0 or plan.revision != _accepted_plan_revision(session):
        return None
    meta = _session_plan_meta(session)
    adherence = _normalize_adherence(meta.get(PLAN_ADHERENCE_METADATA_KEY))
    if _has_outcome_for_turn(adherence, turn_id=turn_id, correlation_id=correlation_id):
        return None
    runtime = build_plan_runtime_capsule(session, plan)
    existing = runtime.get("pending_turn_outcome")
    if isinstance(existing, dict):
        return None

    now = _utc_now_iso()
    pending = {
        "created_at": now,
        "reason": reason,
        "turn_id": turn_id,
        "correlation_id": correlation_id,
        "plan_revision": plan.revision,
        "accepted_revision": _accepted_plan_revision(session) or None,
        "step_id": runtime.get("current_step_id") or runtime.get("next_step_id"),
        "assistant_summary": _clip_plan_context(assistant_summary, 500) if assistant_summary else None,
    }
    runtime["pending_turn_outcome"] = pending
    runtime["last_updated_at"] = now
    runtime["last_update_reason"] = reason
    adherence["status"] = "warning"
    adherence["last_transition"] = reason
    adherence["last_updated_at"] = now
    meta[PLAN_RUNTIME_METADATA_KEY] = runtime
    meta[PLAN_ADHERENCE_METADATA_KEY] = adherence
    session.metadata_ = meta
    flag_modified(session, "metadata_")
    return pending


def sync_plan_runtime_capsule(
    session: Session,
    plan: SessionPlan | None = None,
    *,
    reason: str,
) -> dict[str, Any]:
    runtime = build_plan_runtime_capsule(session, plan)
    runtime["last_updated_at"] = _utc_now_iso()
    runtime["last_update_reason"] = reason
    meta = _session_plan_meta(session)
    meta[PLAN_RUNTIME_METADATA_KEY] = runtime
    session.metadata_ = meta
    flag_modified(session, "metadata_")
    return runtime


def _plan_channel_id(session: Session) -> uuid.UUID | None:
    return session.channel_id or session.parent_channel_id


def build_plan_path(session: Session, task_slug: str) -> str:
    channel_id = _plan_channel_id(session)
    if channel_id is None:
        raise ValidationError("Plan mode requires a channel-backed session.")
    bot = get_bot(session.bot_id)
    ws_root = ensure_channel_workspace(str(channel_id), bot)
    plan_dir = os.path.join(ws_root, ".sessions", str(session.id), "plans")
    os.makedirs(plan_dir, exist_ok=True)
    return os.path.join(plan_dir, f"{task_slug}.md")


def build_plan_snapshot_path(session: Session, task_slug: str, revision: int) -> str:
    plan_path = build_plan_path(session, task_slug)
    snapshot_dir = os.path.join(os.path.dirname(plan_path), ".revisions")
    os.makedirs(snapshot_dir, exist_ok=True)
    return os.path.join(snapshot_dir, f"{task_slug}.r{revision}.md")


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
        meta.pop(PLAN_RUNTIME_METADATA_KEY, None)
        meta.pop(PLAN_PLANNING_STATE_METADATA_KEY, None)
        meta.pop(PLAN_ADHERENCE_METADATA_KEY, None)
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
            raise NotFoundError("Session has no active plan.")
        return None
    if not os.path.isfile(path):
        if required:
            raise NotFoundError("Active plan file is missing.")
        return None
    try:
        return parse_plan_markdown(Path(path).read_text(), path=path)
    except ValueError as exc:
        raise ConflictError(f"Invalid active plan file: {exc}")


def _plan_file_timestamp(path: str) -> str | None:
    try:
        return datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).isoformat()
    except OSError:
        return None


def _load_plan_from_path(path: str, *, required: bool = False) -> SessionPlan | None:
    if not os.path.isfile(path):
        if required:
            raise NotFoundError("Requested plan revision is missing.")
        return None
    try:
        return parse_plan_markdown(Path(path).read_text(), path=path)
    except ValueError as exc:
        raise ConflictError(f"Invalid plan revision file: {exc}")


def load_session_plan_revision(
    session: Session,
    revision: int,
    *,
    prefer_snapshot: bool = True,
    required: bool = False,
) -> SessionPlan | None:
    if revision <= 0:
        if required:
            raise NotFoundError("Requested plan revision is invalid.")
        return None
    task_slug = (session.metadata_ or {}).get(PLAN_SLUG_METADATA_KEY)
    current_revision = (session.metadata_ or {}).get(PLAN_REVISION_METADATA_KEY)
    if task_slug:
        snapshot_path = build_plan_snapshot_path(session, str(task_slug), revision)
        if prefer_snapshot and os.path.isfile(snapshot_path):
            return _load_plan_from_path(snapshot_path, required=required)
    current_plan = load_session_plan(session, required=False)
    if current_plan is not None and current_plan.revision == revision:
        return current_plan
    if task_slug:
        snapshot_path = build_plan_snapshot_path(session, str(task_slug), revision)
        if os.path.isfile(snapshot_path):
            return _load_plan_from_path(snapshot_path, required=required)
    if current_revision and int(current_revision) == revision:
        return current_plan
    if required:
        raise NotFoundError("Requested plan revision was not found.")
    return None


def _changed_sections(previous: SessionPlan | None, current: SessionPlan) -> list[str]:
    if previous is None:
        return []
    changed: list[str] = []
    if previous.title != current.title:
        changed.append("title")
    if previous.status != current.status:
        changed.append("status")
    if previous.summary != current.summary:
        changed.append("summary")
    if previous.scope != current.scope:
        changed.append("scope")
    if previous.key_changes != current.key_changes:
        changed.append("key_changes")
    if previous.interfaces != current.interfaces:
        changed.append("interfaces")
    if previous.assumptions != current.assumptions:
        changed.append("assumptions")
    if previous.assumptions_and_defaults != current.assumptions_and_defaults:
        changed.append("assumptions_and_defaults")
    if previous.open_questions != current.open_questions:
        changed.append("open_questions")
    if [step.as_dict() for step in previous.steps] != [step.as_dict() for step in current.steps]:
        changed.append("steps")
    if [artifact.as_dict() for artifact in previous.artifacts] != [artifact.as_dict() for artifact in current.artifacts]:
        changed.append("artifacts")
    if previous.test_plan != current.test_plan:
        changed.append("test_plan")
    if previous.acceptance_criteria != current.acceptance_criteria:
        changed.append("acceptance_criteria")
    if previous.risks != current.risks:
        changed.append("risks")
    if previous.outcome != current.outcome:
        changed.append("outcome")
    return changed


def list_session_plan_revisions(session: Session) -> list[dict[str, Any]]:
    plan = load_session_plan(session, required=False)
    if plan is None:
        return []
    current_revision = plan.revision
    accepted_revision = _accepted_plan_revision(session)
    task_slug = plan.task_slug
    seen: set[int] = set()
    entries: list[dict[str, Any]] = []
    for revision in range(current_revision, 0, -1):
        snapshot_plan = load_session_plan_revision(session, revision, prefer_snapshot=True, required=False)
        previous_snapshot = load_session_plan_revision(session, revision - 1, prefer_snapshot=True, required=False)
        if revision == current_revision:
            current_plan = plan
            changed_sections = _changed_sections(previous_snapshot, snapshot_plan or current_plan)
            entries.append({
                "revision": revision,
                "title": current_plan.title,
                "status": current_plan.status,
                "summary": current_plan.summary,
                "path": current_plan.path,
                "created_at": _plan_file_timestamp(current_plan.path) if current_plan.path else None,
                "is_active": True,
                "is_accepted": accepted_revision > 0 and revision == accepted_revision,
                "source": "current",
                "changed_sections": changed_sections,
            })
            seen.add(revision)
        if snapshot_plan is None or revision in seen:
            continue
        entries.append({
            "revision": revision,
            "title": snapshot_plan.title,
            "status": snapshot_plan.status,
            "summary": snapshot_plan.summary,
            "path": snapshot_plan.path,
            "created_at": _plan_file_timestamp(snapshot_plan.path) if snapshot_plan.path else None,
            "is_active": False,
            "is_accepted": accepted_revision > 0 and revision == accepted_revision,
            "source": "snapshot",
            "changed_sections": _changed_sections(previous_snapshot, snapshot_plan),
        })
        seen.add(revision)
    entries.sort(key=lambda item: (item["revision"], 1 if item["source"] == "current" else 0), reverse=True)
    return entries


def build_session_plan_revision_diff(
    session: Session,
    *,
    from_revision: int,
    to_revision: int,
) -> dict[str, Any]:
    from_plan = load_session_plan_revision(session, from_revision, prefer_snapshot=True, required=True)
    to_plan = load_session_plan_revision(session, to_revision, prefer_snapshot=True, required=True)
    assert from_plan is not None and to_plan is not None
    from_label = f"rev-{from_revision}"
    to_label = f"rev-{to_revision}"
    from_lines = render_plan_markdown(from_plan).splitlines()
    to_lines = render_plan_markdown(to_plan).splitlines()
    diff = "\n".join(
        difflib.unified_diff(
            from_lines,
            to_lines,
            fromfile=from_label,
            tofile=to_label,
            lineterm="",
        )
    )
    return {
        "from_revision": from_revision,
        "to_revision": to_revision,
        "changed_sections": _changed_sections(from_plan, to_plan),
        "diff": diff,
    }


def build_session_plan_response(session: Session, plan: SessionPlan | None = None) -> dict[str, Any] | None:
    current_plan = plan or load_session_plan(session, required=False)
    if current_plan is None:
        return None
    return {
        **current_plan.as_dict(),
        "mode": get_session_plan_mode(session),
        "accepted_revision": _accepted_plan_revision(session) or None,
        "revisions": list_session_plan_revisions(session),
        "planning_state": get_planning_state(session),
        "adherence": build_plan_adherence_state(session, current_plan),
        "runtime": build_plan_runtime_capsule(session, current_plan),
        "validation": validate_plan_for_approval(current_plan, planning_state=get_planning_state(session)),
    }


def publish_session_plan_event(session: Session, reason: str) -> None:
    from app.domain.channel_events import ChannelEvent, ChannelEventKind
    from app.domain.payloads import SessionPlanUpdatedPayload
    from app.services.channel_events import publish_typed

    payload = SessionPlanUpdatedPayload(
        session_id=session.id,
        reason=reason,
        state=get_session_plan_state(session),
        plan=build_session_plan_response(session),
    )
    publish_typed(
        session.id,
        ChannelEvent(
            channel_id=session.id,
            kind=ChannelEventKind.SESSION_PLAN_UPDATED,
            payload=payload,
        ),
    )


def save_session_plan(
    session: Session,
    plan: SessionPlan,
    *,
    mode: str | None = None,
    accepted_revision: int | None = None,
    reason: str = "save_plan",
) -> SessionPlan:
    plan_path = plan.path or build_plan_path(session, plan.task_slug)
    rendered = render_plan_markdown(plan)
    Path(plan_path).parent.mkdir(parents=True, exist_ok=True)
    Path(plan_path).write_text(rendered)
    if plan.status == PLAN_STATUS_DRAFT:
        snapshot_path = build_plan_snapshot_path(session, plan.task_slug, plan.revision)
        if not os.path.exists(snapshot_path):
            Path(snapshot_path).write_text(rendered)
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
    sync_plan_runtime_capsule(session, plan, reason=reason)
    return plan


def enter_session_plan_mode(session: Session) -> dict[str, Any]:
    write_session_plan_metadata(session, mode=PLAN_MODE_PLANNING)
    sync_plan_runtime_capsule(session, None, reason="enter_plan_mode")
    return get_session_plan_state(session)


def create_session_plan(
    session: Session,
    *,
    title: str,
    summary: str | None = None,
    scope: str | None = None,
    key_changes: list[str] | None = None,
    interfaces: list[str] | None = None,
    assumptions: list[str] | None = None,
    assumptions_and_defaults: list[str] | None = None,
    open_questions: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    test_plan: list[str] | None = None,
    risks: list[str] | None = None,
    steps: list[dict[str, Any]] | None = None,
) -> SessionPlan:
    plan = _build_new_session_plan(
        session,
        title=title,
        summary=summary,
        scope=scope,
        key_changes=key_changes,
        interfaces=interfaces,
        assumptions=assumptions,
        assumptions_and_defaults=assumptions_and_defaults,
        open_questions=open_questions,
        acceptance_criteria=acceptance_criteria,
        test_plan=test_plan,
        risks=risks,
        steps=steps,
    )
    return save_session_plan(session, plan, mode=PLAN_MODE_PLANNING, reason="create_plan")


def _coerce_plan_steps(title: str, steps: list[dict[str, Any]] | None) -> list[PlanStep]:
    plan_steps = [
        PlanStep(
            id=str(item.get("id") or slugify_task(str(item.get("label") or f"step-{idx + 1}"))),
            label=str(item.get("label") or f"Step {idx + 1}"),
            status=str(item.get("status") or STEP_STATUS_PENDING),
            note=(str(item.get("note")).strip() if item.get("note") is not None else None),
        )
        for idx, item in enumerate(steps or [])
    ]
    return plan_steps or _default_steps(title)


def _build_new_session_plan(
    session: Session,
    *,
    title: str,
    summary: str | None = None,
    scope: str | None = None,
    key_changes: list[str] | None = None,
    interfaces: list[str] | None = None,
    assumptions: list[str] | None = None,
    assumptions_and_defaults: list[str] | None = None,
    open_questions: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    test_plan: list[str] | None = None,
    risks: list[str] | None = None,
    steps: list[dict[str, Any]] | None = None,
) -> SessionPlan:
    task_slug = slugify_task(title)
    plan = SessionPlan(
        title=title.strip(),
        status=PLAN_STATUS_DRAFT,
        revision=1,
        session_id=session.id,
        task_slug=task_slug,
        summary=_normalize_free_text(summary, "Pending summary."),
        scope=_normalize_free_text(scope, "Pending scope."),
        key_changes=[item.strip() for item in (key_changes or []) if item.strip()],
        interfaces=[item.strip() for item in (interfaces or []) if item.strip()],
        assumptions=[item.strip() for item in (assumptions or []) if item.strip()],
        assumptions_and_defaults=[item.strip() for item in (assumptions_and_defaults or []) if item.strip()],
        open_questions=[item.strip() for item in (open_questions or []) if item.strip()],
        steps=_coerce_plan_steps(title, steps),
        test_plan=[item.strip() for item in (test_plan or []) if item.strip()],
        artifacts=[],
        acceptance_criteria=[item.strip() for item in (acceptance_criteria or []) if item.strip()],
        risks=[item.strip() for item in (risks or []) if item.strip()],
        outcome="Pending execution.",
    )
    return plan


def preview_session_plan_publish(
    session: Session,
    *,
    title: str,
    summary: str | None = None,
    scope: str | None = None,
    key_changes: list[str] | None = None,
    interfaces: list[str] | None = None,
    assumptions: list[str] | None = None,
    assumptions_and_defaults: list[str] | None = None,
    open_questions: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    test_plan: list[str] | None = None,
    risks: list[str] | None = None,
    steps: list[dict[str, Any]] | None = None,
    outcome: str | None = None,
) -> SessionPlan:
    existing = load_session_plan(session, required=False)
    if existing is None:
        plan = _build_new_session_plan(
            session,
            title=title,
            summary=summary,
            scope=scope,
            key_changes=key_changes,
            interfaces=interfaces,
            assumptions=assumptions,
            assumptions_and_defaults=assumptions_and_defaults,
            open_questions=open_questions,
            acceptance_criteria=acceptance_criteria,
            test_plan=test_plan,
            risks=risks,
            steps=steps,
        )
        if outcome is not None:
            plan.outcome = outcome.strip() or plan.outcome
        return plan

    plan = copy.deepcopy(existing)
    plan.title = title.strip() or plan.title
    plan.summary = _normalize_free_text(summary, plan.summary)
    plan.scope = _normalize_free_text(scope, plan.scope)
    if key_changes is not None:
        plan.key_changes = [item.strip() for item in key_changes if item.strip()]
    if interfaces is not None:
        plan.interfaces = [item.strip() for item in interfaces if item.strip()]
    if assumptions is not None:
        plan.assumptions = [item.strip() for item in assumptions if item.strip()]
    if assumptions_and_defaults is not None:
        plan.assumptions_and_defaults = [item.strip() for item in assumptions_and_defaults if item.strip()]
    if open_questions is not None:
        plan.open_questions = [item.strip() for item in open_questions if item.strip()]
    if acceptance_criteria is not None:
        plan.acceptance_criteria = [item.strip() for item in acceptance_criteria if item.strip()]
    if test_plan is not None:
        plan.test_plan = [item.strip() for item in test_plan if item.strip()]
    if risks is not None:
        plan.risks = [item.strip() for item in risks if item.strip()]
    if outcome is not None:
        plan.outcome = outcome.strip() or plan.outcome
    if steps is not None:
        plan.steps = _coerce_plan_steps(plan.title, steps)
    plan.revision += 1
    plan.status = PLAN_STATUS_DRAFT
    return plan


def publish_session_plan(
    session: Session,
    *,
    title: str,
    summary: str | None = None,
    scope: str | None = None,
    key_changes: list[str] | None = None,
    interfaces: list[str] | None = None,
    assumptions: list[str] | None = None,
    assumptions_and_defaults: list[str] | None = None,
    open_questions: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    test_plan: list[str] | None = None,
    risks: list[str] | None = None,
    steps: list[dict[str, Any]] | None = None,
    outcome: str | None = None,
) -> SessionPlan:
    plan = preview_session_plan_publish(
        session,
        title=title,
        summary=summary,
        scope=scope,
        key_changes=key_changes,
        interfaces=interfaces,
        assumptions=assumptions,
        assumptions_and_defaults=assumptions_and_defaults,
        open_questions=open_questions,
        acceptance_criteria=acceptance_criteria,
        test_plan=test_plan,
        risks=risks,
        outcome=outcome,
        steps=steps,
    )
    return save_session_plan(
        session,
        plan,
        mode=PLAN_MODE_PLANNING,
        accepted_revision=_accepted_plan_revision(session) or 0,
        reason="publish_plan",
    )


def update_session_plan(
    session: Session,
    *,
    revision: int,
    title: str | None = None,
    summary: str | None = None,
    scope: str | None = None,
    key_changes: list[str] | None = None,
    interfaces: list[str] | None = None,
    assumptions: list[str] | None = None,
    assumptions_and_defaults: list[str] | None = None,
    open_questions: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    test_plan: list[str] | None = None,
    risks: list[str] | None = None,
    outcome: str | None = None,
) -> SessionPlan:
    plan = load_session_plan(session, required=True)
    assert plan is not None
    if revision != plan.revision:
        raise ConflictError(f"Revision mismatch. Expected {plan.revision}.")
    if title is not None and title.strip():
        plan.title = title.strip()
    if summary is not None:
        plan.summary = _normalize_free_text(summary, plan.summary)
    if scope is not None:
        plan.scope = _normalize_free_text(scope, plan.scope)
    if key_changes is not None:
        plan.key_changes = [item.strip() for item in key_changes if item.strip()]
    if interfaces is not None:
        plan.interfaces = [item.strip() for item in interfaces if item.strip()]
    if assumptions is not None:
        plan.assumptions = [item.strip() for item in assumptions if item.strip()]
    if assumptions_and_defaults is not None:
        plan.assumptions_and_defaults = [item.strip() for item in assumptions_and_defaults if item.strip()]
    if open_questions is not None:
        plan.open_questions = [item.strip() for item in open_questions if item.strip()]
    if acceptance_criteria is not None:
        plan.acceptance_criteria = [item.strip() for item in acceptance_criteria if item.strip()]
    if test_plan is not None:
        plan.test_plan = [item.strip() for item in test_plan if item.strip()]
    if risks is not None:
        plan.risks = [item.strip() for item in risks if item.strip()]
    if outcome is not None:
        plan.outcome = outcome.strip() or plan.outcome
    plan.revision += 1
    plan.status = PLAN_STATUS_DRAFT
    return save_session_plan(
        session,
        plan,
        mode=PLAN_MODE_PLANNING,
        accepted_revision=_accepted_plan_revision(session) or 0,
        reason="update_plan",
    )


def _validate_plan_for_execution(plan: SessionPlan) -> None:
    validation = validate_plan_for_approval(plan)
    if not validation["ok"]:
        messages = "; ".join(issue["message"] for issue in validation["issues"] if issue["severity"] == PLAN_VALIDATION_ERROR)
        raise UnprocessableError(messages or "Plan is not ready for execution.")


def _is_placeholder_text(value: str | None, placeholders: set[str]) -> bool:
    text = " ".join((value or "").strip().split()).lower()
    return not text or text in placeholders


def _validation_issue(
    code: str,
    message: str,
    *,
    field: str,
    severity: str = PLAN_VALIDATION_ERROR,
) -> dict[str, str]:
    return {
        "code": code,
        "severity": severity,
        "field": field,
        "message": message,
    }


def _has_substantive_list_item(items: list[str], placeholders: set[str] | None = None) -> bool:
    placeholders = placeholders or {"none", "n/a", "na", "pending", "todo", "tbd"}
    return any(not _is_placeholder_text(item, placeholders) for item in items)


def _planning_state_has_publish_signal(planning_state: dict[str, Any]) -> bool:
    """Return whether durable planning notes show enough intent to draft."""
    signal_fields = ("decisions", "assumptions", "constraints", "non_goals", "evidence", "preference_changes")
    for field in signal_fields:
        for item in planning_state.get(field) or []:
            if isinstance(item, dict) and str(item.get("text") or item.get("label") or item).strip():
                return True
            if not isinstance(item, dict) and str(item).strip():
                return True
    return False


def validate_plan_for_publish(
    session: Session,
    *,
    assumptions: list[str] | None = None,
    assumptions_and_defaults: list[str] | None = None,
    open_questions: list[str] | None = None,
) -> dict[str, Any]:
    """Validate whether the native planning tool should publish a first draft.

    Approval validation decides whether a draft may execute. This readiness
    check is earlier: it prevents the model from using ``publish_plan`` as a
    substitute for narrowing scope on the first visible plan.
    """
    issues: list[dict[str, str]] = []
    existing = load_session_plan(session, required=False)
    if existing is not None:
        return {"ok": True, "blocking_count": 0, "issues": []}

    carried_questions = [item.strip() for item in (open_questions or []) if item.strip()]
    if carried_questions:
        issues.append(_validation_issue(
            "publish_has_open_questions",
            "Ask or resolve key planning questions before publishing a first draft; proceed with explicit assumptions if the user requested that.",
            field="open_questions",
        ))

    planning_state = get_planning_state(session)
    has_durable_signal = _planning_state_has_publish_signal(planning_state)
    has_explicit_assumptions = (
        _has_substantive_list_item(assumptions_and_defaults or [])
        or _has_substantive_list_item(assumptions or [])
    )
    if not has_durable_signal and not has_explicit_assumptions:
        issues.append(_validation_issue(
            "publish_missing_readiness",
            "First drafts need answered planning context or explicit assumptions/defaults before publish_plan can create the plan.",
            field="planning_state",
        ))

    return {
        "ok": not issues,
        "blocking_count": len(issues),
        "issues": issues,
    }


def _is_vague_step_label(label: str) -> bool:
    text = " ".join(label.strip().lower().split())
    if not text:
        return True
    vague_exact = {
        "implement",
        "implementation",
        "implement changes",
        "implement the changes",
        "implement the agreed changes",
        "make changes",
        "fix issue",
        "fix bug",
        "test",
        "test it",
        "verify",
        "ship",
        "do work",
    }
    if text in vague_exact:
        return True
    words = text.split()
    generic_objects = {
        "change",
        "changes",
        "fix",
        "fixes",
        "issue",
        "issues",
        "bug",
        "bugs",
        "it",
        "thing",
        "things",
        "stuff",
        "work",
        "task",
        "tasks",
    }
    if (
        len(words) <= 3
        and words[0] in {"implement", "fix", "update", "test", "verify"}
        and all(word in generic_objects or word == words[0] for word in words[1:])
    ):
        return True
    return False


def validate_plan_for_approval(
    plan: SessionPlan | None,
    *,
    planning_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    if plan is None:
        issues.append(_validation_issue(
            "missing_plan",
            "Publish a plan before approval.",
            field="plan",
        ))
    else:
        if _is_placeholder_text(plan.summary, {"pending summary.", "pending summary", "none"}):
            issues.append(_validation_issue(
                "missing_summary",
                "Plan summary must describe the intended outcome.",
                field="summary",
            ))
        if _is_placeholder_text(plan.scope, {"pending scope.", "pending scope", "none"}):
            issues.append(_validation_issue(
                "missing_scope",
                "Plan scope must define what is in and out of the work.",
                field="scope",
            ))
        elif not re.search(r"\b(out of scope|not in scope|non-goal|non-goals|only|exclude|excludes|excluded)\b", plan.scope.lower()):
            issues.append(_validation_issue(
                "scope_missing_boundary",
                "Plan scope should state an explicit boundary or non-goal.",
                field="scope",
                severity=PLAN_VALIDATION_WARNING,
            ))
        if not _has_substantive_list_item(plan.key_changes):
            issues.append(_validation_issue(
                "missing_key_changes",
                "Add key implementation changes before approval, or explicitly state that no implementation changes are needed.",
                field="key_changes",
            ))
        if not _has_substantive_list_item(plan.interfaces):
            issues.append(_validation_issue(
                "missing_interfaces",
                "Add public API/type/interface impact before approval, even if the answer is no interface changes.",
                field="interfaces",
            ))
        if not _has_substantive_list_item(plan.assumptions_and_defaults) and not _has_substantive_list_item(plan.assumptions):
            issues.append(_validation_issue(
                "missing_assumptions_and_defaults",
                "Record assumptions/defaults before approval, even if there are no unresolved assumptions.",
                field="assumptions_and_defaults",
            ))
        if plan.open_questions:
            issues.append(_validation_issue(
                "open_questions",
                "Resolve open questions before approval.",
                field="open_questions",
            ))
        if not plan.acceptance_criteria:
            issues.append(_validation_issue(
                "missing_acceptance_criteria",
                "Add at least one acceptance criterion before approval.",
                field="acceptance_criteria",
            ))
        if not plan.steps:
            issues.append(_validation_issue(
                "missing_steps",
                "Plan must have at least one execution step.",
                field="steps",
            ))
        if not _has_substantive_list_item(plan.test_plan):
            issues.append(_validation_issue(
                "missing_test_plan",
                "Add a concrete verification/test plan before approval.",
                field="test_plan",
            ))
        seen_step_ids: set[str] = set()
        for idx, step in enumerate(plan.steps):
            field = f"steps[{idx}]"
            if step.status not in _VALID_STEP_STATUSES:
                issues.append(_validation_issue(
                    "invalid_step_status",
                    f"Step {step.id!r} has invalid status {step.status!r}.",
                    field=f"{field}.status",
                ))
            elif step.status == STEP_STATUS_BLOCKED:
                issues.append(_validation_issue(
                    "blocked_step_before_approval",
                    f"Step {step.id!r} is blocked; revise or reset it before approval.",
                    field=f"{field}.status",
                ))
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", step.id or ""):
                issues.append(_validation_issue(
                    "invalid_step_id",
                    f"Step id {step.id!r} must be stable kebab/snake case.",
                    field=f"{field}.id",
                ))
            if step.id in seen_step_ids:
                issues.append(_validation_issue(
                    "duplicate_step_id",
                    f"Step id {step.id!r} is duplicated.",
                    field=f"{field}.id",
                ))
            seen_step_ids.add(step.id)
            if _is_placeholder_text(step.label, {"step", "todo", "pending", "implementation"}):
                issues.append(_validation_issue(
                    "thin_step_label",
                    f"Step {step.id!r} needs a concrete action label.",
                    field=f"{field}.label",
                ))
            elif _is_vague_step_label(step.label):
                issues.append(_validation_issue(
                    "vague_step_label",
                    f"Step {step.id!r} needs a concrete, outcome-oriented action label.",
                    field=f"{field}.label",
                ))
        if len(plan.steps) == 1:
            issues.append(_validation_issue(
                "single_step_plan",
                "Single-step plans are allowed, but consider whether verification should be explicit.",
                field="steps",
                severity=PLAN_VALIDATION_WARNING,
            ))
        if planning_state:
            plan_text = " ".join([
                plan.title,
                plan.summary,
                plan.scope,
                " ".join(plan.key_changes),
                " ".join(plan.interfaces),
                " ".join(plan.assumptions),
                " ".join(plan.assumptions_and_defaults),
                " ".join(plan.open_questions),
                " ".join(plan.acceptance_criteria),
                " ".join(plan.test_plan),
                " ".join(plan.risks),
                " ".join(step.label for step in plan.steps),
            ]).lower()
            missing_decisions = [
                item for item in planning_state.get("decisions", [])[-6:]
                if isinstance(item, dict)
                and str(item.get("text") or "").strip()
                and str(item.get("text") or "").strip().lower()[:80] not in plan_text
            ]
            if missing_decisions:
                issues.append(_validation_issue(
                    "planning_state_not_reflected",
                    "Some confirmed planning decisions are not visibly reflected in the draft.",
                    field="planning_state.decisions",
                    severity=PLAN_VALIDATION_WARNING,
                ))
            unresolved_questions = [
                item for item in planning_state.get("open_questions", [])
                if isinstance(item, dict) and str(item.get("text") or "").strip()
            ]
            if unresolved_questions and not plan.open_questions:
                issues.append(_validation_issue(
                    "planning_questions_not_carried_forward",
                    "Planning notes still contain open questions; carry them into the draft or resolve them.",
                    field="open_questions",
                    severity=PLAN_VALIDATION_WARNING,
                ))
    blocking = [issue for issue in issues if issue["severity"] == PLAN_VALIDATION_ERROR]
    warnings = [issue for issue in issues if issue["severity"] == PLAN_VALIDATION_WARNING]
    return {
        "ok": not blocking,
        "blocking_count": len(blocking),
        "warning_count": len(warnings),
        "issues": issues,
    }


def _find_next_pending_step(plan: SessionPlan) -> PlanStep | None:
    for step in plan.steps:
        if step.status == STEP_STATUS_PENDING:
            return step
    return None


def _accepted_plan_revision(session: Session) -> int:
    accepted = (session.metadata_ or {}).get(PLAN_ACCEPTED_REVISION_METADATA_KEY)
    try:
        return int(accepted or 0)
    except (TypeError, ValueError):
        return 0


def _ensure_plan_is_approved_for_execution(session: Session, plan: SessionPlan) -> int:
    accepted_revision = _accepted_plan_revision(session)
    if accepted_revision <= 0:
        raise ConflictError(
            "Execution status cannot change until the current plan revision is approved.",
        )
    if plan.revision != accepted_revision:
        raise ConflictError(
            f"Execution status applies only to accepted revision {accepted_revision}. "
            f"Revision {plan.revision} is still a draft.",
        )
    return accepted_revision


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
        reason="approve_plan",
    )


def exit_session_plan_mode(session: Session) -> None:
    if load_session_plan(session, required=False) is None:
        write_session_plan_metadata(session, mode=PLAN_MODE_CHAT)
        sync_plan_runtime_capsule(session, None, reason="exit_plan_mode")
        return
    plan = load_session_plan(session, required=True)
    assert plan is not None
    write_session_plan_metadata(session, mode=PLAN_MODE_CHAT, plan_status=plan.status)
    sync_plan_runtime_capsule(session, plan, reason="exit_plan_mode")


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
        reason="resume_plan",
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
        raise UnprocessableError(f"Invalid step status: {status}")
    plan = load_session_plan(session, required=True)
    assert plan is not None
    _ensure_plan_is_approved_for_execution(session, plan)
    step = next((item for item in plan.steps if item.id == step_id), None)
    if step is None:
        raise NotFoundError("Plan step not found.")
    step.status = status
    if note is not None:
        step.note = note.strip() or None
    if status == STEP_STATUS_BLOCKED:
        plan.status = PLAN_STATUS_BLOCKED
        if note:
            plan.outcome = note.strip()
        return save_session_plan(session, plan, mode=PLAN_MODE_BLOCKED, reason="step_blocked")
    if status == STEP_STATUS_DONE:
        next_step = _find_next_pending_step(plan)
        if next_step is not None:
            next_step.status = STEP_STATUS_IN_PROGRESS
            plan.status = PLAN_STATUS_EXECUTING
            if note:
                plan.outcome = note.strip()
            return save_session_plan(session, plan, mode=PLAN_MODE_EXECUTING, reason="step_done")
        plan.status = PLAN_STATUS_DONE
        plan.outcome = note.strip() if note and note.strip() else "Execution complete."
        return save_session_plan(session, plan, mode=PLAN_MODE_DONE, reason="plan_done")
    if status == STEP_STATUS_IN_PROGRESS:
        for other in plan.steps:
            if other.id != step.id and other.status == STEP_STATUS_IN_PROGRESS:
                other.status = STEP_STATUS_PENDING
        plan.status = PLAN_STATUS_EXECUTING
        return save_session_plan(session, plan, mode=PLAN_MODE_EXECUTING, reason="step_in_progress")
    plan.status = PLAN_STATUS_APPROVED
    return save_session_plan(session, plan, mode=PLAN_MODE_EXECUTING, reason="step_pending")


def request_plan_replan(
    session: Session,
    *,
    reason: str,
    affected_step_ids: list[str] | None = None,
    evidence: str | None = None,
    revision: int | None = None,
) -> SessionPlan:
    plan = load_session_plan(session, required=True)
    assert plan is not None
    if revision is not None and revision != plan.revision:
        raise ConflictError(f"Revision mismatch. Expected {plan.revision}.")
    accepted_revision = _accepted_plan_revision(session)
    if accepted_revision <= 0:
        raise ConflictError("Only an accepted plan can be marked for replanning.")

    affected = [item.strip() for item in (affected_step_ids or []) if item and item.strip()]
    unknown = [step_id for step_id in affected if all(step.id != step_id for step in plan.steps)]
    if unknown:
        raise NotFoundError(f"Unknown plan step ids: {', '.join(unknown)}")

    reason_text = reason.strip()
    if not reason_text:
        raise UnprocessableError("Replan reason is required.")
    evidence_text = (evidence or "").strip() or None

    for step in plan.steps:
        if affected and step.id not in affected:
            continue
        if step.status == STEP_STATUS_IN_PROGRESS:
            step.status = STEP_STATUS_BLOCKED
            step.note = reason_text

    question = f"Replan required: {reason_text}"
    if question not in plan.open_questions:
        plan.open_questions.append(question)
    plan.revision += 1
    plan.status = PLAN_STATUS_DRAFT
    plan.outcome = reason_text

    meta = _session_plan_meta(session)
    runtime_raw = meta.get(PLAN_RUNTIME_METADATA_KEY)
    runtime = copy.deepcopy(runtime_raw if isinstance(runtime_raw, dict) else {})
    runtime["replan"] = {
        "reason": reason_text,
        "affected_step_ids": affected,
        "evidence": evidence_text,
        "from_revision": accepted_revision,
        "created_at": _utc_now_iso(),
    }
    meta[PLAN_RUNTIME_METADATA_KEY] = runtime
    session.metadata_ = meta
    flag_modified(session, "metadata_")
    return save_session_plan(
        session,
        plan,
        mode=PLAN_MODE_PLANNING,
        accepted_revision=accepted_revision,
        reason="request_replan",
    )


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
    return save_session_plan(session, plan, mode=get_session_plan_mode(session), reason="append_artifact")


def _clip_plan_context(value: str | None, limit: int) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def build_plan_artifact_context(session: Session) -> str | None:
    """Build a compact, load-bearing context block from the canonical plan file."""
    plan = load_session_plan(session, required=False)
    mode = get_session_plan_mode(session)
    if mode not in {
        PLAN_MODE_PLANNING,
        PLAN_MODE_EXECUTING,
        PLAN_MODE_BLOCKED,
        PLAN_MODE_DONE,
    }:
        return None

    runtime = build_plan_runtime_capsule(session, plan)
    runtime_lines = [
        "Plan runtime capsule (durable execution state):",
        f"Mode: {runtime.get('mode')}",
        f"Plan revision: {runtime.get('plan_revision')}",
        f"Accepted revision: {runtime.get('accepted_revision')}",
        f"Plan status: {runtime.get('plan_status')}",
        f"Current step id: {runtime.get('current_step_id')}",
        f"Next step id: {runtime.get('next_step_id')}",
        f"Last completed step id: {runtime.get('last_completed_step_id')}",
        f"Next action: {runtime.get('next_action')}",
    ]
    if runtime.get("unresolved_questions"):
        runtime_lines.append(
            "Unresolved questions:\n" + "\n".join(
                f"- {_clip_plan_context(str(item), 180)}"
                for item in runtime.get("unresolved_questions", [])[:8]
            )
        )
    if runtime.get("blockers"):
        runtime_lines.append(
            "Blockers:\n" + "\n".join(
                f"- {_clip_plan_context(str(item), 180)}"
                for item in runtime.get("blockers", [])[:5]
            )
        )
    if runtime.get("adherence_status"):
        runtime_lines.append(f"Adherence status: {runtime.get('adherence_status')}")
    if runtime.get("semantic_status"):
        runtime_lines.append(f"Semantic review status: {runtime.get('semantic_status')}")
    if runtime.get("latest_evidence"):
        latest = runtime.get("latest_evidence") or {}
        runtime_lines.append(
            "Latest execution evidence: "
            + _clip_plan_context(
                str(latest.get("summary") or latest.get("tool_name") or "recorded"),
                240,
            )
        )
    if runtime.get("latest_outcome"):
        latest_outcome = runtime.get("latest_outcome") or {}
        runtime_lines.append(
            "Latest plan outcome: "
            + _clip_plan_context(
                f"{latest_outcome.get('outcome')}: {latest_outcome.get('summary') or 'recorded'}",
                240,
            )
        )
    if runtime.get("latest_semantic_review"):
        latest_review = runtime.get("latest_semantic_review") or {}
        runtime_lines.append(
            "Latest semantic review: "
            + _clip_plan_context(
                f"{latest_review.get('verdict')}: {latest_review.get('reason') or latest_review.get('recommended_action') or 'reviewed'}",
                240,
            )
        )
    pending_outcome = runtime.get("pending_turn_outcome") or {}
    if pending_outcome:
        runtime_lines.append(
            "Pending turn outcome: "
            + _clip_plan_context(str(pending_outcome.get("reason") or "missing"), 240)
        )
    replan = runtime.get("replan") or {}
    if replan:
        runtime_lines.append(
            "Replan request: "
            + _clip_plan_context(str(replan.get("reason") or "pending"), 240)
        )

    planning_state = get_planning_state(session)
    planning_lines = _planning_state_context_lines(planning_state)

    if plan is None:
        return "\n\n".join(["\n".join(planning_lines), "\n".join(runtime_lines)])

    path = plan.path or get_session_active_plan_path(session) or "<unknown>"
    accepted_revision = (session.metadata_ or {}).get(PLAN_ACCEPTED_REVISION_METADATA_KEY) or plan.revision

    lines = [
        "Active plan artifact (derived from the canonical plan file):",
        f"Title: {plan.title}",
        f"Path: {path}",
        f"Revision: {plan.revision}",
        f"Status: {plan.status}",
    ]
    if mode in {PLAN_MODE_EXECUTING, PLAN_MODE_BLOCKED, PLAN_MODE_DONE}:
        lines.append(f"Accepted revision: {accepted_revision}")

    if plan.summary:
        lines.append(f"Summary: {_clip_plan_context(plan.summary, 600)}")
    if plan.scope:
        lines.append(f"Scope: {_clip_plan_context(plan.scope, 600)}")
    if plan.key_changes:
        lines.append(
            "Key changes:\n" + "\n".join(
                f"- {_clip_plan_context(item, 180)}" for item in plan.key_changes[:8]
            )
        )
    if plan.interfaces:
        lines.append(
            "Interface impact:\n" + "\n".join(
                f"- {_clip_plan_context(item, 180)}" for item in plan.interfaces[:8]
            )
        )
    if plan.assumptions:
        lines.append(
            "Assumptions:\n" + "\n".join(
                f"- {_clip_plan_context(item, 180)}" for item in plan.assumptions[:8]
            )
        )
    if plan.assumptions_and_defaults:
        lines.append(
            "Assumptions/defaults:\n" + "\n".join(
                f"- {_clip_plan_context(item, 180)}" for item in plan.assumptions_and_defaults[:8]
            )
        )
    if plan.open_questions and mode == PLAN_MODE_PLANNING:
        lines.append(
            "Open questions:\n" + "\n".join(
                f"- {_clip_plan_context(item, 180)}" for item in plan.open_questions[:8]
            )
        )
    if plan.steps:
        lines.append(
            "Checklist:\n" + "\n".join(
                (
                    f"- [{step.status}] {step.id} | {_clip_plan_context(step.label, 180)}"
                    + (
                        f" -- {_clip_plan_context(step.note, 180)}"
                        if step.note else ""
                    )
                )
                for step in plan.steps[:12]
            )
        )
    if plan.test_plan:
        lines.append(
            "Test plan:\n" + "\n".join(
                f"- {_clip_plan_context(item, 180)}"
                for item in plan.test_plan[:8]
            )
        )
    if plan.acceptance_criteria:
        lines.append(
            "Acceptance criteria:\n" + "\n".join(
                f"- {_clip_plan_context(item, 180)}"
                for item in plan.acceptance_criteria[:8]
            )
        )
    if plan.risks:
        lines.append(
            "Risks:\n" + "\n".join(
                f"- {_clip_plan_context(item, 180)}"
                for item in plan.risks[:5]
            )
        )
    if plan.artifacts and mode in {PLAN_MODE_EXECUTING, PLAN_MODE_BLOCKED, PLAN_MODE_DONE}:
        lines.append(
            "Recent artifacts:\n" + "\n".join(
                f"- {artifact.kind}: {_clip_plan_context(artifact.label, 180)}"
                for artifact in plan.artifacts[-5:]
            )
        )
    if plan.outcome and plan.status == PLAN_STATUS_DONE:
        lines.append(f"Outcome: {_clip_plan_context(plan.outcome, 400)}")

    if any(planning_state.get(key) for key in ("decisions", "open_questions", "assumptions", "constraints", "non_goals", "evidence", "preference_changes")):
        lines.append("\n".join(planning_lines))
    lines.append("\n".join(runtime_lines))

    return "\n\n".join(line for line in lines if line.strip())


def build_plan_mode_system_context(session: Session) -> list[str]:
    plan = load_session_plan(session, required=False)
    mode = get_session_plan_mode(session)
    if mode not in _VALID_PLAN_MODES or mode == PLAN_MODE_CHAT:
        return []
    lines: list[str] = []
    if plan is None:
        if mode == PLAN_MODE_PLANNING:
            lines = [
                "Plan mode is active. Stay in planning mode: do not execute implementation changes, do not edit non-plan files, and do not answer with long freeform proposals before the scope is clear.",
                "Your first job in plan mode is to narrow scope. Explore/read available context first when possible, then ask at most 1-3 focused clarifying questions, preferably by using ask_plan_questions when multiple structured answers would help.",
                "If the user asks for a plan but the target subsystem, success signal, mutation scope, or verification expectation is missing, call ask_plan_questions instead of answering with prose or publishing a draft.",
                "If the user explicitly asks for a structured question card, you must use ask_plan_questions.",
                "If the user explicitly says to use publish_plan now, says not to ask follow-up questions, and provides the professional plan fields, treat that as permission to publish; do not ask a confirmation question just to confirm tool usage, exact labels, or retry behavior.",
                "A publishable plan must be decision-complete: goal and success criteria clear, scope and non-goals explicit, key implementation changes named, interface/API/type impact stated, assumptions/defaults recorded, concrete execution steps listed, and verification/test plan included.",
                "Treat the visible planning-state capsule as durable notes for the back-and-forth: preserve confirmed decisions, open questions, constraints, assumptions, non-goals, evidence, and preference changes there instead of relying only on chat history.",
                "Formatting contract: keep chat replies short, avoid giant markdown sections/lists unless the user explicitly asks for a prose writeup, and use tools for structured planning surfaces instead of hand-formatting them in chat.",
                "Do not publish a plan until the user has answered the key scope questions or explicitly said to proceed with assumptions; when proceeding with assumptions, record those defaults in the plan.",
                "When you are ready to propose the actual plan, use publish_plan instead of writing a giant markdown response in chat. Keep conversational replies short and scoped to the next decision.",
            ]
            if settings.PLAN_MODE_SUBAGENT_GUIDANCE_ENABLED:
                lines.append(
                    f"If independent read-heavy research would materially speed up planning, you may use {PLAN_GUIDED_SUBAGENT_TOOL} for bounded parallel exploration. "
                    "Do not use cross-bot delegation from plan mode."
                )
            return lines
        return []
    path = plan.path or get_session_active_plan_path(session) or "<unknown>"
    if mode == PLAN_MODE_PLANNING:
        lines.append(
            "Plan mode is active. Stay in planning mode: ask focused clarifying questions, keep chat replies concise, refine the canonical plan artifact via tools, "
            "and do not edit non-plan files or execute implementation changes."
        )
        lines.append("Use the planning-state capsule as durable notes for confirmed decisions, open questions, assumptions, constraints, non-goals, evidence, and preference changes.")
        lines.append("Before approval, the plan artifact must include key changes, interface impact, assumptions/defaults, concrete steps, acceptance criteria, and a test plan. Revise with publish_plan instead of asking approval for a thin draft.")
        lines.append("Formatting contract: keep planning chat terse and decision-oriented; use publish_plan for the structured draft and avoid restating the whole plan in normal assistant prose.")
        lines.append(f"Canonical plan file: {path}")
        lines.append(f"Current revision: {plan.revision} ({plan.status})")
        lines.append("Use publish_plan for plan revisions instead of dumping long markdown into chat. If more user input is needed, prefer ask_plan_questions.")
        if settings.PLAN_MODE_SUBAGENT_GUIDANCE_ENABLED:
            lines.append(
                f"If planning requires independent read-only side research, {PLAN_GUIDED_SUBAGENT_TOOL} is allowed for bounded exploration. "
                "Keep cross-bot delegation out of plan mode unless explicitly reviewed."
            )
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
        lines.append(
            "If execution reveals the accepted plan is stale, stop and use request_plan_replan with the reason/evidence instead of continuing or silently editing around the plan."
        )
        lines.append(
            "Before ending an execution turn, use record_plan_progress to record progress, verification, step_done, blocked, or no_progress. "
            "If a prior turn has a pending outcome, record that outcome before using more mutating tools."
        )
        lines.append(
            "Only record step_done after the current step is actually complete and any requested verification/readback has succeeded. "
            "If verification is still pending or failed, record progress, verification, blocked, or no_progress instead."
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
    real_target = os.path.realpath(resolved_path)
    if os.path.realpath(active_plan_path) == real_target:
        return True
    task_slug = (session.metadata_ or {}).get(PLAN_SLUG_METADATA_KEY)
    revision = (session.metadata_ or {}).get(PLAN_REVISION_METADATA_KEY)
    if task_slug and revision:
        snapshot_path = build_plan_snapshot_path(session, str(task_slug), int(revision))
        if os.path.realpath(snapshot_path) == real_target:
            return True
    return False


def tool_allowed_in_plan_mode(
    session: Session,
    *,
    tool_name: str,
    tool_kind: str,
    safety_tier: str | None = None,
) -> bool:
    mode = get_session_plan_mode(session)
    if mode not in {PLAN_MODE_PLANNING, PLAN_MODE_EXECUTING, PLAN_MODE_BLOCKED}:
        return True
    mutating = tool_kind in {"client", "widget"} or safety_tier in {"mutating", "exec_capable", "control_plane"}
    if mode == PLAN_MODE_PLANNING:
        if tool_kind == "local":
            if tool_name in PLAN_MUTATING_TOOL_ALLOWLIST:
                return True
            return safety_tier not in {"mutating", "exec_capable", "control_plane"}
        if tool_kind in {"client", "widget"}:
            return False
        return True
    if not mutating:
        return True
    runtime_raw = (session.metadata_ or {}).get(PLAN_RUNTIME_METADATA_KEY)
    runtime = runtime_raw if isinstance(runtime_raw, dict) else {}
    plan = load_session_plan(session, required=False)
    accepted_revision = _accepted_plan_revision(session)
    if tool_kind == "local" and tool_name in PLAN_EXECUTION_OUTCOME_TOOL_ALLOWLIST:
        if tool_name == "request_plan_replan":
            return plan is not None and accepted_revision > 0 and not runtime.get("replan")
        return plan is not None and accepted_revision > 0
    if runtime.get("pending_turn_outcome"):
        return False
    if _runtime_semantic_blocks_mutation(runtime, session):
        return False
    if mode == PLAN_MODE_BLOCKED or runtime.get("replan"):
        return False
    if plan is None or accepted_revision <= 0 or plan.revision != accepted_revision:
        return False
    if not any(step.status == STEP_STATUS_IN_PROGRESS for step in plan.steps):
        return False
    return True


def plan_mode_tool_denial_reason(
    session: Session,
    *,
    tool_name: str,
    tool_kind: str,
    safety_tier: str | None = None,
) -> str | None:
    if tool_allowed_in_plan_mode(
        session,
        tool_name=tool_name,
        tool_kind=tool_kind,
        safety_tier=safety_tier,
    ):
        return None
    mode = get_session_plan_mode(session)
    if mode == PLAN_MODE_EXECUTING:
        runtime_raw = (session.metadata_ or {}).get(PLAN_RUNTIME_METADATA_KEY)
        runtime = runtime_raw if isinstance(runtime_raw, dict) else {}
        if runtime.get("replan"):
            return "The accepted plan has a pending replan request. Mutating tools are disabled until the plan is revised and approved again."
        if runtime.get("pending_turn_outcome"):
            return "The previous execution turn is missing a plan outcome. Use record_plan_progress before running more mutating tools."
        latest_review = _runtime_latest_semantic_review(runtime, session)
        if _semantic_status_from_review(latest_review) == PLAN_SEMANTIC_STATUS_NEEDS_REPLAN:
            return "The latest plan adherence review says the accepted plan needs replanning. Use request_plan_replan before running more mutating tools."
        if str((latest_review or {}).get("verdict") or "").strip() == PLAN_SEMANTIC_REVIEW_UNSUPPORTED:
            return "The latest plan adherence review says the recorded step is unsupported. Repeat the step or record corrected progress before running more mutating tools."
        return "Plan execution guard blocked this mutating tool because the accepted revision/current step contract is not valid."
    if mode == PLAN_MODE_BLOCKED:
        runtime_raw = (session.metadata_ or {}).get(PLAN_RUNTIME_METADATA_KEY)
        runtime = runtime_raw if isinstance(runtime_raw, dict) else {}
        if runtime.get("pending_turn_outcome"):
            return "The previous blocked-plan turn is missing a plan outcome. Use record_plan_progress or request_plan_replan before running more mutating tools."
        return "Plan execution is blocked. Resolve the blocker or request a replan before running mutating tools."
    if tool_name == "file":
        return "Plan mode is active. Direct file mutations are disabled while drafting; use publish_plan to revise the canonical plan."
    if tool_kind in {"client", "widget"}:
        return "Plan mode is active. Interactive or client-side actions are disabled while drafting the plan."
    if safety_tier in {"exec_capable", "control_plane"}:
        return f"Plan mode is active. Tool '{tool_name}' is disabled until the plan is approved."
    return f"Plan mode is active. Tool '{tool_name}' cannot mutate state while the plan is still a draft."
