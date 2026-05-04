from types import SimpleNamespace
import uuid

from app.services.injected_messages import build_injected_message_metadata
from app.services.turn_event_emit import _EmitContext, _typed_event_from_run_stream_event


def test_assistant_injection_metadata_uses_owning_bot(monkeypatch):
    def fake_get_bot(bot_id):
        assert bot_id == "qa-bot"
        return SimpleNamespace(display_name="Rolland", name="QA Bot")

    monkeypatch.setattr("app.agent.bots.get_bot", fake_get_bot)

    metadata = build_injected_message_metadata(
        role="assistant",
        source="codex-live-memory-verification",
        bot_id="qa-bot",
    )

    assert metadata == {
        "source": "codex-live-memory-verification",
        "sender_type": "bot",
        "sender_id": "bot:qa-bot",
        "sender_display_name": "Rolland",
    }


def test_user_injection_metadata_does_not_impersonate_bot():
    metadata = build_injected_message_metadata(
        role="user",
        source="codex-live-memory-verification",
        bot_id="qa-bot",
    )

    assert metadata == {"source": "codex-live-memory-verification"}


def test_compaction_tool_events_are_not_published_to_chat_stream():
    ctx = _EmitContext(
        channel_id=uuid.uuid4(),
        bot_id="qa-bot",
        turn_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
    )

    event = _typed_event_from_run_stream_event(
        {"type": "tool_result", "tool": "memory", "compaction": True},
        ctx,
    )

    assert event is None
