"""F.3 — slack/uploads.py: _store_slack_file_id swallowed exception drops tracking ID.

Seam class: partial-commit (external-side commits, local write fails silently)
Suspected drift: file successfully uploaded to Slack (files.completeUploadExternal
succeeds), but ``_store_slack_file_id`` raises inside the outer try/except at
integrations/slack/uploads.py:133-134. The file is now in Slack with no local
``slack_file_id`` — subsequent delete attempts hit 404, user-deletion UX is
broken. Related to the 'Slack image doesn't show up in web UI' Loose End.

Tests pin:
- Happy-path JSONB write (flag_modified fires, cross-session read confirms)
- Second call updates existing slack_file_id (accumulation correct)
- Missing attachment → no-op, no exception
- metadata_=None → fresh dict created, no NoneType mutation
- DRIFT PIN: _store_slack_file_id raises → upload_image still returns file_id,
  attachment metadata_ has no slack_file_id key (silent data loss confirmed)
"""
from __future__ import annotations

import base64
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.db.models import Attachment
from tests.factories import build_attachment

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok_response(json_data: dict | None = None) -> MagicMock:
    """Build a mock httpx Response that raise_for_status does nothing."""
    r = MagicMock()
    r.raise_for_status = MagicMock()
    if json_data is not None:
        r.json = MagicMock(return_value=json_data)
    return r


def _make_upload_http_mock(file_id: str = "F_TEST_123"):
    """Return an async mock for ``_http.post`` simulating a fully successful upload.

    Three Slack API calls in order:
      1. files.getUploadURLExternal  → ok + upload_url + file_id
      2. PUT to pre-signed URL       → 200
      3. files.completeUploadExternal → ok
    """
    call_count = [0]
    responses = [
        _ok_response({"ok": True, "upload_url": "https://upload.example.test/u", "file_id": file_id}),
        _ok_response(),
        _ok_response({"ok": True}),
    ]

    async def _post(url, **kwargs):
        result = responses[call_count[0]]
        call_count[0] += 1
        return result

    return _post


# ---------------------------------------------------------------------------
# Tests: _store_slack_file_id persistence contracts
# ---------------------------------------------------------------------------


class TestStoreSlackFileId:
    async def test_when_attachment_exists_then_slack_file_id_persisted(
        self, db_session, patched_async_sessions
    ):
        """Happy path: flag_modified fires and the JSONB write survives a cross-session
        expire_all round-trip — confirming the value was written to disk, not just
        mutated in memory."""
        from integrations.slack.uploads import _store_slack_file_id

        att = build_attachment()
        db_session.add(att)
        await db_session.commit()
        att_id = att.id

        await _store_slack_file_id(str(att_id), "F12345")

        db_session.expire_all()
        refreshed = await db_session.get(Attachment, att_id)
        assert refreshed.metadata_["slack_file_id"] == "F12345"

    async def test_second_call_updates_existing_slack_file_id(
        self, db_session, patched_async_sessions
    ):
        """JSONB mutation correctness: a second _store_slack_file_id call overwrites
        the previous file_id rather than appending or silently no-oping."""
        from integrations.slack.uploads import _store_slack_file_id

        att = build_attachment(metadata_={"slack_file_id": "OLD-F"})
        db_session.add(att)
        await db_session.commit()
        att_id = att.id

        await _store_slack_file_id(str(att_id), "NEW-F")

        db_session.expire_all()
        refreshed = await db_session.get(Attachment, att_id)
        assert refreshed.metadata_["slack_file_id"] == "NEW-F"

    async def test_when_attachment_missing_then_no_exception(
        self, db_session, patched_async_sessions
    ):
        """db.get returns None → function returns without raising, no INSERT attempted."""
        from integrations.slack.uploads import _store_slack_file_id

        ghost_id = str(uuid.uuid4())
        # Must not raise
        await _store_slack_file_id(ghost_id, "F99999")

        # Confirm no attachment was created as a side-effect.
        count_result = await db_session.execute(
            select(Attachment).where(Attachment.id == uuid.UUID(ghost_id))
        )
        assert count_result.scalar_one_or_none() is None

    async def test_when_metadata_is_none_then_fresh_dict_created(
        self, db_session, patched_async_sessions
    ):
        """metadata_=None → copy.deepcopy({}) path creates a fresh dict and persists
        slack_file_id without mutating None in place."""
        from integrations.slack.uploads import _store_slack_file_id

        att = build_attachment(metadata_=None)
        db_session.add(att)
        await db_session.commit()
        att_id = att.id

        await _store_slack_file_id(str(att_id), "F55555")

        db_session.expire_all()
        refreshed = await db_session.get(Attachment, att_id)
        assert isinstance(refreshed.metadata_, dict)
        assert refreshed.metadata_["slack_file_id"] == "F55555"

    async def test_sibling_keys_preserved_on_update(
        self, db_session, patched_async_sessions
    ):
        """Existing metadata_ keys are preserved when slack_file_id is added."""
        from integrations.slack.uploads import _store_slack_file_id

        att = build_attachment(metadata_={"custom_key": "custom_val"})
        db_session.add(att)
        await db_session.commit()
        att_id = att.id

        await _store_slack_file_id(str(att_id), "F77777")

        db_session.expire_all()
        refreshed = await db_session.get(Attachment, att_id)
        assert refreshed.metadata_["custom_key"] == "custom_val"
        assert refreshed.metadata_["slack_file_id"] == "F77777"


# ---------------------------------------------------------------------------
# Tests: upload_image outer exception-swallow drift pin
# ---------------------------------------------------------------------------


class TestUploadImageStoreFileIdDriftPin:
    async def test_when_store_file_id_raises_then_upload_still_returns_file_id(
        self, db_session, patched_async_sessions
    ):
        """DRIFT PIN — _store_slack_file_id raises inside the outer try/except.

        The upload to Slack has already fully succeeded at this point: all three
        API calls completed, file_id returned. The outer function logs a warning
        and continues, returning file_id to the caller. The attachment is left
        with no slack_file_id in metadata_ — deletion via files.delete will hit 404.

        This pins the current silent-warning behavior as the documented contract.
        If the outer try/except is tightened in the future, this test will fail
        and force an explicit decision about the failure mode.
        """
        from integrations.slack import uploads as uploads_mod

        att = build_attachment()
        db_session.add(att)
        await db_session.commit()
        att_id = att.id

        action = {
            "data": base64.b64encode(b"fake-image-bytes").decode(),
            "filename": "test.png",
            "attachment_id": str(att_id),
        }

        with (
            patch.object(uploads_mod._http, "post", side_effect=_make_upload_http_mock("F_EXPECTED")),
            patch(
                "integrations.slack.uploads._store_slack_file_id",
                side_effect=RuntimeError("disk full"),
            ),
        ):
            result = await uploads_mod.upload_image(
                token="xoxb-fake",
                channel_id="C12345",
                thread_ts=None,
                reply_in_thread=False,
                action=action,
            )

        # Outer function returns file_id despite _store_slack_file_id raising.
        assert result == "F_EXPECTED"

        # Attachment metadata_ has no slack_file_id — local write was silently lost.
        db_session.expire_all()
        refreshed = await db_session.get(Attachment, att_id)
        assert "slack_file_id" not in (refreshed.metadata_ or {})
