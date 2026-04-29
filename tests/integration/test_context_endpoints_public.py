"""Integration tests for the public channel context endpoints.

Mirrors the admin-prefixed endpoints in `api_v1_admin/channels.py` but under
`/api/v1/channels/{id}/` so bot-authenticated HTML widgets can consume them
without the `admin` scope. Covers:

- GET /api/v1/channels/{id}/context-budget
- GET /api/v1/channels/{id}/context-breakdown

And asserts parity with the admin routes where they overlap.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Message, Session, TraceEvent


AUTH_HEADERS = {"Authorization": "Bearer test-key"}


async def _setup_channel_with_trace(
    db_session: AsyncSession,
    *,
    budget: dict | None = None,
) -> str:
    """Insert a channel + session + optional context_injection_summary trace."""
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    db_session.add(Channel(
        id=channel_id,
        name="ctx-endpoint-test",
        bot_id="test-bot",
        active_session_id=session_id,
    ))
    db_session.add(Session(
        id=session_id,
        bot_id="test-bot",
        client_id=f"c-{channel_id.hex[:8]}",
        channel_id=channel_id,
    ))
    if budget is not None:
        db_session.add(TraceEvent(
            session_id=session_id,
            event_type="context_injection_summary",
            data={"context_budget": budget, "context_profile": "chat"},
            created_at=now,
        ))
    await db_session.commit()
    return str(channel_id)


class TestPublicContextBudget:
    @pytest.mark.asyncio
    async def test_returns_latest_budget(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        cid = await _setup_channel_with_trace(
            db_session,
            budget={"utilization": 0.42, "consumed_tokens": 8400, "total_tokens": 20000},
        )
        resp = await client.get(
            f"/api/v1/channels/{cid}/context-budget",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body == {
            "utilization": 0.42,
            "consumed_tokens": 8400,
            "total_tokens": 20000,
            "gross_prompt_tokens": 8400,
            "current_prompt_tokens": 8400,
            "cached_prompt_tokens": None,
            "completion_tokens": None,
            "context_profile": "chat",
            "source": "estimate",
        }

    @pytest.mark.asyncio
    async def test_returns_sentinel_when_no_trace(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        cid = await _setup_channel_with_trace(db_session, budget=None)
        resp = await client.get(
            f"/api/v1/channels/{cid}/context-budget",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "utilization": None,
            "consumed_tokens": None,
            "total_tokens": None,
            "gross_prompt_tokens": None,
            "current_prompt_tokens": None,
            "cached_prompt_tokens": None,
            "completion_tokens": None,
            "context_profile": None,
            "source": "none",
        }

    @pytest.mark.asyncio
    async def test_unknown_channel_404s(
        self, client: AsyncClient,
    ):
        fake = uuid.uuid4()
        resp = await client.get(
            f"/api/v1/channels/{fake}/context-budget",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_parity_with_admin_route(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        """The public and admin endpoints must return identical payloads —
        drift between them is exactly what moving to a shared helper
        (`fetch_latest_context_budget`) is meant to prevent."""
        cid = await _setup_channel_with_trace(
            db_session,
            budget={"utilization": 0.1, "consumed_tokens": 2000, "total_tokens": 20000},
        )
        public = (await client.get(
            f"/api/v1/channels/{cid}/context-budget", headers=AUTH_HEADERS,
        )).json()
        admin = (await client.get(
            f"/api/v1/admin/channels/{cid}/context-budget", headers=AUTH_HEADERS,
        )).json()
        assert public == admin

    @pytest.mark.asyncio
    async def test_session_scoped_query_matches_admin_route(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        channel_id = uuid.uuid4()
        scratch_session_id = uuid.uuid4()
        channel_session_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        db_session.add(Channel(
            id=channel_id,
            name="ctx-public-session-scope",
            bot_id="test-bot",
            active_session_id=channel_session_id,
        ))
        db_session.add_all([
            Session(
                id=scratch_session_id,
                bot_id="test-bot",
                client_id=f"c-{channel_id.hex[:8]}-scratch",
                channel_id=None,
                parent_channel_id=channel_id,
                session_type="ephemeral",
            ),
            Session(
                id=channel_session_id,
                bot_id="test-bot",
                client_id=f"c-{channel_id.hex[:8]}-main",
                channel_id=channel_id,
            ),
        ])
        db_session.add_all([
            TraceEvent(
                session_id=scratch_session_id,
                event_type="context_injection_summary",
                data={"context_budget": {"utilization": 0.12, "consumed_tokens": 1200, "total_tokens": 10000}},
                created_at=now.replace(microsecond=1000),
            ),
            TraceEvent(
                session_id=channel_session_id,
                event_type="context_injection_summary",
                data={"context_budget": {"utilization": 0.55, "consumed_tokens": 5500, "total_tokens": 10000}},
                created_at=now.replace(microsecond=2000),
            ),
        ])
        await db_session.commit()

        public = (await client.get(
            f"/api/v1/channels/{channel_id}/context-budget?session_id={scratch_session_id}",
            headers=AUTH_HEADERS,
        )).json()
        admin = (await client.get(
            f"/api/v1/admin/channels/{channel_id}/context-budget?session_id={scratch_session_id}",
            headers=AUTH_HEADERS,
        )).json()
        assert public == admin
        assert public["consumed_tokens"] == 1200


class TestPublicContextBreakdown:
    @pytest.mark.asyncio
    async def test_shape_matches_expected(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        cid = await _setup_channel_with_trace(db_session, budget=None)
        resp = await client.get(
            f"/api/v1/channels/{cid}/context-breakdown",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Core fields that widgets will actually consume.
        for key in (
            "channel_id", "session_id", "bot_id",
            "categories", "total_chars", "total_tokens_approx",
            "compaction", "reranking", "context_budget", "context_profile", "disclaimer",
        ):
            assert key in body, f"missing key {key!r} in breakdown response"
        assert isinstance(body["categories"], list)

    @pytest.mark.asyncio
    async def test_session_scoped_breakdown_uses_selected_session(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        channel_id = uuid.uuid4()
        main_session_id = uuid.uuid4()
        scratch_session_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        watermark_time = now - timedelta(minutes=10)
        after_watermark = now - timedelta(minutes=5)

        db_session.add(Channel(
            id=channel_id,
            name="ctx-public-breakdown-session-scope",
            bot_id="test-bot",
            active_session_id=main_session_id,
            compaction_interval=10,
        ))
        db_session.add_all([
            Session(
                id=main_session_id,
                bot_id="test-bot",
                client_id=f"c-{channel_id.hex[:8]}-main",
                channel_id=channel_id,
            ),
            Session(
                id=scratch_session_id,
                bot_id="test-bot",
                client_id=f"c-{channel_id.hex[:8]}-scratch",
                channel_id=channel_id,
                summary="Scratch summary",
            ),
        ])
        watermark_message = Message(
            id=uuid.uuid4(),
            session_id=scratch_session_id,
            role="assistant",
            content="summary watermark",
            created_at=watermark_time,
        )
        db_session.add(watermark_message)
        await db_session.flush()

        scratch_session = await db_session.get(Session, scratch_session_id)
        assert scratch_session is not None
        scratch_session.summary_message_id = watermark_message.id

        db_session.add_all([
            Message(
                id=uuid.uuid4(),
                session_id=main_session_id,
                role="user",
                content="main session message",
                created_at=after_watermark,
            ),
            Message(
                id=uuid.uuid4(),
                session_id=scratch_session_id,
                role="user",
                content="scratch user one",
                created_at=after_watermark,
            ),
            Message(
                id=uuid.uuid4(),
                session_id=scratch_session_id,
                role="assistant",
                content="scratch assistant one",
                created_at=after_watermark + timedelta(seconds=1),
            ),
            Message(
                id=uuid.uuid4(),
                session_id=scratch_session_id,
                role="user",
                content="scratch user two",
                created_at=after_watermark + timedelta(seconds=2),
            ),
        ])
        await db_session.commit()

        public = (await client.get(
            f"/api/v1/channels/{channel_id}/context-breakdown?session_id={scratch_session_id}",
            headers=AUTH_HEADERS,
        )).json()
        admin = (await client.get(
            f"/api/v1/admin/channels/{channel_id}/context-breakdown?session_id={scratch_session_id}",
            headers=AUTH_HEADERS,
        )).json()

        assert "effective_settings" not in public
        assert "effective_settings" in admin
        admin_without_effective = dict(admin)
        admin_without_effective.pop("effective_settings", None)
        assert public == admin_without_effective
        assert public["session_id"] == str(scratch_session_id)
        assert public["compaction"]["messages_since_watermark"] == 3
        assert public["compaction"]["total_messages"] == 4
        assert public["compaction"]["turns_until_next"] == 8


class TestWidgetPinImplicitAuth:
    """A widget JWT whose pin lives on channel:<channel_id>'s dashboard must
    be able to read that channel's context without the bot carrying
    `channels:read` — the pin itself is the authorization.

    The `client` fixture overrides `verify_auth_or_user` to always return
    admin, so we exercise the auth helper directly. That's the right
    granularity anyway — we're asserting the auth decision, not the full
    HTTP round trip."""

    @pytest.mark.asyncio
    async def test_widget_with_matching_pin_bypasses_scope_gate(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        from app.dependencies import ApiKeyAuth
        from app.db.models import WidgetDashboard, WidgetDashboardPin
        from app.routers.api_v1_channels import _auth_channel_context

        cid = await _setup_channel_with_trace(db_session, budget=None)
        db_session.add(WidgetDashboard(
            slug=f"channel:{cid}",
            name="Channel dashboard",
        ))
        await db_session.flush()
        pin = WidgetDashboardPin(
            dashboard_key=f"channel:{cid}",
            position=0,
            source_kind="builtin",
            source_bot_id="test-bot",
            tool_name="context_tracker",
            envelope={"content_type": "application/vnd.spindrel.html+interactive", "body": ""},
        )
        db_session.add(pin)
        await db_session.commit()
        await db_session.refresh(pin)

        auth = ApiKeyAuth(
            key_id=uuid.uuid4(),
            scopes=[],  # no channels:read
            name="widget:test-bot",
            pin_id=pin.id,
        )
        await _auth_channel_context(uuid.UUID(cid), auth, db_session)  # no raise

    @pytest.mark.asyncio
    async def test_widget_pin_on_different_channel_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        from fastapi import HTTPException
        from app.dependencies import ApiKeyAuth
        from app.db.models import WidgetDashboard, WidgetDashboardPin
        from app.routers.api_v1_channels import _auth_channel_context

        target_cid = await _setup_channel_with_trace(db_session, budget=None)
        other_cid = await _setup_channel_with_trace(db_session, budget=None)
        db_session.add(WidgetDashboard(
            slug=f"channel:{other_cid}",
            name="Other",
        ))
        await db_session.flush()
        pin = WidgetDashboardPin(
            dashboard_key=f"channel:{other_cid}",  # pin on OTHER channel
            position=0,
            source_kind="builtin",
            source_bot_id="test-bot",
            tool_name="context_tracker",
            envelope={"content_type": "application/vnd.spindrel.html+interactive", "body": ""},
        )
        db_session.add(pin)
        await db_session.commit()
        await db_session.refresh(pin)

        auth = ApiKeyAuth(
            key_id=uuid.uuid4(),
            scopes=[],
            name="widget:test-bot",
            pin_id=pin.id,
        )
        with pytest.raises(HTTPException) as exc:
            await _auth_channel_context(uuid.UUID(target_cid), auth, db_session)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_widget_without_pin_id_requires_scope(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        from fastapi import HTTPException
        from app.dependencies import ApiKeyAuth
        from app.routers.api_v1_channels import _auth_channel_context

        cid = await _setup_channel_with_trace(db_session, budget=None)
        auth = ApiKeyAuth(
            key_id=uuid.uuid4(),
            scopes=[],
            name="widget:test-bot",
            pin_id=None,  # no pin → falls through to scope check → 403
        )
        with pytest.raises(HTTPException) as exc:
            await _auth_channel_context(uuid.UUID(cid), auth, db_session)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_api_key_with_channels_read_passes(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        from app.dependencies import ApiKeyAuth
        from app.routers.api_v1_channels import _auth_channel_context

        cid = await _setup_channel_with_trace(db_session, budget=None)
        auth = ApiKeyAuth(
            key_id=uuid.uuid4(),
            scopes=["channels:read"],
            name="scoped-key",
        )
        await _auth_channel_context(uuid.UUID(cid), auth, db_session)  # no raise
