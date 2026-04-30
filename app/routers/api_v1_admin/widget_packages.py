"""Widget template packages admin API.

Endpoints: list/detail CRUD, fork, activate, preview, validate. Seed
packages are read-only — edits must fork first.

Trust model: saved Python code executes unsandboxed in the server
process. Admin-scoped only — same trust level as editing integration.yaml.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WidgetTemplatePackage
from app.dependencies import get_db, require_scopes
from app.services.widget_package_loader import (
    discard_preview_module,
    invalidate as invalidate_package_module,
    load_preview_module,
    rewrite_refs_for_preview,
)
from app.services.widget_package_validation import validate_package
from app.services.widget_preview import (
    PreviewEnvelope,
    PreviewOut,
    ValidationIssueOut,
    preview_active_widget_for_tool,
    render_preview_envelope,
)
from app.services.widget_templates import (
    _pick_fallback_seed,
    _substitute,
    _substitute_string,
    reload_tool,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class WidgetPackageOut(BaseModel):
    id: UUID
    tool_name: str
    name: str
    description: Optional[str] = None
    source: str
    is_readonly: bool
    is_active: bool
    is_orphaned: bool
    is_invalid: bool
    invalid_reason: Optional[str] = None
    source_file: Optional[str] = None
    source_integration: Optional[str] = None
    group_kind: Optional[str] = None
    group_ref: Optional[str] = None
    version: int
    yaml_template: Optional[str] = None
    python_code: Optional[str] = None
    has_python_code: bool = False
    sample_payload: Optional[dict] = None
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class WidgetPackageListOut(BaseModel):
    id: UUID
    tool_name: str
    name: str
    description: Optional[str] = None
    source: str
    is_readonly: bool
    is_active: bool
    is_orphaned: bool
    is_invalid: bool
    has_python_code: bool
    source_integration: Optional[str] = None
    group_kind: Optional[str] = None
    group_ref: Optional[str] = None
    version: int
    updated_at: datetime


class WidgetPackageCreate(BaseModel):
    tool_name: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: Optional[str] = None
    yaml_template: str = Field(min_length=1)
    python_code: Optional[str] = None
    sample_payload: Optional[dict] = None


class WidgetPackageUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    yaml_template: Optional[str] = None
    python_code: Optional[str] = None
    sample_payload: Optional[dict] = None


class WidgetPackageForkIn(BaseModel):
    name: Optional[str] = None


class ValidateIn(BaseModel):
    yaml_template: str
    python_code: Optional[str] = None


class ValidateOut(BaseModel):
    ok: bool
    errors: list[ValidationIssueOut] = []
    warnings: list[ValidationIssueOut] = []


class PreviewIn(BaseModel):
    sample_payload: Optional[dict] = None
    widget_config: Optional[dict] = None
    # Optional overrides for unsaved drafts.
    yaml_template: Optional[str] = None
    python_code: Optional[str] = None


class PreviewInlineIn(BaseModel):
    """Package-less template preview. Used by the widget developer panel."""

    yaml_template: str = Field(min_length=1)
    python_code: Optional[str] = None
    sample_payload: Optional[dict] = None
    widget_config: Optional[dict] = None
    tool_name: Optional[str] = None
    # Sandbox-selected identity. Echoed on the returned envelope so HTML
    # widget previews can mint widget-auth tokens for the chosen bot.
    source_bot_id: Optional[str] = None
    source_channel_id: Optional[str] = None


class PreviewForToolIn(BaseModel):
    """Render the active widget template for a given tool against a payload."""

    tool_name: str = Field(min_length=1)
    sample_payload: Optional[dict] = None
    widget_config: Optional[dict] = None
    source_bot_id: Optional[str] = None
    source_channel_id: Optional[str] = None


class AuthoringCheckIn(BaseModel):
    yaml_template: str = Field(min_length=1)
    python_code: Optional[str] = None
    sample_payload: Optional[dict] = None
    widget_config: Optional[dict] = None
    tool_name: Optional[str] = None
    source_bot_id: Optional[str] = None
    source_channel_id: Optional[str] = None
    include_runtime: bool = False
    include_screenshot: bool = False


class HtmlAuthoringCheckIn(BaseModel):
    library_ref: Optional[str] = None
    html: Optional[str] = None
    path: Optional[str] = None
    js: str = ""
    css: str = ""
    display_label: str = ""
    display_mode: str = "inline"
    runtime: Optional[str] = None
    extra_csp: Optional[dict] = None
    include_runtime: bool = False
    include_screenshot: bool = False


class GenericRenderIn(BaseModel):
    """Auto-render an arbitrary tool result as a dashboard card.

    Used when no widget template exists for the tool — turns raw JSON into a
    component tree so the sandbox can offer a single-click pin. Reserved
    ``config`` hook is unused in v1.
    """

    tool_name: str = Field(min_length=1)
    raw_result: Any = None
    config: Optional[dict] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_body(yaml_text: str, python_code: str | None) -> str:
    combined = f"{yaml_text}\n---\n{python_code or ''}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def _extract_grouping(yaml_template: str | None) -> tuple[str | None, str | None]:
    if not yaml_template or not yaml_template.strip():
        return (None, None)
    try:
        parsed = yaml.safe_load(yaml_template) or {}
    except yaml.YAMLError:
        return (None, None)
    if not isinstance(parsed, dict):
        return (None, None)
    suite = parsed.get("suite")
    if isinstance(suite, str) and suite.strip():
        return ("suite", suite.strip())
    package = parsed.get("package")
    if isinstance(package, str) and package.strip():
        return ("package", package.strip())
    return (None, None)


def _to_out(row: WidgetTemplatePackage, *, include_bodies: bool = True) -> WidgetPackageOut:
    group_kind, group_ref = _extract_grouping(row.yaml_template)
    return WidgetPackageOut(
        id=row.id,
        tool_name=row.tool_name,
        name=row.name,
        description=row.description,
        source=row.source,
        is_readonly=row.is_readonly,
        is_active=row.is_active,
        is_orphaned=row.is_orphaned,
        is_invalid=row.is_invalid,
        invalid_reason=row.invalid_reason,
        source_file=row.source_file,
        source_integration=row.source_integration,
        group_kind=group_kind,
        group_ref=group_ref,
        version=row.version,
        yaml_template=row.yaml_template if include_bodies else None,
        python_code=row.python_code if include_bodies else None,
        has_python_code=bool(row.python_code and row.python_code.strip()),
        sample_payload=row.sample_payload if include_bodies else None,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_list_out(row: WidgetTemplatePackage) -> WidgetPackageListOut:
    group_kind, group_ref = _extract_grouping(row.yaml_template)
    return WidgetPackageListOut(
        id=row.id,
        tool_name=row.tool_name,
        name=row.name,
        description=row.description,
        source=row.source,
        is_readonly=row.is_readonly,
        is_active=row.is_active,
        is_orphaned=row.is_orphaned,
        is_invalid=row.is_invalid,
        has_python_code=bool(row.python_code and row.python_code.strip()),
        source_integration=row.source_integration,
        group_kind=group_kind,
        group_ref=group_ref,
        version=row.version,
        updated_at=row.updated_at,
    )


def _issue_out(issue) -> ValidationIssueOut:
    return ValidationIssueOut(
        phase=issue.phase,
        message=issue.message,
        line=issue.line,
        severity=issue.severity,
    )


async def _get_or_404(db: AsyncSession, pkg_id: UUID) -> WidgetTemplatePackage:
    row = await db.get(WidgetTemplatePackage, pkg_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Widget package not found")
    return row


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/widget-packages", response_model=list[WidgetPackageListOut])
async def list_widget_packages(
    tool_name: Optional[str] = Query(None),
    source: Optional[str] = Query(None, pattern="^(seed|user)$"),
    include_orphaned: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("admin")),
):
    stmt = select(WidgetTemplatePackage).order_by(
        WidgetTemplatePackage.tool_name,
        WidgetTemplatePackage.source.desc(),  # user before seed
        WidgetTemplatePackage.name,
    )
    if tool_name:
        stmt = stmt.where(WidgetTemplatePackage.tool_name == tool_name)
    if source:
        stmt = stmt.where(WidgetTemplatePackage.source == source)
    if not include_orphaned:
        stmt = stmt.where(WidgetTemplatePackage.is_orphaned.is_(False))

    rows = (await db.execute(stmt)).scalars().all()
    return [_to_list_out(r) for r in rows]


@router.get("/widget-packages/{pkg_id}", response_model=WidgetPackageOut)
async def get_widget_package(
    pkg_id: UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("admin")),
):
    row = await _get_or_404(db, pkg_id)
    return _to_out(row)


@router.post(
    "/widget-packages",
    response_model=WidgetPackageOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_widget_package(
    body: WidgetPackageCreate,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("admin")),
):
    result = validate_package(body.yaml_template, body.python_code)
    if not result.ok:
        raise HTTPException(
            status_code=422,
            detail={
                "errors": [_issue_out(e).model_dump() for e in result.errors],
                "warnings": [_issue_out(w).model_dump() for w in result.warnings],
            },
        )

    row = WidgetTemplatePackage(
        tool_name=body.tool_name,
        name=body.name,
        description=body.description,
        yaml_template=body.yaml_template,
        python_code=body.python_code,
        source="user",
        is_readonly=False,
        is_active=False,
        is_orphaned=False,
        content_hash=_hash_body(body.yaml_template, body.python_code),
        sample_payload=body.sample_payload,
        version=1,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.put("/widget-packages/{pkg_id}", response_model=WidgetPackageOut)
async def update_widget_package(
    pkg_id: UUID,
    body: WidgetPackageUpdate,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("admin")),
):
    row = await _get_or_404(db, pkg_id)
    if row.is_readonly:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Seed packages are read-only — fork first.",
                "fork_url": f"/api/v1/admin/widget-packages/{row.id}/fork",
            },
        )

    new_yaml = body.yaml_template if body.yaml_template is not None else row.yaml_template
    new_python = body.python_code if body.python_code is not None else row.python_code

    body_changed = (
        body.yaml_template is not None and body.yaml_template != row.yaml_template
    ) or (
        body.python_code is not None and body.python_code != row.python_code
    )

    if body_changed:
        result = validate_package(new_yaml, new_python)
        if not result.ok:
            raise HTTPException(
                status_code=422,
                detail={
                    "errors": [_issue_out(e).model_dump() for e in result.errors],
                    "warnings": [_issue_out(w).model_dump() for w in result.warnings],
                },
            )

    if body.name is not None:
        row.name = body.name
    if body.description is not None:
        row.description = body.description
    if body.sample_payload is not None:
        row.sample_payload = body.sample_payload
    if body_changed:
        row.yaml_template = new_yaml
        row.python_code = new_python
        row.content_hash = _hash_body(new_yaml, new_python)
        row.version = (row.version or 1) + 1
        row.is_invalid = False
        row.invalid_reason = None
        invalidate_package_module(row.id)

    row.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(row)

    if row.is_active:
        await reload_tool(row.tool_name)

    return _to_out(row)


@router.post(
    "/widget-packages/{pkg_id}/fork",
    response_model=WidgetPackageOut,
    status_code=status.HTTP_201_CREATED,
)
async def fork_widget_package(
    pkg_id: UUID,
    body: WidgetPackageForkIn,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("admin")),
):
    src = await _get_or_404(db, pkg_id)
    new_name = (body.name or "").strip() or f"{src.name} (copy)"
    row = WidgetTemplatePackage(
        tool_name=src.tool_name,
        name=new_name,
        description=src.description,
        yaml_template=src.yaml_template,
        python_code=src.python_code,
        source="user",
        is_readonly=False,
        is_active=False,
        is_orphaned=False,
        content_hash=src.content_hash,
        sample_payload=copy.deepcopy(src.sample_payload) if src.sample_payload else None,
        version=1,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.delete(
    "/widget-packages/{pkg_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_widget_package(
    pkg_id: UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("admin")),
):
    row = await _get_or_404(db, pkg_id)
    if row.is_readonly:
        raise HTTPException(
            status_code=409, detail="Seed packages are read-only and cannot be deleted.",
        )

    tool_name = row.tool_name
    was_active = row.is_active

    # Flip active off first so the partial unique index allows the replacement activate.
    if was_active:
        row.is_active = False
        await db.flush()
        fallback = await _pick_fallback_seed(db, tool_name)
        if fallback is not None:
            fallback.is_active = True

    await db.delete(row)
    await db.commit()
    invalidate_package_module(pkg_id)

    if was_active:
        await reload_tool(tool_name)

    return None


@router.post("/widget-packages/{pkg_id}/activate", response_model=WidgetPackageOut)
async def activate_widget_package(
    pkg_id: UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("admin")),
):
    row = await _get_or_404(db, pkg_id)
    if row.is_invalid:
        raise HTTPException(
            status_code=409,
            detail="Package is invalid — fix YAML/Python errors before activating.",
        )
    if row.is_orphaned:
        raise HTTPException(
            status_code=409,
            detail="Package is orphaned — its source is no longer present.",
        )

    stmt = select(WidgetTemplatePackage).where(
        WidgetTemplatePackage.tool_name == row.tool_name,
        WidgetTemplatePackage.is_active.is_(True),
        WidgetTemplatePackage.id != row.id,
    )
    current = (await db.execute(stmt)).scalars().all()
    for other in current:
        other.is_active = False
    await db.flush()
    row.is_active = True

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="Another activation raced — retry.",
        )
    await db.refresh(row)

    await reload_tool(row.tool_name)
    return _to_out(row)


@router.post("/widget-packages/validate", response_model=ValidateOut)
async def validate_widget_package(
    body: ValidateIn,
    _auth: str = Depends(require_scopes("admin")),
):
    result = validate_package(body.yaml_template, body.python_code)
    return ValidateOut(
        ok=result.ok,
        errors=[_issue_out(e) for e in result.errors],
        warnings=[_issue_out(w) for w in result.warnings],
    )


@router.post("/widget-packages/preview-for-tool", response_model=PreviewOut)
async def preview_widget_for_tool(
    body: PreviewForToolIn,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("admin")),
):
    return await preview_active_widget_for_tool(
        db,
        tool_name=body.tool_name,
        sample_payload=body.sample_payload,
        widget_config=body.widget_config,
        source_bot_id=body.source_bot_id,
        source_channel_id=body.source_channel_id,
    )


@router.post("/widget-packages/preview-inline", response_model=PreviewOut)
async def preview_widget_inline(
    body: PreviewInlineIn,
    _auth: str = Depends(require_scopes("admin")),
):
    """Render a widget envelope from an ad-hoc YAML template + sample payload.

    Unlike ``/widget-packages/{pkg_id}/preview`` this does not require a
    saved package — used by the widget developer panel to preview tool
    output against an arbitrary template (or the active template for a
    given tool_name when no YAML is supplied by the caller).
    """
    result = validate_package(body.yaml_template, body.python_code)
    if not result.ok:
        return PreviewOut(
            ok=False,
            errors=[_issue_out(e) for e in result.errors],
        )

    widget_def = result.template or yaml.safe_load(body.yaml_template) or {}
    preview_mod_name: str | None = None
    try:
        if body.python_code and body.python_code.strip():
            _, preview_mod_name = load_preview_module(body.python_code)
        rewritten = rewrite_refs_for_preview(widget_def, preview_mod_name)
        envelope = render_preview_envelope(
            rewritten,
            tool_name=body.tool_name or "",
            sample_payload=body.sample_payload or {},
            widget_config=body.widget_config,
            source_bot_id=body.source_bot_id,
            source_channel_id=body.source_channel_id,
        )
    except Exception as exc:
        logger.warning("Inline preview render failed: %s", exc, exc_info=True)
        return PreviewOut(
            ok=False,
            errors=[ValidationIssueOut(phase="python", message=str(exc))],
        )
    finally:
        discard_preview_module(preview_mod_name)

    return PreviewOut(ok=True, envelope=envelope)


@router.post("/widget-packages/authoring-check")
async def widget_authoring_check(
    body: AuthoringCheckIn,
    _auth: str = Depends(require_scopes("admin")),
):
    from app.services.widget_authoring_check import run_widget_authoring_check

    return await run_widget_authoring_check(
        yaml_template=body.yaml_template,
        python_code=body.python_code,
        sample_payload=body.sample_payload,
        widget_config=body.widget_config,
        tool_name=body.tool_name,
        source_bot_id=body.source_bot_id,
        source_channel_id=body.source_channel_id,
        include_runtime=body.include_runtime,
        include_screenshot=body.include_screenshot,
    )


@router.post("/widget-packages/html-authoring-check")
async def html_widget_authoring_check(
    body: HtmlAuthoringCheckIn,
    _auth: str = Depends(require_scopes("admin")),
):
    from app.services.html_widget_authoring_check import run_html_widget_authoring_check

    return await run_html_widget_authoring_check(
        html=body.html,
        path=body.path,
        library_ref=body.library_ref,
        js=body.js,
        css=body.css,
        display_label=body.display_label,
        extra_csp=body.extra_csp,
        display_mode=body.display_mode,
        runtime=body.runtime,
        include_runtime=body.include_runtime,
        include_screenshot=body.include_screenshot,
    )


@router.post("/widget-packages/generic-render", response_model=PreviewOut)
async def generic_render(
    body: GenericRenderIn,
    _auth: str = Depends(require_scopes("admin")),
):
    """Auto-render an arbitrary tool result as a generic dashboard card.

    Untemplated tools have no bespoke widget YAML; this endpoint turns their
    raw JSON into a component-tree envelope so users can pin the result as a
    static card from ``/widgets/dev#tools``. Static snapshot only — the
    returned envelope is never refreshable.
    """
    from app.services.generic_widget_view import render_generic_view

    try:
        env = render_generic_view(
            body.raw_result,
            tool_name=body.tool_name,
            config=body.config,
        )
    except Exception as exc:
        logger.warning(
            "generic-render failed for %s: %s", body.tool_name, exc, exc_info=True,
        )
        return PreviewOut(
            ok=False,
            errors=[ValidationIssueOut(phase="render", message=str(exc))],
        )

    envelope = PreviewEnvelope(
        content_type=env.content_type,
        body=env.body or "",
        display=env.display,
        display_label=env.display_label,
        refreshable=env.refreshable,
        refresh_interval_seconds=env.refresh_interval_seconds,
    )
    return PreviewOut(ok=True, envelope=envelope)


@router.post("/widget-packages/{pkg_id}/preview", response_model=PreviewOut)
async def preview_widget_package(
    pkg_id: UUID,
    body: PreviewIn,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("admin")),
):
    row = await _get_or_404(db, pkg_id)
    yaml_text = body.yaml_template if body.yaml_template is not None else row.yaml_template
    python_code = body.python_code if body.python_code is not None else row.python_code
    sample_payload = body.sample_payload if body.sample_payload is not None else row.sample_payload

    result = validate_package(yaml_text, python_code)
    if not result.ok:
        return PreviewOut(
            ok=False,
            errors=[_issue_out(e) for e in result.errors],
        )

    widget_def = result.template or yaml.safe_load(yaml_text) or {}
    preview_mod_name: str | None = None
    try:
        if python_code and python_code.strip():
            _, preview_mod_name = load_preview_module(python_code)
        rewritten = rewrite_refs_for_preview(widget_def, preview_mod_name)
        envelope = render_preview_envelope(
            rewritten,
            tool_name=row.tool_name,
            sample_payload=sample_payload or {},
            widget_config=body.widget_config,
        )
    except Exception as exc:
        logger.warning("Preview render failed for %s: %s", pkg_id, exc, exc_info=True)
        return PreviewOut(
            ok=False,
            errors=[ValidationIssueOut(phase="python", message=str(exc))],
        )
    finally:
        discard_preview_module(preview_mod_name)

    return PreviewOut(ok=True, envelope=envelope)
