"""Phase Q-MACH — admin /machines router drift seams.

Companion to ``test_machine_control_drift.py`` (Phase O, service layer) and
``test_machine_target_sessions.py`` (happy-path grant). This file drift-pins
the router-level contract in ``app/routers/api_v1_admin/machines.py``:

  QM.1  Exception-to-HTTP mapping — ``KeyError`` → 404, ``ValueError`` →
        400, ``RuntimeError`` → 409 on enroll/probe/delete. The three
        endpoints share this shape; a silent swap to a different
        exception type would bypass the intended status code.
  QM.2  ``delete_machine_target`` returning False → 404 (not silent 200).
  QM.3  Scope gate — GET ``/machines`` requires ``integrations:read``;
        write routes require ``integrations:write``. A read-only scope
        MUST NOT reach the write endpoints.
  QM.4  No-body POST /enroll is accepted (both ``body`` and ``body.label``
        / ``body.config`` default cleanly). Drift here would surface as a
        422 from Pydantic.
  QM.5  ``label`` and ``config`` in the enroll body flow through to
        ``enroll_machine_target`` verbatim; URL path ``provider_id`` wins
        over any body-level field.
  QM.6  DELETE on unknown provider returns 404 (provider lookup
        ``KeyError`` bubbles up via the shared mapping).
  QM.7  Probe against a disconnected target returns the provider's
        failure envelope, not a 5xx — disconnected is a valid response
        shape, not an error.
  QM.8  ``server_base_url`` passed to ``enroll_machine_target`` is the
        request's ``base_url`` (string-coerced). Drift here would break
        the ``curl`` launch command the UI relies on.

Seams deliberately NOT covered: concurrent-enroll race (that's a service-
layer concern pinned in Phase O when it lands), full DB wiring (this file
monkeypatches the service layer), the WS handshake (see
``test_local_companion_ws_drift.py``).
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import ApiKeyAuth, get_db, verify_auth_or_user
from app.routers.api_v1_admin import machines as machines_router_module


# ---------------------------------------------------------------------------
# Fixtures — minimal app, stubbed service layer, scope-parameterised auth.
# ---------------------------------------------------------------------------


class _FakeAuth:
    """Small stand-in for ``ApiKeyAuth`` that lets tests drive the scope set."""

    def __init__(self, *, scopes: list[str]):
        self.scopes = list(scopes)


def _build_app(*, scopes: list[str]) -> FastAPI:
    app = FastAPI()
    app.include_router(machines_router_module.router, prefix="/admin")

    auth = ApiKeyAuth(
        key_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
        scopes=list(scopes),
        name="test",
    )

    async def _override_get_db():
        yield object()

    async def _override_auth_or_user():
        return auth

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[verify_auth_or_user] = _override_auth_or_user
    return app


def _client(*, scopes: list[str]) -> TestClient:
    return TestClient(_build_app(scopes=scopes))


class _Calls:
    """Container tests use to assert what the router forwarded to services."""

    def __init__(self) -> None:
        self.enroll: list[dict[str, Any]] = []
        self.probe: list[dict[str, Any]] = []
        self.delete: list[dict[str, Any]] = []
        self.providers: list[None] = []


@pytest.fixture
def calls(monkeypatch):
    record = _Calls()

    async def _fake_enroll(db, *, provider_id, server_base_url, label=None, config=None):
        record.enroll.append(
            {
                "provider_id": provider_id,
                "server_base_url": server_base_url,
                "label": label,
                "config": config,
            }
        )
        return {"provider_id": provider_id, "ok": True}

    async def _fake_probe(db, *, provider_id, target_id):
        record.probe.append({"provider_id": provider_id, "target_id": target_id})
        return {"provider_id": provider_id, "target_id": target_id, "ready": False}

    async def _fake_delete(db, *, provider_id, target_id):
        record.delete.append({"provider_id": provider_id, "target_id": target_id})
        return True

    def _fake_providers_status():
        record.providers.append(None)
        return [{"provider_id": "local_companion", "targets": []}]

    monkeypatch.setattr(machines_router_module, "enroll_machine_target", _fake_enroll)
    monkeypatch.setattr(machines_router_module, "probe_machine_target", _fake_probe)
    monkeypatch.setattr(machines_router_module, "delete_machine_target", _fake_delete)
    monkeypatch.setattr(
        machines_router_module, "build_providers_status", _fake_providers_status
    )
    return record


# ---------------------------------------------------------------------------
# QM.1 — Exception-to-HTTP mapping (three endpoints, three exception types)
# ---------------------------------------------------------------------------


class TestExceptionToHttpMapping:
    def test_enroll_keyerror_is_404(self, monkeypatch):
        async def _raise(db, **_kwargs):
            raise KeyError("unknown provider 'nope'")

        monkeypatch.setattr(machines_router_module, "enroll_machine_target", _raise)
        resp = _client(scopes=["integrations:write"]).post(
            "/admin/machines/providers/nope/enroll", json={}
        )
        assert resp.status_code == 404
        assert "nope" in resp.json()["detail"]

    def test_enroll_valueerror_is_400(self, monkeypatch):
        async def _raise(db, **_kwargs):
            raise ValueError("provider does not support enrollment")

        monkeypatch.setattr(machines_router_module, "enroll_machine_target", _raise)
        resp = _client(scopes=["integrations:write"]).post(
            "/admin/machines/providers/readonly/enroll", json={}
        )
        assert resp.status_code == 400
        assert "does not support" in resp.json()["detail"]

    def test_enroll_runtimeerror_is_409(self, monkeypatch):
        async def _raise(db, **_kwargs):
            raise RuntimeError("already enrolled")

        monkeypatch.setattr(machines_router_module, "enroll_machine_target", _raise)
        resp = _client(scopes=["integrations:write"]).post(
            "/admin/machines/providers/local_companion/enroll", json={}
        )
        assert resp.status_code == 409
        assert "already" in resp.json()["detail"]

    def test_probe_keyerror_is_404(self, monkeypatch):
        async def _raise(db, **_kwargs):
            raise KeyError("unknown provider 'missing'")

        monkeypatch.setattr(machines_router_module, "probe_machine_target", _raise)
        resp = _client(scopes=["integrations:write"]).post(
            "/admin/machines/providers/missing/targets/t1/probe"
        )
        assert resp.status_code == 404

    def test_probe_valueerror_is_400(self, monkeypatch):
        async def _raise(db, **_kwargs):
            raise ValueError("Unknown machine target.")

        monkeypatch.setattr(machines_router_module, "probe_machine_target", _raise)
        resp = _client(scopes=["integrations:write"]).post(
            "/admin/machines/providers/local_companion/targets/ghost/probe"
        )
        assert resp.status_code == 400

    def test_delete_keyerror_is_404(self, monkeypatch):
        async def _raise(db, **_kwargs):
            raise KeyError("unknown provider")

        monkeypatch.setattr(machines_router_module, "delete_machine_target", _raise)
        resp = _client(scopes=["integrations:write"]).delete(
            "/admin/machines/providers/nope/targets/t1"
        )
        assert resp.status_code == 404

    def test_delete_valueerror_is_400(self, monkeypatch):
        async def _raise(db, **_kwargs):
            raise ValueError("provider does not support target removal")

        monkeypatch.setattr(machines_router_module, "delete_machine_target", _raise)
        resp = _client(scopes=["integrations:write"]).delete(
            "/admin/machines/providers/ro/targets/t1"
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# QM.2 — Delete of unknown target returns 404 (not silent 200)
# ---------------------------------------------------------------------------


class TestDeleteNotFound:
    def test_delete_nonexistent_target_returns_404(self, monkeypatch):
        """Service layer returns ``False`` when the (provider, target) pair
        has no row to delete. The router MUST convert that to 404 so callers
        don't mistake the no-op for a successful removal.
        """

        async def _fake_delete(db, **_kwargs):
            return False

        monkeypatch.setattr(machines_router_module, "delete_machine_target", _fake_delete)
        resp = _client(scopes=["integrations:write"]).delete(
            "/admin/machines/providers/local_companion/targets/ghost"
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_delete_success_returns_ok_envelope(self, calls):
        resp = _client(scopes=["integrations:write"]).delete(
            "/admin/machines/providers/local_companion/targets/t1"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "status": "ok",
            "provider_id": "local_companion",
            "target_id": "t1",
        }
        assert calls.delete == [{"provider_id": "local_companion", "target_id": "t1"}]


# ---------------------------------------------------------------------------
# QM.3 — Scope gate (read vs write)
# ---------------------------------------------------------------------------


class TestScopeGate:
    def test_read_scope_can_list_providers(self, calls):
        resp = _client(scopes=["integrations:read"]).get("/admin/machines")
        assert resp.status_code == 200
        assert len(calls.providers) == 1

    def test_read_only_scope_cannot_enroll(self, calls):
        resp = _client(scopes=["integrations:read"]).post(
            "/admin/machines/providers/local_companion/enroll", json={}
        )
        assert resp.status_code == 403
        assert calls.enroll == []

    def test_read_only_scope_cannot_probe(self, calls):
        resp = _client(scopes=["integrations:read"]).post(
            "/admin/machines/providers/local_companion/targets/t1/probe"
        )
        assert resp.status_code == 403
        assert calls.probe == []

    def test_read_only_scope_cannot_delete(self, calls):
        resp = _client(scopes=["integrations:read"]).delete(
            "/admin/machines/providers/local_companion/targets/t1"
        )
        assert resp.status_code == 403
        assert calls.delete == []

    def test_no_scopes_rejects_list(self, calls):
        """Empty-scope keys must not read the provider list either."""
        resp = _client(scopes=[]).get("/admin/machines")
        assert resp.status_code == 403

    def test_admin_scope_covers_write(self, calls):
        """A key with the umbrella ``admin`` scope is the canonical bypass
        and should still reach write endpoints — regression check against
        any tightening that accidentally stops recognising it.
        """
        resp = _client(scopes=["admin"]).post(
            "/admin/machines/providers/local_companion/enroll", json={}
        )
        assert resp.status_code == 200
        assert len(calls.enroll) == 1


# ---------------------------------------------------------------------------
# QM.4 — No-body POST /enroll is accepted
# ---------------------------------------------------------------------------


class TestEnrollBodyOptional:
    def test_post_enroll_without_body_succeeds(self, calls):
        resp = _client(scopes=["integrations:write"]).post(
            "/admin/machines/providers/local_companion/enroll"
        )
        assert resp.status_code == 200
        assert calls.enroll == [
            {
                "provider_id": "local_companion",
                "server_base_url": calls.enroll[0]["server_base_url"],
                "label": None,
                "config": None,
            }
        ]

    def test_post_enroll_with_null_body_fields_succeeds(self, calls):
        resp = _client(scopes=["integrations:write"]).post(
            "/admin/machines/providers/local_companion/enroll",
            json={"label": None, "config": None},
        )
        assert resp.status_code == 200
        assert calls.enroll[0]["label"] is None
        assert calls.enroll[0]["config"] is None

    def test_post_enroll_with_unknown_body_field_is_tolerated(self, calls):
        """Extra fields in the request body should not 422 — Pydantic's
        default ``extra = 'ignore'`` is the forward-compat contract."""
        resp = _client(scopes=["integrations:write"]).post(
            "/admin/machines/providers/local_companion/enroll",
            json={"label": "x", "future_field": True},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# QM.5 — Body passthrough + URL path wins over body
# ---------------------------------------------------------------------------


class TestEnrollBodyPassthrough:
    def test_label_and_config_forwarded_verbatim(self, calls):
        resp = _client(scopes=["integrations:write"]).post(
            "/admin/machines/providers/local_companion/enroll",
            json={"label": "Desk", "config": {"nested": {"room": "office"}}},
        )
        assert resp.status_code == 200
        entry = calls.enroll[0]
        assert entry["label"] == "Desk"
        assert entry["config"] == {"nested": {"room": "office"}}

    def test_url_path_provider_id_always_wins(self, calls):
        """The URL path ``provider_id`` is the authoritative source. Even
        if a future client smuggles a ``provider_id`` into the body, the
        router must not let it override the path parameter.
        """
        resp = _client(scopes=["integrations:write"]).post(
            "/admin/machines/providers/local_companion/enroll",
            json={"label": "Desk", "provider_id": "rogue"},
        )
        assert resp.status_code == 200
        assert calls.enroll[0]["provider_id"] == "local_companion"


# ---------------------------------------------------------------------------
# QM.7 — Probe of disconnected target returns the provider envelope (200)
# ---------------------------------------------------------------------------


class TestProbeDisconnectedShape:
    def test_probe_disconnected_target_returns_200_envelope(self, calls):
        """A disconnected target is a valid status, not an error. The
        service layer returns a normal envelope and the router must pass
        it through with 200 so the admin UI can render ``status: offline``.
        """
        resp = _client(scopes=["integrations:write"]).post(
            "/admin/machines/providers/local_companion/targets/t1/probe"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["provider_id"] == "local_companion"
        assert body["target_id"] == "t1"
        assert body["ready"] is False
        assert calls.probe == [
            {"provider_id": "local_companion", "target_id": "t1"}
        ]


# ---------------------------------------------------------------------------
# QM.8 — server_base_url passes through from the request
# ---------------------------------------------------------------------------


class TestServerBaseUrlPassthrough:
    def test_enroll_forwards_request_base_url(self, calls):
        """``enroll_machine_target`` must receive the HTTP request's
        base_url as a string; the launch command the UI builds depends
        on that exact host+scheme.
        """
        resp = _client(scopes=["integrations:write"]).post(
            "/admin/machines/providers/local_companion/enroll",
            json={"label": "Desk"},
        )
        assert resp.status_code == 200
        sent = calls.enroll[0]["server_base_url"]
        assert isinstance(sent, str)
        # FastAPI TestClient's ``base_url`` is http://testserver/ by default.
        assert sent.startswith("http://testserver")
