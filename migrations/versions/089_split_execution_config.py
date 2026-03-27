"""Split execution_config from callback_config on tasks.

Adds execution_config JSONB column to tasks and backfills harness/exec
execution parameters from callback_config.

Revision ID: 089
Revises: 088
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "089"
down_revision = "088"

# Keys that belong in execution_config (harness/exec params)
_EXEC_KEYS = {
    "harness_name", "command", "args", "working_directory", "stream_to",
    "sandbox_instance_id", "output_dispatch_type", "output_dispatch_config",
    "source_correlation_id", "model_override", "model_provider_id_override",
    "resume_extra_args", "resume_retries", "claude_session_id",
    "claude_cost_usd", "claude_num_turns",
}


def upgrade() -> None:
    op.add_column("tasks", sa.Column("execution_config", JSONB, nullable=True))

    # Backfill: move execution-related keys from callback_config to execution_config
    # for harness and exec task types
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, callback_config FROM tasks "
            "WHERE task_type IN ('harness', 'exec') "
            "AND callback_config IS NOT NULL"
        )
    ).fetchall()

    for row in rows:
        cb = row[1]
        if not isinstance(cb, dict):
            continue
        exec_cfg = {k: v for k, v in cb.items() if k in _EXEC_KEYS}
        new_cb = {k: v for k, v in cb.items() if k not in _EXEC_KEYS}
        if exec_cfg:
            conn.execute(
                sa.text(
                    "UPDATE tasks SET execution_config = :exec_cfg, callback_config = :new_cb WHERE id = :id"
                ),
                {"exec_cfg": sa.type_coerce(exec_cfg, JSONB), "new_cb": sa.type_coerce(new_cb or None, JSONB), "id": row[0]},
            )

    # Also backfill model_override/model_provider_id_override for non-harness/exec tasks
    rows2 = conn.execute(
        sa.text(
            "SELECT id, callback_config FROM tasks "
            "WHERE task_type NOT IN ('harness', 'exec') "
            "AND callback_config IS NOT NULL "
            "AND (callback_config->>'model_override' IS NOT NULL "
            "  OR callback_config->>'model_provider_id_override' IS NOT NULL)"
        )
    ).fetchall()

    for row in rows2:
        cb = row[1]
        if not isinstance(cb, dict):
            continue
        exec_cfg = {}
        new_cb = dict(cb)
        for k in ("model_override", "model_provider_id_override"):
            if k in new_cb:
                exec_cfg[k] = new_cb.pop(k)
        if exec_cfg:
            conn.execute(
                sa.text(
                    "UPDATE tasks SET execution_config = :exec_cfg, callback_config = :new_cb WHERE id = :id"
                ),
                {"exec_cfg": sa.type_coerce(exec_cfg, JSONB), "new_cb": sa.type_coerce(new_cb or None, JSONB), "id": row[0]},
            )


def downgrade() -> None:
    # Merge execution_config back into callback_config
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, callback_config, execution_config FROM tasks WHERE execution_config IS NOT NULL")
    ).fetchall()

    for row in rows:
        cb = row[1] or {}
        ec = row[2] or {}
        merged = {**cb, **ec}
        conn.execute(
            sa.text("UPDATE tasks SET callback_config = :merged WHERE id = :id"),
            {"merged": sa.type_coerce(merged, JSONB), "id": row[0]},
        )

    op.drop_column("tasks", "execution_config")
