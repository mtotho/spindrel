"""Factories for app.db.models.Attachment."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.db.models import Attachment


def build_attachment(**overrides) -> Attachment:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid.uuid4(),
        message_id=None,
        channel_id=None,
        type="image",
        url="https://example.com/file.png",
        file_data=None,
        filename="test-image.png",
        mime_type="image/png",
        size_bytes=1024,
        posted_by=None,
        source_integration="web",
        metadata_={},
        description=None,
        created_at=now,
    )
    return Attachment(**{**defaults, **overrides})
