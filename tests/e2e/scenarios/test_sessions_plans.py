"""Tier 1: Sessions & Plans API — CRUD, message injection, context, plan endpoints.

Deterministic API contract tests — no LLM dependency.  Uses the integration
sessions API to create sessions and inject messages, then verifies all
session/plan endpoints return correct shapes and status codes.

Tier 1 — API contract (no model needed).
"""

from __future__ import annotations

import uuid

import pytest

from ..harness.client import E2EClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SESSIONS = "/api/v1/sessions"
_UI_SESSIONS = "/sessions"


def _unique(prefix: str = "e2e-sess") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _create_session(client: E2EClient, client_id: str) -> str:
    """Create a session via integration API, return session_id."""
    resp = await client.post(
        _SESSIONS,
        json={"bot_id": client.default_bot_id, "client_id": client_id},
    )
    assert resp.status_code == 201, f"Session create failed: {resp.status_code} {resp.text[:200]}"
    return resp.json()["session_id"]


async def _inject_message(
    client: E2EClient, session_id: str, content: str, *, role: str = "user",
) -> dict:
    """Inject a message into a session, return the response."""
    resp = await client.post(
        f"{_SESSIONS}/{session_id}/messages",
        json={"content": content, "role": role, "run_agent": False, "notify": False},
    )
    assert resp.status_code == 201, f"Inject failed: {resp.status_code} {resp.text[:200]}"
    return resp.json()


async def _delete_session(client: E2EClient, session_id: str) -> None:
    """Delete a session (cleanup)."""
    await client.delete(f"{_UI_SESSIONS}/{session_id}")


# ---------------------------------------------------------------------------
# Session creation & retrieval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_create_and_get(client: E2EClient) -> None:
    """Create a session via integration API, retrieve it via UI API."""
    cid = _unique()
    session_id = await _create_session(client, cid)
    try:
        # Get session detail via UI sessions endpoint
        resp = await client.get(f"{_UI_SESSIONS}/{session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session"]["bot_id"] == client.default_bot_id
        assert isinstance(data["messages"], list)
    finally:
        await _delete_session(client, session_id)


@pytest.mark.asyncio
async def test_session_list_includes_created(client: E2EClient) -> None:
    """Created session appears in the session list."""
    cid = _unique()
    session_id = await _create_session(client, cid)
    try:
        resp = await client.get(_UI_SESSIONS)
        assert resp.status_code == 200
        ids = [s["id"] for s in resp.json()]
        assert session_id in ids
    finally:
        await _delete_session(client, session_id)


@pytest.mark.asyncio
async def test_session_list_filter_by_client_id(client: E2EClient) -> None:
    """Filter sessions by client_id returns only matching sessions."""
    cid = _unique()
    session_id = await _create_session(client, cid)
    try:
        resp = await client.get(_UI_SESSIONS, params={"client_id": cid})
        assert resp.status_code == 200
        sessions = resp.json()
        assert len(sessions) >= 1
        assert all(s["client_id"] == cid for s in sessions)
    finally:
        await _delete_session(client, session_id)


@pytest.mark.asyncio
async def test_session_delete(client: E2EClient) -> None:
    """Delete a session, verify 204 and subsequent GET returns 404."""
    cid = _unique()
    session_id = await _create_session(client, cid)

    resp = await client.delete(f"{_UI_SESSIONS}/{session_id}")
    assert resp.status_code == 204

    resp = await client.get(f"{_UI_SESSIONS}/{session_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_session_get_nonexistent_404(client: E2EClient) -> None:
    """GET a nonexistent session returns 404."""
    fake_id = str(uuid.uuid4())
    resp = await client.get(f"{_UI_SESSIONS}/{fake_id}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Message injection & listing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_message_inject_and_list(client: E2EClient) -> None:
    """Inject messages into a session, list them back."""
    cid = _unique()
    session_id = await _create_session(client, cid)
    try:
        # Inject two messages
        r1 = await _inject_message(client, session_id, "Hello from E2E test")
        assert "message_id" in r1
        assert r1["session_id"] == session_id
        assert r1["task_id"] is None  # run_agent=False

        r2 = await _inject_message(client, session_id, "Second message")

        # List messages via integration API
        resp = await client.get(f"{_SESSIONS}/{session_id}/messages")
        assert resp.status_code == 200
        messages = resp.json()
        assert len(messages) >= 2
        contents = [m["content"] for m in messages]
        assert "Hello from E2E test" in contents
        assert "Second message" in contents

        # List messages via UI API (paginated)
        resp2 = await client.get(f"{_UI_SESSIONS}/{session_id}/messages")
        assert resp2.status_code == 200
        page = resp2.json()
        assert "messages" in page
        assert "has_more" in page
        assert isinstance(page["messages"], list)
    finally:
        await _delete_session(client, session_id)


@pytest.mark.asyncio
async def test_message_inject_with_source_metadata(client: E2EClient) -> None:
    """Injected message with source stores it in metadata."""
    cid = _unique()
    session_id = await _create_session(client, cid)
    try:
        await client.post(
            f"{_SESSIONS}/{session_id}/messages",
            json={"content": "From email", "source": "gmail", "notify": False},
        )

        resp = await client.get(f"{_SESSIONS}/{session_id}/messages")
        messages = resp.json()
        email_msg = next((m for m in messages if m["content"] == "From email"), None)
        assert email_msg is not None
        assert email_msg["metadata"].get("source") == "gmail"
    finally:
        await _delete_session(client, session_id)


@pytest.mark.asyncio
async def test_message_inject_nonexistent_session_404(client: E2EClient) -> None:
    """Injecting into a nonexistent session returns 404."""
    fake_id = str(uuid.uuid4())
    resp = await client.post(
        f"{_SESSIONS}/{fake_id}/messages",
        json={"content": "should fail", "notify": False},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Session context endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_context_shape(client: E2EClient) -> None:
    """Session context endpoint returns valid shape."""
    cid = _unique()
    session_id = await _create_session(client, cid)
    try:
        await _inject_message(client, session_id, "Context test message")

        # UI context endpoint (trace-based)
        resp = await client.get(f"{_UI_SESSIONS}/{session_id}/context")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_chars" in data
        assert "total_messages" in data

        # Integration context endpoint (full assembly)
        resp2 = await client.get(f"{_SESSIONS}/{session_id}/context")
        assert resp2.status_code == 200
        ctx = resp2.json()
        assert "session_id" in ctx
        assert "bot_id" in ctx
        assert "message_count" in ctx
        assert "total_chars" in ctx
        assert isinstance(ctx["messages"], list)
    finally:
        await _delete_session(client, session_id)


@pytest.mark.asyncio
async def test_session_context_diagnostics_shape(client: E2EClient) -> None:
    """Context diagnostics endpoint returns compaction info."""
    cid = _unique()
    session_id = await _create_session(client, cid)
    try:
        resp = await client.get(f"{_UI_SESSIONS}/{session_id}/context/diagnostics")
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert "total_messages" in data
        assert "compaction" in data
        compaction = data["compaction"]
        assert "enabled" in compaction
        assert isinstance(compaction["enabled"], bool)
        assert "has_summary" in compaction
    finally:
        await _delete_session(client, session_id)


# ---------------------------------------------------------------------------
# Plans (session-scoped)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_plans_empty(client: E2EClient) -> None:
    """New session has no plans."""
    cid = _unique()
    session_id = await _create_session(client, cid)
    try:
        resp = await client.get(f"{_UI_SESSIONS}/{session_id}/plans")
        assert resp.status_code == 200
        plans = resp.json()
        assert isinstance(plans, list)
        assert len(plans) == 0

        # Also check with status=all
        resp2 = await client.get(
            f"{_UI_SESSIONS}/{session_id}/plans", params={"status": "all"},
        )
        assert resp2.status_code == 200
        assert isinstance(resp2.json(), list)
    finally:
        await _delete_session(client, session_id)


@pytest.mark.asyncio
async def test_plan_status_update_nonexistent_404(client: E2EClient) -> None:
    """Updating status of a nonexistent plan returns 404."""
    cid = _unique()
    session_id = await _create_session(client, cid)
    try:
        fake_plan_id = str(uuid.uuid4())
        resp = await client.post(
            f"{_UI_SESSIONS}/{session_id}/plans/{fake_plan_id}/status",
            json={"status": "complete"},
        )
        assert resp.status_code == 404
    finally:
        await _delete_session(client, session_id)


@pytest.mark.asyncio
async def test_plan_item_status_update_nonexistent_404(client: E2EClient) -> None:
    """Updating status of an item in a nonexistent plan returns 404."""
    cid = _unique()
    session_id = await _create_session(client, cid)
    try:
        fake_plan_id = str(uuid.uuid4())
        resp = await client.post(
            f"{_UI_SESSIONS}/{session_id}/plans/{fake_plan_id}/items/1/status",
            json={"status": "done"},
        )
        assert resp.status_code == 404
    finally:
        await _delete_session(client, session_id)
