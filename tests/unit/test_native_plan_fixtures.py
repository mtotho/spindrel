from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.db.models import Channel, Message, Session, ToolCall
from app.services import native_plan_fixtures as fixtures
from app.services import session_plan_mode as spm


def _patch_workspace(monkeypatch, tmp_path) -> None:
    bot = SimpleNamespace(id="e2e-bot", shared_workspace_id=None)
    monkeypatch.setattr(fixtures, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(spm, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(fixtures, "ensure_channel_workspace", lambda *_args, **_kwargs: str(tmp_path))
    monkeypatch.setattr(spm, "ensure_channel_workspace", lambda *_args, **_kwargs: str(tmp_path))

    def _write(_channel_id, _bot, path: str, content: str) -> dict:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return {"path": path, "size": len(content)}

    monkeypatch.setattr(fixtures, "write_workspace_file", _write)


def _make_rows() -> tuple[Channel, Session]:
    channel_id = uuid.uuid4()
    channel = Channel(id=channel_id, name="Native fixture", bot_id="e2e-bot")
    session = Session(
        id=uuid.uuid4(),
        client_id=f"fixture-{uuid.uuid4().hex[:8]}",
        bot_id="e2e-bot",
        channel_id=channel_id,
        metadata_={},
    )
    return channel, session


@pytest.mark.asyncio
async def test_unsupported_fixture_records_plan_card_tool_calls_and_semantic_review(
    db_session,
    monkeypatch,
    tmp_path,
):
    _patch_workspace(monkeypatch, tmp_path)
    channel, session = _make_rows()
    db_session.add_all([channel, session])
    await db_session.flush()

    result = await fixtures.seed_native_plan_unsupported_adherence_fixture(
        db_session,
        session,
        channel_id=channel.id,
        bot_id="e2e-bot",
        variant="unsupported",
        marker="unit-unsupported",
    )

    review = result["unsupported"]["review"]
    assert review["verdict"] == spm.PLAN_SEMANTIC_REVIEW_UNSUPPORTED
    assert review["semantic_status"] == spm.PLAN_SEMANTIC_STATUS_WARNING
    assert "mutation_path_outside_plan_contract" in review["deterministic_flags"]
    assert (tmp_path / result["paths"]["wrong"]).exists()
    assert not (tmp_path / result["paths"]["planned"]).exists()

    calls = (await db_session.execute(select(ToolCall).where(ToolCall.session_id == session.id))).scalars().all()
    assert {call.tool_name for call in calls} == {"file", "record_plan_progress"}

    messages = (await db_session.execute(select(Message).where(Message.session_id == session.id))).scalars().all()
    assistant = next(message for message in messages if message.role == "assistant")
    tool_call_ids = {str(call.get("id")) for call in assistant.tool_calls}
    plan_results = [
        item
        for item in assistant.metadata_["tool_results"]
        if item.get("content_type") == fixtures.PLAN_CONTENT_TYPE
    ]
    assert plan_results
    assert plan_results[0]["tool_call_id"] in tool_call_ids


@pytest.mark.asyncio
async def test_retry_recovered_fixture_preserves_unsupported_history_then_supports_retry(
    db_session,
    monkeypatch,
    tmp_path,
):
    _patch_workspace(monkeypatch, tmp_path)
    channel, session = _make_rows()
    db_session.add_all([channel, session])
    await db_session.flush()

    result = await fixtures.seed_native_plan_unsupported_adherence_fixture(
        db_session,
        session,
        channel_id=channel.id,
        bot_id="e2e-bot",
        variant="retry_recovered",
        marker="unit-retry",
    )

    assert result["unsupported"]["review"]["verdict"] == spm.PLAN_SEMANTIC_REVIEW_UNSUPPORTED
    assert result["corrected"]["review"]["verdict"] == spm.PLAN_SEMANTIC_REVIEW_SUPPORTED
    assert "step_done_supported_by_mutation" in result["corrected"]["review"]["deterministic_flags"]
    assert (tmp_path / result["paths"]["wrong"]).exists()
    assert (tmp_path / result["paths"]["planned"]).exists()

    reviews = result["adherence"]["semantic_reviews"]
    assert [item["verdict"] for item in reviews[-2:]] == [
        spm.PLAN_SEMANTIC_REVIEW_UNSUPPORTED,
        spm.PLAN_SEMANTIC_REVIEW_SUPPORTED,
    ]
    steps = {step["id"]: step for step in result["plan"]["steps"]}
    assert steps["create-marker"]["status"] == spm.STEP_STATUS_DONE
    assert steps["review-adherence"]["status"] == spm.STEP_STATUS_IN_PROGRESS
