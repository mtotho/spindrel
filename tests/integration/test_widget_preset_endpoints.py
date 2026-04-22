from __future__ import annotations

import uuid

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


@pytest.mark.asyncio
async def test_preset_pin_creates_dashboard_pin(client, db_session, monkeypatch):
    from app.db.models import Bot, Channel
    from app.services.widget_preview import PreviewEnvelope, PreviewOut

    bot = Bot(
        id="bot-123",
        name="rolland",
        display_name="Rolland",
        model="gpt-5.4",
        system_prompt="",
    )
    channel_id = uuid.uuid4()
    channel = Channel(id=channel_id, name="quality-assurance", bot_id=bot.id)
    db_session.add(bot)
    db_session.add(channel)
    await db_session.commit()

    async def _preview_widget_preset(_db, *, preset_id, config, source_bot_id, source_channel_id):
        assert preset_id == "homeassistant-entity-chip"
        assert config == {"entity_id": "light.kitchen_ceiling_lights"}
        assert source_bot_id == "bot-123"
        assert source_channel_id == str(channel_id)
        return (
            PreviewOut(
                ok=True,
                envelope=PreviewEnvelope(
                    content_type="application/vnd.spindrel.components+json",
                    body="{\"v\":1,\"components\":[{\"type\":\"status\",\"text\":\"Kitchen Ceiling Lights\"}]}",
                    display="inline",
                    display_label="light.kitchen_ceiling_lights",
                    source_bot_id="bot-123",
                    source_channel_id=str(channel_id),
                ),
            ),
            {"entity_id": "light.kitchen_ceiling_lights", "preset_variant": "entity_chip"},
            {"entity_id": "light.kitchen_ceiling_lights"},
        )

    monkeypatch.setattr(
        "app.services.widget_presets.preview_widget_preset",
        _preview_widget_preset,
    )
    monkeypatch.setattr(
        "app.services.widget_presets.get_widget_preset",
        lambda preset_id: {"id": preset_id, "tool_name": "ha_get_state"},
    )

    resp = await client.post(
        "/api/v1/widgets/presets/homeassistant-entity-chip/pin",
        json={
            "dashboard_key": f"channel:{channel_id}",
            "config": {"entity_id": "light.kitchen_ceiling_lights"},
            "source_bot_id": "bot-123",
            "source_channel_id": str(channel_id),
            "display_label": "Kitchen Ceiling Lights",
        },
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tool_name"] == "ha_get_state"
    assert body["display_label"] == "Kitchen Ceiling Lights"
    assert body["source_bot_id"] == "bot-123"
    assert body["source_channel_id"] == str(channel_id)
    assert body["tool_args"] == {"entity_id": "light.kitchen_ceiling_lights"}
    assert body["widget_config"]["entity_id"] == "light.kitchen_ceiling_lights"
