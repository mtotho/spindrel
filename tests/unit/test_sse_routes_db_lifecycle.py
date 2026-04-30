import inspect

from app.routers import api_v1_channels, api_v1_sessions


def test_channel_events_closes_db_before_streaming_response():
    source = inspect.getsource(api_v1_channels.channel_events)
    assert "await db.close()" in source
    assert source.index("await db.close()") < source.index("return StreamingResponse")


def test_session_events_closes_db_before_streaming_response():
    source = inspect.getsource(api_v1_sessions.session_events)
    assert "await db.close()" in source
    assert source.index("await db.close()") < source.index("return StreamingResponse")
