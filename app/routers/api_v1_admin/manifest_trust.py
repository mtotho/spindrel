"""POST /api/v1/admin/manifest/trust-current-state — recompute and persist
HMAC signatures over every skill / widget row.

Phase 2 verify-on-read refuses to load any row whose persisted
``signature`` no longer matches its body. After legitimate operator
edits (file seeders, raw-SQL repairs) or after a ``MANIFEST_SIGNING_KEY``
rotation, every existing row is in the "tampered" state until this
action runs.

The endpoint is a two-step gate: without ``confirm: true`` it returns
the dry-run count of rows that *would* change. With ``confirm: true``
it persists the new signatures.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Skill, WidgetTemplatePackage
from app.dependencies import get_db, require_scopes
from app.services.manifest_signing import (
    sign_skill_payload,
    sign_widget_payload,
    verify_skill_row,
    verify_widget_row,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_VALID_TARGETS = {"skills", "widgets", "all"}


async def _resign_skills(db: AsyncSession, *, dry_run: bool) -> dict[str, int]:
    rows = (await db.execute(select(Skill))).scalars().all()
    would_change = 0
    updated = 0
    skipped = 0
    for row in rows:
        if verify_skill_row(row) and row.signature:
            skipped += 1
            continue
        new_sig = sign_skill_payload(row.content or "", row.scripts or [])
        if new_sig is None:
            # No signing key — caller's environment isn't set up; surface
            # the row in the response so the operator notices.
            skipped += 1
            continue
        if new_sig != row.signature:
            would_change += 1
            if not dry_run:
                row.signature = new_sig
                updated += 1
    return {"would_change": would_change, "updated": updated, "skipped": skipped}


async def _resign_widgets(db: AsyncSession, *, dry_run: bool) -> dict[str, int]:
    rows = (await db.execute(select(WidgetTemplatePackage))).scalars().all()
    would_change = 0
    updated = 0
    skipped = 0
    for row in rows:
        if verify_widget_row(row) and row.signature:
            skipped += 1
            continue
        new_sig = sign_widget_payload(row.yaml_template or "", row.python_code)
        if new_sig is None:
            skipped += 1
            continue
        if new_sig != row.signature:
            would_change += 1
            if not dry_run:
                row.signature = new_sig
                updated += 1
    return {"would_change": would_change, "updated": updated, "skipped": skipped}


@router.post("/manifest/trust-current-state")
async def trust_current_state(
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    target = str(payload.get("target", "")).strip().lower()
    confirm = bool(payload.get("confirm", False))

    if target not in _VALID_TARGETS:
        raise HTTPException(
            status_code=422,
            detail=f"target must be one of {sorted(_VALID_TARGETS)}",
        )

    dry_run = not confirm
    result: dict = {"target": target, "confirm": confirm, "dry_run": dry_run}

    if target in ("skills", "all"):
        result["skills"] = await _resign_skills(db, dry_run=dry_run)
    if target in ("widgets", "all"):
        result["widgets"] = await _resign_widgets(db, dry_run=dry_run)

    if not dry_run:
        await db.commit()
        logger.info(
            "manifest_trust_current_state: target=%s result=%s", target, result,
        )
    return result
