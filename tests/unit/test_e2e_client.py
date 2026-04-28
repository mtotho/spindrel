from tests.e2e.harness.client import replay_lapsed_resume_cursor


def test_replay_lapsed_resume_cursor_accepts_valid_oldest_available() -> None:
    assert replay_lapsed_resume_cursor({"oldest_available": 2150}) == "2150"
    assert replay_lapsed_resume_cursor({"oldest_available": "2150"}) == "2150"
    assert replay_lapsed_resume_cursor({"oldest_available": " 2150 "}) == "2150"


def test_replay_lapsed_resume_cursor_rejects_invalid_values() -> None:
    assert replay_lapsed_resume_cursor({}) is None
    assert replay_lapsed_resume_cursor({"oldest_available": -1}) is None
    assert replay_lapsed_resume_cursor({"oldest_available": True}) is None
    assert replay_lapsed_resume_cursor({"oldest_available": "abc"}) is None
