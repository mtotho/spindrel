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
    HarnessQuestionResult,
    TurnContext,
    execute_harness_spindrel_tool,
    format_question_answer_for_runtime,
    request_harness_approval,
    request_harness_question,
)

logger = logging.getLogger(__name__)


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
    except asyncio.TimeoutError:
        await request.respond_error("expired", "user question expired without an answer")
        return
    except Exception as exc:
        logger.exception("codex: user-input routing failed")
        await request.respond_error("error", str(exc))
        return
    await request.respond(format_question_answer_for_runtime(result, request.params or {}))


async def _route_tool_call(
    ctx: TurnContext,
    request: ServerRequest,
    *,
    allowed_tool_names: set[str] | frozenset[str],
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
    try:
        text = await execute_harness_spindrel_tool(
            ctx,
            tool_name=tool_name,
            arguments=arguments if isinstance(arguments, dict) else {},
            allowed_tool_names=allowed_tool_names,
        )
    except Exception as exc:
        logger.exception("codex: dynamicTool dispatch failed for %s", tool_name)
        await request.respond(schema.dynamic_tool_text_result(str(exc), success=False))
        return
    await request.respond(schema.dynamic_tool_text_result(text, success=True))


async def handle_server_request(
    ctx: TurnContext,
    runtime: Any,
    request: ServerRequest,
    *,
    allowed_tool_names: set[str] | frozenset[str],
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
        await _route_tool_call(ctx, request, allowed_tool_names=allowed_tool_names)
        return

    logger.warning("codex: unsupported server request method %r", method)
    await request.respond_error(
        "not_supported", f"server request method {method!r} is not supported"
    )
