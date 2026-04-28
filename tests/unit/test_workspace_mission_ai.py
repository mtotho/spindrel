from __future__ import annotations

from types import SimpleNamespace

import httpx
import openai
import pytest

from app.domain.errors import ValidationError
import app.services.workspace_mission_ai as mission_ai
from app.services.workspace_mission_ai import _create_mission_control_completion


def _bad_request(message: str = "unsupported parameter") -> openai.BadRequestError:
    request = httpx.Request("POST", "https://example.test/v1/responses")
    response = httpx.Response(400, request=request)
    return openai.BadRequestError(message=message, response=response, body={"error": {"message": message}})


class _FlakyCompletions:
    def __init__(self):
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if "max_tokens" in kwargs or "temperature" in kwargs:
            raise _bad_request("max_tokens is not supported")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"brief": {}, "drafts": []}'))])


class _AlwaysBadCompletions:
    async def create(self, **_kwargs):
        raise _bad_request("reasoning.summary is not supported")


class _FakeDb:
    def __init__(self):
        self.events: list[str] = []

    async def rollback(self):
        self.events.append("rollback")

    def add(self, _row):
        self.events.append("add")

    async def commit(self):
        self.events.append("commit")

    async def refresh(self, row):
        self.events.append("refresh")
        row.id = "brief-1"


@pytest.mark.asyncio
async def test_mission_control_completion_retries_without_optional_generation_knobs():
    completions = _FlakyCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = await _create_mission_control_completion(
        client,
        model="gpt-test",
        messages=[{"role": "user", "content": "inspect"}],
    )

    assert result.choices[0].message.content
    assert len(completions.calls) == 2
    assert "temperature" in completions.calls[0]
    assert "max_tokens" in completions.calls[0]
    assert "temperature" not in completions.calls[1]
    assert "max_tokens" not in completions.calls[1]


@pytest.mark.asyncio
async def test_mission_control_completion_returns_validation_error_after_retry_rejected():
    client = SimpleNamespace(chat=SimpleNamespace(completions=_AlwaysBadCompletions()))

    with pytest.raises(ValidationError, match="provider rejected"):
        await _create_mission_control_completion(
            client,
            model="gpt-test",
            messages=[{"role": "user", "content": "inspect"}],
        )


@pytest.mark.asyncio
async def test_mission_control_releases_read_transaction_before_provider_call(monkeypatch):
    db = _FakeDb()

    async def fake_grounding_context(_db, *, auth, user_instruction=None):
        db.events.append("grounding")
        return {
            "recent_tasks_and_heartbeats": [],
            "channels": [],
            "bots": [],
            "mission_control": {"summary": {"active_missions": 0}},
        }

    async def fake_completion(_client, *, model, messages):
        db.events.append("provider")
        assert "rollback" in db.events
        assert db.events.index("rollback") < db.events.index("provider")
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"brief": {"summary": "Done", "confidence": "high"}, "drafts": []}'
                    )
                )
            ]
        )

    async def fake_visible_channel_ids(_db, _auth):
        return set()

    monkeypatch.setattr(mission_ai, "_resolve_model", lambda: ("gpt-test", None))
    monkeypatch.setattr(mission_ai, "build_ai_grounding_context", fake_grounding_context)
    monkeypatch.setattr(mission_ai, "get_llm_client", lambda _provider_id=None: object())
    monkeypatch.setattr(mission_ai, "_create_mission_control_completion", fake_completion)
    monkeypatch.setattr(mission_ai, "_visible_channel_ids", fake_visible_channel_ids)
    monkeypatch.setattr(mission_ai, "list_bots", lambda: [])

    result = await mission_ai.generate_mission_control_drafts(
        db,
        auth=object(),
        actor="tester",
    )

    assert result["assistant_brief"]["summary"] == "Done"
    assert db.events[:3] == ["grounding", "rollback", "provider"]
