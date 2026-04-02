"""Tests for the Jellyseerr integration tools."""

import json
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _mock_settings(monkeypatch):
    """Provide valid settings via env vars (property-based settings read from env)."""
    monkeypatch.setenv("JELLYSEERR_URL", "http://jellyseerr:5055")
    monkeypatch.setenv("JELLYSEERR_API_KEY", "test-key")


# ---------------------------------------------------------------------------
# jellyseerr_requests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_requests_includes_titles_and_media_status():
    """Verify requests include resolved titles and media_status."""
    from integrations.arr.tools.jellyseerr import jellyseerr_requests

    mock_requests_response = {
        "pageInfo": {"results": 2},
        "results": [
            {
                "id": 1,
                "type": "movie",
                "status": 2,  # approved
                "media": {
                    "mediaType": "movie",
                    "tmdbId": 550,
                    "status": 5,  # available
                    "externalServiceSlug": "fight-club-550",
                },
                "requestedBy": {"displayName": "alice"},
                "createdAt": "2025-01-01T00:00:00Z",
            },
            {
                "id": 2,
                "type": "tv",
                "status": 2,
                "media": {
                    "mediaType": "tv",
                    "tmdbId": 1396,
                    "tvdbId": 81189,
                    "status": 3,  # processing
                    "externalServiceSlug": "breaking-bad",
                },
                "requestedBy": {"displayName": "bob"},
                "createdAt": "2025-01-02T00:00:00Z",
            },
        ],
    }
    mock_movie_detail = {"title": "Fight Club", "id": 550}
    mock_tv_detail = {"name": "Breaking Bad", "id": 1396}

    async def mock_get(path, **kwargs):
        if path == "/api/v1/request":
            return mock_requests_response
        if path == "/api/v1/movie/550":
            return mock_movie_detail
        if path == "/api/v1/tv/1396":
            return mock_tv_detail
        raise ValueError(f"Unexpected path: {path}")

    with patch("integrations.arr.tools.jellyseerr._get", side_effect=mock_get):
        result = json.loads(await jellyseerr_requests())

    assert result["total"] == 2
    reqs = result["requests"]

    # Movie: title resolved, available in Jellyfin
    assert reqs[0]["title"] == "Fight Club"
    assert reqs[0]["media_status"] == "available"
    assert reqs[0]["status"] == "approved"
    assert reqs[0]["tmdb_id"] == 550

    # TV: title resolved, processing
    assert reqs[1]["title"] == "Breaking Bad"
    assert reqs[1]["media_status"] == "processing"
    assert reqs[1]["tvdb_id"] == 81189


@pytest.mark.asyncio
async def test_requests_graceful_title_failure():
    """If title lookup fails for one request, others still get titles."""
    from integrations.arr.tools.jellyseerr import jellyseerr_requests

    mock_requests_response = {
        "pageInfo": {"results": 2},
        "results": [
            {
                "id": 1, "type": "movie", "status": 1,
                "media": {"mediaType": "movie", "tmdbId": 550, "status": 5},
                "requestedBy": {"displayName": "alice"}, "createdAt": "",
            },
            {
                "id": 2, "type": "movie", "status": 1,
                "media": {"mediaType": "movie", "tmdbId": 999, "status": 2},
                "requestedBy": {"displayName": "bob"}, "createdAt": "",
            },
        ],
    }

    async def mock_get(path, **kwargs):
        if path == "/api/v1/request":
            return mock_requests_response
        if path == "/api/v1/movie/550":
            return {"title": "Fight Club"}
        if path == "/api/v1/movie/999":
            raise Exception("TMDB cache miss")
        raise ValueError(f"Unexpected: {path}")

    with patch("integrations.arr.tools.jellyseerr._get", side_effect=mock_get):
        result = json.loads(await jellyseerr_requests())

    reqs = result["requests"]
    assert reqs[0]["title"] == "Fight Club"
    assert "title" not in reqs[1]  # failed lookup, no title
    # But media_status is still present (from the request itself, no extra call)
    assert reqs[1]["media_status"] == "pending"


@pytest.mark.asyncio
async def test_requests_no_tmdb_id():
    """Requests without tmdbId don't trigger title lookups."""
    from integrations.arr.tools.jellyseerr import jellyseerr_requests

    mock_response = {
        "pageInfo": {"results": 1},
        "results": [
            {
                "id": 1, "type": "movie", "status": 1,
                "media": {"mediaType": "movie", "status": 1},
                "requestedBy": {"displayName": "alice"}, "createdAt": "",
            },
        ],
    }

    call_count = 0

    async def mock_get(path, **kwargs):
        nonlocal call_count
        call_count += 1
        if path == "/api/v1/request":
            return mock_response
        raise ValueError(f"Unexpected: {path}")

    with patch("integrations.arr.tools.jellyseerr._get", side_effect=mock_get):
        result = json.loads(await jellyseerr_requests())

    assert call_count == 1  # Only the request list call, no title lookups
    assert "title" not in result["requests"][0]
    assert result["requests"][0]["media_status"] == "unknown"


@pytest.mark.asyncio
async def test_requests_not_configured(monkeypatch):
    """Returns error when JELLYSEERR_URL is not set."""
    from integrations.arr.tools.jellyseerr import jellyseerr_requests

    monkeypatch.setenv("JELLYSEERR_URL", "")
    result = json.loads(await jellyseerr_requests())
    assert "error" in result


@pytest.mark.asyncio
async def test_requests_paging():
    """Verify paging parameters are passed through."""
    from integrations.arr.tools.jellyseerr import jellyseerr_requests

    captured_params = {}

    async def mock_get(path, params=None, **kwargs):
        if path == "/api/v1/request":
            captured_params.update(params or {})
            return {"pageInfo": {"results": 0}, "results": []}
        raise ValueError(f"Unexpected: {path}")

    with patch("integrations.arr.tools.jellyseerr._get", side_effect=mock_get):
        result = json.loads(await jellyseerr_requests(filter="pending", limit=5, skip=10, sort="modified"))

    assert captured_params["take"] == 5
    assert captured_params["skip"] == 10
    assert captured_params["filter"] == "pending"
    assert captured_params["sort"] == "modified"
    assert result["page"]["limit"] == 5
    assert result["page"]["skip"] == 10
