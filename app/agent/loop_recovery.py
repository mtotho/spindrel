import copy
import json
import re
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from app.agent.llm import AccumulatedMessage
from app.agent.loop_state import LoopRunContext, LoopRunState


PLAN_MODE_CONTROL_TOOLS = frozenset({
    "ask_plan_questions",
    "publish_plan",
    "record_plan_progress",
    "request_plan_replan",
})


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
        synthetic_tool_call = _synthesize_publish_plan_retry_tool_call(
            messages=state.messages,
            tools_used=state.tool_calls_made,
        )
        if synthetic_tool_call is not None:
            _authorize_synthetic_plan_tool(effective_allowed, "publish_plan")
            _apply_synthetic_tool_calls(
                accumulated_msg=accumulated_msg,
                messages=state.messages,
                tool_calls=[synthetic_tool_call],
            )

    if not _has_tool_call(accumulated_msg.tool_calls, "ask_plan_questions"):
        synthetic_question_call = _synthesize_required_plan_question_tool_call(
            accumulated_msg=accumulated_msg,
            messages=state.messages,
            tools_used=state.tool_calls_made,
        )
        if synthetic_question_call is not None:
            _authorize_synthetic_plan_tool(effective_allowed, "ask_plan_questions")
            _apply_synthetic_tool_calls(
                accumulated_msg=accumulated_msg,
                messages=state.messages,
                tool_calls=[*(accumulated_msg.tool_calls or []), synthetic_question_call],
            )

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


def _authorize_synthetic_plan_tool(effective_allowed: set[str] | None, name: str) -> None:
    if effective_allowed is not None and name in PLAN_MODE_CONTROL_TOOLS:
        effective_allowed.add(name)


def _has_tool_call(tool_calls: list[dict[str, Any]] | None, name: str) -> bool:
    for tool_call in tool_calls or []:
        function = tool_call.get("function") if isinstance(tool_call, dict) else None
        if isinstance(function, dict) and function.get("name") == name:
            return True
        if isinstance(tool_call, dict) and tool_call.get("name") == name:
            return True
    return False


def _apply_synthetic_tool_calls(
    *,
    accumulated_msg: AccumulatedMessage,
    messages: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
) -> None:
    accumulated_msg.content = ""
    accumulated_msg.tool_calls = tool_calls
    if messages and messages[-1].get("role") == "assistant":
        messages[-1]["content"] = ""
        messages[-1]["tool_calls"] = tool_calls


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


def _latest_tool_message(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if message.get("role") == "tool":
            return message
    return None


def _latest_tool_call_for_result(
    messages: list[dict[str, Any]],
    tool_message: dict[str, Any],
    name: str,
) -> dict[str, Any] | None:
    tool_call_id = tool_message.get("tool_call_id")
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for tool_call in reversed(tool_calls):
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function")
            if not isinstance(function, dict) or function.get("name") != name:
                continue
            if tool_call_id and tool_call.get("id") != tool_call_id:
                continue
            return tool_call
    return None


def _parse_tool_arguments(tool_call: dict[str, Any]) -> dict[str, Any] | None:
    function = tool_call.get("function")
    if not isinstance(function, dict):
        return None
    raw_args = function.get("arguments")
    if isinstance(raw_args, dict):
        return copy.deepcopy(raw_args)
    if not isinstance(raw_args, str) or not raw_args.strip():
        return None
    try:
        parsed = json.loads(raw_args)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_step_ids_from_publish_error(error_text: str) -> set[str]:
    return set(re.findall(r"Step\s+['\"]([^'\"]+)['\"]\s+needs a concrete", error_text, flags=re.IGNORECASE))


def _publish_retry_subject(args: dict[str, Any]) -> str:
    for key in ("title", "summary", "scope"):
        value = str(args.get(key) or "").strip()
        if value:
            return " ".join(value.split())
    return "the accepted plan"


def _repair_publish_step_label(label: str, args: dict[str, Any]) -> str:
    clean = " ".join(str(label or "").split())
    subject = _publish_retry_subject(args)
    lowered = clean.lower()
    if not clean or lowered.startswith("step "):
        return f"Verify {subject} against acceptance criteria"
    if lowered in {"test", "verify", "validate"}:
        return f"{clean.capitalize()} {subject} against acceptance criteria"
    if lowered in {"implement", "implementation", "implement changes", "implement the changes", "make changes"}:
        return f"Implement scoped changes for {subject}"
    if lowered in {"fix issue", "fix bug", "update", "update changes"}:
        return f"{clean.capitalize()} in {subject}"
    if subject.lower() not in lowered:
        return f"{clean} for {subject}"
    return f"{clean} against acceptance criteria"


def _synthesize_publish_plan_retry_tool_call(
    *,
    messages: list[dict[str, Any]],
    tools_used: list[str],
) -> dict[str, Any] | None:
    if tools_used.count("publish_plan") >= 2:
        return None
    if not _plan_mode_context_active(messages):
        return None

    tool_message = _latest_tool_message(messages)
    if tool_message is None:
        return None
    error_text = str(tool_message.get("content") or "")
    if "needs a concrete" not in error_text or "action label" not in error_text:
        return None

    prior_call = _latest_tool_call_for_result(messages, tool_message, "publish_plan")
    if prior_call is None:
        return None
    args = _parse_tool_arguments(prior_call)
    if args is None:
        return None
    steps = args.get("steps")
    if not isinstance(steps, list):
        return None

    target_step_ids = _extract_step_ids_from_publish_error(error_text)
    repaired = False
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("id") or "")
        if target_step_ids and step_id not in target_step_ids:
            continue
        original = str(step.get("label") or "")
        repaired_label = _repair_publish_step_label(original, args)
        if repaired_label != original:
            step["label"] = repaired_label
            repaired = True

    if not repaired:
        return None

    return {
        "id": f"synthetic_publish_plan_retry_{uuid.uuid4().hex[:12]}",
        "type": "function",
        "function": {
            "name": "publish_plan",
            "arguments": json.dumps(args),
        },
    }


def _synthesize_required_plan_question_tool_call(
    *,
    accumulated_msg: AccumulatedMessage,
    messages: list[dict[str, Any]],
    tools_used: list[str],
) -> dict[str, Any] | None:
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
