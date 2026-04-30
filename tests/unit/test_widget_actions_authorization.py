from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import ast
import uuid
from pathlib import Path

import pytest

from app.dependencies import ApiKeyAuth
from app.domain.errors import ForbiddenError, ValidationError
from app.schemas.widget_actions import WidgetActionRequest, WidgetActionResponse
from app.services import widget_action_dispatch as dispatch_mod
from app.services import widget_action_state_poll as refresh_mod
from app.services.widget_action_auth import system_widget_action_auth


def _widget_auth(pin_id: uuid.UUID) -> ApiKeyAuth:
    return ApiKeyAuth(
        key_id=uuid.uuid4(),
        scopes=[],
        name="widget:test-bot",
        pin_id=pin_id,
    )


async def _make_pin(
    *,
    dashboard_key: str = "default",
    source_channel_id: uuid.UUID | None = None,
    widget_instance_id: uuid.UUID | None = None,
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        dashboard_key=dashboard_key,
        source_channel_id=source_channel_id,
        widget_instance_id=widget_instance_id,
    )


def _make_user(*, is_admin: bool = False):
    return SimpleNamespace(
        id=uuid.uuid4(),
        is_admin=is_admin,
    )


def _make_channel(*, user_id: uuid.UUID | None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        private=True,
        user_id=user_id,
    )


class FakeDb:
    def __init__(self) -> None:
        self.rows: dict[tuple[object, uuid.UUID], object] = {}

    def add(self, model: object, row: object) -> object:
        self.rows[(model, row.id)] = row
        return row

    async def get(self, model: object, key: uuid.UUID):
        return self.rows.get((model, key))


def _fake_db(*rows: object) -> FakeDb:
    from app.db.models import Channel, WidgetDashboardPin, WidgetInstance

    db = FakeDb()
    for row in rows:
        if hasattr(row, "dashboard_key"):
            db.add(WidgetDashboardPin, row)
        elif hasattr(row, "scope_kind"):
            db.add(WidgetInstance, row)
        else:
            db.add(Channel, row)
    return db


@pytest.mark.asyncio
async def test_tool_dispatch_stops_when_policy_requires_approval():
    req = WidgetActionRequest(
        dispatch="tool",
        tool="dangerous_tool",
        args={"target": "prod"},
        bot_id="bot-1",
    )

    decision = SimpleNamespace(
        action="require_approval",
        reason="dangerous action",
    )

    with patch.object(dispatch_mod, "_resolve_tool_name", return_value="dangerous_tool"), \
         patch.object(dispatch_mod, "is_local_tool", return_value=True), \
         patch.object(dispatch_mod, "call_local_tool", new=AsyncMock(return_value="{}")) as call_local, \
         patch("app.tools.registry.get_tool_execution_policy", return_value="normal"), \
         patch("app.tools.registry.get_tool_safety_tier", return_value="exec_capable"), \
         patch("app.agent.tool_dispatch._check_tool_policy", new=AsyncMock(return_value=decision)):
        resp = await dispatch_mod._dispatch_tool(req, db=object())

    assert resp.ok is False
    assert resp.error_kind == "conflict"
    assert resp.error == "dangerous action"
    call_local.assert_not_awaited()


@pytest.mark.asyncio
async def test_exec_capable_tool_requires_bot_context():
    req = WidgetActionRequest(
        dispatch="tool",
        tool="dangerous_tool",
        args={},
    )

    with patch.object(dispatch_mod, "_resolve_tool_name", return_value="dangerous_tool"), \
         patch.object(dispatch_mod, "is_local_tool", return_value=True), \
         patch.object(dispatch_mod, "call_local_tool", new=AsyncMock(return_value="{}")) as call_local, \
         patch("app.tools.registry.get_tool_execution_policy", return_value="normal"), \
         patch("app.tools.registry.get_tool_safety_tier", return_value="exec_capable"):
        resp = await dispatch_mod._dispatch_tool(req, db=object())

    assert resp.ok is False
    assert resp.error_kind == "forbidden"
    assert "bot context" in (resp.error or "")
    call_local.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_dispatch_raises_domain_validation_error():
    req = WidgetActionRequest.model_construct(dispatch="unknown")

    with pytest.raises(ValidationError) as excinfo:
        await dispatch_mod.dispatch_widget_action(
            req,
            db=object(),
            auth=system_widget_action_auth("test"),
        )

    assert str(excinfo.value) == "Unknown dispatch type: unknown"


@pytest.mark.asyncio
async def test_widget_token_cannot_dispatch_against_different_pin():
    own_pin = await _make_pin()
    other_pin = await _make_pin()
    db = _fake_db(own_pin, other_pin)

    req = WidgetActionRequest(
        dispatch="tool",
        tool="safe_tool",
        dashboard_pin_id=other_pin.id,
    )

    with patch.object(
        dispatch_mod,
        "_dispatch_tool",
        new=AsyncMock(return_value=WidgetActionResponse(ok=True)),
    ) as dispatch_tool:
        with pytest.raises(ForbiddenError, match="different pin"):
            await dispatch_mod.dispatch_widget_action(
                req,
                db,
                auth=_widget_auth(own_pin.id),
            )

    dispatch_tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_widget_token_can_dispatch_against_own_pin():
    pin = await _make_pin()
    db = _fake_db(pin)

    req = WidgetActionRequest(
        dispatch="tool",
        tool="safe_tool",
        dashboard_pin_id=pin.id,
    )

    with patch.object(
        dispatch_mod,
        "_dispatch_tool",
        new=AsyncMock(return_value=WidgetActionResponse(ok=True)),
    ) as dispatch_tool:
        resp = await dispatch_mod.dispatch_widget_action(
            req,
            db,
            auth=_widget_auth(pin.id),
        )

    assert resp.ok is True
    dispatch_tool.assert_awaited_once()


@pytest.mark.asyncio
async def test_pin_and_widget_instance_must_match_before_native_dispatch():
    pin = await _make_pin(widget_instance_id=None)
    db = _fake_db(pin)

    req = WidgetActionRequest(
        dispatch="native_widget",
        action="replace_body",
        dashboard_pin_id=pin.id,
        widget_instance_id=uuid.uuid4(),
    )

    with patch.object(
        dispatch_mod,
        "_dispatch_native_widget",
        new=AsyncMock(return_value=WidgetActionResponse(ok=True)),
    ) as dispatch_native:
        with pytest.raises(ForbiddenError, match="does not reference"):
            await dispatch_mod.dispatch_widget_action(
                req,
                db,
                auth=_widget_auth(pin.id),
            )

    dispatch_native.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_owner_user_cannot_dispatch_against_channel_pin():
    owner = _make_user()
    intruder = _make_user()
    intruder._resolved_scopes = ["channels:write"]
    channel = _make_channel(user_id=owner.id)
    pin = await _make_pin(
        dashboard_key=f"channel:{channel.id}",
        source_channel_id=channel.id,
    )
    db = _fake_db(channel, pin)

    req = WidgetActionRequest(
        dispatch="tool",
        tool="safe_tool",
        dashboard_pin_id=pin.id,
    )

    with patch.object(
        dispatch_mod,
        "_dispatch_tool",
        new=AsyncMock(return_value=WidgetActionResponse(ok=True)),
    ) as dispatch_tool:
        with pytest.raises(ForbiddenError, match="Channel owner"):
            await dispatch_mod.dispatch_widget_action(req, db, auth=intruder)

    dispatch_tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_user_can_dispatch_against_channel_pin():
    owner = _make_user()
    owner._resolved_scopes = ["channels:write"]
    channel = _make_channel(user_id=owner.id)
    pin = await _make_pin(
        dashboard_key=f"channel:{channel.id}",
        source_channel_id=channel.id,
    )
    db = _fake_db(channel, pin)

    req = WidgetActionRequest(
        dispatch="tool",
        tool="safe_tool",
        dashboard_pin_id=pin.id,
    )

    with patch.object(
        dispatch_mod,
        "_dispatch_tool",
        new=AsyncMock(return_value=WidgetActionResponse(ok=True)),
    ) as dispatch_tool:
        resp = await dispatch_mod.dispatch_widget_action(req, db, auth=owner)

    assert resp.ok is True
    dispatch_tool.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_batch_widget_token_cannot_refresh_different_pin():
    own_pin = await _make_pin()
    other_pin = await _make_pin()
    db = _fake_db(own_pin, other_pin)

    req = refresh_mod.WidgetRefreshBatchRequest(
        requests=[
            refresh_mod.WidgetRefreshBatchItem(
                request_id="other",
                tool_name="get_weather",
                dashboard_pin_id=other_pin.id,
            )
        ]
    )

    with pytest.raises(ForbiddenError, match="different pin"):
        await refresh_mod.refresh_widget_states_batch(
            req,
            db=db,
            auth=_widget_auth(own_pin.id),
        )


@pytest.mark.asyncio
async def test_widget_event_stream_auth_rejects_different_channel():
    from app.services.widget_action_auth import authorize_widget_channel_access

    other_channel = _make_channel(user_id=None)
    target_channel = _make_channel(user_id=None)
    pin = await _make_pin(
        dashboard_key=f"channel:{other_channel.id}",
        source_channel_id=other_channel.id,
    )
    db = _fake_db(other_channel, target_channel, pin)

    with pytest.raises(ForbiddenError, match="different channel"):
        await authorize_widget_channel_access(
            db,
            _widget_auth(pin.id),
            target_channel.id,
            required_scope="channels:read",
        )


@pytest.mark.asyncio
async def test_widget_actions_route_passes_auth_to_dispatch_guard():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.dependencies import get_db, verify_auth_or_user
    from app.domain.errors import install_domain_error_handler
    from app.routers.api_v1_widget_actions import router

    own_pin = await _make_pin()
    other_pin = await _make_pin()
    db = _fake_db(own_pin, other_pin)

    app = FastAPI()
    install_domain_error_handler(app)
    app.include_router(router)

    async def _override_db():
        yield db

    async def _override_auth():
        return _widget_auth(own_pin.id)

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[verify_auth_or_user] = _override_auth

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/widget-actions",
            json={
                "dispatch": "tool",
                "tool": "safe_tool",
                "dashboard_pin_id": str(other_pin.id),
            },
            headers={"Authorization": "Bearer widget-token"},
        )

    assert resp.status_code == 403
    assert "different pin" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_api_dispatch_rejects_endpoint_outside_allowlist():
    req = WidgetActionRequest(
        dispatch="api",
        endpoint="/api/v1/admin/users",
        method="GET",
    )

    resp = await dispatch_mod._dispatch_api(req)

    assert resp.ok is False
    assert "allowlist" in (resp.error or "")


@pytest.mark.asyncio
async def test_db_dispatch_rejects_sqlite_attach(tmp_path):
    pin = await _make_pin()
    db_path = tmp_path / "widget.sqlite"
    other_path = tmp_path / "other.sqlite"
    other_path.touch()
    req = WidgetActionRequest(
        dispatch="db_query",
        dashboard_pin_id=pin.id,
        sql="ATTACH DATABASE ? AS other",
        params=[str(other_path)],
    )

    with patch("app.services.dashboard_pins.get_pin", new=AsyncMock(return_value=pin)), \
         patch.object(dispatch_mod, "_load_pin_manifest_safely", return_value=None), \
         patch("app.services.widget_db.resolve_db_path", return_value=db_path):
        resp = await dispatch_mod._dispatch_db(req, db=object())

    assert resp.ok is False
    assert "not authorized" in (resp.error or "").lower()


def test_widget_actions_router_stays_thin() -> None:
    router_path = Path(__file__).resolve().parents[2] / "app" / "routers" / "api_v1_widget_actions.py"
    tree = ast.parse(router_path.read_text(encoding="utf-8"))
    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert function_names == {
        "dispatch_widget_action",
        "widget_event_stream_endpoint",
        "refresh_widget_states_batch",
        "refresh_widget_state",
    }

    forbidden = {
        "call_local_tool",
        "call_mcp_tool",
        "get_state_poll_config",
        "apply_state_poll",
        "apply_widget_template",
        "sqlite3",
        "dispatch_native_widget_action",
        "update_pin_envelope",
    }
    source = router_path.read_text(encoding="utf-8")
    assert all(name not in source for name in forbidden)
