"""Spindrel ↔ Codex approval-mode translation + server-request handling.

The Spindrel approval mode (set on the channel header pill) maps to a pair
of Codex options on ``thread/start``: ``approvalPolicy`` (when the binary
asks for permission to run a tool) and the legacy flat ``sandbox`` value
(what the binary's process can touch). Both come from ``schema.py``
constants.

When the codex server *does* issue an approval / question / dynamic-tool
request mid-turn, ``handle_server_request`` translates that back into the
existing Spindrel approval / question / tool-bridge primitives.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from integrations.codex import schema
from integrations.codex.app_server import ServerRequest
from integrations.sdk import (
    AllowDeny,
    ChannelEventEmitter,
    HarnessQuestionResult,
    TurnContext,
    execute_harness_spindrel_tool_result,
    request_harness_approval,
    request_harness_question,
)

logger = logging.getLogger(__name__)


class CodexServerRequestFatal(RuntimeError):
    """Raised when a Codex server request must end the active turn."""


def mode_to_codex_policy(mode: str) -> dict[str, Any]:
    """Translate a Spindrel approval mode into Codex thread/start kwargs.

    Returned dict is splatted into ``thread/start`` params. The legacy flat
    ``sandbox`` field is used (rather than ``permissionProfile``) because
    Spindrel's four modes map cleanly onto the three sandbox profiles —
    revisit if/when we expose finer-grained permission controls in the
    runtime settings bag.
    """
    if mode == "bypassPermissions":
        return {
            "approvalPolicy": schema.APPROVAL_POLICY_NEVER,
            "sandbox": schema.SANDBOX_DANGER_FULL_ACCESS,
        }
    if mode == "plan":
        return {
            "approvalPolicy": schema.APPROVAL_POLICY_NEVER,
            "sandbox": schema.SANDBOX_READ_ONLY,
        }
    # default + acceptEdits — codex still asks for risky commands; Spindrel
    # routes those server-issued asks through approval cards.
    return {
        "approvalPolicy": schema.APPROVAL_POLICY_UNLESS_TRUSTED,
        "sandbox": schema.SANDBOX_WORKSPACE_WRITE,
    }


def mode_to_codex_turn_policy(
    mode: str,
    *,
    session_plan_mode: str = "chat",
) -> dict[str, Any]:
    """Translate Spindrel mode into current ``turn/start`` policy fields.

    ``thread/start`` still accepts a legacy flat ``sandbox`` enum. Resumed
    native threads do not run ``thread/start``, so every turn also sends the
    current schema's ``sandboxPolicy`` object. When Spindrel session plan mode
    is active, read-only Codex sandboxing wins over the approval-mode pill.
    """
    if session_plan_mode == "planning":
        return {
            "approvalPolicy": schema.APPROVAL_POLICY_NEVER,
            "sandboxPolicy": {"type": schema.SANDBOX_POLICY_READ_ONLY},
        }
    if mode == "bypassPermissions":
        return {
            "approvalPolicy": schema.APPROVAL_POLICY_NEVER,
            "sandboxPolicy": {"type": schema.SANDBOX_POLICY_DANGER_FULL_ACCESS},
        }
    if mode == "plan":
        return {
            "approvalPolicy": schema.APPROVAL_POLICY_NEVER,
            "sandboxPolicy": {"type": schema.SANDBOX_POLICY_READ_ONLY},
        }
    return {
        "approvalPolicy": schema.APPROVAL_POLICY_UNLESS_TRUSTED,
        "sandboxPolicy": {"type": schema.SANDBOX_POLICY_WORKSPACE_WRITE},
    }


def _approval_tool_name(method: str, params: dict[str, Any]) -> str:
    """Best-effort label for the Spindrel approval card."""
    item = params.get("item") if isinstance(params.get("item"), dict) else None
    candidate = (
        params.get("toolName")
        or params.get("tool")
        or params.get("command")
        or (item or {}).get("name")
        or (item or {}).get("command")
    )
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    if method == schema.SERVER_REQUEST_COMMAND_APPROVAL:
        return "codex.commandExecution"
    if method == schema.SERVER_REQUEST_FILE_CHANGE_APPROVAL:
        return "codex.fileChange"
    if method == schema.SERVER_REQUEST_PERMISSIONS:
        return "codex.permissions"
    return "codex_action"


async def _route_approval(
    ctx: TurnContext,
    runtime: Any,
    request: ServerRequest,
) -> None:
    tool_name = _approval_tool_name(request.method, request.params or {})
    try:
        decision: AllowDeny = await request_harness_approval(
            ctx=ctx,
            runtime=runtime,
            tool_name=tool_name,
            tool_input=request.params or {},
        )
    except Exception as exc:
        logger.exception("codex: approval routing failed for %s", tool_name)
        await request.respond(
            {"decision": schema.APPROVAL_DECISION_DECLINE, "reason": f"approval routing failed: {exc}"}
        )
        return
    if decision.allow:
        await request.respond({"decision": schema.APPROVAL_DECISION_ACCEPT})
    else:
        await request.respond(
            {"decision": schema.APPROVAL_DECISION_DECLINE, "reason": decision.reason or "denied"}
        )


async def _route_user_input(
    ctx: TurnContext,
    runtime: Any,
    request: ServerRequest,
) -> None:
    try:
        result: HarnessQuestionResult = await request_harness_question(
            ctx=ctx,
            runtime_name=getattr(runtime, "name", "codex"),
            tool_input=request.params or {},
        )
    except asyncio.TimeoutError as exc:
        await request.respond_error("expired", "user question expired without an answer")
        raise CodexServerRequestFatal("user question expired without an answer") from exc
    except Exception as exc:
        logger.exception("codex: user-input routing failed")
        await request.respond_error("error", str(exc))
        raise CodexServerRequestFatal(f"user-input routing failed: {exc}") from exc
    await request.respond(format_user_input_response_for_codex(result))


def format_user_input_response_for_codex(
    result: HarnessQuestionResult,
) -> dict[str, dict[str, dict[str, list[str]]]]:
    """Return Codex's ``item/tool/requestUserInput`` response schema.

    Codex keys answers by question id, and each answer value is an object with
    an ``answers`` string array. This intentionally differs from Claude's
    AskUserQuestion callback shape.
    """
    answers: dict[str, dict[str, list[str]]] = {}
    for index, answer in enumerate(result.answers):
        qid = str(answer.get("question_id") or answer.get("id") or "").strip()
        if not qid:
            qid = _fallback_question_id(result.questions, index)
        parts: list[str] = []
        selected = answer.get("selected_options")
        if isinstance(selected, list):
            parts.extend(str(item).strip() for item in selected if str(item).strip())
        text = str(answer.get("answer") or "").strip()
        if text:
            parts.append(text)
        answers[qid] = {"answers": parts}
    return {"answers": answers}


def _fallback_question_id(questions: list[dict[str, Any]], index: int) -> str:
    if index < len(questions):
        question = questions[index]
        for key in ("id", "question_id", "key"):
            value = question.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return f"q{index + 1}"


async def _route_tool_call(
    ctx: TurnContext,
    request: ServerRequest,
    *,
    allowed_tool_names: set[str] | frozenset[str],
    emit: ChannelEventEmitter | None = None,
) -> None:
    params = request.params or {}
    tool_name = str(params.get(schema.TOOL_CALL_REQUEST_TOOL_FIELD) or "")
    arguments = params.get(schema.TOOL_CALL_REQUEST_ARGUMENTS_FIELD) or {}
    if not tool_name:
        await request.respond(
            schema.dynamic_tool_text_result(
                f"item/tool/call missing {schema.TOOL_CALL_REQUEST_TOOL_FIELD!r} field",
                success=False,
            )
        )
        return
    tool_call_id = _tool_call_id_for_request(request)
    tool_args = arguments if isinstance(arguments, dict) else {}
    if emit is not None:
        emit.tool_start(
            tool_name=tool_name,
            arguments=tool_args,
            tool_call_id=tool_call_id,
        )
    try:
        rich_result = await execute_harness_spindrel_tool_result(
            ctx,
            tool_name=tool_name,
            arguments=tool_args,
            allowed_tool_names=allowed_tool_names,
        )
    except Exception as exc:
        logger.exception("codex: dynamicTool dispatch failed for %s", tool_name)
        if emit is not None:
            emit.tool_result(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                result_summary=str(exc),
                is_error=True,
            )
        await request.respond(schema.dynamic_tool_text_result(str(exc), success=False))
        return
    if emit is not None:
            emit.tool_result(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                result_summary=_summarize_dynamic_tool_text(rich_result.text),
                is_error=rich_result.is_error,
                envelope=rich_result.envelope,
                surface=rich_result.surface,
                summary=rich_result.summary,
            )
    await request.respond(schema.dynamic_tool_text_result(
        rich_result.text,
        success=not rich_result.is_error,
    ))


async def handle_server_request(
    ctx: TurnContext,
    runtime: Any,
    request: ServerRequest,
    *,
    allowed_tool_names: set[str] | frozenset[str],
    emit: ChannelEventEmitter | None = None,
) -> None:
    """Route one server-initiated request through Spindrel's primitives."""
    method = request.method

    if method in schema.APPROVAL_REQUEST_METHODS:
        await _route_approval(ctx, runtime, request)
        return

    if method == schema.SERVER_REQUEST_USER_INPUT:
        await _route_user_input(ctx, runtime, request)
        return

    if method == schema.SERVER_REQUEST_TOOL_CALL:
        # Bridged Spindrel tool. Spindrel's dispatch_tool_call already runs
        # policy + approval + audit — do NOT also call request_harness_approval
        # here, that would double-prompt.
        await _route_tool_call(
            ctx,
            request,
            allowed_tool_names=allowed_tool_names,
            emit=emit,
        )
        return

    logger.warning("codex: unsupported server request method %r", method)
    await request.respond_error(
        "not_supported", f"server request method {method!r} is not supported"
    )


def _tool_call_id_for_request(request: ServerRequest) -> str:
    params = request.params or {}
    raw = params.get(schema.TOOL_CALL_REQUEST_CALL_ID_FIELD) or params.get("id")
    if raw is None:
        raw = request.id
    value = str(raw).strip()
    return value or "codex-dynamic-tool"


def _summarize_dynamic_tool_text(text: str) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= 700:
        return normalized
    return normalized[:697].rstrip() + "..."
