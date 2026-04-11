"""Tests for app.domain.message — domain Message dataclass + ORM bridge."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.domain.actor import ActorRef
from app.domain.message import AttachmentBrief, Message
from app.schemas.messages import MessageOut


def _orm_row(**overrides) -> SimpleNamespace:
    """A SimpleNamespace masquerading as an ORM Message row.

    The from_orm helper supports plain Python objects via the
    _attachments_if_loaded fallback, so SimpleNamespace works.
    """
    base = {
        "id": uuid.uuid4(),
        "session_id": uuid.uuid4(),
        "role": "assistant",
        "content": "hello world",
        "tool_calls": None,
        "tool_call_id": None,
        "correlation_id": None,
        "created_at": datetime.now(timezone.utc),
        "metadata_": {},
        "attachments": [],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestFromORM:
    def test_basic_assistant_message(self):
        row = _orm_row(role="assistant", content="hi")
        msg = Message.from_orm(row)
        assert msg.id == row.id
        assert msg.role == "assistant"
        assert msg.content == "hi"
        assert msg.actor.kind == "bot"
        assert msg.attachments == ()

    def test_user_role_derives_user_actor(self):
        row = _orm_row(role="user", content="ping")
        msg = Message.from_orm(row)
        assert msg.actor.kind == "user"

    def test_system_role_derives_system_actor(self):
        row = _orm_row(role="system", content="ctx")
        msg = Message.from_orm(row)
        assert msg.actor.kind == "system"

    def test_legacy_metadata_sender_id_user(self):
        row = _orm_row(
            role="user",
            metadata_={"sender_id": "user:U999", "sender_display_name": "Tester"},
        )
        msg = Message.from_orm(row)
        assert msg.actor.kind == "user"
        assert msg.actor.id == "U999"
        assert msg.actor.display_name == "Tester"

    def test_legacy_metadata_sender_id_bot(self):
        row = _orm_row(
            role="assistant",
            metadata_={"sender_id": "bot:e2e", "sender_display_name": "E2E Bot"},
        )
        msg = Message.from_orm(row)
        assert msg.actor.kind == "bot"
        assert msg.actor.id == "e2e"
        assert msg.actor.display_name == "E2E Bot"

    def test_channel_id_propagated(self):
        ch = uuid.uuid4()
        row = _orm_row()
        msg = Message.from_orm(row, channel_id=ch)
        assert msg.channel_id == ch

    def test_metadata_is_copied_not_aliased(self):
        meta = {"foo": "bar"}
        row = _orm_row(metadata_=meta)
        msg = Message.from_orm(row)
        # Mutating the original should NOT affect the domain message
        meta["foo"] = "baz"
        assert msg.metadata["foo"] == "bar"

    def test_attachments_unloaded_returns_empty(self):
        # SimpleNamespace doesn't have a SQLAlchemy state — _attachments_if_loaded
        # falls back to direct access
        row = _orm_row(attachments=None)
        msg = Message.from_orm(row)
        assert msg.attachments == ()


class TestToDict:
    def test_round_trip_shape(self):
        ch = uuid.uuid4()
        actor = ActorRef.bot("e2e", "E2E")
        msg = Message(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            role="assistant",
            content="hi",
            created_at=datetime(2026, 4, 11, 12, 0, 0, tzinfo=timezone.utc),
            actor=actor,
            channel_id=ch,
            metadata={"k": "v"},
        )
        d = msg.to_dict()
        assert d["id"] == str(msg.id)
        assert d["channel_id"] == str(ch)
        assert d["role"] == "assistant"
        assert d["actor"]["kind"] == "bot"
        assert d["actor"]["id"] == "e2e"
        assert d["actor"]["display_name"] == "E2E"
        assert d["created_at"] == "2026-04-11T12:00:00+00:00"
        assert d["attachments"] == []
        assert d["metadata"] == {"k": "v"}


class TestMessageOutFromDomain:
    def test_basic_round_trip(self):
        actor = ActorRef.user("U999", "Tester")
        att = AttachmentBrief(
            id=uuid.uuid4(),
            type="image",
            filename="pic.png",
            mime_type="image/png",
            size_bytes=42,
        )
        msg = Message(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            role="user",
            content="hi",
            created_at=datetime.now(timezone.utc),
            actor=actor,
            attachments=(att,),
        )
        out = MessageOut.from_domain(msg)
        assert out.id == msg.id
        assert out.session_id == msg.session_id
        assert out.role == "user"
        assert out.content == "hi"
        assert len(out.attachments) == 1
        assert out.attachments[0].filename == "pic.png"

    def test_metadata_is_copied(self):
        actor = ActorRef.user("U", "T")
        msg = Message(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            role="user",
            content="x",
            created_at=datetime.now(timezone.utc),
            actor=actor,
            metadata={"foo": "bar"},
        )
        out = MessageOut.from_domain(msg)
        # Mutating the source should not affect the schema
        msg.metadata["foo"] = "BANG"  # this works because the dict is mutable
        assert out.metadata["foo"] == "bar"


class TestImmutability:
    def test_message_is_frozen(self):
        msg = Message(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            role="user",
            content="x",
            created_at=datetime.now(timezone.utc),
            actor=ActorRef.user("u", "U"),
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            msg.content = "y"  # type: ignore[misc]
