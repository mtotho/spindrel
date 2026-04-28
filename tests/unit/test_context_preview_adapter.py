from __future__ import annotations

import uuid
from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest

from app.routers.api_v1_admin import channels
from app.services.context_preview import build_context_preview_response


def _preview(messages, *, inject_chars=None, decisions=None):
    return SimpleNamespace(
        messages=messages,
        inject_chars=inject_chars or {},
        assembly=SimpleNamespace(
            inject_decisions=decisions or {},
            context_profile="chat",
            context_policy={"live_history_turns": 6},
        ),
        budget=SimpleNamespace(
            total_tokens=1000,
            reserve_tokens=100,
            used_tokens=250,
            remaining_tokens=650,
        ),
        bot_id="test-bot",
        model="test/model",
        history_mode="file",
    )


def test_preview_adapter_splits_base_prompt_without_recomposing(monkeypatch):
    monkeypatch.setattr("app.config.settings.GLOBAL_BASE_PROMPT", "Global rules")

    response = build_context_preview_response(
        _preview([
            {"role": "system", "content": "Global rules\n\nYou are a test bot."},
            {"role": "system", "content": "Current time: 2026-04-28 12:00 EDT"},
            {"role": "system", "content": "Everything above is context and conversation history."},
        ]),
        include_history=False,
    )

    assert [block["label"] for block in response["blocks"]] == [
        "Global Base Prompt",
        "Bot System Prompt",
        "Date/Time",
    ]
    assert response["blocks"][1]["content"] == "You are a test bot."
    assert response["conversation"] == []
    assert response["total_chars"] == sum(len(block["content"]) for block in response["blocks"])


def test_preview_adapter_exposes_runtime_decisions_without_status_blocks():
    response = build_context_preview_response(
        _preview(
            [{"role": "system", "content": "You are a test bot."}],
            decisions={"pinned_widgets": "skipped_empty"},
        ),
        include_history=False,
    )

    labels = [block["label"] for block in response["blocks"]]
    assert "Pinned Widget Context" not in labels
    assert response["pinned_widget_context"] == {
        "enabled": True,
        "decision": "skipped_empty",
    }


def test_preview_adapter_keeps_bot_prompt_label_when_memory_scheme_is_present(monkeypatch):
    monkeypatch.setattr("app.config.settings.GLOBAL_BASE_PROMPT", "Global rules")

    response = build_context_preview_response(
        _preview([
            {
                "role": "system",
                "content": (
                    "Global rules\n\n"
                    "You are the e2e test bot.\n\n"
                    "Your persistent memory lives in `memory/` relative to your workspace root.\n"
                    "### Memory Tools\n"
                    "- `search_memory(query)`"
                ),
            },
        ]),
        include_history=False,
    )

    blocks = {block["label"]: block["content"] for block in response["blocks"]}
    assert "test bot" in blocks["Bot System Prompt"]
    assert "persistent memory" in blocks["Memory Scheme Prompt"]


def test_preview_adapter_optionally_keeps_conversation_messages():
    response = build_context_preview_response(
        _preview([
            {"role": "system", "content": "You are a test bot."},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]),
        include_history=True,
    )

    assert response["conversation"] == [
        {"label": "User", "role": "user", "content": "hello"},
        {"label": "Assistant", "role": "assistant", "content": "hi"},
    ]


@pytest.mark.asyncio
async def test_admin_context_preview_route_uses_runtime_assembler(monkeypatch):
    monkeypatch.setattr("app.config.settings.GLOBAL_BASE_PROMPT", "")
    channel_id = uuid.uuid4()
    db = SimpleNamespace(get=AsyncMock(return_value=object()))
    called = {}

    async def fake_assemble_for_preview(actual_channel_id, *, user_message=""):
        called["channel_id"] = actual_channel_id
        called["user_message"] = user_message
        return _preview([
            {"role": "system", "content": "Assembled preview only."},
        ])

    monkeypatch.setattr(channels, "assemble_for_preview", fake_assemble_for_preview)

    response = await channels.admin_channel_context_preview(
        channel_id,
        include_history=False,
        db=db,
        _auth="token",
    )

    assert called == {"channel_id": channel_id, "user_message": ""}
    assert response["blocks"] == [
        {
            "label": "Bot System Prompt",
            "role": "system",
            "content": "Assembled preview only.",
        }
    ]
