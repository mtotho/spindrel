"""Tests for Sonarr tool functions."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from integrations.arr.tools.sonarr import (
    sonarr_calendar,
    sonarr_command,
    sonarr_quality_profile_update,
    sonarr_quality_profiles,
    sonarr_queue,
    sonarr_releases,
    sonarr_series,
    sonarr_series_update,
    sonarr_wanted,
)

MODULE = "integrations.arr.tools.sonarr"


# ---------------------------------------------------------------------------
# sonarr_calendar
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_calendar_success():
    api_data = [
        {
            "series": {"title": "Breaking Bad"},
            "seasonNumber": 5,
            "episodeNumber": 16,
            "title": "Felina",
            "airDateUtc": "2013-09-29T00:00:00Z",
            "hasFile": True,
        },
    ]
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=api_data) as mock_get:
        result = json.loads(await sonarr_calendar(days_ahead=3))

    assert result["count"] == 1
    assert result["episodes"][0]["series"] == "Breaking Bad"
    assert result["episodes"][0]["has_file"] is True
    mock_get.assert_awaited_once()
    call_args = mock_get.call_args
    assert call_args[0][0] == "/api/v3/calendar"
    assert call_args[1]["params"]["includeSeries"] == "true"


@pytest.mark.asyncio
async def test_calendar_not_configured(monkeypatch):
    monkeypatch.setenv("SONARR_URL", "")
    result = json.loads(await sonarr_calendar())
    assert result["error"] == "SONARR_URL is not configured"


@pytest.mark.asyncio
async def test_calendar_http_error():
    mock_resp = httpx.Response(500, request=httpx.Request("GET", "http://test"))
    with patch(
        f"{MODULE}._get",
        new_callable=AsyncMock,
        side_effect=httpx.HTTPStatusError("err", request=mock_resp.request, response=mock_resp),
    ):
        result = json.loads(await sonarr_calendar())
    assert "HTTP 500" in result["error"]


@pytest.mark.asyncio
async def test_calendar_connect_error():
    with patch(
        f"{MODULE}._get",
        new_callable=AsyncMock,
        side_effect=httpx.ConnectError("Connection refused"),
    ):
        result = json.loads(await sonarr_calendar())
    assert "Cannot connect to Sonarr" in result["error"]


# ---------------------------------------------------------------------------
# sonarr_series
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_series_list_success():
    api_data = [
        {
            "id": 1,
            "title": "The Wire",
            "year": 2002,
            "status": "ended",
            "monitored": True,
            "statistics": {"seasonCount": 5, "episodeCount": 60, "episodeFileCount": 60},
        },
    ]
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=api_data) as mock_get:
        result = json.loads(await sonarr_series())

    assert result["count"] == 1
    assert result["series"][0]["title"] == "The Wire"
    assert result["series"][0]["monitored"] is True
    mock_get.assert_awaited_once_with("/api/v3/series")


@pytest.mark.asyncio
async def test_series_search_success():
    api_data = [
        {
            "tvdbId": 81189,
            "title": "Breaking Bad",
            "year": 2008,
            "overview": "A high school teacher turns to cooking meth.",
            "status": "ended",
            "statistics": {"seasonCount": 5},
        },
    ]
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=api_data) as mock_get:
        result = json.loads(await sonarr_series(search="breaking bad"))

    assert result["count"] == 1
    assert result["results"][0]["tvdb_id"] == 81189
    assert "id" not in result["results"][0]  # not in library
    mock_get.assert_awaited_once_with("/api/v3/series/lookup", params={"term": "breaking bad"})


@pytest.mark.asyncio
async def test_series_search_includes_library_id():
    """When a searched series is already in the library, include the internal Sonarr ID."""
    api_data = [
        {
            "id": 42,
            "tvdbId": 81189,
            "title": "Breaking Bad",
            "year": 2008,
            "overview": "A high school teacher turns to cooking meth.",
            "status": "ended",
            "statistics": {"seasonCount": 5},
        },
    ]
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=api_data):
        result = json.loads(await sonarr_series(search="breaking bad"))

    assert result["results"][0]["id"] == 42
    assert result["results"][0]["tvdb_id"] == 81189


@pytest.mark.asyncio
async def test_series_not_configured(monkeypatch):
    monkeypatch.setenv("SONARR_URL", "")
    result = json.loads(await sonarr_series())
    assert result["error"] == "SONARR_URL is not configured"


@pytest.mark.asyncio
async def test_series_http_error():
    mock_resp = httpx.Response(401, request=httpx.Request("GET", "http://test"))
    with patch(
        f"{MODULE}._get",
        new_callable=AsyncMock,
        side_effect=httpx.HTTPStatusError("err", request=mock_resp.request, response=mock_resp),
    ):
        result = json.loads(await sonarr_series())
    assert "HTTP 401" in result["error"]


# ---------------------------------------------------------------------------
# sonarr_wanted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wanted_success():
    api_data = {
        "totalRecords": 5,
        "records": [
            {
                "series": {"title": "Lost"},
                "seasonNumber": 1,
                "episodeNumber": 1,
                "title": "Pilot Part 1",
                "airDateUtc": "2004-09-22T00:00:00Z",
            },
        ],
    }
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=api_data):
        result = json.loads(await sonarr_wanted(limit=10))

    assert result["total_records"] == 5
    assert len(result["episodes"]) == 1
    assert result["episodes"][0]["series"] == "Lost"


@pytest.mark.asyncio
async def test_wanted_not_configured(monkeypatch):
    monkeypatch.setenv("SONARR_URL", "")
    result = json.loads(await sonarr_wanted())
    assert result["error"] == "SONARR_URL is not configured"


@pytest.mark.asyncio
async def test_wanted_connect_error():
    with patch(
        f"{MODULE}._get",
        new_callable=AsyncMock,
        side_effect=httpx.ConnectError("Connection refused"),
    ):
        result = json.loads(await sonarr_wanted())
    assert "Cannot connect to Sonarr" in result["error"]


# ---------------------------------------------------------------------------
# sonarr_queue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queue_success():
    api_data = {
        "records": [
            {
                "series": {"title": "Dark"},
                "episode": {"seasonNumber": 1, "episodeNumber": 1},
                "quality": {"quality": {"name": "HDTV-720p"}},
                "size": 524_288_000,
                "sizeleft": 262_144_000,
                "status": "downloading",
                "estimatedCompletionTime": "2024-01-01T12:00:00Z",
            },
        ],
    }
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=api_data):
        result = json.loads(await sonarr_queue())

    assert result["count"] == 1
    item = result["items"][0]
    assert item["series"] == "Dark"
    assert item["quality"] == "HDTV-720p"
    assert item["progress_pct"] == 50.0
    assert item["status"] == "downloading"


@pytest.mark.asyncio
async def test_queue_not_configured(monkeypatch):
    monkeypatch.setenv("SONARR_URL", "")
    result = json.loads(await sonarr_queue())
    assert result["error"] == "SONARR_URL is not configured"


@pytest.mark.asyncio
async def test_queue_http_error():
    mock_resp = httpx.Response(503, request=httpx.Request("GET", "http://test"))
    with patch(
        f"{MODULE}._get",
        new_callable=AsyncMock,
        side_effect=httpx.HTTPStatusError("err", request=mock_resp.request, response=mock_resp),
    ):
        result = json.loads(await sonarr_queue())
    assert "HTTP 503" in result["error"]


# ---------------------------------------------------------------------------
# sonarr_command
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_command_series_search():
    with patch(f"{MODULE}._post", new_callable=AsyncMock, return_value={"id": 42}) as mock_post:
        result = json.loads(await sonarr_command("SeriesSearch", series_id=5))

    assert result["status"] == "ok"
    assert result["command_id"] == 42
    assert result["action"] == "SeriesSearch"
    mock_post.assert_awaited_once_with(
        "/api/v3/command", {"name": "SeriesSearch", "seriesId": 5}
    )


@pytest.mark.asyncio
async def test_command_episode_search():
    with patch(f"{MODULE}._post", new_callable=AsyncMock, return_value={"id": 43}) as mock_post:
        result = json.loads(await sonarr_command("EpisodeSearch", episode_ids=[10, 11]))

    assert result["status"] == "ok"
    mock_post.assert_awaited_once_with(
        "/api/v3/command", {"name": "EpisodeSearch", "episodeIds": [10, 11]}
    )


@pytest.mark.asyncio
async def test_command_missing_episode_search():
    with patch(f"{MODULE}._post", new_callable=AsyncMock, return_value={"id": 44}):
        result = json.loads(await sonarr_command("MissingEpisodeSearch"))

    assert result["status"] == "ok"
    assert result["action"] == "MissingEpisodeSearch"


@pytest.mark.asyncio
async def test_command_series_search_missing_id():
    result = json.loads(await sonarr_command("SeriesSearch"))
    assert result["error"] == "series_id required for SeriesSearch"


@pytest.mark.asyncio
async def test_command_episode_search_missing_ids():
    result = json.loads(await sonarr_command("EpisodeSearch"))
    assert result["error"] == "episode_ids required for EpisodeSearch"


@pytest.mark.asyncio
async def test_command_not_configured(monkeypatch):
    monkeypatch.setenv("SONARR_URL", "")
    result = json.loads(await sonarr_command("SeriesSearch", series_id=1))
    assert result["error"] == "SONARR_URL is not configured"


# ---------------------------------------------------------------------------
# sonarr_releases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_releases_search_by_series():
    api_data = [
        {
            "title": "Breaking.Bad.S05E16.720p",
            "size": 1_048_576_000,
            "seeders": 50,
            "leechers": 5,
            "quality": {"quality": {"name": "Bluray-720p"}},
            "guid": "abc-123",
            "indexerId": 1,
            "indexer": "NZBgeek",
            "ageMinutes": 4320,
            "rejections": [],
        },
    ]
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=api_data) as mock_get:
        result = json.loads(await sonarr_releases(action="search", series_id=5))

    assert result["count"] == 1
    assert result["releases"][0]["seeders"] == 50
    assert result["releases"][0]["age_days"] == 3
    mock_get.assert_awaited_once_with("/api/v3/release", params={"seriesId": 5}, timeout=30.0)


@pytest.mark.asyncio
async def test_releases_search_by_episode():
    api_data = [
        {
            "title": "Release1",
            "size": 0,
            "seeders": 10,
            "leechers": 1,
            "quality": {"quality": {"name": "HDTV"}},
            "guid": "def-456",
            "indexerId": 2,
            "indexer": "Prowlarr",
            "ageMinutes": None,
            "rejections": [],
        },
    ]
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=api_data) as mock_get:
        result = json.loads(await sonarr_releases(action="search", episode_id=99))

    assert result["count"] == 1
    mock_get.assert_awaited_once_with("/api/v3/release", params={"episodeId": 99}, timeout=30.0)


@pytest.mark.asyncio
async def test_releases_search_no_id():
    result = json.loads(await sonarr_releases(action="search"))
    assert result["error"] == "series_id or episode_id required for search"


@pytest.mark.asyncio
async def test_releases_grab_success():
    with patch(f"{MODULE}._post", new_callable=AsyncMock, return_value={}) as mock_post:
        result = json.loads(
            await sonarr_releases(action="grab", guid="abc-123", indexer_id=1)
        )

    assert result["status"] == "ok"
    assert result["message"] == "Release grabbed successfully"
    mock_post.assert_awaited_once_with(
        "/api/v3/release", {"guid": "abc-123", "indexerId": 1}
    )


@pytest.mark.asyncio
async def test_releases_grab_missing_params():
    result = json.loads(await sonarr_releases(action="grab", guid="abc-123"))
    assert result["error"] == "guid and indexer_id required for grab"

    result = json.loads(await sonarr_releases(action="grab", indexer_id=1))
    assert result["error"] == "guid and indexer_id required for grab"


@pytest.mark.asyncio
async def test_releases_not_configured(monkeypatch):
    monkeypatch.setenv("SONARR_URL", "")
    result = json.loads(await sonarr_releases(action="search", series_id=1))
    assert result["error"] == "SONARR_URL is not configured"


@pytest.mark.asyncio
async def test_releases_http_error():
    mock_resp = httpx.Response(500, request=httpx.Request("GET", "http://test"))
    with patch(
        f"{MODULE}._get",
        new_callable=AsyncMock,
        side_effect=httpx.HTTPStatusError("err", request=mock_resp.request, response=mock_resp),
    ):
        result = json.loads(await sonarr_releases(action="search", series_id=1))
    assert "HTTP 500" in result["error"]


@pytest.mark.asyncio
async def test_releases_connect_error():
    with patch(
        f"{MODULE}._get",
        new_callable=AsyncMock,
        side_effect=httpx.ConnectError("Connection refused"),
    ):
        result = json.loads(await sonarr_releases(action="search", series_id=1))
    assert "Cannot connect to Sonarr" in result["error"]


# ---------------------------------------------------------------------------
# sonarr_series_update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_series_update_quality_profile():
    current = {"id": 224, "title": "Criminal Minds", "qualityProfileId": 1, "monitored": True, "seriesType": "standard"}
    updated = {**current, "qualityProfileId": 6}
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=current):
        with patch(f"{MODULE}._put", new_callable=AsyncMock, return_value=updated):
            result = json.loads(await sonarr_series_update(series_id=224, quality_profile_id=6))

    assert result["status"] == "ok"
    assert result["quality_profile_id"] == 6
    assert result["title"] == "Criminal Minds"


@pytest.mark.asyncio
async def test_series_update_not_configured(monkeypatch):
    monkeypatch.setenv("SONARR_URL", "")
    result = json.loads(await sonarr_series_update(series_id=1))
    assert result["error"] == "SONARR_URL is not configured"


# ---------------------------------------------------------------------------
# sonarr_quality_profiles
# ---------------------------------------------------------------------------


SAMPLE_PROFILE = {
    "id": 1,
    "name": "HD-1080p",
    "upgradeAllowed": True,
    "cutoff": 1080,
    "items": [
        {"quality": {"id": 1, "name": "SDTV"}, "allowed": False},
        {"quality": {"id": 4, "name": "HDTV-720p"}, "allowed": False},
        {
            "id": 1080,
            "name": "WEB 1080p",
            "allowed": True,
            "items": [
                {"quality": {"id": 3, "name": "WEBDL-1080p"}, "allowed": True},
                {"quality": {"id": 15, "name": "WEBRip-1080p"}, "allowed": True},
            ],
        },
        {"quality": {"id": 7, "name": "Bluray-1080p"}, "allowed": True},
    ],
}


@pytest.mark.asyncio
async def test_quality_profiles_list():
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=[SAMPLE_PROFILE]):
        result = json.loads(await sonarr_quality_profiles())

    assert result["count"] == 1
    assert result["profiles"][0]["name"] == "HD-1080p"
    assert result["profiles"][0]["upgrade_allowed"] is True
    # WEB 1080p group and Bluray-1080p should be in qualities
    q_names = []
    for q in result["profiles"][0]["qualities"]:
        if isinstance(q, dict):
            q_names.append(q["group"])
        else:
            q_names.append(q)
    assert "WEB 1080p" in q_names
    assert "Bluray-1080p" in q_names
    # SDTV should NOT be included (allowed=False)
    assert "SDTV" not in q_names


@pytest.mark.asyncio
async def test_quality_profiles_single():
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=SAMPLE_PROFILE):
        result = json.loads(await sonarr_quality_profiles(profile_id=1))

    assert result["id"] == 1
    assert result["cutoff"] == "WEB 1080p"


@pytest.mark.asyncio
async def test_quality_profile_update_cutoff():
    updated = {**SAMPLE_PROFILE, "cutoff": 7}  # Bluray-1080p
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=SAMPLE_PROFILE):
        with patch(f"{MODULE}._put", new_callable=AsyncMock, return_value=updated):
            result = json.loads(await sonarr_quality_profile_update(
                profile_id=1, cutoff_quality="Bluray-1080p",
            ))

    assert result["cutoff"] == "Bluray-1080p"


@pytest.mark.asyncio
async def test_quality_profile_update_bad_cutoff():
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=SAMPLE_PROFILE):
        result = json.loads(await sonarr_quality_profile_update(
            profile_id=1, cutoff_quality="NonexistentQuality",
        ))

    assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_quality_profiles_not_configured(monkeypatch):
    monkeypatch.setenv("SONARR_URL", "")
    result = json.loads(await sonarr_quality_profiles())
    assert result["error"] == "SONARR_URL is not configured"
