"""Tests for Radarr tool functions."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from integrations.arr.tools.radarr import (
    radarr_command,
    radarr_movies,
    radarr_queue,
    radarr_releases,
)

MODULE = "integrations.arr.tools.radarr"


# ---------------------------------------------------------------------------
# radarr_movies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_movies_list_success():
    api_data = [
        {
            "id": 1,
            "title": "Inception",
            "year": 2010,
            "status": "released",
            "hasFile": True,
            "monitored": True,
            "sizeOnDisk": 2_097_152_000,
        },
        {
            "id": 2,
            "title": "Tenet",
            "year": 2020,
            "status": "released",
            "hasFile": False,
            "monitored": True,
            "sizeOnDisk": 0,
        },
    ]
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=api_data) as mock_get:
        result = json.loads(await radarr_movies())

    assert result["count"] == 2
    assert result["movies"][0]["title"] == "Inception"
    assert result["movies"][0]["size_mb"] == 2000.0
    mock_get.assert_awaited_once_with("/api/v3/movie")


@pytest.mark.asyncio
async def test_movies_search_success():
    api_data = [
        {
            "tmdbId": 27205,
            "title": "Inception",
            "year": 2010,
            "overview": "A thief who steals corporate secrets through dream-sharing technology.",
            "status": "released",
            "runtime": 148,
        },
    ]
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=api_data) as mock_get:
        result = json.loads(await radarr_movies(search="inception"))

    assert result["count"] == 1
    assert result["results"][0]["tmdb_id"] == 27205
    assert result["results"][0]["runtime"] == 148
    mock_get.assert_awaited_once_with("/api/v3/movie/lookup", params={"term": "inception"})


@pytest.mark.asyncio
async def test_movies_filter_missing():
    api_data = [
        {"id": 1, "title": "Has File", "year": 2020, "status": "released",
         "hasFile": True, "monitored": True, "sizeOnDisk": 1000},
        {"id": 2, "title": "No File", "year": 2021, "status": "released",
         "hasFile": False, "monitored": True, "sizeOnDisk": 0},
    ]
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=api_data):
        result = json.loads(await radarr_movies(filter="missing"))

    assert result["count"] == 1
    assert result["movies"][0]["title"] == "No File"


@pytest.mark.asyncio
async def test_movies_filter_wanted():
    api_data = [
        {"id": 1, "title": "Has File", "year": 2020, "status": "released",
         "hasFile": True, "monitored": True, "sizeOnDisk": 1000},
        {"id": 2, "title": "Missing Monitored", "year": 2021, "status": "released",
         "hasFile": False, "monitored": True, "sizeOnDisk": 0},
        {"id": 3, "title": "Missing Unmonitored", "year": 2022, "status": "released",
         "hasFile": False, "monitored": False, "sizeOnDisk": 0},
    ]
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=api_data):
        result = json.loads(await radarr_movies(filter="wanted"))

    # wanted = missing + monitored, so only "Missing Monitored"
    assert result["count"] == 1
    assert result["movies"][0]["title"] == "Missing Monitored"


@pytest.mark.asyncio
async def test_movies_not_configured(monkeypatch):
    monkeypatch.setenv("RADARR_URL", "")
    result = json.loads(await radarr_movies())
    assert result["error"] == "RADARR_URL is not configured"


@pytest.mark.asyncio
async def test_movies_http_error():
    mock_resp = httpx.Response(401, request=httpx.Request("GET", "http://test"))
    with patch(
        f"{MODULE}._get",
        new_callable=AsyncMock,
        side_effect=httpx.HTTPStatusError("err", request=mock_resp.request, response=mock_resp),
    ):
        result = json.loads(await radarr_movies())
    assert "HTTP 401" in result["error"]


@pytest.mark.asyncio
async def test_movies_connect_error():
    with patch(
        f"{MODULE}._get",
        new_callable=AsyncMock,
        side_effect=httpx.ConnectError("Connection refused"),
    ):
        result = json.loads(await radarr_movies())
    assert "Cannot connect to Radarr" in result["error"]


# ---------------------------------------------------------------------------
# radarr_command
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_command_movies_search():
    with patch(f"{MODULE}._post", new_callable=AsyncMock, return_value={"id": 10}) as mock_post:
        result = json.loads(await radarr_command("MoviesSearch", movie_ids=[1, 2]))

    assert result["status"] == "ok"
    assert result["command_id"] == 10
    assert result["action"] == "MoviesSearch"
    mock_post.assert_awaited_once_with(
        "/api/v3/command", {"name": "MoviesSearch", "movieIds": [1, 2]}
    )


@pytest.mark.asyncio
async def test_command_missing_movies_search():
    with patch(f"{MODULE}._post", new_callable=AsyncMock, return_value={"id": 11}):
        result = json.loads(await radarr_command("MissingMoviesSearch"))

    assert result["status"] == "ok"
    assert result["action"] == "MissingMoviesSearch"


@pytest.mark.asyncio
async def test_command_movies_search_missing_ids():
    result = json.loads(await radarr_command("MoviesSearch"))
    assert result["error"] == "movie_ids required for MoviesSearch"


@pytest.mark.asyncio
async def test_command_not_configured(monkeypatch):
    monkeypatch.setenv("RADARR_URL", "")
    result = json.loads(await radarr_command("MoviesSearch", movie_ids=[1]))
    assert result["error"] == "RADARR_URL is not configured"


@pytest.mark.asyncio
async def test_command_http_error():
    mock_resp = httpx.Response(500, request=httpx.Request("POST", "http://test"))
    with patch(
        f"{MODULE}._post",
        new_callable=AsyncMock,
        side_effect=httpx.HTTPStatusError("err", request=mock_resp.request, response=mock_resp),
    ):
        result = json.loads(await radarr_command("MissingMoviesSearch"))
    assert "HTTP 500" in result["error"]


# ---------------------------------------------------------------------------
# radarr_queue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queue_success():
    api_data = {
        "records": [
            {
                "movie": {"title": "Dune", "year": 2021},
                "quality": {"quality": {"name": "Bluray-1080p"}},
                "size": 4_194_304_000,
                "sizeleft": 1_048_576_000,
                "status": "downloading",
                "estimatedCompletionTime": "2024-06-15T10:00:00Z",
            },
        ],
    }
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=api_data) as mock_get:
        result = json.loads(await radarr_queue())

    assert result["count"] == 1
    item = result["items"][0]
    assert item["movie"] == "Dune"
    assert item["quality"] == "Bluray-1080p"
    assert item["progress_pct"] == 75.0
    assert item["status"] == "downloading"
    mock_get.assert_awaited_once()
    call_args = mock_get.call_args
    assert call_args[1]["params"]["includeMovie"] == "true"


@pytest.mark.asyncio
async def test_queue_not_configured(monkeypatch):
    monkeypatch.setenv("RADARR_URL", "")
    result = json.loads(await radarr_queue())
    assert result["error"] == "RADARR_URL is not configured"


@pytest.mark.asyncio
async def test_queue_connect_error():
    with patch(
        f"{MODULE}._get",
        new_callable=AsyncMock,
        side_effect=httpx.ConnectError("Connection refused"),
    ):
        result = json.loads(await radarr_queue())
    assert "Cannot connect to Radarr" in result["error"]


# ---------------------------------------------------------------------------
# radarr_releases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_releases_search_success():
    api_data = [
        {
            "title": "Inception.2010.1080p.BluRay",
            "size": 2_097_152_000,
            "seeders": 100,
            "leechers": 10,
            "quality": {"quality": {"name": "Bluray-1080p"}},
            "guid": "rel-001",
            "indexerId": 3,
            "indexer": "Jackett",
            "ageMinutes": 7200,
            "rejections": [],
        },
    ]
    with patch(f"{MODULE}._get", new_callable=AsyncMock, return_value=api_data) as mock_get:
        result = json.loads(await radarr_releases(action="search", movie_id=42))

    assert result["count"] == 1
    assert result["releases"][0]["seeders"] == 100
    assert result["releases"][0]["age_days"] == 5
    mock_get.assert_awaited_once_with(
        "/api/v3/release", params={"movieId": 42}, timeout=30.0
    )


@pytest.mark.asyncio
async def test_releases_search_missing_movie_id():
    result = json.loads(await radarr_releases(action="search"))
    assert result["error"] == "movie_id required for search"


@pytest.mark.asyncio
async def test_releases_grab_success():
    with patch(f"{MODULE}._post", new_callable=AsyncMock, return_value={}) as mock_post:
        result = json.loads(
            await radarr_releases(action="grab", guid="rel-001", indexer_id=3)
        )

    assert result["status"] == "ok"
    assert result["message"] == "Release grabbed successfully"
    mock_post.assert_awaited_once_with(
        "/api/v3/release", {"guid": "rel-001", "indexerId": 3}
    )


@pytest.mark.asyncio
async def test_releases_grab_missing_params():
    result = json.loads(await radarr_releases(action="grab", guid="rel-001"))
    assert result["error"] == "guid and indexer_id required for grab"

    result = json.loads(await radarr_releases(action="grab", indexer_id=3))
    assert result["error"] == "guid and indexer_id required for grab"


@pytest.mark.asyncio
async def test_releases_not_configured(monkeypatch):
    monkeypatch.setenv("RADARR_URL", "")
    result = json.loads(await radarr_releases(action="search", movie_id=1))
    assert result["error"] == "RADARR_URL is not configured"


@pytest.mark.asyncio
async def test_releases_http_error():
    mock_resp = httpx.Response(500, request=httpx.Request("GET", "http://test"))
    with patch(
        f"{MODULE}._get",
        new_callable=AsyncMock,
        side_effect=httpx.HTTPStatusError("err", request=mock_resp.request, response=mock_resp),
    ):
        result = json.loads(await radarr_releases(action="search", movie_id=1))
    assert "HTTP 500" in result["error"]


@pytest.mark.asyncio
async def test_releases_connect_error():
    with patch(
        f"{MODULE}._get",
        new_callable=AsyncMock,
        side_effect=httpx.ConnectError("Connection refused"),
    ):
        result = json.loads(await radarr_releases(action="search", movie_id=1))
    assert "Cannot connect to Radarr" in result["error"]
