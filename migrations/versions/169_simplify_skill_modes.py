"""Simplify skill modes: remove RAG mode and skills_override

- Convert all mode="rag" to mode="on_demand" in bots.skills, channels.skills_extra,
  shared_workspaces.skills
- NULL out channels.skills_override (legacy whitelist removed)
- Remove similarity_threshold keys from skill config dicts
- Column NOT dropped for rollback safety

Revision ID: 169
Revises: 168
"""
import json

from alembic import op
import sqlalchemy as sa

revision = "169"
down_revision = "168"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Convert rag→on_demand and strip similarity_threshold in bots.skills
    rows = conn.execute(
        sa.text("SELECT id, skills FROM bots WHERE skills IS NOT NULL")
    ).fetchall()
    for row_id, skills in rows:
        if not isinstance(skills, list):
            continue
        changed = False
        new_skills = []
        for entry in skills:
            if not isinstance(entry, dict):
                new_skills.append(entry)
                continue
            updated = dict(entry)
            if updated.get("mode") == "rag":
                updated["mode"] = "on_demand"
                changed = True
            if "similarity_threshold" in updated:
                del updated["similarity_threshold"]
                changed = True
            new_skills.append(updated)
        if changed:
            conn.execute(
                sa.text("UPDATE bots SET skills = :skills WHERE id = :id"),
                {"skills": json.dumps(new_skills), "id": row_id},
            )

    # Convert in channels.skills_extra
    ch_rows = conn.execute(
        sa.text("SELECT id, skills_extra FROM channels WHERE skills_extra IS NOT NULL")
    ).fetchall()
    for row_id, skills in ch_rows:
        if not isinstance(skills, list):
            continue
        changed = False
        new_skills = []
        for entry in skills:
            if not isinstance(entry, dict):
                new_skills.append(entry)
                continue
            updated = dict(entry)
            if updated.get("mode") == "rag":
                updated["mode"] = "on_demand"
                changed = True
            if "similarity_threshold" in updated:
                del updated["similarity_threshold"]
                changed = True
            new_skills.append(updated)
        if changed:
            conn.execute(
                sa.text("UPDATE channels SET skills_extra = :skills WHERE id = :id"),
                {"skills": json.dumps(new_skills), "id": row_id},
            )

    # NULL out skills_override for all channels (legacy whitelist removed)
    conn.execute(sa.text("UPDATE channels SET skills_override = NULL"))

    # Convert in shared_workspaces.skills
    sw_rows = conn.execute(
        sa.text("SELECT id, skills FROM shared_workspaces WHERE skills IS NOT NULL")
    ).fetchall()
    for row_id, skills in sw_rows:
        if not isinstance(skills, list):
            continue
        changed = False
        new_skills = []
        for entry in skills:
            if not isinstance(entry, dict):
                new_skills.append(entry)
                continue
            updated = dict(entry)
            if updated.get("mode") == "rag":
                updated["mode"] = "on_demand"
                changed = True
            if "similarity_threshold" in updated:
                del updated["similarity_threshold"]
                changed = True
            new_skills.append(updated)
        if changed:
            conn.execute(
                sa.text("UPDATE shared_workspaces SET skills = :skills WHERE id = :id"),
                {"skills": json.dumps(new_skills), "id": row_id},
            )


def downgrade() -> None:
    # No-op: rag mode and similarity_threshold cannot be meaningfully restored
    pass
