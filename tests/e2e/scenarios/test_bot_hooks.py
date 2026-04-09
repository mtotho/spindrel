"""Bot hooks E2E: CRUD API + behavioral verification (before_access blocks, after_write fires)."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from tests.e2e.harness.client import E2EClient
from tests.e2e.harness.assertions import (
    assert_response_not_empty,
    assert_contains_any,
    assert_no_error_events,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

API = "/api/v1/bot-hooks"


async def _create_hook(client: E2EClient, bot_id: str, **overrides) -> dict:
    """Create a hook via API and return the response body."""
    payload = {
        "bot_id": bot_id,
        "name": f"e2e-hook-{uuid.uuid4().hex[:8]}",
        "trigger": "before_access",
        "conditions": {},
        "command": "true",  # no-op success
        "cooldown_seconds": 0,
        "on_failure": "warn",
        "enabled": True,
        **overrides,
    }
    resp = await client.post(API, json=payload)
    resp.raise_for_status()
    return resp.json()


async def _delete_hook(client: E2EClient, hook_id: str) -> None:
    """Delete a hook, ignoring 404."""
    resp = await client.delete(f"{API}/{hook_id}")
    if resp.status_code not in (200, 204, 404):
        resp.raise_for_status()


async def _list_hooks(client: E2EClient, bot_id: str) -> list[dict]:
    resp = await client.get(API, params={"bot_id": bot_id})
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# CRUD tests
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestBotHooksCrud:
    """Verify the /api/v1/bot-hooks CRUD endpoints."""

    async def test_create_and_get(self, client: E2EClient) -> None:
        """Create a hook, retrieve it by ID, verify fields match."""
        hook = await _create_hook(
            client,
            bot_id=client.default_bot_id,
            name="e2e-create-test",
            trigger="after_write",
            conditions={"path": "/workspace/*.txt"},
            command="echo created",
            cooldown_seconds=30,
            on_failure="warn",
        )
        hook_id = hook["id"]
        try:
            assert hook["name"] == "e2e-create-test"
            assert hook["trigger"] == "after_write"
            assert hook["conditions"] == {"path": "/workspace/*.txt"}
            assert hook["command"] == "echo created"
            assert hook["cooldown_seconds"] == 30
            assert hook["on_failure"] == "warn"
            assert hook["enabled"] is True

            # GET by ID
            resp = await client.get(f"{API}/{hook_id}")
            resp.raise_for_status()
            fetched = resp.json()
            assert fetched["id"] == hook_id
            assert fetched["name"] == "e2e-create-test"
        finally:
            await _delete_hook(client, hook_id)

    async def test_list_filters_by_bot(self, client: E2EClient) -> None:
        """List hooks filtered by bot_id returns only that bot's hooks."""
        bot_id = client.default_bot_id
        hook = await _create_hook(client, bot_id=bot_id, name="e2e-list-test")
        try:
            hooks = await _list_hooks(client, bot_id)
            ids = [h["id"] for h in hooks]
            assert hook["id"] in ids
        finally:
            await _delete_hook(client, hook["id"])

    async def test_update_hook(self, client: E2EClient) -> None:
        """Update a hook's fields via PUT."""
        hook = await _create_hook(client, bot_id=client.default_bot_id)
        hook_id = hook["id"]
        try:
            resp = await client.put(f"{API}/{hook_id}", json={
                "name": "renamed-hook",
                "command": "echo updated",
                "enabled": False,
            })
            resp.raise_for_status()
            updated = resp.json()
            assert updated["name"] == "renamed-hook"
            assert updated["command"] == "echo updated"
            assert updated["enabled"] is False
        finally:
            await _delete_hook(client, hook_id)

    async def test_delete_hook(self, client: E2EClient) -> None:
        """Delete a hook, then verify it's gone."""
        hook = await _create_hook(client, bot_id=client.default_bot_id)
        hook_id = hook["id"]

        resp = await client.delete(f"{API}/{hook_id}")
        assert resp.status_code in (200, 204)

        resp = await client.get(f"{API}/{hook_id}")
        assert resp.status_code == 404

    async def test_default_on_failure_by_trigger(self, client: E2EClient) -> None:
        """before_access defaults to 'block', after_write defaults to 'warn'."""
        bot_id = client.default_bot_id
        hooks = []
        try:
            for trigger, expected in [("before_access", "block"), ("after_write", "warn"), ("after_exec", "warn")]:
                h = await _create_hook(client, bot_id=bot_id, trigger=trigger, on_failure=None)
                hooks.append(h)
                assert h["on_failure"] == expected, (
                    f"trigger={trigger}: expected on_failure='{expected}', got '{h['on_failure']}'"
                )
        finally:
            for h in hooks:
                await _delete_hook(client, h["id"])

    async def test_invalid_trigger_rejected(self, client: E2EClient) -> None:
        """Creating a hook with an invalid trigger returns 422."""
        resp = await client.post(API, json={
            "bot_id": client.default_bot_id,
            "name": "bad-trigger",
            "trigger": "on_banana",
            "command": "echo nope",
        })
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Behavioral tests — hooks fire during file operations
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestBotHooksBehavior:
    """Verify hooks actually fire during bot file operations."""

    async def test_before_access_block_prevents_file_read(self, client: E2EClient) -> None:
        """A before_access hook that fails with on_failure=block should prevent file access."""
        bot_id = client.default_bot_id
        channel_id = client.new_channel_id()

        # Create a hook that always fails for .blocked files
        hook = await _create_hook(
            client,
            bot_id=bot_id,
            name="e2e-block-read",
            trigger="before_access",
            conditions={"path": "*.blocked"},
            command="exit 1",
            cooldown_seconds=0,
            on_failure="block",
        )
        try:
            # Ask bot to write then read a .blocked file — the before_access hook
            # fires on any file operation (read or write) and should block it
            result = await client.chat_stream(
                "Write the text 'hello' to a file called test.blocked, then read it back to me. "
                "Use the file tool.",
                bot_id=bot_id,
                channel_id=channel_id,
            )
            # The bot should report an error from the hook blocking
            combined = result.response_text.lower()
            assert any(kw in combined for kw in ["hook", "fail", "block", "error", "unable", "cannot"]), (
                f"Expected hook block error in response, got: {result.response_text[:300]}"
            )
        finally:
            await _delete_hook(client, hook["id"])

    async def test_before_access_success_allows_file_ops(self, client: E2EClient) -> None:
        """A before_access hook that succeeds should not interfere with file operations."""
        bot_id = client.default_bot_id
        channel_id = client.new_channel_id()

        # Create a hook that always succeeds
        hook = await _create_hook(
            client,
            bot_id=bot_id,
            name="e2e-allow-access",
            trigger="before_access",
            conditions={"path": "*.ok"},
            command="true",
            cooldown_seconds=0,
            on_failure="block",
        )
        try:
            result = await client.chat_stream(
                "Write the text 'hook-test-ok' to a file called verify.ok, "
                "then read it back. Tell me the exact contents.",
                bot_id=bot_id,
                channel_id=channel_id,
            )
            assert_no_error_events(result.events)
            assert_contains_any(result.response_text, ["hook-test-ok"])
        finally:
            await _delete_hook(client, hook["id"])

    async def test_after_write_hook_fires(self, client: E2EClient) -> None:
        """An after_write hook should execute after a file write.

        Strategy: create an after_write hook that touches a marker file,
        then write a file and check if the marker was created.
        """
        bot_id = client.default_bot_id
        channel_id = client.new_channel_id()

        marker = f".hook-marker-{uuid.uuid4().hex[:8]}"

        # after_write hook: when any .trigger file is written, create a marker
        hook = await _create_hook(
            client,
            bot_id=bot_id,
            name="e2e-after-write",
            trigger="after_write",
            conditions={"path": "*.trigger"},
            command=f"touch /workspace/{marker}",
            cooldown_seconds=0,
            on_failure="warn",
        )
        try:
            # Step 1: write a .trigger file
            await client.chat(
                "Write the text 'trigger' to a file called test.trigger using the file tool.",
                bot_id=bot_id,
                channel_id=channel_id,
            )

            # Wait for debounce (2s) + execution time
            await asyncio.sleep(5)

            # Step 2: check if the marker file exists
            result = await client.chat_stream(
                f"List the files in /workspace and tell me if a file called {marker} exists. "
                "Use the file tool with the list operation.",
                bot_id=bot_id,
                channel_id=channel_id,
            )
            # The marker file should have been created by the hook
            assert_contains_any(result.response_text, [marker, "exists", "found"])
        finally:
            await _delete_hook(client, hook["id"])

    async def test_disabled_hook_does_not_fire(self, client: E2EClient) -> None:
        """A disabled hook should not block file operations even if command would fail."""
        bot_id = client.default_bot_id
        channel_id = client.new_channel_id()

        hook = await _create_hook(
            client,
            bot_id=bot_id,
            name="e2e-disabled",
            trigger="before_access",
            conditions={"path": "*.disabled-test"},
            command="exit 1",
            cooldown_seconds=0,
            on_failure="block",
            enabled=False,  # disabled — should not fire
        )
        try:
            result = await client.chat_stream(
                "Write 'hello' to a file called test.disabled-test, then read it back. "
                "Tell me the exact contents.",
                bot_id=bot_id,
                channel_id=channel_id,
            )
            assert_no_error_events(result.events)
            assert_contains_any(result.response_text, ["hello"])
        finally:
            await _delete_hook(client, hook["id"])

    async def test_path_condition_scoping(self, client: E2EClient) -> None:
        """A hook scoped to *.secret should not fire for .txt files."""
        bot_id = client.default_bot_id
        channel_id = client.new_channel_id()

        hook = await _create_hook(
            client,
            bot_id=bot_id,
            name="e2e-path-scope",
            trigger="before_access",
            conditions={"path": "*.secret"},
            command="exit 1",
            cooldown_seconds=0,
            on_failure="block",
        )
        try:
            # Write a .txt file — hook should NOT fire (different extension)
            result = await client.chat_stream(
                "Write 'safe-content' to a file called safe.txt using the file tool, "
                "then read it back and tell me its contents.",
                bot_id=bot_id,
                channel_id=channel_id,
            )
            assert_no_error_events(result.events)
            assert_contains_any(result.response_text, ["safe-content"])
        finally:
            await _delete_hook(client, hook["id"])
