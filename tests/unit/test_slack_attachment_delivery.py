"""Slack attachment deletion delivery tests."""
from __future__ import annotations

import uuid

import pytest

from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.dispatch_target import NoneTarget
from app.domain.payloads import AttachmentDeletedPayload
from integrations.slack.attachment_delivery import SlackAttachmentDelivery
from integrations.slack.target import SlackTarget

pytestmark = pytest.mark.asyncio


def _target(*, token: str = "xoxb-test") -> SlackTarget:
    return SlackTarget(channel_id="C123", token=token)


def _attachment_event(metadata: dict | None = None) -> ChannelEvent:
    return ChannelEvent(
        channel_id=uuid.uuid4(),
        kind=ChannelEventKind.ATTACHMENT_DELETED,
        payload=AttachmentDeletedPayload(
            attachment_id=uuid.uuid4(),
            metadata=metadata or {},
        ),
    )


class _DeleteRecorder:
    def __init__(self, *, result: bool = True, exc: Exception | None = None):
        self.result = result
        self.exc = exc
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, token: str, file_id: str) -> bool:
        self.calls.append((token, file_id))
        if self.exc is not None:
            raise self.exc
        return self.result


class TestSlackAttachmentEventDelivery:
    async def test_deletes_slack_file_from_event_metadata(self):
        delete = _DeleteRecorder()
        receipt = await SlackAttachmentDelivery(delete_file=delete).render(
            _attachment_event({"slack_file_id": "F123"}),
            _target(),
        )

        assert receipt.success is True
        assert receipt.skip_reason is None
        assert delete.calls == [("xoxb-test", "F123")]

    async def test_skips_event_without_slack_file_id(self):
        delete = _DeleteRecorder()
        receipt = await SlackAttachmentDelivery(delete_file=delete).render(
            _attachment_event({"other": "value"}),
            _target(),
        )

        assert receipt.success is True
        assert receipt.skip_reason == "attachment_deleted without slack_file_id"
        assert delete.calls == []

    async def test_failed_delete_is_retryable(self):
        delete = _DeleteRecorder(result=False)
        receipt = await SlackAttachmentDelivery(delete_file=delete).render(
            _attachment_event({"slack_file_id": "F123"}),
            _target(),
        )

        assert receipt.success is False
        assert receipt.retryable is True
        assert receipt.error == "delete_slack_file returned False"

    async def test_delete_exception_is_retryable_failure(self):
        delete = _DeleteRecorder(exc=RuntimeError("slack unavailable"))
        receipt = await SlackAttachmentDelivery(delete_file=delete).render(
            _attachment_event({"slack_file_id": "F123"}),
            _target(),
        )

        assert receipt.success is False
        assert receipt.retryable is True
        assert "slack unavailable" in (receipt.error or "")


class TestSlackAttachmentDirectDelete:
    async def test_direct_delete_returns_false_for_non_slack_target(self):
        delete = _DeleteRecorder()
        ok = await SlackAttachmentDelivery(delete_file=delete).delete_attachment(
            {"slack_file_id": "F123"},
            NoneTarget(),
        )

        assert ok is False
        assert delete.calls == []

    async def test_direct_delete_returns_false_without_file_id(self):
        delete = _DeleteRecorder()
        ok = await SlackAttachmentDelivery(delete_file=delete).delete_attachment(
            {"other": "value"},
            _target(),
        )

        assert ok is False
        assert delete.calls == []

    async def test_direct_delete_returns_false_without_token(self):
        delete = _DeleteRecorder()
        ok = await SlackAttachmentDelivery(delete_file=delete).delete_attachment(
            {"slack_file_id": "F123"},
            _target(token=""),
        )

        assert ok is False
        assert delete.calls == []

    async def test_direct_delete_returns_injected_delete_result(self):
        delete = _DeleteRecorder(result=True)
        ok = await SlackAttachmentDelivery(delete_file=delete).delete_attachment(
            {"slack_file_id": "F123"},
            _target(),
        )

        assert ok is True
        assert delete.calls == [("xoxb-test", "F123")]

    async def test_direct_delete_exception_returns_false(self):
        delete = _DeleteRecorder(exc=RuntimeError("boom"))
        ok = await SlackAttachmentDelivery(delete_file=delete).delete_attachment(
            {"slack_file_id": "F123"},
            _target(),
        )

        assert ok is False
        assert delete.calls == [("xoxb-test", "F123")]
