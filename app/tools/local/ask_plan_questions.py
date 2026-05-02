from __future__ import annotations

import json

from app.agent.context import current_session_id
from app.db.engine import async_session
from app.db.models import Session
from app.tools.registry import register

NATIVE_APP_CONTENT_TYPE = "application/vnd.spindrel.native-app+json"

_SCHEMA = {
    "type": "function",
    "function": {
        "name": "ask_plan_questions",
        "description": (
            "Render a structured plan-questions card in chat so the user can answer a few focused planning questions "
            "without reading a giant wall of text. Use this in plan mode before publishing a plan when key scope details are missing."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": {"type": "string"},
                "intro": {"type": "string"},
                "questions": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            "type": {"type": "string", "enum": ["text", "textarea", "select"]},
                            "help": {"type": "string"},
                            "placeholder": {"type": "string"},
                            "required": {"type": "boolean"},
                            "choices": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["id", "label", "type"],
                    },
                },
                "submit_label": {"type": "string"},
            },
            "required": ["title", "questions"],
        },
    },
}


def _question_set_label(title: str) -> str:
    cleaned = " ".join(str(title or "").strip().split())
    if not cleaned:
        return "Planning questions"
    topic = cleaned.split(":", 1)[0].strip()
    first_word = (topic.split() or [cleaned])[0].strip(" -")
    if not first_word:
        return "Planning questions"
    return f"{first_word} planning questions"


def _coerce_questions(raw_questions: list[dict] | str) -> list[dict]:
    parsed: object = raw_questions
    if isinstance(raw_questions, str):
        try:
            parsed = json.loads(raw_questions)
        except json.JSONDecodeError as exc:
            raise ValueError("questions must be an array of question objects or a JSON-encoded array.") from exc

    if isinstance(parsed, dict) and isinstance(parsed.get("questions"), list):
        parsed = parsed["questions"]
    if not isinstance(parsed, list):
        raise ValueError("questions must be an array of question objects.")

    questions: list[dict] = []
    for index, item in enumerate(parsed[:3]):
        if not isinstance(item, dict):
            raise ValueError("each question must be an object.")
        question_id = str(item.get("id") or f"question_{index + 1}").strip() or f"question_{index + 1}"
        label = str(item.get("label") or item.get("question") or question_id).strip()
        question_type = str(item.get("type") or "text").strip().lower()
        if question_type not in {"text", "textarea", "select"}:
            question_type = "text"
        choices_raw = item.get("choices")
        if isinstance(choices_raw, str):
            choices = [choice.strip() for choice in choices_raw.split("|") if choice.strip()]
        elif isinstance(choices_raw, list):
            choices = [str(choice).strip() for choice in choices_raw if str(choice).strip()]
        else:
            choices = []
        question: dict = {
            "id": question_id,
            "label": label or question_id,
            "type": question_type,
        }
        for key in ("help", "placeholder"):
            value = str(item.get(key) or "").strip()
            if value:
                question[key] = value
        if "required" in item:
            question["required"] = bool(item.get("required"))
        if choices:
            question["choices"] = choices
            if question_type == "text":
                question["type"] = "select"
        questions.append(question)

    if not questions:
        raise ValueError("questions must include at least one question.")
    return questions


@register(
    _SCHEMA,
    safety_tier="readonly",
    requires_bot_context=True,
    requires_channel_context=True,
    tool_metadata={
        "domains": ["plan_control"],
        "exposure": "ambient",
    },
    returns={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "_envelope": {"type": "object"},
            "llm": {"type": "string"},
        },
        "required": ["_envelope", "llm"],
    },
)
async def ask_plan_questions(
    title: str,
    questions: list[dict] | str,
    intro: str = "",
    submit_label: str = "Submit Answers",
) -> str:
    from app.agent.tool_dispatch import ToolResultEnvelope
    from app.services.session_plan_mode import publish_session_plan_event, update_planning_state

    normalized_questions = _coerce_questions(questions)
    question_set_label = _question_set_label(title)
    payload = {
        "widget_ref": "core/plan_questions",
        "display_label": title,
        "attention_label": question_set_label,
        "state": {
            "title": title.strip(),
            "attention_label": question_set_label,
            "intro": intro.strip(),
            "submit_label": submit_label.strip() or "Submit Answers",
            "questions": normalized_questions,
        },
    }
    envelope = ToolResultEnvelope(
        content_type=NATIVE_APP_CONTENT_TYPE,
        body=json.dumps(payload),
        plain_body=f"Plan questions: {title.strip()}",
        display="inline",
        display_label=title.strip() or "Plan questions",
    )
    session_id = current_session_id.get()
    if session_id is not None:
        async with async_session() as db:
            session = await db.get(Session, session_id)
            if session is not None:
                update_planning_state(
                    session,
                    open_questions=[
                        {
                            "text": str(question.get("label") or question.get("id") or "").strip(),
                            "question_id": question.get("id"),
                            "source": "ask_plan_questions",
                        }
                        for question in normalized_questions
                        if str(question.get("label") or question.get("id") or "").strip()
                    ],
                    evidence=[f"Asked structured plan questions: {title.strip() or 'Plan questions'}"],
                    reason="ask_plan_questions",
                )
                await db.commit()
                publish_session_plan_event(session, "ask_questions")
    return json.dumps(
        {
            "_envelope": envelope.compact_dict(),
            "llm": "Displayed focused plan questions for the user. Wait for their answers before publishing the plan.",
        }
    )
