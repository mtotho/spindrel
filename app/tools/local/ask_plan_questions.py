from __future__ import annotations

import json

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


@register(
    _SCHEMA,
    safety_tier="readonly",
    requires_bot_context=True,
    requires_channel_context=True,
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
    questions: list[dict],
    intro: str = "",
    submit_label: str = "Submit Answers",
) -> str:
    from app.agent.tool_dispatch import ToolResultEnvelope

    payload = {
        "widget_ref": "core/plan_questions",
        "display_label": title,
        "state": {
            "title": title.strip(),
            "intro": intro.strip(),
            "submit_label": submit_label.strip() or "Submit Answers",
            "questions": questions,
        },
    }
    envelope = ToolResultEnvelope(
        content_type=NATIVE_APP_CONTENT_TYPE,
        body=json.dumps(payload),
        plain_body=f"Plan questions: {title.strip()}",
        display="inline",
        display_label=title.strip() or "Plan questions",
    )
    return json.dumps(
        {
            "_envelope": envelope.compact_dict(),
            "llm": "Displayed focused plan questions for the user. Wait for their answers before publishing the plan.",
        }
    )
