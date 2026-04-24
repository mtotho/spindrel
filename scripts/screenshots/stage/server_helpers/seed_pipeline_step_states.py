"""Run inside the e2e agent-server container.

Usage:
    python - <task_id> <current_step_index>

Sets ``tasks.step_states`` to a plausible mid-run shape:
[done, done, ..., running] — with ``current_step_index`` still ``running`` and
all earlier steps ``done``. The ``steps`` column is read to derive the step
count so this script can't be mis-used to fabricate states for non-pipeline
tasks.
"""
from __future__ import annotations

import asyncio
import sys


async def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: python - <task_id> <current_step_index>")

    task_id = sys.argv[1]
    try:
        current = int(sys.argv[2])
    except ValueError as e:
        raise SystemExit(f"current_step_index must be an integer: {e}")

    # Import inside the container's venv — these paths only resolve there.
    from app.db.engine import async_session  # type: ignore
    from app.db.models import Task  # type: ignore
    from sqlalchemy import select  # type: ignore

    import uuid
    task_uuid = uuid.UUID(task_id)

    async with async_session() as db:
        task = (await db.execute(select(Task).where(Task.id == task_uuid))).scalar_one_or_none()
        if task is None:
            raise SystemExit(f"Task {task_id} not found")
        if task.task_type != "pipeline":
            raise SystemExit(f"Task {task_id} is not a pipeline (task_type={task.task_type!r})")
        steps = task.steps or []
        if not steps:
            raise SystemExit(f"Task {task_id} has no steps; refusing to seed step_states")
        if not (0 <= current < len(steps)):
            raise SystemExit(
                f"current_step_index {current} out of range for {len(steps)} steps"
            )

        step_states = []
        for idx in range(len(steps)):
            if idx < current:
                step_states.append(
                    {
                        "status": "done",
                        "result": f"[seeded] step {idx + 1} completed",
                        "started_at": "2026-04-24T16:00:00Z",
                        "finished_at": "2026-04-24T16:00:15Z",
                    }
                )
            elif idx == current:
                step_states.append(
                    {
                        "status": "running",
                        "started_at": "2026-04-24T16:00:16Z",
                    }
                )
            else:
                step_states.append({"status": "pending"})

        task.step_states = step_states
        task.status = "running"
        await db.commit()

        print(
            f"ok task_id={task_id} steps={len(steps)} current={current} "
            f"status={task.status}"
        )


if __name__ == "__main__":
    asyncio.run(main())
