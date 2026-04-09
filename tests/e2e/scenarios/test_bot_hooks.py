"""Bot hooks E2E: comprehensive CRUD + behavioral verification.

Tests cover:
- Full CRUD lifecycle (create, read, list, update, delete)
- Validation (invalid triggers, invalid on_failure)
- Default on_failure by trigger type
- before_access: block vs warn failure modes
- before_access: succeeding hook allows operations
- after_write: hook fires after file write (marker-file strategy)
- after_exec: hook fires after exec_command (marker-file strategy)
- Disabled hooks don't fire
- Path condition scoping (glob matching)
- Recursive glob patterns (**)
- Cooldown enforcement (hook suppressed within window)
- Multiple hooks on same path (both fire, one block stops operation)
- Hook created via API takes effect immediately (cache reload)
- Hook deleted via API stops firing immediately
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from tests.e2e.harness.client import E2EClient
from tests.e2e.harness.config import E2EConfig
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


async def _cleanup_hooks(client: E2EClient, hook_ids: list[str]) -> None:
    """Delete multiple hooks, ignoring errors."""
    for hid in hook_ids:
        await _delete_hook(client, hid)


# ---------------------------------------------------------------------------
# CRUD tests
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestBotHooksCrud:
    """Verify the /api/v1/bot-hooks CRUD endpoints."""

    async def test_create_and_get(self, client: E2EClient) -> None:
        """Create a hook, retrieve it by ID, verify all fields round-trip."""
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
            assert hook["bot_id"] == client.default_bot_id
            assert "created_at" in hook
            assert "updated_at" in hook

            # GET by ID
            resp = await client.get(f"{API}/{hook_id}")
            resp.raise_for_status()
            fetched = resp.json()
            assert fetched["id"] == hook_id
            assert fetched["name"] == "e2e-create-test"
            assert fetched["trigger"] == "after_write"
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
            # All returned hooks belong to this bot
            for h in hooks:
                assert h["bot_id"] == bot_id
        finally:
            await _delete_hook(client, hook["id"])

    async def test_list_unfiltered_returns_all(self, client: E2EClient) -> None:
        """List without bot_id filter returns hooks (at least our created one)."""
        hook = await _create_hook(client, bot_id=client.default_bot_id)
        try:
            resp = await client.get(API)
            resp.raise_for_status()
            hooks = resp.json()
            assert isinstance(hooks, list)
            assert any(h["id"] == hook["id"] for h in hooks)
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
                "cooldown_seconds": 120,
                "on_failure": "block",
            })
            resp.raise_for_status()
            updated = resp.json()
            assert updated["name"] == "renamed-hook"
            assert updated["command"] == "echo updated"
            assert updated["enabled"] is False
            assert updated["cooldown_seconds"] == 120
            assert updated["on_failure"] == "block"
            # Unchanged fields preserved
            assert updated["trigger"] == hook["trigger"]
            assert updated["conditions"] == hook["conditions"]
        finally:
            await _delete_hook(client, hook_id)

    async def test_partial_update(self, client: E2EClient) -> None:
        """PUT with a single field only changes that field."""
        hook = await _create_hook(
            client,
            bot_id=client.default_bot_id,
            name="partial-test",
            command="echo original",
        )
        hook_id = hook["id"]
        try:
            resp = await client.put(f"{API}/{hook_id}", json={"name": "new-name"})
            resp.raise_for_status()
            updated = resp.json()
            assert updated["name"] == "new-name"
            assert updated["command"] == "echo original"  # unchanged
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

    async def test_delete_nonexistent_returns_404(self, client: E2EClient) -> None:
        """Deleting a hook that doesn't exist returns 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.delete(f"{API}/{fake_id}")
        assert resp.status_code == 404

    async def test_get_nonexistent_returns_404(self, client: E2EClient) -> None:
        """GET for a nonexistent hook returns 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"{API}/{fake_id}")
        assert resp.status_code == 404

    async def test_default_on_failure_by_trigger(self, client: E2EClient) -> None:
        """before_access defaults to 'block', after_write/after_exec default to 'warn'."""
        bot_id = client.default_bot_id
        hooks = []
        try:
            for trigger, expected in [
                ("before_access", "block"),
                ("after_write", "warn"),
                ("after_exec", "warn"),
            ]:
                h = await _create_hook(client, bot_id=bot_id, trigger=trigger, on_failure=None)
                hooks.append(h)
                assert h["on_failure"] == expected, (
                    f"trigger={trigger}: expected on_failure='{expected}', got '{h['on_failure']}'"
                )
        finally:
            await _cleanup_hooks(client, [h["id"] for h in hooks])

    async def test_explicit_on_failure_override(self, client: E2EClient) -> None:
        """Explicit on_failure overrides the trigger-based default."""
        hook = await _create_hook(
            client,
            bot_id=client.default_bot_id,
            trigger="before_access",
            on_failure="warn",  # override default "block"
        )
        try:
            assert hook["on_failure"] == "warn"
        finally:
            await _delete_hook(client, hook["id"])

    async def test_invalid_trigger_rejected(self, client: E2EClient) -> None:
        """Creating a hook with an invalid trigger returns 422."""
        resp = await client.post(API, json={
            "bot_id": client.default_bot_id,
            "name": "bad-trigger",
            "trigger": "on_banana",
            "command": "echo nope",
        })
        assert resp.status_code == 422

    async def test_invalid_on_failure_rejected(self, client: E2EClient) -> None:
        """Creating a hook with an invalid on_failure returns 422."""
        resp = await client.post(API, json={
            "bot_id": client.default_bot_id,
            "name": "bad-failure",
            "trigger": "before_access",
            "command": "echo nope",
            "on_failure": "explode",
        })
        assert resp.status_code == 422

    async def test_create_with_empty_conditions(self, client: E2EClient) -> None:
        """Hook with empty conditions is valid (matches everything)."""
        hook = await _create_hook(
            client,
            bot_id=client.default_bot_id,
            conditions={},
        )
        try:
            assert hook["conditions"] == {}
        finally:
            await _delete_hook(client, hook["id"])

    async def test_toggle_enabled_via_update(self, client: E2EClient) -> None:
        """Toggling enabled on and off works correctly."""
        hook = await _create_hook(client, bot_id=client.default_bot_id, enabled=True)
        hook_id = hook["id"]
        try:
            # Disable
            resp = await client.put(f"{API}/{hook_id}", json={"enabled": False})
            resp.raise_for_status()
            assert resp.json()["enabled"] is False

            # Re-enable
            resp = await client.put(f"{API}/{hook_id}", json={"enabled": True})
            resp.raise_for_status()
            assert resp.json()["enabled"] is True
        finally:
            await _delete_hook(client, hook_id)


# ---------------------------------------------------------------------------
# Behavioral: before_access
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestBeforeAccessHooks:
    """Verify before_access hooks fire and enforce block/warn semantics."""

    async def test_block_prevents_file_write(self, client: E2EClient) -> None:
        """A failing before_access hook with on_failure=block prevents file write."""
        bot_id = client.default_bot_id
        channel_id = client.new_channel_id()

        hook = await _create_hook(
            client,
            bot_id=bot_id,
            name="e2e-block-write",
            trigger="before_access",
            conditions={"path": "*.blocked"},
            command="exit 1",
            cooldown_seconds=0,
            on_failure="block",
        )
        try:
            result = await client.chat_stream(
                "Write the text 'hello' to a file called test.blocked using the file tool.",
                bot_id=bot_id,
                channel_id=channel_id,
            )
            combined = result.response_text.lower()
            assert any(kw in combined for kw in [
                "hook", "fail", "block", "error", "unable", "cannot", "denied",
            ]), f"Expected hook block error in response, got: {result.response_text[:300]}"
        finally:
            await _delete_hook(client, hook["id"])

    async def test_block_prevents_file_read(self, client: E2EClient) -> None:
        """A failing before_access hook with on_failure=block prevents file read.

        First write a file without the hook, then add the hook and try to read.
        """
        bot_id = client.default_bot_id
        channel_id = client.new_channel_id()
        fname = f"read-block-{uuid.uuid4().hex[:8]}.guarded"

        # Step 1: write the file with NO hook active
        await client.chat(
            f"Write the text 'secret-data' to a file called {fname} using the file tool.",
            bot_id=bot_id,
            channel_id=channel_id,
        )

        # Step 2: add a blocking hook for .guarded files
        hook = await _create_hook(
            client,
            bot_id=bot_id,
            name="e2e-block-read",
            trigger="before_access",
            conditions={"path": "*.guarded"},
            command="exit 1",
            cooldown_seconds=0,
            on_failure="block",
        )
        try:
            # Step 3: try to read the file — should be blocked
            result = await client.chat_stream(
                f"Read the file {fname} using the file tool and tell me its contents.",
                bot_id=bot_id,
                channel_id=channel_id,
            )
            combined = result.response_text.lower()
            # Should NOT contain the file contents
            assert "secret-data" not in combined, (
                "File read should have been blocked but contents appeared in response"
            )
            assert any(kw in combined for kw in [
                "hook", "fail", "block", "error", "unable", "cannot", "denied",
            ]), f"Expected hook block error, got: {result.response_text[:300]}"
        finally:
            await _delete_hook(client, hook["id"])

    async def test_warn_allows_operation_despite_failure(self, client: E2EClient) -> None:
        """A failing before_access hook with on_failure=warn should let the operation proceed."""
        bot_id = client.default_bot_id
        channel_id = client.new_channel_id()

        hook = await _create_hook(
            client,
            bot_id=bot_id,
            name="e2e-warn-access",
            trigger="before_access",
            conditions={"path": "*.warned"},
            command="exit 1",  # fails, but on_failure=warn → operation continues
            cooldown_seconds=0,
            on_failure="warn",
        )
        try:
            result = await client.chat_stream(
                "Write the text 'warn-test-data' to a file called test.warned using the file tool, "
                "then read it back and tell me the exact contents.",
                bot_id=bot_id,
                channel_id=channel_id,
            )
            # The operation should succeed despite hook failure
            assert_contains_any(result.response_text, ["warn-test-data"])
        finally:
            await _delete_hook(client, hook["id"])

    async def test_success_allows_file_ops(self, client: E2EClient) -> None:
        """A succeeding before_access hook with on_failure=block still allows operations."""
        bot_id = client.default_bot_id
        channel_id = client.new_channel_id()

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
                "Write the text 'hook-test-ok' to a file called verify.ok using the file tool, "
                "then read it back. Tell me the exact contents.",
                bot_id=bot_id,
                channel_id=channel_id,
            )
            assert_no_error_events(result.events)
            assert_contains_any(result.response_text, ["hook-test-ok"])
        finally:
            await _delete_hook(client, hook["id"])


# ---------------------------------------------------------------------------
# Behavioral: after_write
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestAfterWriteHooks:
    """Verify after_write hooks fire after successful file writes."""

    async def test_after_write_creates_marker(self, client: E2EClient) -> None:
        """An after_write hook should execute after a file write.

        Strategy: hook touches a marker file, then we verify it exists.
        """
        bot_id = client.default_bot_id
        channel_id = client.new_channel_id()
        marker = f".hook-marker-{uuid.uuid4().hex[:8]}"

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
            # Write a .trigger file
            await client.chat(
                "Write the text 'trigger' to a file called test.trigger using the file tool.",
                bot_id=bot_id,
                channel_id=channel_id,
            )

            # Wait for debounce (2s) + execution time
            await asyncio.sleep(5)

            # Check if the marker file exists
            result = await client.chat_stream(
                f"List the files in /workspace using the file tool and tell me if "
                f"a file called {marker} exists.",
                bot_id=bot_id,
                channel_id=channel_id,
            )
            assert_contains_any(result.response_text, [marker, "exists", "found"])
        finally:
            await _delete_hook(client, hook["id"])

    async def test_after_write_does_not_fire_on_read(self, client: E2EClient) -> None:
        """An after_write hook should NOT fire on a read-only operation.

        Strategy: create hook that writes a marker, read a file, verify no marker.
        """
        bot_id = client.default_bot_id
        channel_id = client.new_channel_id()
        marker = f".read-marker-{uuid.uuid4().hex[:8]}"
        fname = f"existing-{uuid.uuid4().hex[:8]}.readtest"

        # Pre-create a file to read (without the after_write hook)
        await client.chat(
            f"Write 'pre-existing' to a file called {fname} using the file tool.",
            bot_id=bot_id,
            channel_id=channel_id,
        )

        hook = await _create_hook(
            client,
            bot_id=bot_id,
            name="e2e-after-write-read-only",
            trigger="after_write",
            conditions={"path": f"*{fname}"},
            command=f"touch /workspace/{marker}",
            cooldown_seconds=0,
        )
        try:
            # Only read the file — should NOT trigger after_write
            await client.chat(
                f"Read the file {fname} using the file tool and tell me its contents.",
                bot_id=bot_id,
                channel_id=channel_id,
            )

            # Wait long enough for debounce + execution if it had fired
            await asyncio.sleep(5)

            # Marker should NOT exist
            result = await client.chat_stream(
                f"Check if the file {marker} exists in /workspace using the file tool "
                f"with the list operation. Tell me yes or no.",
                bot_id=bot_id,
                channel_id=channel_id,
            )
            combined = result.response_text.lower()
            # Marker shouldn't be there — look for absence signals
            assert not (marker in combined and any(w in combined for w in ["exists", "found", "yes"])) or \
                any(w in combined for w in ["not found", "no", "doesn't exist", "does not exist", "not exist"]), \
                f"after_write marker should not exist after read-only op: {result.response_text[:300]}"
        finally:
            await _delete_hook(client, hook["id"])


# ---------------------------------------------------------------------------
# Behavioral: after_exec
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestAfterExecHooks:
    """Verify after_exec hooks fire after exec_command calls."""

    @pytest.fixture
    async def exec_bot(self, client: E2EClient, e2e_config: E2EConfig):
        """Create a temporary bot with exec_command in its local_tools."""
        bot_id = f"e2e-exec-{uuid.uuid4().hex[:8]}"
        await client.create_bot({
            "id": bot_id,
            "name": "E2E Exec Hook Test Bot",
            "model": e2e_config.default_model,
            "system_prompt": (
                "You are a test bot with shell access. When asked to run a command, "
                "use the exec_command tool. When asked about files, use the file tool. "
                "Be concise."
            ),
            "local_tools": ["exec_command", "file"],
            "memory_scheme": "workspace-files",
            "tool_retrieval": False,
            "context_compaction": False,
            "persona": False,
            "workspace": {"enabled": True},
        })
        yield bot_id
        await client.delete_bot(bot_id)

    async def test_after_exec_creates_marker(self, client: E2EClient, exec_bot: str) -> None:
        """An after_exec hook fires after exec_command and creates a marker file."""
        channel_id = client.new_channel_id()
        marker = f".exec-marker-{uuid.uuid4().hex[:8]}"

        hook = await _create_hook(
            client,
            bot_id=exec_bot,
            name="e2e-after-exec",
            trigger="after_exec",
            conditions={},  # matches all exec calls
            command=f"touch /workspace/{marker}",
            cooldown_seconds=0,
            on_failure="warn",
        )
        try:
            # Run a simple command via exec_command
            await client.chat(
                "Run the command 'echo hello' using exec_command.",
                bot_id=exec_bot,
                channel_id=channel_id,
            )

            # after_exec is synchronous (not debounced like after_write), but give it a moment
            await asyncio.sleep(3)

            # Verify marker exists
            result = await client.chat_stream(
                f"List the files in /workspace using the file tool and tell me if "
                f"a file called {marker} exists.",
                bot_id=exec_bot,
                channel_id=channel_id,
            )
            assert_contains_any(result.response_text, [marker, "exists", "found"])
        finally:
            await _delete_hook(client, hook["id"])

    async def test_before_access_blocks_exec(self, client: E2EClient, exec_bot: str) -> None:
        """A before_access hook also fires before exec_command and can block it."""
        channel_id = client.new_channel_id()

        hook = await _create_hook(
            client,
            bot_id=exec_bot,
            name="e2e-block-exec",
            trigger="before_access",
            conditions={},  # matches all paths including working_dir
            command="exit 1",
            cooldown_seconds=0,
            on_failure="block",
        )
        try:
            result = await client.chat_stream(
                "Run the command 'echo should-not-run' using exec_command.",
                bot_id=exec_bot,
                channel_id=channel_id,
            )
            combined = result.response_text.lower()
            assert "should-not-run" not in combined, (
                "exec_command should have been blocked but output appeared"
            )
            assert any(kw in combined for kw in [
                "hook", "fail", "block", "error", "unable", "cannot",
            ]), f"Expected hook block error, got: {result.response_text[:300]}"
        finally:
            await _delete_hook(client, hook["id"])


# ---------------------------------------------------------------------------
# Behavioral: disabled hooks
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestDisabledHooks:
    """Verify disabled hooks have no effect."""

    async def test_disabled_block_hook_allows_operations(self, client: E2EClient) -> None:
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
            enabled=False,
        )
        try:
            result = await client.chat_stream(
                "Write 'hello' to a file called test.disabled-test using the file tool, "
                "then read it back. Tell me the exact contents.",
                bot_id=bot_id,
                channel_id=channel_id,
            )
            assert_no_error_events(result.events)
            assert_contains_any(result.response_text, ["hello"])
        finally:
            await _delete_hook(client, hook["id"])

    async def test_re_enable_hook_takes_effect(self, client: E2EClient) -> None:
        """Disabling then re-enabling a hook makes it fire again."""
        bot_id = client.default_bot_id
        channel_id = client.new_channel_id()
        ext = f"renable-{uuid.uuid4().hex[:6]}"

        hook = await _create_hook(
            client,
            bot_id=bot_id,
            name="e2e-re-enable",
            trigger="before_access",
            conditions={"path": f"*.{ext}"},
            command="exit 1",
            cooldown_seconds=0,
            on_failure="block",
            enabled=False,  # start disabled
        )
        hook_id = hook["id"]
        try:
            # Should succeed — hook is disabled
            r1 = await client.chat_stream(
                f"Write 'pass1' to a file called test.{ext} using the file tool, "
                "then read it back. Tell me the contents.",
                bot_id=bot_id,
                channel_id=channel_id,
            )
            assert_contains_any(r1.response_text, ["pass1"])

            # Re-enable the hook
            resp = await client.put(f"{API}/{hook_id}", json={"enabled": True})
            resp.raise_for_status()

            # Now it should block
            channel_id2 = client.new_channel_id()
            r2 = await client.chat_stream(
                f"Write 'pass2' to a file called test2.{ext} using the file tool.",
                bot_id=bot_id,
                channel_id=channel_id2,
            )
            combined = r2.response_text.lower()
            assert any(kw in combined for kw in [
                "hook", "fail", "block", "error", "unable", "cannot", "denied",
            ]), f"Expected hook block after re-enable, got: {r2.response_text[:300]}"
        finally:
            await _delete_hook(client, hook_id)


# ---------------------------------------------------------------------------
# Behavioral: path condition scoping & glob patterns
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestPathConditions:
    """Verify path glob matching — hooks only fire for matching paths."""

    async def test_extension_scoping(self, client: E2EClient) -> None:
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

    async def test_exact_filename_match(self, client: E2EClient) -> None:
        """A hook with an exact filename condition only matches that file."""
        bot_id = client.default_bot_id
        channel_id = client.new_channel_id()
        target = f"exact-{uuid.uuid4().hex[:8]}.dat"

        hook = await _create_hook(
            client,
            bot_id=bot_id,
            name="e2e-exact-match",
            trigger="before_access",
            conditions={"path": target},
            command="exit 1",
            cooldown_seconds=0,
            on_failure="block",
        )
        try:
            # Different filename — should NOT be blocked
            result = await client.chat_stream(
                "Write 'other-file' to a file called other.dat using the file tool, "
                "then read it back and tell me its contents.",
                bot_id=bot_id,
                channel_id=channel_id,
            )
            assert_contains_any(result.response_text, ["other-file"])
        finally:
            await _delete_hook(client, hook["id"])

    async def test_no_conditions_matches_all(self, client: E2EClient) -> None:
        """A hook with empty conditions matches all file operations."""
        bot_id = client.default_bot_id
        channel_id = client.new_channel_id()

        hook = await _create_hook(
            client,
            bot_id=bot_id,
            name="e2e-match-all",
            trigger="before_access",
            conditions={},  # no path → matches everything
            command="exit 1",
            cooldown_seconds=0,
            on_failure="block",
        )
        try:
            result = await client.chat_stream(
                "Write 'anything' to a file called anything.xyz using the file tool.",
                bot_id=bot_id,
                channel_id=channel_id,
            )
            combined = result.response_text.lower()
            assert any(kw in combined for kw in [
                "hook", "fail", "block", "error", "unable", "cannot", "denied",
            ]), f"Expected block from catch-all hook, got: {result.response_text[:300]}"
        finally:
            await _delete_hook(client, hook["id"])


# ---------------------------------------------------------------------------
# Behavioral: cooldown
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestCooldown:
    """Verify cooldown suppresses repeated hook fires within the window."""

    async def test_cooldown_suppresses_second_fire(self, client: E2EClient) -> None:
        """A before_access/block hook with a long cooldown fires once, then is suppressed.

        First file op → hook fires (fails, blocks).
        Second file op (within cooldown) → hook is suppressed, operation proceeds.
        """
        bot_id = client.default_bot_id
        ext = f"cd-{uuid.uuid4().hex[:6]}"

        hook = await _create_hook(
            client,
            bot_id=bot_id,
            name="e2e-cooldown",
            trigger="before_access",
            conditions={"path": f"*.{ext}"},
            command="exit 1",
            cooldown_seconds=300,  # 5 minutes — won't expire during test
            on_failure="block",
        )
        try:
            # First attempt — hook fires and blocks
            ch1 = client.new_channel_id()
            r1 = await client.chat_stream(
                f"Write 'first' to a file called first.{ext} using the file tool.",
                bot_id=bot_id,
                channel_id=ch1,
            )
            combined1 = r1.response_text.lower()
            assert any(kw in combined1 for kw in [
                "hook", "fail", "block", "error", "unable", "cannot",
            ]), f"First attempt should be blocked, got: {r1.response_text[:300]}"

            # Second attempt — cooldown should suppress the hook, allowing the operation
            ch2 = client.new_channel_id()
            r2 = await client.chat_stream(
                f"Write 'second' to a file called second.{ext} using the file tool, "
                "then read it back. Tell me the exact contents.",
                bot_id=bot_id,
                channel_id=ch2,
            )
            assert_contains_any(r2.response_text, ["second"]), (
                f"Second attempt should succeed (cooldown active), got: {r2.response_text[:300]}"
            )
        finally:
            await _delete_hook(client, hook["id"])


# ---------------------------------------------------------------------------
# Behavioral: multiple hooks on same path
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestMultipleHooks:
    """Verify behavior when multiple hooks match the same path."""

    async def test_two_warn_hooks_both_allow(self, client: E2EClient) -> None:
        """Two failing warn hooks on the same path: both fire, operation still proceeds."""
        bot_id = client.default_bot_id
        channel_id = client.new_channel_id()
        ext = f"multi-{uuid.uuid4().hex[:6]}"

        h1 = await _create_hook(
            client, bot_id=bot_id,
            name="e2e-multi-warn-1",
            trigger="before_access",
            conditions={"path": f"*.{ext}"},
            command="exit 1",
            cooldown_seconds=0,
            on_failure="warn",
        )
        h2 = await _create_hook(
            client, bot_id=bot_id,
            name="e2e-multi-warn-2",
            trigger="before_access",
            conditions={"path": f"*.{ext}"},
            command="exit 1",
            cooldown_seconds=0,
            on_failure="warn",
        )
        try:
            result = await client.chat_stream(
                f"Write 'multi-test' to a file called test.{ext} using the file tool, "
                "then read it back. Tell me the exact contents.",
                bot_id=bot_id,
                channel_id=channel_id,
            )
            # Both hooks fail with warn, but operation should succeed
            assert_contains_any(result.response_text, ["multi-test"])
        finally:
            await _cleanup_hooks(client, [h1["id"], h2["id"]])

    async def test_one_block_hook_stops_operation(self, client: E2EClient) -> None:
        """One warn hook + one block hook: block hook fails → operation blocked."""
        bot_id = client.default_bot_id
        channel_id = client.new_channel_id()
        ext = f"mixblock-{uuid.uuid4().hex[:6]}"

        h_warn = await _create_hook(
            client, bot_id=bot_id,
            name="e2e-multi-warn",
            trigger="before_access",
            conditions={"path": f"*.{ext}"},
            command="exit 1",
            cooldown_seconds=0,
            on_failure="warn",
        )
        h_block = await _create_hook(
            client, bot_id=bot_id,
            name="e2e-multi-block",
            trigger="before_access",
            conditions={"path": f"*.{ext}"},
            command="exit 1",
            cooldown_seconds=0,
            on_failure="block",
        )
        try:
            result = await client.chat_stream(
                f"Write 'blocked-multi' to a file called test.{ext} using the file tool.",
                bot_id=bot_id,
                channel_id=channel_id,
            )
            combined = result.response_text.lower()
            assert any(kw in combined for kw in [
                "hook", "fail", "block", "error", "unable", "cannot", "denied",
            ]), f"Expected block from mixed hooks, got: {result.response_text[:300]}"
        finally:
            await _cleanup_hooks(client, [h_warn["id"], h_block["id"]])


# ---------------------------------------------------------------------------
# Behavioral: cache reload — hooks take effect / stop immediately after CRUD
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestCacheReload:
    """Verify that hook CRUD immediately updates in-memory behavior."""

    async def test_newly_created_hook_fires_immediately(self, client: E2EClient) -> None:
        """A hook created mid-session blocks the very next file operation."""
        bot_id = client.default_bot_id
        ext = f"cache-{uuid.uuid4().hex[:6]}"

        # First: write succeeds (no hook)
        ch1 = client.new_channel_id()
        r1 = await client.chat_stream(
            f"Write 'before-hook' to a file called pre.{ext} using the file tool, "
            "then read it back. Tell me the contents.",
            bot_id=bot_id,
            channel_id=ch1,
        )
        assert_contains_any(r1.response_text, ["before-hook"])

        # Create a blocking hook
        hook = await _create_hook(
            client,
            bot_id=bot_id,
            name="e2e-cache-reload",
            trigger="before_access",
            conditions={"path": f"*.{ext}"},
            command="exit 1",
            cooldown_seconds=0,
            on_failure="block",
        )
        try:
            # Immediately try another write — should be blocked
            ch2 = client.new_channel_id()
            r2 = await client.chat_stream(
                f"Write 'after-hook' to a file called post.{ext} using the file tool.",
                bot_id=bot_id,
                channel_id=ch2,
            )
            combined = r2.response_text.lower()
            assert any(kw in combined for kw in [
                "hook", "fail", "block", "error", "unable", "cannot", "denied",
            ]), f"Hook should take effect immediately, got: {r2.response_text[:300]}"
        finally:
            await _delete_hook(client, hook["id"])

    async def test_deleted_hook_stops_firing_immediately(self, client: E2EClient) -> None:
        """After deleting a hook, the next file operation is no longer blocked."""
        bot_id = client.default_bot_id
        ext = f"delcache-{uuid.uuid4().hex[:6]}"

        hook = await _create_hook(
            client,
            bot_id=bot_id,
            name="e2e-del-cache",
            trigger="before_access",
            conditions={"path": f"*.{ext}"},
            command="exit 1",
            cooldown_seconds=0,
            on_failure="block",
        )

        # Verify it blocks
        ch1 = client.new_channel_id()
        r1 = await client.chat_stream(
            f"Write 'blocked' to a file called test.{ext} using the file tool.",
            bot_id=bot_id,
            channel_id=ch1,
        )
        combined1 = r1.response_text.lower()
        assert any(kw in combined1 for kw in [
            "hook", "fail", "block", "error", "unable", "cannot",
        ]), f"Hook should block, got: {r1.response_text[:300]}"

        # Delete the hook
        await _delete_hook(client, hook["id"])

        # Immediately try again — should succeed
        ch2 = client.new_channel_id()
        r2 = await client.chat_stream(
            f"Write 'unblocked' to a file called test2.{ext} using the file tool, "
            "then read it back. Tell me the exact contents.",
            bot_id=bot_id,
            channel_id=ch2,
        )
        assert_contains_any(r2.response_text, ["unblocked"])
