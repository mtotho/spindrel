"""Phase E — POST /chat returns 202 + {session_id, channel_id, turn_id}.

These tests cover the new HTTP contract introduced in Phase E of the
Integration Delivery refactor. The agent loop and turn worker are
mocked at ``app.routers.chat._routes.start_turn`` so we exercise the
request handler in isolation: validation, channel/session resolution,
throttle / pause / busy-session policy, and the 202 response shape.

End-to-end coverage of the worker → bus → outbox → drainer → renderer
flow lives in ``tests/integration/test_outbox_drainer_smoke.py`` and
``tests/integration/test_turn_worker.py``.
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


def _fake_handle():
    """Build a TurnHandle with all-fresh UUIDs."""
    from app.services.turns import TurnHandle
    return TurnHandle(
        session_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        turn_id=uuid.uuid4(),
    )


class TestChat202:
    @pytest.fixture(autouse=True)
    def _mock_start_turn(self):
        with patch(
            "app.routers.chat._routes.start_turn", new_callable=AsyncMock
        ) as mock:
            mock.return_value = _fake_handle()
            self._mock = mock
            yield mock

    async def test_post_chat_returns_202_with_handle(self, client):
        resp = await client.post(
            "/chat",
            json={"message": "hi", "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 202
        body = resp.json()
        assert "session_id" in body
        assert "turn_id" in body
        assert "channel_id" in body
        # The handle fields are UUID strings — round-trip parses them.
        uuid.UUID(body["turn_id"])
        uuid.UUID(body["session_id"])
        uuid.UUID(body["channel_id"])

    async def test_post_chat_stream_returns_same_202(self, client):
        """``/chat/stream`` is a compat shim that returns the same 202."""
        resp = await client.post(
            "/chat/stream",
            json={"message": "hi", "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 202
        body = resp.json()
        assert "turn_id" in body

    async def test_start_turn_called_once_per_request(self, client):
        await client.post(
            "/chat",
            json={"message": "hello", "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert self._mock.await_count == 1
        kwargs = self._mock.await_args.kwargs
        assert kwargs["bot"].id == "test-bot"
        assert kwargs["user_message"] == "hello"

    async def test_passive_message_does_not_call_start_turn(self, client):
        resp = await client.post(
            "/chat",
            json={"message": "store me", "bot_id": "test-bot", "passive": True},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 202
        assert resp.json().get("passive") is True
        self._mock.assert_not_awaited()

    async def test_busy_session_returns_queued_202(self, client):
        """If start_turn raises SessionBusyError, the request returns a
        queued task id rather than failing."""
        from app.services.turns import SessionBusyError
        self._mock.side_effect = SessionBusyError("busy")

        resp = await client.post(
            "/chat",
            json={"message": "queue me", "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body.get("queued") is True
        assert "task_id" in body

    async def test_secondary_channel_session_requires_web_only_delivery(self, client, db_session):
        from app.db.models import Channel, Session

        channel_id = uuid.uuid4()
        primary = Session(
            id=uuid.uuid4(), client_id="web", bot_id="test-bot",
            channel_id=channel_id, session_type="channel",
        )
        secondary = Session(
            id=uuid.uuid4(), client_id="web", bot_id="test-bot",
            channel_id=channel_id, session_type="channel",
        )
        channel = Channel(
            id=channel_id, client_id="web", bot_id="test-bot",
            name="session split", active_session_id=primary.id,
        )
        db_session.add_all([channel, primary, secondary])
        await db_session.flush()

        resp = await client.post(
            "/chat",
            json={
                "message": "secondary visible only in web",
                "bot_id": "test-bot",
                "channel_id": str(channel_id),
                "session_id": str(secondary.id),
            },
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 409
        assert self._mock.await_count == 0

    async def test_secondary_channel_session_can_send_web_only(self, client, db_session):
        from app.db.models import Channel, Session

        channel_id = uuid.uuid4()
        primary = Session(
            id=uuid.uuid4(), client_id="web", bot_id="test-bot",
            channel_id=channel_id, session_type="channel",
        )
        secondary = Session(
            id=uuid.uuid4(), client_id="web", bot_id="test-bot",
            channel_id=channel_id, session_type="channel",
        )
        channel = Channel(
            id=channel_id, client_id="web", bot_id="test-bot",
            name="session split", active_session_id=primary.id,
        )
        db_session.add_all([channel, primary, secondary])
        await db_session.flush()

        resp = await client.post(
            "/chat",
            json={
                "message": "secondary visible only in web",
                "bot_id": "test-bot",
                "channel_id": str(channel_id),
                "session_id": str(secondary.id),
                "external_delivery": "none",
            },
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 202, resp.text
        assert resp.json().get("session_scoped") is True
        assert self._mock.await_count == 1
        kwargs = self._mock.await_args.kwargs
        assert kwargs["session_id"] == secondary.id
        assert kwargs["channel_id"] == channel_id
        assert kwargs["session_scoped"] is True


# ---------------------------------------------------------------------------
# Sub-session follow-up (Phase A of Track - Task Sub-Sessions continuation)
# ---------------------------------------------------------------------------


async def _seed_sub_session_chain(
    db_session,
    *,
    task_status: str = "complete",
    bot_id: str = "test-bot",
):
    """Build a channel → parent_session → sub_session → task chain."""
    from app.db.models import Channel, Session, Task

    channel = Channel(
        id=uuid.uuid4(), client_id="web", bot_id=bot_id, name="t",
    )
    parent = Session(
        id=uuid.uuid4(), client_id="web", bot_id=bot_id,
        channel_id=channel.id, depth=0, session_type="channel",
    )
    sub = Session(
        id=uuid.uuid4(), client_id="task", bot_id=bot_id,
        channel_id=None, parent_session_id=parent.id, root_session_id=parent.id,
        depth=1, session_type="pipeline_run",
    )
    db_session.add_all([channel, parent, sub])
    await db_session.flush()
    task = Task(
        id=uuid.uuid4(), bot_id=bot_id, prompt="p", status=task_status,
        task_type="pipeline", dispatch_type="none",
        run_isolation="sub_session", run_session_id=sub.id,
        channel_id=channel.id,
    )
    db_session.add(task)
    await db_session.flush()
    sub.source_task_id = task.id
    await db_session.flush()
    return channel, parent, sub, task


class TestChatSubSessionFollowUp:
    """POST /chat with session_id pointing at a terminal sub-session routes
    through the dedicated sub-session enqueue path: bot forced to task.bot_id,
    channel_id = parent (for bus routing), start_turn called with
    session_scoped=True."""

    @pytest.fixture(autouse=True)
    def _mock_start_turn(self):
        from app.services.turns import TurnHandle

        with patch(
            "app.routers.chat._routes.start_turn", new_callable=AsyncMock
        ) as mock:
            def _build_handle(*args, **kwargs):
                return TurnHandle(
                    session_id=kwargs["session_id"],
                    channel_id=kwargs["channel_id"],
                    turn_id=uuid.uuid4(),
                    session_scoped=kwargs.get("session_scoped", False),
                )

            mock.side_effect = _build_handle
            self._mock = mock
            yield mock

    async def test_post_with_terminal_sub_session_id_returns_session_scoped(
        self, client, db_session,
    ):
        _, _, sub, task = await _seed_sub_session_chain(
            db_session, task_status="complete", bot_id="test-bot",
        )

        resp = await client.post(
            "/chat",
            json={
                "message": "follow-up question",
                "session_id": str(sub.id),
                "bot_id": "test-bot",
            },
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body.get("session_scoped") is True
        assert body["session_id"] == str(sub.id)

        # start_turn was called exactly once and with session_scoped=True.
        assert self._mock.await_count == 1
        kwargs = self._mock.await_args.kwargs
        assert kwargs["session_scoped"] is True
        assert kwargs["session_id"] == sub.id
        # Bot identity is forced to task.bot_id, not the URL-bar bot_id.
        assert kwargs["bot"].id == task.bot_id

    async def test_non_terminal_run_returns_409(self, client, db_session):
        _, _, sub, _ = await _seed_sub_session_chain(
            db_session, task_status="running",
        )

        resp = await client.post(
            "/chat",
            json={"message": "interrupt", "session_id": str(sub.id), "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 409
        assert "running" in resp.text.lower() or "terminal" in resp.text.lower()
        # start_turn MUST NOT have been invoked for a non-terminal run.
        assert self._mock.await_count == 0

    async def test_channel_less_ephemeral_posts_with_null_channel_id(
        self, client, db_session,
    ):
        """POST /chat against an ephemeral session with no parent channel
        must succeed (not 400) — start_turn receives channel_id=None and
        the 202 response body reports channel_id: null. Covers the widget
        dashboard dock case where the user is on a global dashboard page."""
        from app.db.models import Session

        ephemeral = Session(
            id=uuid.uuid4(),
            client_id="web",
            bot_id="test-bot",
            channel_id=None,
            depth=0,
            session_type="ephemeral",
        )
        db_session.add(ephemeral)
        await db_session.flush()

        resp = await client.post(
            "/chat",
            json={
                "message": "kick off a widget",
                "session_id": str(ephemeral.id),
                "bot_id": "test-bot",
            },
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body.get("session_scoped") is True
        assert body["session_id"] == str(ephemeral.id)
        # Channel-less — channel_id in the response is null.
        assert body["channel_id"] is None

        # start_turn invoked with channel_id=None and session_scoped=True.
        assert self._mock.await_count == 1
        kwargs = self._mock.await_args.kwargs
        assert kwargs["session_scoped"] is True
        assert kwargs["session_id"] == ephemeral.id
        assert kwargs["channel_id"] is None

    async def test_unknown_session_falls_through_to_channel_path(
        self, client, db_session,
    ):
        """A session_id that doesn't resolve to a sub-session must NOT be
        treated as sub-session — the regular channel path handles it, which
        means start_turn receives session_scoped=False."""
        random_sid = uuid.uuid4()
        resp = await client.post(
            "/chat",
            json={
                "message": "hi",
                "session_id": str(random_sid),
                "bot_id": "test-bot",
            },
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 202
        assert self._mock.await_count == 1
        kwargs = self._mock.await_args.kwargs
        # Regular channel path doesn't pass session_scoped (kwarg absent) —
        # that's the tell that the sub-session branch did NOT engage.
        assert not kwargs.get("session_scoped", False)
