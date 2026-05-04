import uuid

from app.domain.capability import Capability
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.payloads import KnowledgeCapturedPayload


def test_knowledge_captured_event_contract():
    payload = KnowledgeCapturedPayload(
        entry_id="entry-1",
        type="note",
        title="Captured fact",
        user_id="user-1",
        source_message_id="message-1",
        confidence=0.72,
    )
    event = ChannelEvent(channel_id=uuid.uuid4(), kind=ChannelEventKind.KNOWLEDGE_CAPTURED, payload=payload)

    assert event.payload.mode == "review"
    assert ChannelEventKind.KNOWLEDGE_CAPTURED.required_capabilities() == frozenset({Capability.TEXT})
    assert ChannelEventKind.KNOWLEDGE_CAPTURED.is_outbox_durable is False
