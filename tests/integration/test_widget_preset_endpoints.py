from __future__ import annotations

import pytest

AUTH_HEADERS = {"Authorization": "Bearer test-key"}


@pytest.mark.asyncio
async def test_binding_options_accepts_body_source_id_with_dots(client, monkeypatch):
    async def _list_binding_options(*, preset_id, source_id, source_bot_id, source_channel_id):
        assert preset_id == "homeassistant-entity-chip"
        assert source_id == "homeassistant.entities"
        assert source_bot_id == "bot-123"
        assert source_channel_id is None
        return [{"value": "light.office", "label": "Office Light"}]

    monkeypatch.setattr(
        "app.services.widget_presets.list_binding_options",
        _list_binding_options,
    )

    resp = await client.post(
        "/api/v1/widgets/presets/homeassistant-entity-chip/binding-options",
        json={
            "source_id": "homeassistant.entities",
            "source_bot_id": "bot-123",
        },
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "options": [{"value": "light.office", "label": "Office Light"}],
    }


@pytest.mark.asyncio
async def test_presets_list_can_inline_binding_options(client, monkeypatch):
    async def _resolve_preset_binding_options(preset, *, source_bot_id, source_channel_id):
        if preset["id"] == "homeassistant-entity-chip":
            assert source_bot_id == "bot-123"
            assert source_channel_id is None
            return (
                {"homeassistant.entities": [{"value": "light.office", "label": "Office Light"}]},
                {},
            )
        return ({}, {})

    monkeypatch.setattr(
        "app.services.widget_presets.resolve_preset_binding_options",
        _resolve_preset_binding_options,
    )

    resp = await client.get(
        "/api/v1/widgets/presets",
        params={
            "include_binding_options": "true",
            "source_bot_id": "bot-123",
        },
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    presets = resp.json()["presets"]
    entity_chip = next(p for p in presets if p["id"] == "homeassistant-entity-chip")
    assert entity_chip["resolved_binding_options"] == {
        "homeassistant.entities": [{"value": "light.office", "label": "Office Light"}],
    }
    assert entity_chip["binding_source_errors"] == {}


@pytest.mark.asyncio
async def test_binding_options_accepts_query_source_id_with_dots(client, monkeypatch):
    async def _list_binding_options(*, preset_id, source_id, source_bot_id, source_channel_id):
        assert preset_id == "homeassistant-entity-chip"
        assert source_id == "homeassistant.entities"
        assert source_bot_id == "bot-123"
        assert source_channel_id is None
        return [{"value": "light.office", "label": "Office Light"}]

    monkeypatch.setattr(
        "app.services.widget_presets.list_binding_options",
        _list_binding_options,
    )

    resp = await client.get(
        "/api/v1/widgets/presets/homeassistant-entity-chip/binding-options",
        params={
            "source_id": "homeassistant.entities",
            "source_bot_id": "bot-123",
        },
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "options": [{"value": "light.office", "label": "Office Light"}],
    }
