from datetime import datetime, timedelta, timezone

from app.routers.api_v1_admin.learning import (
    MemoryFileActivity,
    _build_memory_observatory,
)


def _event(bot_id: str, file_path: str, minutes_ago: int, *, hygiene: bool = False, corr: str | None = None):
    return MemoryFileActivity(
        bot_id=bot_id,
        bot_name=bot_id.title(),
        file_path=file_path,
        operation="append",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        is_hygiene=hygiene,
        correlation_id=corr,
        job_type="memory_hygiene" if hygiene else None,
    )


def test_memory_observatory_promotes_hot_files_and_active_bots():
    response = _build_memory_observatory(
        [
            _event("rolland", "memory/reference/project.md", 1),
            _event("rolland", "memory/reference/project.md", 2, hygiene=True, corr="run-1"),
            _event("rolland", "memory/logs/2026-04.md", 3, hygiene=True, corr="run-1"),
            _event("baker", "memory/reference/recipes.md", 4),
        ],
        days=30,
        lane_limit=1,
    )

    assert response.total_writes == 4
    assert response.active_bot_count == 2
    assert response.hidden_bot_count == 1
    assert response.bots[0].bot_id == "rolland"
    assert response.bots[0].write_count == 3
    assert response.hot_files[0].file_path == "memory/reference/project.md"
    assert response.hot_files[0].write_count == 2
    assert response.hot_files[0].hygiene_count == 1


def test_memory_observatory_groups_run_bursts_by_correlation_id():
    response = _build_memory_observatory(
        [
            _event("rolland", "memory/a.md", 1, hygiene=True, corr="run-1"),
            _event("rolland", "memory/b.md", 2, hygiene=True, corr="run-1"),
            _event("rolland", "memory/c.md", 3),
        ],
        days=7,
    )

    assert len(response.bursts) == 1
    assert response.bursts[0].correlation_id == "run-1"
    assert response.bursts[0].write_count == 2
    assert response.bursts[0].file_count == 2
    assert response.bursts[0].job_type == "memory_hygiene"
