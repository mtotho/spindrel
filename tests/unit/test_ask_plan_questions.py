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
    assert body["attention_label"] == "Clarify planning questions"
    assert body["state"]["title"] == "Clarify widget scope"
    assert body["state"]["attention_label"] == "Clarify planning questions"
    assert body["state"]["questions"][0]["id"] == "target_surface"
    assert "Wait for their answers before publishing the plan." in payload["llm"]


@pytest.mark.asyncio
async def test_ask_plan_questions_accepts_json_encoded_questions() -> None:
    result = await ask_plan_questions(
        title="Behavior parity choices",
        questions=json.dumps([
            {
                "id": "risk_focus",
                "label": "Risk focus",
                "type": "select",
                "choices": [
                    "Prioritize stale-plan handling",
                    "Prioritize missing-outcome blocking",
                ],
            },
            {
                "id": "done_signal",
                "label": "Done signal",
                "type": "select",
                "choices": "Catch wall-of-text regressions|Catch silent failures",
            },
        ]),
    )

    payload = json.loads(result)
    body = json.loads(payload["_envelope"]["body"])
    questions = body["state"]["questions"]

    assert questions[0]["id"] == "risk_focus"
    assert questions[0]["label"] == "Risk focus"
    assert questions[1]["id"] == "done_signal"
    assert questions[1]["choices"] == ["Catch wall-of-text regressions", "Catch silent failures"]
