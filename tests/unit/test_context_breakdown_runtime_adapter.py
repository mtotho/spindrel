from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.db.models import Channel
from app.services.context_breakdown import (
    _runtime_preview_categories,
    compute_context_breakdown,
    fetch_latest_context_budget,
    invalidate_context_breakdown_cache,
)


def _preview(messages, *, consumed_tokens=123, tool_schema_tokens=0):
    return SimpleNamespace(
        messages=messages,
        inject_chars={},
        assembly=SimpleNamespace(
            inject_decisions={},
            context_profile="chat",
            context_origin="test",
            context_policy={
                "live_history_turns": 6,
                "mandatory_static_injections": ["section_index"],
                "optional_static_injections": ["tool_index"],
            },
        ),
        budget=SimpleNamespace(
            consumed_tokens=consumed_tokens,
            breakdown={"tool_schemas": tool_schema_tokens},
        ),
        bot_id="test-bot",
        model="test/model",
        history_mode="file",
    )


def _category(categories, key):
    for category in categories:
        if category.key == key:
            return category
    raise AssertionError(f"missing {key!r}: {[c.key for c in categories]}")


def test_runtime_preview_categories_adapt_assembled_messages(monkeypatch):
    monkeypatch.setattr("app.config.settings.GLOBAL_BASE_PROMPT", "Global rules")

    categories = _runtime_preview_categories(_preview([
        {"role": "system", "content": "Global rules\n\nYou are a test bot."},
        {"role": "system", "content": "Current time: 2026-04-28 12:00 EDT"},
        {"role": "system", "content": "## Bot knowledge base:\n\nretrieved fact"},
        {"role": "system", "content": "Everything above is context and conversation history."},
        {"role": "system", "content": "--- BEGIN RECENT CONVERSATION HISTORY ---"},
        {"role": "user", "content": "ignored by static adapter"},
    ], tool_schema_tokens=10))

    assert _category(categories, "global_base_prompt").chars == len("Global rules")
    assert _category(categories, "system_prompt").chars == len("You are a test bot.")
    assert _category(categories, "datetime").category == "static"
    assert _category(categories, "bot_knowledge_base").category == "rag"
    assert _category(categories, "tool_schemas").chars == 35
    assert "conversation" not in {category.key for category in categories}


@pytest.mark.asyncio
async def test_fetch_latest_context_budget_does_not_recompute_stale_compaction(monkeypatch):
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()

    async def fake_latest_trace_data(db, *, scope_clause, event_type, session_id=None):
        if event_type == "context_injection_summary":
            return {
                "context_budget": {
                    "consumed_tokens": 111,
                    "total_tokens": 1000,
                    "utilization": 0.111,
                },
                "context_profile": "chat",
            }
        if event_type == "token_usage":
            return {
                "prompt_tokens": 222,
                "current_prompt_tokens": 222,
                "cached_prompt_tokens": 0,
                "completion_tokens": 10,
            }
        return {}

    async def fake_latest_trace_time(db, *, scope_clause, event_type, session_id=None):
        if event_type == "compaction_done":
            return datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
        if event_type == "token_usage":
            return datetime(2026, 5, 4, 11, 0, tzinfo=timezone.utc)
        return None

    async def fail_recompute(*args, **kwargs):
        raise AssertionError("context-budget must not recompute full context on refresh")

    monkeypatch.setattr("app.services.context_breakdown._latest_trace_data", fake_latest_trace_data)
    monkeypatch.setattr("app.services.context_breakdown._latest_trace_time", fake_latest_trace_time)
    monkeypatch.setattr("app.services.context_breakdown._fresh_budget_after_compaction", fail_recompute)

    result = await fetch_latest_context_budget(channel_id, object(), session_id=session_id)

    assert result["source"] == "estimate_stale_after_compaction"
    assert result["consumed_tokens"] == 111
    assert result["total_tokens"] == 1000
    assert result["utilization"] == 0.111


@pytest.mark.asyncio
async def test_compute_breakdown_sources_static_categories_from_runtime_preview(monkeypatch):
    monkeypatch.setattr("app.config.settings.GLOBAL_BASE_PROMPT", "")
    channel_id = uuid.uuid4()
    invalidate_context_breakdown_cache(str(channel_id))

    channel = SimpleNamespace(
        id=channel_id,
        bot_id="test-bot",
        active_session_id=None,
        context_compaction=None,
        compaction_interval=None,
        compaction_keep_turns=None,
        max_iterations=None,
        context_pruning=None,
        model_override=None,
        model_provider_id_override=None,
    )
    bot = SimpleNamespace(
        id="test-bot",
        model="test/model",
        model_provider_id=None,
        context_compaction=True,
        compaction_interval=None,
        compaction_keep_turns=None,
        context_pruning=None,
        tool_retrieval=False,
        tool_similarity_threshold=None,
    )

    class FakeDB:
        def __init__(self):
            self.commit = AsyncMock()

        async def get(self, model, pk):
            if model is Channel:
                return channel
            return None

    db = FakeDB()
    called = {}

    async def fake_assemble_for_preview(actual_channel_id, *, user_message="", session_id=None, db=None):
        called["channel_id"] = actual_channel_id
        called["user_message"] = user_message
        called["session_id"] = session_id
        called["db"] = db
        return _preview(
            [{"role": "system", "content": "Runtime assembled only."}],
            consumed_tokens=321,
        )

    monkeypatch.setattr("app.agent.bots.get_bot", lambda bot_id: bot)
    monkeypatch.setattr(
        "app.agent.context_assembly.assemble_for_preview",
        fake_assemble_for_preview,
    )

    result = await compute_context_breakdown(
        str(channel_id),
        db,
        mode="next_turn",
        include_budget=False,
    )

    assert called["channel_id"] == channel_id
    assert called["user_message"] == ""
    assert called["session_id"] is None
    assert called["db"] is None
    assert db.commit.await_count >= 1
    assert result.total_tokens_approx == 321
    assert result.context_profile == "chat"
    assert result.live_history_turns == 6
    assert result.mandatory_static_injections == ["section_index"]
    assert [_category(result.categories, "system_prompt").label] == ["Bot System Prompt"]


def _function_loc(path: Path, name: str) -> int:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node.end_lineno - node.lineno + 1
    raise AssertionError(f"missing function {name}")


def test_context_breakdown_public_functions_stay_coordinators():
    path = Path("app/services/context_breakdown.py")

    assert _function_loc(path, "fetch_latest_context_budget") <= 120
    assert _function_loc(path, "compute_context_breakdown") <= 90


def test_context_breakdown_routers_use_shared_serializer():
    router_paths = [
        Path("app/routers/api_v1_channels.py"),
        Path("app/routers/api_v1_admin/channels.py"),
    ]

    for path in router_paths:
        text = path.read_text()
        assert "context_breakdown_response" in text
        assert '"categories": [asdict(c) for c in result.categories]' not in text
        assert '"compaction": asdict(result.compaction)' not in text
