"""Integration tests for api_v1_admin/providers.py — 11 mutating routes.

Phase 3 of the Test Quality track. Real FastAPI + real SQLite DB + real router
+ real ORM; drivers (true externals — network to LLM providers) are stubbed
per skill rule E.1. `load_providers()` and `get_provider()` are patched because
they reach into the process-wide registry that other tests don't own.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.db.models import ProviderConfig, ProviderModel
from app.db.models import Bot as BotRow
from app.services.provider_drivers import ProviderCapabilities
from tests.factories import build_provider_config, build_provider_model
from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Driver stubs (true externals — E.1 permits mocking these)
# ---------------------------------------------------------------------------

def _make_driver_stub(
    *,
    capabilities: ProviderCapabilities | None = None,
    test_result: tuple[bool, str] = (True, "ok"),
    enriched_models: list[dict] | None = None,
    pull_chunks: list[dict] | None = None,
    model_info: dict | None = None,
    running_models: list[dict] | None = None,
):
    """Build a driver stub that the route can call in lieu of hitting a real LLM API."""
    driver = AsyncMock()
    driver.capabilities = lambda: capabilities or ProviderCapabilities()
    driver.test_connection = AsyncMock(return_value=test_result)
    driver.list_models_enriched = AsyncMock(return_value=enriched_models or [])
    driver.delete_model = AsyncMock(return_value=True)
    driver.get_model_info = AsyncMock(return_value=model_info or {})
    driver.get_running_models = AsyncMock(return_value=running_models or [])

    async def _pull_stream(_cfg, _name):
        for chunk in (pull_chunks or []):
            yield chunk

    driver.pull_model = _pull_stream
    return driver


# ---------------------------------------------------------------------------
# POST /providers — admin_create_provider
# ---------------------------------------------------------------------------

class TestCreateProvider:
    async def test_when_valid_payload_then_row_persisted_and_registry_reloaded(
        self, client, db_session,
    ):
        reload_mock = AsyncMock()
        payload = {
            "id": "openai-main",
            "provider_type": "openai",
            "display_name": "OpenAI Main",
            "api_key": "sk-test-secret-123",
            "base_url": "https://api.openai.com/v1",
        }

        with patch("app.services.providers.load_providers", reload_mock):
            resp = await client.post("/api/v1/admin/providers", json=payload, headers=AUTH_HEADERS)

        assert resp.status_code == 201
        row = await db_session.get(ProviderConfig, "openai-main")
        assert row is not None and row.display_name == "OpenAI Main"
        assert resp.json()["has_api_key"] is True
        reload_mock.assert_awaited_once()

    async def test_when_provider_type_invalid_then_422(self, client):
        payload = {"id": "bad-type", "provider_type": "not-a-real-type", "display_name": "x"}

        resp = await client.post("/api/v1/admin/providers", json=payload, headers=AUTH_HEADERS)

        assert resp.status_code == 422
        assert "Invalid provider_type" in resp.json()["detail"]

    async def test_when_id_already_exists_then_409(self, client, db_session):
        existing = build_provider_config(id="dup-id", display_name="Existing")
        db_session.add(existing)
        await db_session.commit()

        resp = await client.post(
            "/api/v1/admin/providers",
            json={"id": "dup-id", "provider_type": "openai", "display_name": "Duplicate"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    async def test_when_id_blank_then_422(self, client):
        resp = await client.post(
            "/api/v1/admin/providers",
            json={"id": "   ", "provider_type": "openai", "display_name": "Blank ID"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 422

    async def test_when_litellm_with_mgmt_key_then_config_has_encrypted_entry(
        self, client, db_session,
    ):
        payload = {
            "id": "litellm-proxy",
            "provider_type": "litellm",
            "display_name": "LiteLLM Proxy",
            "management_key": "mgmt-secret-xyz",
        }

        with patch("app.services.providers.load_providers", AsyncMock()):
            resp = await client.post("/api/v1/admin/providers", json=payload, headers=AUTH_HEADERS)

        assert resp.status_code == 201
        row = await db_session.get(ProviderConfig, "litellm-proxy")
        assert "management_key" in (row.config or {})
        assert resp.json()["config"].get("management_key") is None  # redacted in response

    async def test_when_non_litellm_mgmt_key_passed_then_ignored(
        self, client, db_session,
    ):
        payload = {
            "id": "openai-ignored-mgmt",
            "provider_type": "openai",
            "display_name": "OpenAI",
            "management_key": "should-not-land",
        }

        with patch("app.services.providers.load_providers", AsyncMock()):
            resp = await client.post("/api/v1/admin/providers", json=payload, headers=AUTH_HEADERS)

        assert resp.status_code == 201
        row = await db_session.get(ProviderConfig, "openai-ignored-mgmt")
        assert "management_key" not in (row.config or {})


# ---------------------------------------------------------------------------
# PUT /providers/{id} — admin_update_provider
# ---------------------------------------------------------------------------

class TestUpdateProvider:
    async def test_when_display_name_and_base_url_updated_then_row_refreshed(
        self, client, db_session,
    ):
        prov = build_provider_config(id="edit-me", display_name="Old Name")
        db_session.add(prov)
        await db_session.commit()

        with patch("app.services.providers.load_providers", AsyncMock()):
            resp = await client.put(
                "/api/v1/admin/providers/edit-me",
                json={"display_name": "New Name", "base_url": "https://new.example/v1"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        await db_session.refresh(prov)
        assert (prov.display_name, prov.base_url) == ("New Name", "https://new.example/v1")

    async def test_when_api_key_empty_string_then_cleared(self, client, db_session):
        prov = build_provider_config(id="clear-key", api_key="enc:existing")
        db_session.add(prov)
        await db_session.commit()

        with patch("app.services.providers.load_providers", AsyncMock()):
            resp = await client.put(
                "/api/v1/admin/providers/clear-key",
                json={"api_key": ""},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        await db_session.refresh(prov)
        assert prov.api_key is None

    async def test_when_billing_switched_to_usage_then_plan_fields_cleared(
        self, client, db_session,
    ):
        prov = build_provider_config(
            id="plan-to-usage",
            billing_type="plan",
            plan_cost=20.0,
            plan_period="month",
        )
        db_session.add(prov)
        await db_session.commit()

        with patch("app.services.providers.load_providers", AsyncMock()):
            resp = await client.put(
                "/api/v1/admin/providers/plan-to-usage",
                json={"billing_type": "usage"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        await db_session.refresh(prov)
        assert (prov.billing_type, prov.plan_cost, prov.plan_period) == ("usage", None, None)

    async def test_when_clear_tpm_limit_true_then_field_nulled(self, client, db_session):
        prov = build_provider_config(id="clear-tpm", tpm_limit=10000)
        db_session.add(prov)
        await db_session.commit()

        with patch("app.services.providers.load_providers", AsyncMock()):
            resp = await client.put(
                "/api/v1/admin/providers/clear-tpm",
                json={"clear_tpm_limit": True},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        await db_session.refresh(prov)
        assert prov.tpm_limit is None

    async def test_when_management_key_empty_then_removed_from_config(
        self, client, db_session,
    ):
        prov = build_provider_config(
            id="litellm-edit",
            provider_type="litellm",
            config={"management_key": "enc:existing", "other_key": "preserved"},
        )
        db_session.add(prov)
        await db_session.commit()

        with patch("app.services.providers.load_providers", AsyncMock()):
            resp = await client.put(
                "/api/v1/admin/providers/litellm-edit",
                json={"management_key": ""},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        await db_session.refresh(prov)
        assert "management_key" not in (prov.config or {})
        assert (prov.config or {}).get("other_key") == "preserved"

    async def test_when_provider_type_invalid_then_422(self, client, db_session):
        prov = build_provider_config(id="bad-type-edit")
        db_session.add(prov)
        await db_session.commit()

        resp = await client.put(
            "/api/v1/admin/providers/bad-type-edit",
            json={"provider_type": "mystery"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 422

    async def test_when_provider_missing_then_404(self, client):
        resp = await client.put(
            "/api/v1/admin/providers/ghost",
            json={"display_name": "Ghost"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /providers/{id} — admin_delete_provider
# ---------------------------------------------------------------------------

class TestDeleteProvider:
    async def test_when_unused_then_deleted(self, client, db_session):
        prov = build_provider_config(id="delete-me")
        sibling = build_provider_config(id="survivor")
        db_session.add_all([prov, sibling])
        await db_session.commit()

        with patch("app.services.providers.load_providers", AsyncMock()):
            resp = await client.delete("/api/v1/admin/providers/delete-me", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        gone = await db_session.execute(
            select(ProviderConfig.id).where(ProviderConfig.id == "delete-me")
        )
        survivor = await db_session.get(ProviderConfig, "survivor")
        assert gone.scalar_one_or_none() is None and survivor is not None

    async def test_when_provider_in_use_by_bot_then_400_with_bot_id(
        self, client, db_session,
    ):
        prov = build_provider_config(id="used-prov")
        bot = BotRow(
            id="consumer-bot",
            name="Consumer",
            model="test/m",
            system_prompt="x",
            model_provider_id="used-prov",
        )
        db_session.add_all([prov, bot])
        await db_session.commit()

        resp = await client.delete("/api/v1/admin/providers/used-prov", headers=AUTH_HEADERS)

        assert resp.status_code == 400
        assert "consumer-bot" in resp.json()["detail"]

    async def test_when_missing_then_404(self, client):
        resp = await client.delete("/api/v1/admin/providers/nope", headers=AUTH_HEADERS)

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /providers/{id}/test — admin_test_provider
# ---------------------------------------------------------------------------

class TestTestProvider:
    async def test_when_registry_hit_then_driver_response_returned(self, client):
        driver = _make_driver_stub(test_result=(True, "Connection OK"))
        prov = build_provider_config(id="reg-hit", provider_type="openai", api_key="key", base_url="url")

        with patch("app.services.providers.get_provider", return_value=prov), \
             patch("app.routers.api_v1_admin.providers.get_driver", return_value=driver):
            resp = await client.post("/api/v1/admin/providers/reg-hit/test", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "message": "Connection OK"}
        driver.test_connection.assert_awaited_once_with("key", "url")

    async def test_when_provider_not_in_registry_even_after_reload_then_ok_false(
        self, client,
    ):
        with patch("app.services.providers.get_provider", return_value=None), \
             patch("app.services.providers.load_providers", AsyncMock()):
            resp = await client.post("/api/v1/admin/providers/nowhere/test", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        assert resp.json() == {"ok": False, "message": "Provider not found in registry"}


# ---------------------------------------------------------------------------
# POST /providers/test-inline — admin_test_provider_inline
# ---------------------------------------------------------------------------

class TestTestProviderInline:
    async def test_when_valid_provider_type_then_driver_invoked(self, client):
        driver = _make_driver_stub(test_result=(True, "pong"))

        with patch("app.routers.api_v1_admin.providers.get_driver", return_value=driver):
            resp = await client.post(
                "/api/v1/admin/providers/test-inline",
                json={"provider_type": "openai", "api_key": "sk-inline", "base_url": "https://x"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "message": "pong"}
        driver.test_connection.assert_awaited_once_with("sk-inline", "https://x")

    async def test_when_driver_raises_valueerror_then_ok_false(self, client):
        def _raise(_):
            raise ValueError("unknown")

        with patch("app.routers.api_v1_admin.providers.get_driver", side_effect=_raise):
            resp = await client.post(
                "/api/v1/admin/providers/test-inline",
                json={"provider_type": "unknown-type"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False and "unknown-type" in body["message"]


# ---------------------------------------------------------------------------
# POST /providers/{id}/models — admin_add_provider_model
# ---------------------------------------------------------------------------

class TestAddProviderModel:
    async def test_when_valid_model_then_persisted(self, client, db_session):
        prov = build_provider_config(id="has-models")
        db_session.add(prov)
        await db_session.commit()

        resp = await client.post(
            "/api/v1/admin/providers/has-models/models",
            json={"model_id": "gpt-5", "display_name": "GPT-5", "max_tokens": 128000},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 201
        rows = (await db_session.execute(
            select(ProviderModel).where(ProviderModel.provider_id == "has-models")
        )).scalars().all()
        assert [r.model_id for r in rows] == ["gpt-5"]

    async def test_when_provider_missing_then_404(self, client):
        resp = await client.post(
            "/api/v1/admin/providers/ghost/models",
            json={"model_id": "m"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 404

    async def test_when_model_id_blank_then_422(self, client, db_session):
        prov = build_provider_config(id="blank-model")
        db_session.add(prov)
        await db_session.commit()

        resp = await client.post(
            "/api/v1/admin/providers/blank-model/models",
            json={"model_id": "   "},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 422

    async def test_when_flag_set_then_registry_reloaded(self, client, db_session):
        prov = build_provider_config(id="flag-prov")
        db_session.add(prov)
        await db_session.commit()
        reload_mock = AsyncMock()

        with patch("app.services.providers.load_providers", reload_mock):
            resp = await client.post(
                "/api/v1/admin/providers/flag-prov/models",
                json={"model_id": "tool-less", "supports_tools": False},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 201
        reload_mock.assert_awaited_once()


# ---------------------------------------------------------------------------
# DELETE /providers/{id}/models/{pk} — admin_delete_provider_model
# ---------------------------------------------------------------------------

class TestDeleteProviderModel:
    async def test_when_model_exists_then_deleted_and_sibling_preserved(
        self, client, db_session,
    ):
        prov = build_provider_config(id="del-models")
        target = build_provider_model("del-models", model_id="doomed")
        sibling = build_provider_model("del-models", model_id="survivor")
        db_session.add_all([prov, target, sibling])
        await db_session.commit()

        resp = await client.delete(
            f"/api/v1/admin/providers/del-models/models/{target.id}",
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        remaining = (await db_session.execute(
            select(ProviderModel.model_id).where(ProviderModel.provider_id == "del-models")
        )).scalars().all()
        assert remaining == ["survivor"]

    async def test_when_model_belongs_to_different_provider_then_404(
        self, client, db_session,
    ):
        prov_a = build_provider_config(id="prov-a")
        prov_b = build_provider_config(id="prov-b")
        model = build_provider_model("prov-a")
        db_session.add_all([prov_a, prov_b, model])
        await db_session.commit()

        resp = await client.delete(
            f"/api/v1/admin/providers/prov-b/models/{model.id}",
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /providers/{id}/sync-models — admin_sync_provider_models
# ---------------------------------------------------------------------------

class TestSyncProviderModels:
    async def test_when_enriched_has_new_and_existing_then_both_counted(
        self, client, db_session,
    ):
        prov = build_provider_config(id="sync-prov")
        existing = build_provider_model(
            "sync-prov", model_id="old-model", display_name="Old", max_tokens=4096,
        )
        db_session.add_all([prov, existing])
        await db_session.commit()
        driver = _make_driver_stub(
            capabilities=ProviderCapabilities(list_models=True),
            enriched_models=[
                {"id": "new-model", "display": "New Model", "max_tokens": 8192,
                 "input_cost_per_1m": "0.1", "output_cost_per_1m": "0.2"},
                {"id": "old-model", "display": "Old", "max_tokens": 16384,
                 "input_cost_per_1m": "0.5", "output_cost_per_1m": "1.0"},
            ],
        )

        with patch("app.services.providers.get_provider", return_value=prov), \
             patch("app.services.providers.load_providers", AsyncMock()), \
             patch("app.routers.api_v1_admin.providers.get_driver", return_value=driver):
            resp = await client.post(
                "/api/v1/admin/providers/sync-prov/sync-models", headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json() == {"created": 1, "updated": 1, "total": 2}

    async def test_when_driver_lacks_list_models_capability_then_400(
        self, client,
    ):
        prov = build_provider_config(id="no-list-caps")
        driver = _make_driver_stub(capabilities=ProviderCapabilities(list_models=False))

        with patch("app.services.providers.get_provider", return_value=prov), \
             patch("app.routers.api_v1_admin.providers.get_driver", return_value=driver):
            resp = await client.post(
                "/api/v1/admin/providers/no-list-caps/sync-models", headers=AUTH_HEADERS,
            )

        assert resp.status_code == 400

    async def test_when_enriched_empty_then_zero_totals(self, client):
        prov = build_provider_config(id="empty-sync")
        driver = _make_driver_stub(
            capabilities=ProviderCapabilities(list_models=True),
            enriched_models=[],
        )

        with patch("app.services.providers.get_provider", return_value=prov), \
             patch("app.services.providers.load_providers", AsyncMock()), \
             patch("app.routers.api_v1_admin.providers.get_driver", return_value=driver):
            resp = await client.post(
                "/api/v1/admin/providers/empty-sync/sync-models", headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json() == {"created": 0, "updated": 0, "total": 0}

    async def test_when_provider_unknown_then_404(self, client):
        with patch("app.services.providers.get_provider", return_value=None), \
             patch("app.services.providers.load_providers", AsyncMock()):
            resp = await client.post(
                "/api/v1/admin/providers/ghost/sync-models", headers=AUTH_HEADERS,
            )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /providers/{id}/pull-model — admin_pull_model (SSE)
# ---------------------------------------------------------------------------

class TestPullModel:
    async def test_when_capable_then_sse_stream_with_success_terminator(
        self, client,
    ):
        prov = build_provider_config(id="pullable", provider_type="ollama")
        driver = _make_driver_stub(
            capabilities=ProviderCapabilities(pull_model=True),
            pull_chunks=[{"status": "downloading", "completed": 50}],
        )

        with patch("app.services.providers.get_provider", return_value=prov), \
             patch("app.routers.api_v1_admin.providers.get_driver", return_value=driver):
            resp = await client.post(
                "/api/v1/admin/providers/pullable/pull-model",
                json={"model_name": "llama3:8b"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.text
        assert '"status": "downloading"' in body and '"status": "success"' in body

    async def test_when_driver_does_not_support_pull_then_400(self, client):
        prov = build_provider_config(id="no-pull")
        driver = _make_driver_stub(capabilities=ProviderCapabilities(pull_model=False))

        with patch("app.services.providers.get_provider", return_value=prov), \
             patch("app.routers.api_v1_admin.providers.get_driver", return_value=driver):
            resp = await client.post(
                "/api/v1/admin/providers/no-pull/pull-model",
                json={"model_name": "x"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 400

    async def test_when_driver_raises_then_error_event_emitted(self, client):
        prov = build_provider_config(id="boom", provider_type="ollama")

        async def _boom(_cfg, _name):
            raise RuntimeError("disk full")
            yield  # pragma: no cover — makes this an async generator

        driver = AsyncMock()
        driver.capabilities = lambda: ProviderCapabilities(pull_model=True)
        driver.pull_model = _boom

        with patch("app.services.providers.get_provider", return_value=prov), \
             patch("app.routers.api_v1_admin.providers.get_driver", return_value=driver):
            resp = await client.post(
                "/api/v1/admin/providers/boom/pull-model",
                json={"model_name": "llama3"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        assert '"status": "error"' in resp.text and "disk full" in resp.text


# ---------------------------------------------------------------------------
# DELETE /providers/{id}/remote-models/{name:path} — admin_delete_remote_model
# ---------------------------------------------------------------------------

class TestDeleteRemoteModel:
    async def test_when_capable_then_driver_called_and_ok_returned(self, client):
        prov = build_provider_config(id="ollama-del", provider_type="ollama")
        driver = _make_driver_stub(capabilities=ProviderCapabilities(delete_model=True))

        with patch("app.services.providers.get_provider", return_value=prov), \
             patch("app.routers.api_v1_admin.providers.get_driver", return_value=driver):
            resp = await client.delete(
                "/api/v1/admin/providers/ollama-del/remote-models/llama3:8b",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        driver.delete_model.assert_awaited_once_with(prov, "llama3:8b")

    async def test_when_driver_raises_then_502(self, client):
        prov = build_provider_config(id="ollama-fail", provider_type="ollama")
        driver = _make_driver_stub(capabilities=ProviderCapabilities(delete_model=True))
        driver.delete_model.side_effect = RuntimeError("boom")

        with patch("app.services.providers.get_provider", return_value=prov), \
             patch("app.routers.api_v1_admin.providers.get_driver", return_value=driver):
            resp = await client.delete(
                "/api/v1/admin/providers/ollama-fail/remote-models/model-x",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 502
        assert "boom" in resp.json()["detail"]

    async def test_when_not_capable_then_400(self, client):
        prov = build_provider_config(id="no-del")
        driver = _make_driver_stub(capabilities=ProviderCapabilities(delete_model=False))

        with patch("app.services.providers.get_provider", return_value=prov), \
             patch("app.routers.api_v1_admin.providers.get_driver", return_value=driver):
            resp = await client.delete(
                "/api/v1/admin/providers/no-del/remote-models/x",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /providers/{id}/remote-models/{name:path}/info — admin_remote_model_info
# ---------------------------------------------------------------------------

class TestRemoteModelInfo:
    async def test_when_capable_then_driver_payload_returned(self, client):
        prov = build_provider_config(id="info-prov", provider_type="ollama")
        driver = _make_driver_stub(
            capabilities=ProviderCapabilities(model_info=True),
            model_info={"parameters": "8B", "quant": "Q4_0"},
        )

        with patch("app.services.providers.get_provider", return_value=prov), \
             patch("app.routers.api_v1_admin.providers.get_driver", return_value=driver):
            resp = await client.get(
                "/api/v1/admin/providers/info-prov/remote-models/llama3:8b/info",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json() == {"parameters": "8B", "quant": "Q4_0"}

    async def test_when_not_capable_then_400(self, client):
        prov = build_provider_config(id="info-unsupp")
        driver = _make_driver_stub(capabilities=ProviderCapabilities(model_info=False))

        with patch("app.services.providers.get_provider", return_value=prov), \
             patch("app.routers.api_v1_admin.providers.get_driver", return_value=driver):
            resp = await client.get(
                "/api/v1/admin/providers/info-unsupp/remote-models/x/info",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /providers/{id}/running-models — admin_running_models
# ---------------------------------------------------------------------------

class TestRunningModels:
    async def test_when_capable_then_driver_list_returned(self, client):
        prov = build_provider_config(id="running-prov", provider_type="ollama")
        driver = _make_driver_stub(
            capabilities=ProviderCapabilities(running_models=True),
            running_models=[{"name": "llama3:8b", "size_vram": 5_000_000_000}],
        )

        with patch("app.services.providers.get_provider", return_value=prov), \
             patch("app.routers.api_v1_admin.providers.get_driver", return_value=driver):
            resp = await client.get(
                "/api/v1/admin/providers/running-prov/running-models",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json() == [{"name": "llama3:8b", "size_vram": 5_000_000_000}]

    async def test_when_driver_raises_then_502(self, client):
        prov = build_provider_config(id="running-fail")
        driver = _make_driver_stub(capabilities=ProviderCapabilities(running_models=True))
        driver.get_running_models.side_effect = RuntimeError("conn refused")

        with patch("app.services.providers.get_provider", return_value=prov), \
             patch("app.routers.api_v1_admin.providers.get_driver", return_value=driver):
            resp = await client.get(
                "/api/v1/admin/providers/running-fail/running-models",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 502
        assert "conn refused" in resp.json()["detail"]
