"""Tests for Prowlarr tool functions."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from integrations.arr.tools.prowlarr import (
    prowlarr_apps,
    prowlarr_health,
    prowlarr_indexer_manage,
    prowlarr_indexer_schemas,
    prowlarr_indexers,
    prowlarr_search,
    prowlarr_tags,
)

MODULE = "integrations.arr.tools.prowlarr"


# ---------------------------------------------------------------------------
# prowlarr_indexers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_indexers_list_success():
    indexer_data = [
        {
            "id": 1,
            "name": "NZBgeek",
            "protocol": "usenet",
            "enable": True,
            "priority": 10,
            "appProfileId": 1,
        },
        {
            "id": 2,
            "name": "ThePirateBay",
            "protocol": "torrent",
            "enable": True,
            "priority": 25,
            "appProfileId": 1,
        },
        {
            "id": 3,
            "name": "BrokenIndexer",
            "protocol": "torrent",
            "enable": False,
            "priority": 50,
            "appProfileId": 1,
        },
    ]
    status_data = [
        {
            "indexerId": 3,
            "disabledTill": "2026-04-10T00:00:00Z",
            "mostRecentFailure": "2026-04-09T12:00:00Z",
            "escalationLevel": 5,
        },
    ]
    with patch(f"{MODULE}._get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [indexer_data, status_data]
        result = json.loads(await prowlarr_indexers())

    assert result["count"] == 3
    assert result["indexers"][0]["name"] == "NZBgeek"
    assert result["indexers"][0]["enabled"] is True
    # Broken indexer should have failure info merged
    broken = result["indexers"][2]
    assert broken["name"] == "BrokenIndexer"
    assert broken["disabled_till"] == "2026-04-10T00:00:00Z"
    assert broken["escalation_level"] == 5


@pytest.mark.asyncio
async def test_indexers_test_success():
    indexer_config = {"id": 1, "name": "NZBgeek", "protocol": "usenet"}
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=indexer_config):
        with patch(f"{MODULE}._post", new_callable=AsyncMock, return_value={}):
            result = json.loads(await prowlarr_indexers(action="test", indexer_id=1))

    assert result["test_result"] == "ok"
    assert result["name"] == "NZBgeek"


@pytest.mark.asyncio
async def test_indexers_test_failure():
    indexer_config = {"id": 1, "name": "DeadIndexer", "protocol": "torrent"}
    mock_resp = httpx.Response(400, request=httpx.Request("POST", "http://test"), text="Connection refused")
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=indexer_config):
        with patch(
            f"{MODULE}._post",
            new_callable=AsyncMock,
            side_effect=httpx.HTTPStatusError("err", request=mock_resp.request, response=mock_resp),
        ):
            result = json.loads(await prowlarr_indexers(action="test", indexer_id=1))

    assert result["test_result"] == "failed"
    assert result["name"] == "DeadIndexer"


@pytest.mark.asyncio
async def test_indexers_not_configured(monkeypatch):
    monkeypatch.setenv("PROWLARR_URL", "")
    result = json.loads(await prowlarr_indexers())
    assert result["error"] == "PROWLARR_URL is not configured"


# ---------------------------------------------------------------------------
# prowlarr_search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_success():
    api_data = [
        {
            "title": "Greys Anatomy S22E12 1080p WEB-DL",
            "size": 3_221_225_472,
            "seeders": 57,
            "leechers": 12,
            "indexer": "ThePirateBay",
            "indexerId": 2,
            "protocol": "torrent",
            "age": 34,
            "guid": "abc-123",
            "categories": [{"name": "TV/HD"}],
        },
        {
            "title": "Greys Anatomy S22E12 720p",
            "size": 1_073_741_824,
            "seeders": 10,
            "leechers": 3,
            "indexer": "Knaben3",
            "indexerId": 5,
            "protocol": "torrent",
            "age": 30,
            "guid": "def-456",
            "categories": [{"name": "TV/HD"}],
        },
    ]
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=api_data) as mock_get:
        result = json.loads(await prowlarr_search(query="Grey's Anatomy S22E12"))

    assert result["count"] == 2
    assert result["results"][0]["seeders"] == 57  # sorted by seeders desc
    assert result["results"][0]["size_mb"] == 3072.0
    assert result["results"][0]["indexer"] == "ThePirateBay"
    mock_get.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_with_indexer_filter():
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=[]) as mock_get:
        result = json.loads(await prowlarr_search(query="test", indexer_ids=[1, 3]))

    call_params = mock_get.call_args[1].get("params") or mock_get.call_args[0][1]
    assert "1,3" in str(call_params)


@pytest.mark.asyncio
async def test_search_not_configured(monkeypatch):
    monkeypatch.setenv("PROWLARR_URL", "")
    result = json.loads(await prowlarr_search(query="test"))
    assert result["error"] == "PROWLARR_URL is not configured"


# ---------------------------------------------------------------------------
# prowlarr_apps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apps_success():
    api_data = [
        {
            "id": 1,
            "name": "Sonarr",
            "implementation": "Sonarr",
            "syncLevel": "fullSync",
        },
        {
            "id": 2,
            "name": "Radarr",
            "implementation": "Radarr",
            "syncLevel": "fullSync",
        },
    ]
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=api_data):
        result = json.loads(await prowlarr_apps())

    assert result["count"] == 2
    assert result["apps"][0]["name"] == "Sonarr"
    assert result["apps"][0]["sync_level"] == "fullSync"


@pytest.mark.asyncio
async def test_apps_not_configured(monkeypatch):
    monkeypatch.setenv("PROWLARR_URL", "")
    result = json.loads(await prowlarr_apps())
    assert result["error"] == "PROWLARR_URL is not configured"


# ---------------------------------------------------------------------------
# prowlarr_health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_success():
    api_data = [
        {
            "type": "warning",
            "source": "IndexerStatusCheck",
            "message": "Indexers unavailable due to failures: ThePirateBay",
            "wikiUrl": "https://wiki.servarr.com/prowlarr/system/status#indexers-unavailable",
        },
    ]
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=api_data):
        result = json.loads(await prowlarr_health())

    assert result["count"] == 1
    assert "ThePirateBay" in result["issues"][0]["message"]
    assert result["issues"][0]["source"] == "IndexerStatusCheck"


@pytest.mark.asyncio
async def test_health_clean():
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=[]):
        result = json.loads(await prowlarr_health())

    assert result["count"] == 0


@pytest.mark.asyncio
async def test_health_not_configured(monkeypatch):
    monkeypatch.setenv("PROWLARR_URL", "")
    result = json.loads(await prowlarr_health())
    assert result["error"] == "PROWLARR_URL is not configured"


# ---------------------------------------------------------------------------
# prowlarr_tags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tags_success():
    api_data = [
        {"id": 1, "label": "flaresolverr"},
        {"id": 2, "label": "movies-only"},
    ]
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=api_data):
        result = json.loads(await prowlarr_tags())

    assert result["count"] == 2
    assert result["tags"][0]["id"] == 1
    assert result["tags"][0]["label"] == "flaresolverr"


@pytest.mark.asyncio
async def test_tags_not_configured(monkeypatch):
    monkeypatch.setenv("PROWLARR_URL", "")
    result = json.loads(await prowlarr_tags())
    assert result["error"] == "PROWLARR_URL is not configured"


# ---------------------------------------------------------------------------
# prowlarr_indexer_schemas
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schemas_list_success():
    api_data = [
        {
            "definitionName": "thepiratebay",
            "name": "The Pirate Bay",
            "implementation": "Cardigann",
            "protocol": "torrent",
            "privacy": "public",
            "supportsRss": True,
            "supportsSearch": True,
            "fields": [
                {"name": "definitionFile", "value": "thepiratebay"},
                {"name": "baseUrl", "label": "Base URL", "type": "textbox", "advanced": False},
            ],
        },
        {
            "definitionName": "nzbgeek",
            "name": "NZBgeek",
            "implementation": "Newznab",
            "protocol": "usenet",
            "privacy": "private",
            "supportsRss": True,
            "supportsSearch": True,
            "fields": [
                {"name": "definitionFile", "value": "nzbgeek"},
                {"name": "apiKey", "label": "API Key", "type": "textbox", "advanced": False},
            ],
        },
    ]
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=api_data):
        result = json.loads(await prowlarr_indexer_schemas())

    assert result["count"] == 2
    assert result["schemas"][0]["definition_name"] == "thepiratebay"
    # required_fields should contain baseUrl but not definitionFile
    assert "baseUrl" in result["schemas"][0]["required_fields"]
    assert "definitionFile" not in result["schemas"][0].get("required_fields", [])
    # apiKey should be in second schema's required_fields
    assert "apiKey" in result["schemas"][1]["required_fields"]


@pytest.mark.asyncio
async def test_schemas_search_filter():
    api_data = [
        {"definitionName": "thepiratebay", "name": "The Pirate Bay", "fields": []},
        {"definitionName": "nzbgeek", "name": "NZBgeek", "fields": []},
    ]
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=api_data):
        result = json.loads(await prowlarr_indexer_schemas(search="pirate"))

    assert result["count"] == 1
    assert result["schemas"][0]["definition_name"] == "thepiratebay"


# ---------------------------------------------------------------------------
# prowlarr_indexer_manage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manage_add_success():
    schema_data = [
        {
            "definitionName": "thepiratebay",
            "name": "The Pirate Bay",
            "implementation": "Cardigann",
            "fields": [
                {"name": "definitionFile", "value": "thepiratebay"},
                {"name": "baseUrl", "label": "Base URL", "type": "textbox", "value": ""},
            ],
        },
    ]
    created = {"id": 5, "name": "The Pirate Bay"}
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=schema_data):
        with patch(f"{MODULE}._post", new_callable=AsyncMock, return_value=created) as mock_post:
            result = json.loads(await prowlarr_indexer_manage(
                action="add",
                definition_name="thepiratebay",
                field_values={"baseUrl": "https://tpb.example.com"},
            ))

    assert result["status"] == "ok"
    assert result["indexer_id"] == 5
    # Verify field values were applied
    posted = mock_post.call_args[0][1]
    base_url_field = next(f for f in posted["fields"] if f["name"] == "baseUrl")
    assert base_url_field["value"] == "https://tpb.example.com"
    assert posted["tags"] == []  # Required for adding enabled indexers
    assert posted["appProfileId"] == 1  # Default app profile


@pytest.mark.asyncio
async def test_manage_add_with_tags():
    schema_data = [
        {
            "definitionName": "1337x",
            "name": "1337x",
            "implementation": "Cardigann",
            "fields": [],
        },
    ]
    created = {"id": 7, "name": "1337x"}
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=schema_data):
        with patch(f"{MODULE}._post", new_callable=AsyncMock, return_value=created) as mock_post:
            result = json.loads(await prowlarr_indexer_manage(
                action="add",
                definition_name="1337x",
                tags=[1],  # FlareSolverr tag
            ))

    assert result["status"] == "ok"
    posted = mock_post.call_args[0][1]
    assert posted["tags"] == [1]


@pytest.mark.asyncio
async def test_manage_add_missing_definition():
    result = json.loads(await prowlarr_indexer_manage(action="add"))
    assert "definition_name required" in result["error"]


@pytest.mark.asyncio
async def test_manage_add_definition_not_found():
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=[]):
        result = json.loads(await prowlarr_indexer_manage(
            action="add", definition_name="nonexistent",
        ))
    assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_manage_delete_success():
    with patch(f"{MODULE}._delete", new_callable=AsyncMock, return_value=200):
        result = json.loads(await prowlarr_indexer_manage(action="delete", indexer_id=5))

    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_manage_delete_missing_id():
    result = json.loads(await prowlarr_indexer_manage(action="delete"))
    assert "indexer_id required" in result["error"]


@pytest.mark.asyncio
async def test_manage_update_success():
    current = {
        "id": 3,
        "name": "Old Name",
        "enable": True,
        "priority": 25,
        "fields": [
            {"name": "apiKey", "value": "old-key"},
        ],
    }
    updated = {"id": 3, "name": "New Name"}
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=current):
        with patch(f"{MODULE}._put", new_callable=AsyncMock, return_value=updated):
            result = json.loads(await prowlarr_indexer_manage(
                action="update",
                indexer_id=3,
                name="New Name",
                field_values={"apiKey": "new-key"},
            ))

    assert result["status"] == "ok"
    assert result["name"] == "New Name"


@pytest.mark.asyncio
async def test_manage_not_configured(monkeypatch):
    monkeypatch.setenv("PROWLARR_URL", "")
    result = json.loads(await prowlarr_indexer_manage(action="add", definition_name="test"))
    assert result["error"] == "PROWLARR_URL is not configured"
