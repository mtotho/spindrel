"""Durable interactive prompts for external harness runtimes.

Harness SDKs can ask the user for more information mid-turn. Spindrel renders
those prompts as persistent native cards, then resolves the in-memory SDK
callback when the user answers. If the process restarted and the callback is
gone, the answer still persists and the router can start a fresh harness turn
against the same Spindrel session.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session
from app.db.models import Message, Session
from app.services.channel_events import publish_message, publish_message_updated
from app.services.secret_registry import redact

logger = logging.getLogger(__name__)

NATIVE_APP_CONTENT_TYPE = "application/vnd.spindrel.native-app+json"
HARNESS_QUESTION_WIDGET_REF = "core/harness_question"
HARNESS_QUESTION_TIMEOUT_SECONDS = 30 * 60


@dataclass(frozen=True)
class HarnessQuestionAnswer:
    question_id: str
    answer: str | None = None
    selected_options: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HarnessQuestionResult:
    interaction_id: str
    questions: list[dict[str, Any]]
    answers: list[dict[str, Any]]
    notes: str | None = None
    answer_message_id: uuid.UUID | None = None


_PENDING_QUESTIONS: dict[str, asyncio.Future[HarnessQuestionResult]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _question_id(question: dict[str, Any], index: int) -> str:
    for key in ("id", "question_id", "key"):
        value = question.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"q{index + 1}"


def _question_text(question: dict[str, Any]) -> str:
    for key in ("question", "text", "label", "prompt"):
        value = question.get(key)
        if isinstance(value, str) and value.strip():
            return redact(value.strip())
    return "Question"


def _question_options(question: dict[str, Any]) -> list[dict[str, str]]:
    raw = question.get("options")
    if raw is None:
        raw = question.get("choices")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, str):
            label = item.strip()
            description = ""
        elif isinstance(item, dict):
            label = str(item.get("label") or item.get("value") or "").strip()
            description = str(item.get("description") or item.get("help") or "").strip()
        else:
            label = ""
        if label:
            out.append(
                {
                    "label": redact(label),
                    "description": redact(description) if description else "",
                }
            )
    return out


def normalize_harness_questions(tool_input: dict[str, Any]) -> list[dict[str, Any]]:
    raw_questions = tool_input.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raw_questions = [tool_input]
    questions: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_questions):
        if not isinstance(raw, dict):
            raw = {"question": str(raw)}
        options = _question_options(raw)
        questions.append(
            {
                "id": _question_id(raw, index),
                "question": _question_text(raw),
                "header": redact(str(raw.get("header") or raw.get("title") or "").strip())
                if raw.get("header") or raw.get("title")
                else "",
                "options": options,
                "allows_multiple": bool(
                    raw.get("allows_multiple")
                    or raw.get("multiSelect")
                    or raw.get("multiple")
                    or raw.get("multi_select")
                ),
                "allows_other": True,
                "required": bool(raw.get("required", True)),
            }
        )
    return questions


def _format_answer_text(
    questions: list[dict[str, Any]],
    answers: list[dict[str, Any]],
    notes: str | None,
) -> str:
    question_by_id = {str(q.get("id")): q for q in questions}
    lines = ["Harness question answers:"]
    for answer in answers:
        qid = str(answer.get("question_id") or "")
        question = question_by_id.get(qid, {})
        label = str(question.get("question") or qid or "Question")
        selected = answer.get("selected_options")
        text = str(answer.get("answer") or "").strip()
        parts: list[str] = []
        if isinstance(selected, list):
            parts.extend(str(item) for item in selected if str(item).strip())
        if text:
            parts.append(text)
        lines.append(f"- {label}: {'; '.join(parts) if parts else '(no answer)'}")
    if notes and notes.strip():
        lines.append("")
        lines.append("Notes:")
        lines.append(notes.strip())
    return "\n".join(lines)


def _envelope_state(
    *,
    interaction_id: str,
    runtime: str | None,
    tool_input: dict[str, Any],
    questions: list[dict[str, Any]],
    status: str,
    answers: list[dict[str, Any]] | None = None,
    notes: str | None = None,
    created_at: str | None = None,
    answered_at: str | None = None,
) -> dict[str, Any]:
    title = tool_input.get("prompt") or tool_input.get("title") or "Harness has a question"
    return {
        "interaction_id": interaction_id,
        "runtime": runtime,
        "title": redact(str(title)),
        "status": status,
        "questions": questions,
        "answers": answers or [],
        "notes": redact(notes or "") if notes else "",
        "created_at": created_at or _now_iso(),
        "answered_at": answered_at,
        "submit_label": "Submit and continue",
    }


def _envelope(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "content_type": NATIVE_APP_CONTENT_TYPE,
        "widget_ref": HARNESS_QUESTION_WIDGET_REF,
        "body": {
            "widget_ref": HARNESS_QUESTION_WIDGET_REF,
            "state": state,
        },
        "plain_body": state.get("title") or "Harness question",
        "display": "block",
        "truncated": False,
        "record_id": state.get("interaction_id"),
        "byte_size": 0,
        "display_label": state.get("title") or "Harness question",
    }


def _metadata_for_state(state: dict[str, Any]) -> dict[str, Any]:
    envelope = _envelope(state)
    return {
        "kind": "harness_question",
        "suppress_outbox": True,
        "harness_interaction": state,
        "envelope": envelope,
        "assistant_turn_body": {"version": 1, "items": []},
    }


async def create_harness_question(
    *,
    db: AsyncSession,
    session_id: uuid.UUID,
    channel_id: uuid.UUID,
    bot_id: str,
    turn_id: uuid.UUID,
    runtime: str | None,
    tool_input: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    questions = normalize_harness_questions(tool_input)
    interaction_id = str(uuid.uuid4())
    state = _envelope_state(
        interaction_id=interaction_id,
        runtime=runtime,
        tool_input=tool_input,
        questions=questions,
        status="pending",
    )
    row = Message(
        id=uuid.UUID(interaction_id),
        session_id=session_id,
        role="assistant",
        content=state["title"],
        correlation_id=turn_id,
        metadata_={
            **_metadata_for_state(state),
            "sender_type": "bot",
            "sender_id": f"bot:{bot_id}",
            "sender_display_name": runtime or "Harness",
        },
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()
    return interaction_id, questions


async def publish_harness_question(interaction_id: str) -> None:
    async with async_session() as db:
        row = await db.get(Message, uuid.UUID(interaction_id))
        if row is None:
            return
        session = await db.get(Session, row.session_id)
        if session and session.channel_id:
            publish_message(session.channel_id, row)


def create_question_pending(interaction_id: str) -> asyncio.Future[HarnessQuestionResult]:
    loop = asyncio.get_running_loop()
    future: asyncio.Future[HarnessQuestionResult] = loop.create_future()
    _PENDING_QUESTIONS[interaction_id] = future
    return future


def _resolve_pending(
    interaction_id: str,
    result: HarnessQuestionResult | Exception,
) -> bool:
    future = _PENDING_QUESTIONS.pop(interaction_id, None)
    if future is None or future.done():
        return False
    if isinstance(result, Exception):
        future.set_exception(result)
    else:
        future.set_result(result)
    return True


async def wait_for_harness_question(
    *,
    interaction_id: str,
    timeout_seconds: int = HARNESS_QUESTION_TIMEOUT_SECONDS,
) -> HarnessQuestionResult:
    future = _PENDING_QUESTIONS.get(interaction_id)
    if future is None:
        future = create_question_pending(interaction_id)
    try:
        return await asyncio.wait_for(future, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        await expire_harness_question(interaction_id, status="expired")
        raise
    finally:
        _PENDING_QUESTIONS.pop(interaction_id, None)


async def answer_harness_question(
    *,
    db: AsyncSession,
    session_id: uuid.UUID,
    interaction_id: str,
    answers: list[HarnessQuestionAnswer],
    notes: str | None = None,
) -> tuple[HarnessQuestionResult, bool]:
    row = await db.get(Message, uuid.UUID(interaction_id))
    if row is None or row.session_id != session_id:
        raise ValueError("harness question not found")
    meta = dict(row.metadata_ or {})
    state = dict(meta.get("harness_interaction") or {})
    if state.get("status") not in (None, "pending"):
        raise RuntimeError(f"harness question is already {state.get('status')}")
    questions = list(state.get("questions") or [])
    answer_dicts = [
        {
            "question_id": answer.question_id,
            "answer": redact(answer.answer or "") if answer.answer else "",
            "selected_options": [redact(item) for item in answer.selected_options],
        }
        for answer in answers
    ]
    answered_at = _now_iso()
    state.update(
        {
            "status": "submitted",
            "answers": answer_dicts,
            "notes": redact(notes or "") if notes else "",
            "answered_at": answered_at,
        }
    )
    row.metadata_ = {**meta, **_metadata_for_state(state)}

    answer_row = Message(
        id=uuid.uuid4(),
        session_id=session_id,
        role="user",
        content=_format_answer_text(questions, answer_dicts, notes),
        correlation_id=row.correlation_id,
        metadata_={
            "source": "harness_question",
            "harness_question_id": interaction_id,
            "suppress_outbox": True,
        },
        created_at=datetime.now(timezone.utc),
    )
    db.add(answer_row)
    session = await db.get(Session, session_id)
    if session is not None:
        session.last_active = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    await db.refresh(answer_row)

    if session and session.channel_id:
        publish_message_updated(session.channel_id, row)
        publish_message(session.channel_id, answer_row)

    result = HarnessQuestionResult(
        interaction_id=interaction_id,
        questions=questions,
        answers=answer_dicts,
        notes=notes,
        answer_message_id=answer_row.id,
    )
    resolved_live = _resolve_pending(interaction_id, result)
    return result, resolved_live


async def expire_harness_question(interaction_id: str, *, status: str) -> None:
    async with async_session() as db:
        row = await db.get(Message, uuid.UUID(interaction_id))
        if row is None:
            _resolve_pending(interaction_id, TimeoutError(status))
            return
        meta = dict(row.metadata_ or {})
        state = dict(meta.get("harness_interaction") or {})
        if state.get("status") == "submitted":
            return
        state["status"] = status
        state["answered_at"] = _now_iso()
        row.metadata_ = {**meta, **_metadata_for_state(state)}
        await db.commit()
        await db.refresh(row)
        session = await db.get(Session, row.session_id)
        if session and session.channel_id:
            publish_message_updated(session.channel_id, row)
    _resolve_pending(interaction_id, TimeoutError(status))


async def cancel_pending_harness_questions_for_session(session_id: uuid.UUID) -> int:
    async with async_session() as db:
        rows = (
            await db.execute(
                select(Message.id, Message.metadata_)
                .where(Message.session_id == session_id)
            )
        ).all()
    count = 0
    for row_id, meta in rows:
        if not isinstance(meta, dict) or meta.get("kind") != "harness_question":
            continue
        key = str(row_id)
        if key in _PENDING_QUESTIONS:
            await expire_harness_question(key, status="cancelled")
            count += 1
    return count


def format_question_answer_for_runtime(
    result: HarnessQuestionResult,
    original_input: dict[str, Any],
) -> dict[str, Any]:
    """Shape a ``HarnessQuestionResult`` into the dict a runtime feeds back.

    Runtimes that issue an ``AskUserQuestion``-style request need a payload
    that mirrors their original tool_input but with the user's answers spliced
    in. Both Claude and Codex re-use this shape — keeping it here means the
    runtime adapter does not own generic answer shaping.
    """
    question_by_id = {str(q.get("id")): q for q in result.questions}
    answers_by_question: dict[str, str] = {}
    structured_answers: list[dict[str, Any]] = []
    for answer in result.answers:
        qid = str(answer.get("question_id") or "")
        question = question_by_id.get(qid, {})
        label = str(question.get("question") or qid or "Question")
        selected = answer.get("selected_options")
        parts: list[str] = []
        if isinstance(selected, list):
            parts.extend(str(item) for item in selected if str(item).strip())
        text = str(answer.get("answer") or "").strip()
        if text:
            parts.append(text)
        rendered = "; ".join(parts)
        answers_by_question[label] = rendered
        structured_answers.append(
            {
                "question_id": qid,
                "question": label,
                "answer": rendered,
                "selected_options": selected if isinstance(selected, list) else [],
            }
        )
    if result.notes:
        answers_by_question["Additional notes"] = result.notes
    return {
        **original_input,
        "questions": result.questions,
        "answers": answers_by_question,
        "spindrel_answers": structured_answers,
        "spindrel_notes": result.notes or "",
    }


async def request_harness_question(
    *,
    ctx,
    runtime_name: str | None,
    tool_input: dict[str, Any],
) -> HarnessQuestionResult:
    if ctx.channel_id is None:
        raise RuntimeError("Cannot ask a harness question without a channel surface")
    async with ctx.db_session_factory() as db:
        interaction_id, _questions = await create_harness_question(
            db=db,
            session_id=ctx.spindrel_session_id,
            channel_id=ctx.channel_id,
            bot_id=ctx.bot_id,
            turn_id=ctx.turn_id,
            runtime=runtime_name,
            tool_input=tool_input,
        )
    create_question_pending(interaction_id)
    await publish_harness_question(interaction_id)
    return await wait_for_harness_question(
        interaction_id=interaction_id,
    )
