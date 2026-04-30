from __future__ import annotations

import json
import uuid
from typing import Any, Literal

# Register local tool safety tiers used by deterministic semantic review.
import app.tools.local.file_ops  # noqa: F401
import app.tools.local.record_plan_progress  # noqa: F401
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import get_bot
from app.agent.tool_dispatch import ToolResultEnvelope
from app.db.models import Channel, Message, Session, ToolCall
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.services.channel_workspace import ensure_channel_workspace, write_workspace_file
from app.services.plan_semantic_review import review_plan_adherence
from app.services.session_plan_mode import (
    PLAN_PROGRESS_OUTCOME_PROGRESS,
    PLAN_PROGRESS_OUTCOME_STEP_DONE,
    approve_session_plan,
    build_session_plan_response,
    create_session_plan,
    enter_session_plan_mode,
    load_session_plan,
    record_plan_progress_outcome,
)

NativePlanFixtureVariant = Literal["unsupported", "retry_recovered"]
PLAN_CONTENT_TYPE = "application/vnd.spindrel.plan+json"


def _fixture_paths(marker: str) -> dict[str, str]:
    return {
        "planned": f".spindrel-plan-parity/fixture-planned-{marker}.txt",
        "wrong": f".spindrel-plan-parity/fixture-wrong-{marker}.txt",
        "corrected": f".spindrel-plan-parity/fixture-corrected-{marker}.txt",
    }


def _tool_call_payload(tool_name: str, call_id: uuid.UUID, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(call_id),
        "name": tool_name,
        "type": "function",
        "function": {
            "name": tool_name,
            "arguments": json.dumps(arguments, sort_keys=True),
        },
    }


def _plan_envelope(
    session: Session,
    *,
    tool_call_id: uuid.UUID,
    plain_body: str,
) -> dict[str, Any]:
    plan = load_session_plan(session, required=True)
    payload = build_session_plan_response(session, plan)
    envelope = ToolResultEnvelope(
        content_type=PLAN_CONTENT_TYPE,
        body=json.dumps(payload),
        plain_body=plain_body,
        display="inline",
        display_label="Plan",
        tool_name="record_plan_progress",
        tool_call_id=str(tool_call_id),
    )
    return envelope.compact_dict()


def _file_envelope(*, path: str, tool_call_id: uuid.UUID, verb: str = "Created") -> dict[str, Any]:
    envelope = ToolResultEnvelope(
        content_type="text/markdown",
        body=f"**{verb}** `{path}`",
        plain_body=f"{verb} {path}",
        display="inline",
        display_label="File",
        tool_name="file",
        tool_call_id=str(tool_call_id),
    )
    return envelope.compact_dict()


async def _record_fixture_turn(
    db: AsyncSession,
    session: Session,
    *,
    correlation_id: uuid.UUID,
    prompt: str,
    assistant_text: str,
    tool_calls: list[ToolCall],
    tool_results: list[dict[str, Any]],
) -> None:
    db.add(Message(
        id=uuid.uuid4(),
        session_id=session.id,
        role="user",
        content=prompt,
        correlation_id=correlation_id,
        metadata_={
            "sender_type": "diagnostic_fixture",
            "sender_display_name": "Native Plan Fixture",
        },
    ))
    db.add(Message(
        id=uuid.uuid4(),
        session_id=session.id,
        role="assistant",
        content=assistant_text,
        tool_calls=[
            _tool_call_payload(tool.tool_name, tool.id, dict(tool.arguments or {}))
            for tool in tool_calls
        ],
        correlation_id=correlation_id,
        metadata_={
            "sender_type": "bot",
            "sender_id": session.bot_id,
            "sender_display_name": "E2E Spindrel Agent",
            "tools_used": [tool.tool_name for tool in tool_calls],
            "tool_results": tool_results,
            "assistant_turn_body": {
                "version": 1,
                "items": [
                    {"id": f"text:{correlation_id}", "kind": "text", "text": assistant_text},
                    *[
                        {
                            "id": f"tool:{tool.id}",
                            "kind": "tool_call",
                            "toolCallId": str(tool.id),
                        }
                        for tool in tool_calls
                    ],
                ],
            },
        },
    ))
    await db.flush()


def _make_tool_call(
    session: Session,
    *,
    correlation_id: uuid.UUID,
    tool_name: str,
    arguments: dict[str, Any],
    result: str,
    iteration: int,
) -> ToolCall:
    return ToolCall(
        id=uuid.uuid4(),
        session_id=session.id,
        bot_id=session.bot_id,
        client_id=session.client_id,
        tool_name=tool_name,
        tool_type="local",
        iteration=iteration,
        arguments=arguments,
        result=result,
        status="done",
        correlation_id=correlation_id,
        summary={"plain_body": result[:500]},
    )


async def _record_marker_completion(
    db: AsyncSession,
    session: Session,
    *,
    channel_id: uuid.UUID,
    bot: Any,
    path: str,
    content: str,
    summary: str,
    prompt: str,
    iteration: int,
) -> dict[str, Any]:
    correlation_id = uuid.uuid4()
    write_result = write_workspace_file(str(channel_id), bot, path, content)
    file_args = {"operation": "create", "path": path, "content": content}
    file_call = _make_tool_call(
        session,
        correlation_id=correlation_id,
        tool_name="file",
        arguments=file_args,
        result=f"Created {path}",
        iteration=iteration,
    )
    db.add(file_call)
    await db.flush()

    outcome = record_plan_progress_outcome(
        session,
        outcome=PLAN_PROGRESS_OUTCOME_STEP_DONE,
        summary=summary,
        evidence=path,
        step_id="create-marker",
        correlation_id=str(correlation_id),
    )
    progress_args = {
        "outcome": PLAN_PROGRESS_OUTCOME_STEP_DONE,
        "summary": summary,
        "evidence": path,
        "step_id": "create-marker",
    }
    progress_call = _make_tool_call(
        session,
        correlation_id=correlation_id,
        tool_name="record_plan_progress",
        arguments=progress_args,
        result=f"Recorded plan outcome: {PLAN_PROGRESS_OUTCOME_STEP_DONE}",
        iteration=iteration + 1,
    )
    db.add(progress_call)
    await db.flush()

    review = await review_plan_adherence(db, session, correlation_id=str(correlation_id))
    await _record_fixture_turn(
        db,
        session,
        correlation_id=correlation_id,
        prompt=prompt,
        assistant_text="Plan progress recorded.",
        tool_calls=[file_call, progress_call],
        tool_results=[
            _file_envelope(path=path, tool_call_id=file_call.id),
            _plan_envelope(
                session,
                tool_call_id=progress_call.id,
                plain_body=f"Plan outcome recorded: {outcome['outcome']}. Review: {review['verdict']}.",
            ),
        ],
    )
    return {
        "correlation_id": str(correlation_id),
        "outcome": outcome,
        "review": review,
        "write_result": write_result,
    }


async def _record_retry_progress(
    db: AsyncSession,
    session: Session,
    *,
    summary: str,
) -> dict[str, Any]:
    correlation_id = uuid.uuid4()
    outcome = record_plan_progress_outcome(
        session,
        outcome=PLAN_PROGRESS_OUTCOME_PROGRESS,
        summary=summary,
        evidence="Unsupported review acknowledged; retrying current step.",
        step_id="create-marker",
        correlation_id=str(correlation_id),
    )
    progress_args = {
        "outcome": PLAN_PROGRESS_OUTCOME_PROGRESS,
        "summary": summary,
        "evidence": "Unsupported review acknowledged; retrying current step.",
        "step_id": "create-marker",
    }
    progress_call = _make_tool_call(
        session,
        correlation_id=correlation_id,
        tool_name="record_plan_progress",
        arguments=progress_args,
        result=f"Recorded plan outcome: {PLAN_PROGRESS_OUTCOME_PROGRESS}",
        iteration=3,
    )
    db.add(progress_call)
    await db.flush()
    await _record_fixture_turn(
        db,
        session,
        correlation_id=correlation_id,
        prompt="Native unsupported adherence retry fixture: acknowledge unsupported review and retry the current step.",
        assistant_text="Retrying the unsupported marker step.",
        tool_calls=[progress_call],
        tool_results=[
            _plan_envelope(
                session,
                tool_call_id=progress_call.id,
                plain_body=f"Plan outcome recorded: {outcome['outcome']}.",
            )
        ],
    )
    return {"correlation_id": str(correlation_id), "outcome": outcome}


async def seed_native_plan_unsupported_adherence_fixture(
    db: AsyncSession,
    session: Session,
    *,
    channel_id: uuid.UUID,
    bot_id: str,
    variant: NativePlanFixtureVariant = "unsupported",
    marker: str | None = None,
) -> dict[str, Any]:
    if session.channel_id != channel_id and session.parent_channel_id != channel_id:
        raise ConflictError("Fixture session is not attached to the requested channel.")
    if session.bot_id != bot_id:
        raise ConflictError("Fixture session bot does not match the requested bot.")

    channel = await db.get(Channel, channel_id)
    if channel is None:
        raise NotFoundError(f"Channel not found: {channel_id}")

    marker = (marker or uuid.uuid4().hex[:12]).strip()
    if not marker.replace("-", "").replace("_", "").isalnum():
        raise ValidationError("Fixture marker must contain only letters, numbers, hyphens, or underscores.")
    paths = _fixture_paths(marker)
    bot = get_bot(bot_id)
    ensure_channel_workspace(str(channel_id), bot, display_name=channel.name)

    enter_session_plan_mode(session)
    title = (
        f"Native Spindrel Unsupported Retry Fixture {marker}"
        if variant == "retry_recovered"
        else f"Native Spindrel Unsupported Fixture {marker}"
    )
    plan = create_session_plan(
        session,
        title=title,
        summary="Verify deterministic unsupported adherence review and retry recovery.",
        scope=f"Live E2E diagnostics only; create only {paths['planned']!r}; do not create alternate marker paths.",
        key_changes=[f"Create the planned marker file {paths['planned']}, not any alternate path."],
        interfaces=["No public API changes; fixture writes only channel workspace and plan transcript state."],
        assumptions_and_defaults=["Use this admin diagnostic only for native plan-mode parity verification."],
        test_plan=["Seed wrong-path evidence, review unsupported, and optionally retry with corrected evidence."],
        risks=["A model-driven wrong-work test can refuse the prompt, so this fixture records the deterministic path directly."],
        acceptance_criteria=[
            "Unsupported review records mutation_path_outside_plan_contract.",
            f"Only {paths['planned']} satisfies the accepted plan contract.",
        ],
        steps=[
            {"id": "create-marker", "label": "Create the planned fixture marker file"},
            {"id": "review-adherence", "label": "Review plan adherence evidence"},
        ],
    )
    approve_session_plan(session)
    session.title = plan.title
    await db.flush()

    unsupported = await _record_marker_completion(
        db,
        session,
        channel_id=channel_id,
        bot=bot,
        path=paths["wrong"],
        content=f"wrong fixture artifact {marker}\n",
        summary="Created wrong fixture marker for unsupported adherence review.",
        prompt="Native unsupported adherence fixture: create wrong marker evidence and record step_done.",
        iteration=1,
    )

    retry: dict[str, Any] | None = None
    corrected: dict[str, Any] | None = None
    if variant == "retry_recovered":
        retry = await _record_retry_progress(
            db,
            session,
            summary="Retrying the unsupported marker step with corrected evidence.",
        )
        corrected = await _record_marker_completion(
            db,
            session,
            channel_id=channel_id,
            bot=bot,
            path=paths["planned"],
            content=f"corrected fixture artifact {marker}\n",
            summary="Created corrected planned fixture marker.",
            prompt="Native unsupported adherence retry fixture: create the planned marker evidence and record step_done.",
            iteration=4,
        )

    payload = build_session_plan_response(session, load_session_plan(session, required=True))
    adherence = payload.get("adherence") if isinstance(payload, dict) else {}
    return {
        "ok": True,
        "variant": variant,
        "marker": marker,
        "session_id": str(session.id),
        "channel_id": str(channel_id),
        "paths": paths,
        "unsupported": unsupported,
        "retry": retry,
        "corrected": corrected,
        "plan": payload,
        "adherence": adherence,
    }
