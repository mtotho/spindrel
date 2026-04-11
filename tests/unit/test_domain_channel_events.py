"""Tests for app.domain.channel_events — typed ChannelEvent + payload validation."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.domain.actor import ActorRef
from app.domain.capability import Capability
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.message import Message
from app.domain.payloads import (
    ApprovalRequestedPayload,
    AttachmentDeletedPayload,
    DeliveryFailedPayload,
    HeartbeatTickPayload,
    MessagePayload,
    MessageUpdatedPayload,
    ReplayLapsedPayload,
    ShutdownPayload,
    ToolActivityPayload,
    TurnEndedPayload,
    TurnStartedPayload,
    TurnStreamToolResultPayload,
    TurnStreamToolStartPayload,
    TurnStreamTokenPayload,
    WorkflowProgressPayload,
)


def _msg() -> Message:
    return Message(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        role="assistant",
        content="hi",
        created_at=datetime.now(timezone.utc),
        actor=ActorRef.bot("e2e", "E2E"),
    )


# ---------------------------------------------------------------------
# kind ↔ payload pairing validation
# ---------------------------------------------------------------------

class TestKindPayloadPairing:
    def test_correct_pairing_succeeds(self):
        evt = ChannelEvent(
            channel_id=uuid.uuid4(),
            kind=ChannelEventKind.NEW_MESSAGE,
            payload=MessagePayload(message=_msg()),
        )
        assert evt.kind == ChannelEventKind.NEW_MESSAGE

    def test_wrong_payload_raises(self):
        with pytest.raises(TypeError, match="requires payload of type MessagePayload"):
            ChannelEvent(
                channel_id=uuid.uuid4(),
                kind=ChannelEventKind.NEW_MESSAGE,
                payload=TurnStartedPayload(bot_id="x", turn_id=uuid.uuid4()),
            )

    def test_all_kinds_have_a_required_payload_class(self):
        # Round-trip every ChannelEventKind with a matching payload to
        # confirm the kind→payload map covers the whole enum.
        cid = uuid.uuid4()
        _tid = uuid.uuid4()
        cases: dict[ChannelEventKind, object] = {
            ChannelEventKind.NEW_MESSAGE: MessagePayload(message=_msg()),
            ChannelEventKind.MESSAGE_UPDATED: MessageUpdatedPayload(message=_msg()),
            ChannelEventKind.TURN_STARTED: TurnStartedPayload(bot_id="x", turn_id=_tid),
            ChannelEventKind.TURN_STREAM_TOKEN: TurnStreamTokenPayload(bot_id="x", turn_id=_tid, delta="hi"),
            ChannelEventKind.TURN_STREAM_TOOL_START: TurnStreamToolStartPayload(bot_id="x", turn_id=_tid, tool_name="foo"),
            ChannelEventKind.TURN_STREAM_TOOL_RESULT: TurnStreamToolResultPayload(bot_id="x", turn_id=_tid, tool_name="foo", result_summary="ok"),
            ChannelEventKind.TURN_ENDED: TurnEndedPayload(bot_id="x", turn_id=_tid, result="done"),
            ChannelEventKind.APPROVAL_REQUESTED: ApprovalRequestedPayload(approval_id="a", bot_id="x", tool_name="t"),
            ChannelEventKind.ATTACHMENT_DELETED: AttachmentDeletedPayload(attachment_id=uuid.uuid4()),
            ChannelEventKind.DELIVERY_FAILED: DeliveryFailedPayload(integration_id="slack", target_summary="C123", last_error="429", attempts=10),
            ChannelEventKind.WORKFLOW_PROGRESS: WorkflowProgressPayload(run_id="r", event="started"),
            ChannelEventKind.HEARTBEAT_TICK: HeartbeatTickPayload(bot_id="x"),
            ChannelEventKind.TOOL_ACTIVITY: ToolActivityPayload(bot_id="x", tool_name="t", status="ok"),
            ChannelEventKind.SHUTDOWN: ShutdownPayload(),
            ChannelEventKind.REPLAY_LAPSED: ReplayLapsedPayload(requested_since=0, oldest_available=10),
        }
        # Every kind except APPROVAL_RESOLVED should be covered. Add it.
        from app.domain.payloads import (
            ApprovalResolvedPayload,
            ContextBudgetPayload,
            MemorySchemeBootstrapPayload,
        )
        cases[ChannelEventKind.APPROVAL_RESOLVED] = ApprovalResolvedPayload(approval_id="a", decision="approved")
        cases[ChannelEventKind.CONTEXT_BUDGET] = ContextBudgetPayload(
            bot_id="x", turn_id=_tid, consumed_tokens=10, total_tokens=1000, utilization=0.01,
        )
        cases[ChannelEventKind.MEMORY_SCHEME_BOOTSTRAP] = MemorySchemeBootstrapPayload(
            bot_id="x", turn_id=_tid, scheme="workspace-files", files_loaded=3,
        )

        for kind in ChannelEventKind:
            assert kind in cases, f"missing test case for {kind}"
            evt = ChannelEvent(channel_id=cid, kind=kind, payload=cases[kind])
            assert evt.kind == kind


# ---------------------------------------------------------------------
# Required-capabilities mapping
# ---------------------------------------------------------------------

class TestRequiredCapabilities:
    def test_streaming_token_requires_streaming_edit(self):
        caps = ChannelEventKind.TURN_STREAM_TOKEN.required_capabilities()
        assert Capability.STREAMING_EDIT in caps

    def test_new_message_requires_only_text(self):
        caps = ChannelEventKind.NEW_MESSAGE.required_capabilities()
        assert caps == frozenset({Capability.TEXT})

    def test_attachment_deleted_requires_file_delete(self):
        caps = ChannelEventKind.ATTACHMENT_DELETED.required_capabilities()
        assert Capability.FILE_DELETE in caps

    def test_shutdown_requires_no_capabilities(self):
        # All renderers should receive shutdown
        assert ChannelEventKind.SHUTDOWN.required_capabilities() == frozenset()

    def test_text_only_renderer_receives_basic_events(self):
        text_only = frozenset({Capability.TEXT})
        # text-only renderer should be able to handle NEW_MESSAGE, TURN_ENDED,
        # TURN_STARTED, APPROVAL_REQUESTED, WORKFLOW_PROGRESS, HEARTBEAT_TICK
        for kind in (
            ChannelEventKind.NEW_MESSAGE,
            ChannelEventKind.TURN_ENDED,
            ChannelEventKind.TURN_STARTED,
            ChannelEventKind.APPROVAL_REQUESTED,
            ChannelEventKind.WORKFLOW_PROGRESS,
            ChannelEventKind.HEARTBEAT_TICK,
        ):
            assert kind.required_capabilities() <= text_only, f"{kind} should be receivable by text-only"

    def test_text_only_renderer_skips_streaming_events(self):
        text_only = frozenset({Capability.TEXT})
        # text-only renderer should NOT receive any streaming events
        for kind in (
            ChannelEventKind.TURN_STREAM_TOKEN,
            ChannelEventKind.TURN_STREAM_TOOL_START,
            ChannelEventKind.TURN_STREAM_TOOL_RESULT,
            ChannelEventKind.MESSAGE_UPDATED,
        ):
            assert not (kind.required_capabilities() <= text_only), f"{kind} should NOT be receivable by text-only"


# ---------------------------------------------------------------------
# Construction / immutability
# ---------------------------------------------------------------------

class TestChannelEventConstruction:
    def test_seq_defaults_to_zero(self):
        evt = ChannelEvent(
            channel_id=uuid.uuid4(),
            kind=ChannelEventKind.SHUTDOWN,
            payload=ShutdownPayload(),
        )
        assert evt.seq == 0

    def test_timestamp_defaults_to_now(self):
        before = datetime.now(timezone.utc)
        evt = ChannelEvent(
            channel_id=uuid.uuid4(),
            kind=ChannelEventKind.SHUTDOWN,
            payload=ShutdownPayload(),
        )
        after = datetime.now(timezone.utc)
        assert before <= evt.timestamp <= after

    def test_event_is_frozen(self):
        evt = ChannelEvent(
            channel_id=uuid.uuid4(),
            kind=ChannelEventKind.SHUTDOWN,
            payload=ShutdownPayload(),
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            evt.seq = 5  # type: ignore[misc]
