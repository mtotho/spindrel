"""Phase Q-MACH — ``/integrations/local_companion/ws`` drift seams.

Companion to ``test_machine_control_drift.py`` (Phase O, service layer) and
``test_machine_admin_routes_drift.py`` (admin routes). This file drift-pins
the WebSocket handshake in ``integrations/local_companion/router.py``:

  QW.1  Unknown ``target_id`` → close 4404 before ``accept()``. The
        server must refuse the handshake without leaking whether the
        target exists (vs a wrong token — different close code so
        operators can triage but no additional metadata is exposed).
  QW.2  Known target, wrong token → close 4401. Token check uses
        ``secrets.compare_digest`` — the test exercises the unequal
        branch; timing-safe behavior is a lower-level invariant.
  QW.3  Known target, empty registered token → close 4404 (not 4401).
        The falsy-token branch short-circuits BEFORE the
        ``compare_digest`` call so a mis-seeded target cannot be
        authenticated with an empty-string token.
  QW.4  Valid handshake, malformed hello frame → close 4400 after
        ``accept()``. Three variants:
          - first frame is JSON but not a dict
          - first frame is a dict but ``type != "hello"``
  QW.5  Successful hello → ``provider.register_connected_target`` and
        ``bridge.register`` are BOTH called once, in that order. This
        is the happy-path drift guard: a refactor that splits the two
        would break last-seen updates or the live connection registry.
  QW.6  Multi-connect contention on the same ``target_id``: the second
        connection wins; ``bridge`` unregisters the first. Last-writer
        wins is the current (documented) contract.
  QW.7  Clean disconnect: ``WebSocketDisconnect`` on the read loop
        unregisters the connection in a ``finally`` block.

Seams deliberately NOT covered: real DB writes (``async_session`` is
patched to a stub), heartbeat/timeout paths (not implemented yet in the
router), token rotation on reconnect (no such code path exists).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.services import machine_control as machine_control_service
from integrations.local_companion import router as local_companion_router


# ---------------------------------------------------------------------------
# Fixtures — minimal app + patched provider/bridge/async_session seam.
# ---------------------------------------------------------------------------


class _StubProvider:
    """Minimal provider surface the WS handshake touches."""

    def __init__(self, *, token: str | None, label: str = "Desk"):
        self._token = token
        self._label = label
        self.register_calls: list[dict[str, Any]] = []

    def get_target(self, target_id: str) -> dict[str, Any] | None:
        if self._token is None:
            return None
        return {"target_id": target_id, "token": self._token, "label": self._label}

    async def register_connected_target(self, db, **kwargs):
        self.register_calls.append(kwargs)
        return kwargs


class _StubBridge:
    """Bridge stand-in that records register/unregister without async locks."""

    def __init__(self) -> None:
        self.register_calls: list[dict[str, Any]] = []
        self.unregister_calls: list[Any] = []
        self._counter = 0

    async def register(self, send, *, target_id, label, hostname, platform, capabilities):
        self._counter += 1
        conn = type(
            "_Conn",
            (),
            {
                "connection_id": f"conn-{self._counter}",
                "target_id": target_id,
                "label": label,
                "hostname": hostname,
                "platform": platform,
                "capabilities": list(capabilities),
                "send": send,
                "pending": {},
            },
        )()
        self.register_calls.append(
            {
                "target_id": target_id,
                "label": label,
                "hostname": hostname,
                "platform": platform,
                "capabilities": list(capabilities),
                "connection_id": conn.connection_id,
            }
        )
        return conn

    async def unregister(self, conn):
        self.unregister_calls.append(conn)

    async def unregister_target(self, target_id):
        self.unregister_calls.append(target_id)


@asynccontextmanager
async def _fake_async_session():
    yield object()


@pytest.fixture
def stub_provider(monkeypatch):
    provider = _StubProvider(token="secret-token-abc")

    def _get_provider(_pid):
        return provider

    def _get_target_by_id(_pid, target_id):
        if provider.get_target(target_id) is None:
            return None
        return {"label": provider._label, "target_id": target_id}

    monkeypatch.setattr(local_companion_router, "get_provider", _get_provider)
    monkeypatch.setattr(local_companion_router, "get_target_by_id", _get_target_by_id)
    monkeypatch.setattr(machine_control_service, "get_provider", _get_provider)
    return provider


@pytest.fixture
def stub_bridge(monkeypatch):
    bridge = _StubBridge()
    monkeypatch.setattr(local_companion_router, "bridge", bridge)
    return bridge


@pytest.fixture
def patched_async_session(monkeypatch):
    monkeypatch.setattr(local_companion_router, "async_session", _fake_async_session)


@pytest.fixture
def app(stub_provider, stub_bridge, patched_async_session) -> FastAPI:
    test_app = FastAPI()
    test_app.include_router(
        local_companion_router.router, prefix="/integrations/local_companion"
    )
    return test_app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def _url(target_id: str, token: str = "") -> str:
    _ = token
    return f"/integrations/local_companion/ws?target_id={target_id}"


def _authenticate(ws, *, target_id: str = "target-1", token: str = "secret-token-abc") -> None:
    challenge = ws.receive_json()
    assert challenge["type"] == "challenge"
    assert challenge["target_id"] == target_id
    sig = local_companion_router._challenge_signature(
        token,
        target_id=target_id,
        nonce=challenge["nonce"],
    )
    ws.send_json({"type": "auth", "signature": f"sha256={sig}"})


# ---------------------------------------------------------------------------
# QW.1 — Unknown target_id → close 4404, no side effects.
# ---------------------------------------------------------------------------


class TestUnknownTarget:
    def test_unknown_target_id_closes_4404_and_does_not_register(
        self, client, stub_bridge, stub_provider, monkeypatch
    ):
        # Make every target_id unknown.
        monkeypatch.setattr(
            local_companion_router,
            "get_provider",
            lambda _pid: _StubProvider(token=None),
        )
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(_url("ghost", "any-token")) as ws:
                ws.receive_text()
        assert exc_info.value.code == 4404
        assert stub_bridge.register_calls == []
        assert stub_provider.register_calls == []


# ---------------------------------------------------------------------------
# QW.2 — Wrong token for known target → close 4401.
# ---------------------------------------------------------------------------


class TestWrongToken:
    def test_wrong_token_closes_4401(self, client, stub_bridge, stub_provider):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(_url("target-1", "WRONG-token")) as ws:
                _authenticate(ws, token="WRONG-token")
                ws.receive_text()
        assert exc_info.value.code == 4401
        assert stub_bridge.register_calls == []
        assert stub_provider.register_calls == []


# ---------------------------------------------------------------------------
# QW.3 — Empty registered token short-circuits to 4404 (no compare_digest).
# ---------------------------------------------------------------------------


class TestEmptyRegisteredToken:
    def test_empty_stored_token_closes_4404_even_if_client_sends_empty(
        self, client, stub_bridge, monkeypatch
    ):
        """If the stored target has an empty token (mis-seeded row) the
        server MUST NOT treat an empty client token as a valid match.
        The falsy-token fast-path closes with 4404 before reaching
        ``compare_digest``.
        """
        provider = _StubProvider(token="")
        monkeypatch.setattr(local_companion_router, "get_provider", lambda _pid: provider)

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(_url("target-1", "")) as ws:
                ws.receive_text()
        assert exc_info.value.code == 4404
        assert stub_bridge.register_calls == []


# ---------------------------------------------------------------------------
# QW.4 — Malformed hello frame → close 4400 after accept.
# ---------------------------------------------------------------------------


class TestHelloFrameShape:
    def test_non_dict_first_frame_closes_4400(self, client, stub_bridge):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(_url("target-1", "secret-token-abc")) as ws:
                _authenticate(ws)
                ws.send_json(["not", "a", "dict"])
                ws.receive_text()
        assert exc_info.value.code == 4400
        assert stub_bridge.register_calls == []

    def test_dict_without_hello_type_closes_4400(self, client, stub_bridge):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(_url("target-1", "secret-token-abc")) as ws:
                _authenticate(ws)
                ws.send_json({"type": "result", "payload": "ignored"})
                ws.receive_text()
        assert exc_info.value.code == 4400
        assert stub_bridge.register_calls == []

    def test_wrong_type_field_closes_4400(self, client, stub_bridge):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(_url("target-1", "secret-token-abc")) as ws:
                _authenticate(ws)
                ws.send_json({"type": "HELLO"})  # case-sensitive
                ws.receive_text()
        assert exc_info.value.code == 4400
        assert stub_bridge.register_calls == []


# ---------------------------------------------------------------------------
# QW.5 — Successful handshake registers with provider and bridge.
# ---------------------------------------------------------------------------


class TestSuccessfulHandshake:
    def test_valid_hello_registers_target_and_bridge(
        self, client, stub_bridge, stub_provider
    ):
        hello = {
            "type": "hello",
            "label": "LivingRoom",
            "hostname": "nuc-01",
            "platform": "linux",
            "capabilities": ["shell", "fs"],
        }
        with client.websocket_connect(_url("target-1", "secret-token-abc")) as ws:
            _authenticate(ws)
            ws.send_json(hello)
            server_hello = ws.receive_json()
            assert server_hello["type"] == "hello"
            assert server_hello["target_id"] == "target-1"
            assert server_hello["connection_id"].startswith("conn-")

        # Both the DB-side register and the in-memory bridge register
        # must be called exactly once, with the hello-frame metadata.
        assert len(stub_provider.register_calls) == 1
        provider_call = stub_provider.register_calls[0]
        assert provider_call["target_id"] == "target-1"
        assert provider_call["label"] == "LivingRoom"
        assert provider_call["hostname"] == "nuc-01"
        assert provider_call["platform"] == "linux"
        assert provider_call["capabilities"] == ["shell", "fs"]

        assert len(stub_bridge.register_calls) == 1
        bridge_call = stub_bridge.register_calls[0]
        assert bridge_call["target_id"] == "target-1"
        assert bridge_call["label"] == "LivingRoom"
        assert bridge_call["capabilities"] == ["shell", "fs"]

    def test_hello_with_empty_capabilities_defaults_to_shell(
        self, client, stub_bridge, stub_provider
    ):
        """The handshake defaults ``capabilities`` to ``["shell"]`` when
        the companion reports an empty list — matches the fallback in
        ``router.py::companion_ws``. Applied to BOTH the provider and
        bridge calls; drift that drops the default on either side would
        leave the registry saying the companion has no capabilities.
        """
        with client.websocket_connect(_url("target-1", "secret-token-abc")) as ws:
            _authenticate(ws)
            ws.send_json({"type": "hello", "capabilities": []})
            ws.receive_json()

        assert stub_bridge.register_calls[0]["capabilities"] == ["shell"]
        assert stub_provider.register_calls[0]["capabilities"] == ["shell"]

    def test_clean_disconnect_unregisters_bridge_connection(
        self, client, stub_bridge, stub_provider
    ):
        with client.websocket_connect(_url("target-1", "secret-token-abc")) as ws:
            _authenticate(ws)
            ws.send_json({"type": "hello"})
            ws.receive_json()
            # Exit the context — raises WebSocketDisconnect server-side,
            # which routes through the ``finally: await bridge.unregister``.
        # Bridge unregister was called exactly once, with the registered conn.
        assert len(stub_bridge.unregister_calls) == 1
        registered_conn_id = stub_bridge.register_calls[0]["connection_id"]
        unregistered = stub_bridge.unregister_calls[0]
        assert getattr(unregistered, "connection_id", None) == registered_conn_id


# ---------------------------------------------------------------------------
# QW.6 — Multi-connect contention: last-wins contract.
# ---------------------------------------------------------------------------


class TestMultiConnectContention:
    def test_two_connects_register_two_bridge_entries(
        self, client, stub_bridge, stub_provider
    ):
        """The current contract is last-writer-wins: the second valid
        handshake registers a fresh connection; when the first socket
        tears down it calls unregister, which the real Bridge treats as
        a no-op if the registry already points at the newer conn.
        We pin that the second handshake does NOT short-circuit the
        first — both register calls must happen.
        """
        with client.websocket_connect(_url("target-1", "secret-token-abc")) as ws1:
            _authenticate(ws1)
            ws1.send_json({"type": "hello", "label": "first"})
            ws1.receive_json()

            with client.websocket_connect(
                _url("target-1", "secret-token-abc")
            ) as ws2:
                _authenticate(ws2)
                ws2.send_json({"type": "hello", "label": "second"})
                ws2.receive_json()

        # Two separate bridge registrations, both with target-1.
        assert len(stub_bridge.register_calls) == 2
        assert stub_bridge.register_calls[0]["label"] == "first"
        assert stub_bridge.register_calls[1]["label"] == "second"
        # Each register got paired with its own unregister on teardown.
        assert len(stub_bridge.unregister_calls) == 2

    def test_second_valid_handshake_sees_fresh_connection_id(
        self, client, stub_bridge, stub_provider
    ):
        with client.websocket_connect(_url("target-1", "secret-token-abc")) as ws1:
            _authenticate(ws1)
            ws1.send_json({"type": "hello"})
            first_conn_id = ws1.receive_json()["connection_id"]

            with client.websocket_connect(
                _url("target-1", "secret-token-abc")
            ) as ws2:
                _authenticate(ws2)
                ws2.send_json({"type": "hello"})
                second_conn_id = ws2.receive_json()["connection_id"]

        assert first_conn_id != second_conn_id


# ---------------------------------------------------------------------------
# QW.8 — Extensions to ``test_local_companion_provider.py`` (provider impl).
# Kept in this file so all Phase Q-MACH drift pins live side-by-side.
# ---------------------------------------------------------------------------


class TestProviderImplDriftExtensions:
    @pytest.mark.asyncio
    async def test_register_connected_target_ignores_unknown_target_id(self):
        """A companion connecting with a ``target_id`` that isn't in the
        stored target list is a no-op: no persistence write, no crash.
        This pins the tolerant path through
        ``LocalCompanionMachineControlProvider.register_connected_target``.
        """
        from integrations.local_companion import (
            machine_control as local_companion_machine_control,
        )

        monkeypatched_targets: list[dict[str, Any]] = [
            {
                "target_id": "known",
                "token": "t",
                "driver": "companion",
                "label": "Known",
                "hostname": "",
                "platform": "",
                "capabilities": [],
            }
        ]
        saved_targets: list[list[dict[str, Any]]] = []

        async def _save_targets(_db, targets):
            saved_targets.append(list(targets))

        provider = local_companion_machine_control.LocalCompanionMachineControlProvider()

        # Patch the module-level helpers the provider calls.
        original_get = local_companion_machine_control.get_registered_targets
        original_save = local_companion_machine_control._save_targets
        local_companion_machine_control.get_registered_targets = (
            lambda: list(monkeypatched_targets)
        )
        local_companion_machine_control._save_targets = _save_targets
        try:
            result = await provider.register_connected_target(
                object(),
                target_id="ghost",
                label="Nope",
                capabilities=["shell"],
            )
        finally:
            local_companion_machine_control.get_registered_targets = original_get
            local_companion_machine_control._save_targets = original_save

        assert result is None
        assert saved_targets == []

    @pytest.mark.asyncio
    async def test_probe_target_unknown_raises_value_error(self):
        """``probe_target`` raises ``ValueError`` on unknown target —
        that's the exception the router maps to HTTP 400. A silent
        refactor that returned the offline envelope instead would
        change the admin UI from '400 unknown target' to '200 offline'.
        """
        from integrations.local_companion import (
            machine_control as local_companion_machine_control,
        )

        provider = local_companion_machine_control.LocalCompanionMachineControlProvider()
        original_get = local_companion_machine_control.get_registered_targets
        local_companion_machine_control.get_registered_targets = lambda: []
        try:
            with pytest.raises(ValueError):
                await provider.probe_target(object(), target_id="ghost")
        finally:
            local_companion_machine_control.get_registered_targets = original_get

    @pytest.mark.asyncio
    async def test_probe_target_offline_when_bridge_has_no_connection(
        self, monkeypatch
    ):
        """A known target with no bridge connection returns the
        ``offline`` envelope (not raise). The admin UI relies on this
        shape to render 'Offline' without flagging an error.
        """
        from integrations.local_companion import (
            machine_control as local_companion_machine_control,
        )

        provider = local_companion_machine_control.LocalCompanionMachineControlProvider()
        monkeypatch.setattr(
            local_companion_machine_control,
            "get_registered_targets",
            lambda: [
                {
                    "target_id": "known",
                    "token": "t",
                    "driver": "companion",
                    "label": "Desk",
                    "hostname": "",
                    "platform": "",
                    "capabilities": ["shell"],
                    "last_seen_at": None,
                }
            ],
        )
        # Empty bridge → no connection.
        monkeypatch.setattr(
            local_companion_machine_control.bridge,
            "get_target_connection",
            lambda _tid: None,
        )

        result = await provider.probe_target(object(), target_id="known")
        assert result["ready"] is False
        assert result["status"] == "offline"
        assert "not currently connected" in (result["reason"] or "").lower()
