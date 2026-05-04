from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.knowledge_capture import (
    KnowledgeCandidate,
    should_run_knowledge_capture,
    write_pending_user_knowledge_candidates,
)


def _bot(**overrides):
    data = {
        "id": "bot-1",
        "user_id": "user-1",
        "shared_workspace_id": "ws-1",
        "knowledge_capture_enabled": True,
        "integration_config": {},
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_capture_skip_rules_require_opt_in_and_owner():
    decision = should_run_knowledge_capture(
        bot=_bot(knowledge_capture_enabled=False, integration_config={}),
        channel=SimpleNamespace(config={}),
        message_metadata={"sender_type": "human"},
        run_origin="chat",
        assistant_content="This is a substantive answer with enough content to consider for capture.",
    )
    assert decision.reason == "bot_capture_disabled"

    decision = should_run_knowledge_capture(
        bot=_bot(user_id=None),
        channel=SimpleNamespace(config={}),
        message_metadata={"sender_type": "human"},
        run_origin="chat",
        assistant_content="This is a substantive answer with enough content to consider for capture.",
    )
    assert decision.reason == "ownerless_bot"


def test_capture_skip_rules_respect_channel_off_background_and_ack():
    assert should_run_knowledge_capture(
        bot=_bot(),
        channel=SimpleNamespace(config={"knowledge_capture": "off"}),
        message_metadata={"sender_type": "human"},
        run_origin="chat",
        assistant_content="This is a substantive answer with enough content to consider for capture.",
    ).reason == "channel_capture_disabled"

    assert should_run_knowledge_capture(
        bot=_bot(),
        channel=SimpleNamespace(config={}),
        message_metadata={"sender_type": "human", "context_visibility": "background"},
        run_origin="chat",
        assistant_content="This is a substantive answer with enough content to consider for capture.",
    ).reason == "background_context"

    assert should_run_knowledge_capture(
        bot=_bot(),
        channel=SimpleNamespace(config={}),
        message_metadata={"sender_type": "human"},
        run_origin="chat",
        assistant_content="Done.",
    ).reason == "tool_ack"


def test_capture_allows_enabled_human_chat_turn():
    decision = should_run_knowledge_capture(
        bot=_bot(),
        channel=SimpleNamespace(config={}),
        message_metadata={"sender_type": "human"},
        run_origin="chat",
        assistant_content="This answer contains a meaningful durable preference about how the user wants reports formatted.",
    )
    assert decision.should_run is True


@pytest.mark.asyncio
async def test_write_pending_candidates_uses_user_knowledge_surface(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge_capture.shared_workspace_service.ensure_host_dirs",
        lambda workspace_id: str(tmp_path / "shared" / workspace_id),
    )

    docs = await write_pending_user_knowledge_candidates(
        bot=_bot(),
        session_id="session-1",
        source_message_id="message-1",
        candidates=[KnowledgeCandidate(title="Favorite Format", body="# Favorite Format\n\nUse concise bullets.", confidence=0.8)],
    )

    assert len(docs) == 1
    assert docs[0]["status"] == "pending_review"
    assert docs[0]["session_binding"] == {"mode": "inline", "session_id": "session-1"}
    path = tmp_path / "shared" / "ws-1" / "users" / "user-1" / "knowledge-base" / "notes" / "favorite-format.md"
    assert path.is_file()
    assert "source_message_id: message-1" in path.read_text()
