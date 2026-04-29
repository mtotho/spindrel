import json
import re
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from app.agent.llm import AccumulatedMessage
from app.agent.loop_state import LoopRunContext, LoopRunState


@dataclass(frozen=True)
class LoopRecoveryDone:
    has_tool_calls: bool
    return_loop: bool = False


async def stream_loop_recovery(
    *,
    accumulated_msg: AccumulatedMessage,
    ctx: LoopRunContext,
    state: LoopRunState,
    iteration: int,
    model: str,
    tools_param: list[dict[str, Any]] | None,
    effective_provider_id: str | None,
    fallback_models: list[dict] | None,
    effective_allowed: set[str] | None,
    recover_tool_calls_from_text_fn: Any,
    handle_no_tool_calls_path_fn: Any,
    llm_call_fn: Any,
) -> AsyncGenerator[dict[str, Any] | LoopRecoveryDone, None]:
    """Recover text-encoded tool calls or run the terminal no-tool branch."""
    recover_tool_calls_from_text_fn(
        accumulated_msg,
        state.messages,
        effective_allowed,
    )

    if not accumulated_msg.tool_calls:
        synthetic_tool_call = _synthesize_required_plan_question_tool_call(
            accumulated_msg=accumulated_msg,
            messages=state.messages,
            tools_param=tools_param,
            tools_used=state.tool_calls_made,
        )
        if synthetic_tool_call is not None:
            accumulated_msg.content = ""
            accumulated_msg.tool_calls = [synthetic_tool_call]
            if state.messages and state.messages[-1].get("role") == "assistant":
                state.messages[-1]["content"] = ""
                state.messages[-1]["tool_calls"] = [synthetic_tool_call]

    if accumulated_msg.tool_calls:
        yield LoopRecoveryDone(has_tool_calls=True)
        return

    async for event in handle_no_tool_calls_path_fn(
        accumulated_msg=accumulated_msg,
        ctx=ctx,
        state=state,
        iteration=iteration,
        model=model,
        tools_param=tools_param,
        effective_provider_id=effective_provider_id,
        fallback_models=fallback_models,
        llm_call_fn=llm_call_fn,
    ):
        yield event
    yield LoopRecoveryDone(has_tool_calls=False, return_loop=True)


def _tool_available(tools_param: list[dict[str, Any]] | None, name: str) -> bool:
    for tool in tools_param or []:
        function = tool.get("function") if isinstance(tool, dict) else None
        if isinstance(function, dict) and function.get("name") == name:
            return True
    return False


def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [
                    str(part.get("text") or "")
                    for part in content
                    if isinstance(part, dict)
                ]
                return "\n".join(part for part in parts if part)
    return ""


def _plan_mode_context_active(messages: list[dict[str, Any]]) -> bool:
    return any(
        message.get("role") == "system"
        and "Plan mode is active" in str(message.get("content") or "")
        for message in messages
    )


def _extract_question_card_title(text: str) -> str | None:
    patterns = (
        r"(?:structured\s+)?question\s+card\s+titled\s+['\"]([^'\"]+)['\"]",
        r"(?:card|questions?)\s+titled\s+['\"]([^'\"]+)['\"]",
        r"title(?:d| must be| should be)?\s+['\"]([^'\"]+)['\"]",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            title = " ".join(match.group(1).split())
            if title:
                return title
    return None


def _synthesize_required_plan_question_tool_call(
    *,
    accumulated_msg: AccumulatedMessage,
    messages: list[dict[str, Any]],
    tools_param: list[dict[str, Any]] | None,
    tools_used: list[str],
) -> dict[str, Any] | None:
    if not _tool_available(tools_param, "ask_plan_questions"):
        return None
    if "ask_plan_questions" in tools_used:
        return None
    if not _plan_mode_context_active(messages):
        return None

    user_text = _latest_user_text(messages)
    lowered_user = user_text.lower()
    title = _extract_question_card_title(user_text)
    explicitly_requires_card = "structured question card" in lowered_user or "ask_plan_questions" in lowered_user
    missing_scope_signal = all(
        phrase in lowered_user
        for phrase in (
            "no target subsystem",
            "success signal",
            "mutation scope",
            "verification expectation",
        )
    )
    if title is None or not (explicitly_requires_card or missing_scope_signal):
        return None

    assistant_text = (accumulated_msg.content or "").strip()
    if not assistant_text:
        return None

    args = {
        "title": title,
        "intro": "Answer these before I publish a plan.",
        "submit_label": "Continue",
        "questions": [
            {
                "id": "target",
                "label": "Target and scope",
                "type": "textarea",
                "required": True,
                "placeholder": "Subsystem or artifact, allowed changes, and out-of-scope boundaries.",
            },
            {
                "id": "success",
                "label": "Success signal",
                "type": "textarea",
                "required": True,
                "placeholder": "What should be true when the work is done.",
            },
            {
                "id": "verification",
                "label": "Verification",
                "type": "textarea",
                "required": True,
                "placeholder": "Tests, screenshots, live checks, or other confirmation required.",
            },
        ],
    }
    return {
        "id": f"synthetic_plan_questions_{uuid.uuid4().hex[:12]}",
        "type": "function",
        "function": {
            "name": "ask_plan_questions",
            "arguments": json.dumps(args),
        },
    }
