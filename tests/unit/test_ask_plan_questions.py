from __future__ import annotations

import json

import pytest

from app.tools.local.ask_plan_questions import ask_plan_questions


@pytest.mark.asyncio
async def test_ask_plan_questions_returns_native_app_envelope() -> None:
    result = await ask_plan_questions(
        title="Clarify widget scope",
        intro="Answer the key questions before the first draft.",
        questions=[
            {
                "id": "target_surface",
                "label": "What surface is this for?",
                "type": "select",
                "choices": ["chat", "dashboard"],
                "required": True,
            },
            {
                "id": "must_have",
                "label": "What must be included?",
                "type": "textarea",
            },
        ],
    )

    payload = json.loads(result)
    envelope = payload["_envelope"]
    body = json.loads(envelope["body"])

    assert envelope["content_type"] == "application/vnd.spindrel.native-app+json"
    assert body["widget_ref"] == "core/plan_questions"
    assert body["state"]["title"] == "Clarify widget scope"
    assert body["state"]["questions"][0]["id"] == "target_surface"
    assert "Wait for their answers before publishing the plan." in payload["llm"]
