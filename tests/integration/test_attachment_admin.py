"""Integration tests for api_v1_admin/attachments.py — 2 mutating routes.

Phase 3 of the Test Quality track. Real FastAPI + real SQLite DB + real router
+ real ORM.

DELETE /attachments/{id} delegates to `app.services.attachments.delete_attachment`
which opens its own session via `async_session` — already patched in the
integration conftest.

POST /attachments/purge uses the route's injected `db` session directly —
no extra patching needed.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db.models import Attachment
from tests.factories import build_attachment
from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio

_PAST = datetime(2025, 1, 1, tzinfo=timezone.utc)
_FUTURE = datetime(2030, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# DELETE /attachments/{attachment_id} — delete_attachment route
# ---------------------------------------------------------------------------

class TestDeleteAttachment:
    async def test_when_attachment_exists_then_deleted_and_sibling_survives(
        self, client, db_session,
    ):
        target = build_attachment(filename="target.png")
        sibling = build_attachment(filename="sibling.png")
        db_session.add(target)
        db_session.add(sibling)
        await db_session.commit()
        target_id = target.id

        resp = await client.delete(
            f"/api/v1/admin/attachments/{target_id}", headers=AUTH_HEADERS,
        )

        assert resp.status_code == 204
        gone = await db_session.execute(
            select(Attachment).where(Attachment.id == target_id)
        )
        assert gone.scalar_one_or_none() is None
        # extra mile: sibling survives
        still_here = await db_session.execute(
            select(Attachment).where(Attachment.id == sibling.id)
        )
        assert still_here.scalar_one_or_none() is not None

    async def test_when_attachment_missing_then_404(self, client):
        resp = await client.delete(
            f"/api/v1/admin/attachments/{uuid.uuid4()}", headers=AUTH_HEADERS,
        )

        assert resp.status_code == 404

    async def test_when_attachment_has_no_integration_metadata_then_deleted_cleanly(
        self, client, db_session,
    ):
        att = build_attachment(metadata_={}, source_integration="web")
        db_session.add(att)
        await db_session.commit()
        att_id = att.id

        resp = await client.delete(
            f"/api/v1/admin/attachments/{att_id}", headers=AUTH_HEADERS,
        )

        assert resp.status_code == 204
        gone = await db_session.execute(
            select(Attachment).where(Attachment.id == att_id)
        )
        assert gone.scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# POST /attachments/purge — purge_attachments route
# ---------------------------------------------------------------------------

class TestPurgeAttachments:
    async def test_when_hard_delete_then_old_rows_gone_and_new_rows_survive(
        self, client, db_session,
    ):
        old = build_attachment(created_at=_PAST)
        new = build_attachment(created_at=_FUTURE)
        db_session.add(old)
        db_session.add(new)
        await db_session.commit()
        old_id, new_id = old.id, new.id

        resp = await client.post(
            "/api/v1/admin/attachments/purge",
            json={"before_date": "2026-01-01T00:00:00Z"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        assert resp.json()["purged_count"] == 1
        gone = await db_session.execute(
            select(Attachment).where(Attachment.id == old_id)
        )
        assert gone.scalar_one_or_none() is None
        surviving = await db_session.execute(
            select(Attachment).where(Attachment.id == new_id)
        )
        assert surviving.scalar_one_or_none() is not None

    async def test_when_purge_file_data_only_then_rows_survive_but_file_data_cleared(
        self, client, db_session,
    ):
        with_data = build_attachment(created_at=_PAST, file_data=b"binary-data")
        without_data = build_attachment(created_at=_PAST, file_data=None)
        db_session.add(with_data)
        db_session.add(without_data)
        await db_session.commit()
        with_id = with_data.id

        resp = await client.post(
            "/api/v1/admin/attachments/purge",
            json={"before_date": "2026-01-01T00:00:00Z", "purge_file_data_only": True},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        assert resp.json()["purged_count"] == 1  # only the row with file_data
        row = await db_session.execute(
            select(Attachment).where(Attachment.id == with_id)
        )
        surviving = row.scalar_one()
        assert surviving.file_data is None  # file_data cleared, row still present

    async def test_when_type_filter_then_only_matching_type_purged(
        self, client, db_session,
    ):
        image = build_attachment(created_at=_PAST, type="image")
        document = build_attachment(created_at=_PAST, type="file")
        db_session.add(image)
        db_session.add(document)
        await db_session.commit()

        resp = await client.post(
            "/api/v1/admin/attachments/purge",
            json={"before_date": "2026-01-01T00:00:00Z", "type": "image"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        assert resp.json()["purged_count"] == 1
        # image gone, document survives
        doc_check = await db_session.execute(
            select(Attachment).where(Attachment.id == document.id)
        )
        assert doc_check.scalar_one_or_none() is not None

    async def test_when_no_matching_rows_then_zero_purged(self, client, db_session):
        new = build_attachment(created_at=_FUTURE)
        db_session.add(new)
        await db_session.commit()

        resp = await client.post(
            "/api/v1/admin/attachments/purge",
            json={"before_date": "2020-01-01T00:00:00Z"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        assert resp.json()["purged_count"] == 0

    async def test_when_channel_filter_applied_then_other_channels_untouched(
        self, client, db_session,
    ):
        ch_a = uuid.uuid4()
        ch_b = uuid.uuid4()
        att_a = build_attachment(created_at=_PAST, channel_id=ch_a)
        att_b = build_attachment(created_at=_PAST, channel_id=ch_b)
        db_session.add(att_a)
        db_session.add(att_b)
        await db_session.commit()

        resp = await client.post(
            "/api/v1/admin/attachments/purge",
            json={"before_date": "2026-01-01T00:00:00Z", "channel_id": str(ch_a)},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        assert resp.json()["purged_count"] == 1
        # ch_b attachment survives
        check_b = await db_session.execute(
            select(Attachment).where(Attachment.id == att_b.id)
        )
        assert check_b.scalar_one_or_none() is not None
