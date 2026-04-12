"""Tests for PINNED_FILE_UPDATED event kind and payload."""
import uuid

import pytest

from app.domain.channel_events import ChannelEvent, ChannelEventKind, _KIND_PAYLOAD, _REQUIRED_CAPS
from app.domain.payloads import PinnedFileUpdatedPayload
from app.domain.capability import Capability


class TestPinnedFileUpdatedEvent:
    def test_event_kind_registered(self):
        assert hasattr(ChannelEventKind, "PINNED_FILE_UPDATED")
        assert ChannelEventKind.PINNED_FILE_UPDATED.value == "pinned_file_updated"

    def test_required_caps_is_text(self):
        caps = _REQUIRED_CAPS[ChannelEventKind.PINNED_FILE_UPDATED]
        assert Capability.TEXT in caps

    def test_kind_payload_mapping(self):
        assert _KIND_PAYLOAD[ChannelEventKind.PINNED_FILE_UPDATED] is PinnedFileUpdatedPayload

    def test_construct_event(self):
        cid = uuid.uuid4()
        evt = ChannelEvent(
            channel_id=cid,
            kind=ChannelEventKind.PINNED_FILE_UPDATED,
            payload=PinnedFileUpdatedPayload(
                channel_id=cid,
                path="report.md",
                content_type="text/markdown",
            ),
        )
        assert evt.kind == ChannelEventKind.PINNED_FILE_UPDATED
        assert evt.payload.path == "report.md"

    def test_wrong_payload_raises(self):
        from app.domain.payloads import ShutdownPayload
        cid = uuid.uuid4()
        with pytest.raises(TypeError):
            ChannelEvent(
                channel_id=cid,
                kind=ChannelEventKind.PINNED_FILE_UPDATED,
                payload=ShutdownPayload(),
            )

    def test_payload_is_frozen(self):
        p = PinnedFileUpdatedPayload(
            channel_id=uuid.uuid4(),
            path="test.md",
            content_type="text/plain",
        )
        with pytest.raises(AttributeError):
            p.path = "other.md"  # type: ignore[misc]

    def test_payload_serializable(self):
        """Payloads must be JSON-serializable for the outbox."""
        import dataclasses
        import json
        p = PinnedFileUpdatedPayload(
            channel_id=uuid.uuid4(),
            path="data.json",
            content_type="application/json",
        )
        d = dataclasses.asdict(p)
        d["channel_id"] = str(d["channel_id"])
        assert json.loads(json.dumps(d))["path"] == "data.json"
