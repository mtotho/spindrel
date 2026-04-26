from datetime import datetime, timezone

from app.services.spatial_map_view import _recency


class SqlAlchemyChannelShape:
    """Minimal SQLAlchemy Channel shape: no computed last_message_at field."""

    def __init__(self) -> None:
        self.updated_at = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
        self.created_at = datetime(2026, 4, 25, 12, 0, tzinfo=timezone.utc)


def test_recency_handles_sqlalchemy_channel_without_last_message_at() -> None:
    assert _recency(SqlAlchemyChannelShape()) == datetime(
        2026,
        4,
        26,
        12,
        0,
        tzinfo=timezone.utc,
    ).timestamp()
