"""Tests for ``POST /api/v1/admin/manifest/trust-current-state`` —
the operator recovery action that re-signs every skill / widget row
after a legitimate body change or key rotation.

We exercise the resign helpers directly with a stub DB session to keep
this fast and not require a Postgres harness.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.routers.api_v1_admin import manifest_trust
from app.services import manifest_signing as ms


@pytest.fixture
def signing_key(monkeypatch):
    monkeypatch.setattr(
        "app.services.manifest_signing.settings.MANIFEST_SIGNING_KEY", "phase2-key"
    )
    monkeypatch.setattr(
        "app.services.manifest_signing.settings.ENCRYPTION_KEY", "fallback"
    )


class _StubResult:
    def __init__(self, rows: list):
        self._rows = rows

    def scalars(self):
        return _StubScalars(self._rows)


class _StubScalars:
    def __init__(self, rows: list):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _StubDB:
    def __init__(self, skill_rows=None, widget_rows=None):
        self._skill_rows = skill_rows or []
        self._widget_rows = widget_rows or []
        self.committed = False

    async def execute(self, stmt):
        text = str(stmt).lower()
        if "from skills" in text:
            return _StubResult(self._skill_rows)
        return _StubResult(self._widget_rows)

    async def commit(self):
        self.committed = True


def _skill(content="body", scripts=None, signature=None):
    return SimpleNamespace(
        content=content, scripts=scripts or [], signature=signature,
    )


def _widget(yaml="yaml: 1", python=None, signature=None):
    return SimpleNamespace(
        yaml_template=yaml, python_code=python, signature=signature,
    )


# -- _resign_skills -------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_does_not_mutate_rows(signing_key):
    """Without confirm, signatures must remain untouched and commit
    must not fire. Otherwise the operator can't preview the effect
    before pulling the trigger."""
    rows = [_skill(signature=None), _skill(signature="bogus")]
    db = _StubDB(skill_rows=rows)
    result = await manifest_trust._resign_skills(db, dry_run=True)
    assert result["would_change"] == 2
    assert result["updated"] == 0
    assert all(r.signature in (None, "bogus") for r in rows)


@pytest.mark.asyncio
async def test_resign_unsigned_row(signing_key):
    rows = [_skill(content="body", signature=None)]
    db = _StubDB(skill_rows=rows)
    result = await manifest_trust._resign_skills(db, dry_run=False)
    assert result["updated"] == 1
    assert rows[0].signature  # populated
    assert ms.verify_skill_row(rows[0])


@pytest.mark.asyncio
async def test_resign_recovers_tampered_row(signing_key):
    """A row whose signature stayed put while content changed gets
    re-signed against the *current* body — that's the recovery path."""
    rows = [_skill(content="real body", signature="stale-sig")]
    db = _StubDB(skill_rows=rows)
    result = await manifest_trust._resign_skills(db, dry_run=False)
    assert result["updated"] == 1
    assert rows[0].signature != "stale-sig"
    assert ms.verify_skill_row(rows[0])


@pytest.mark.asyncio
async def test_resign_skips_clean_signed_rows(signing_key):
    sig = ms.sign_skill_payload("body", [])
    rows = [_skill(content="body", signature=sig)]
    db = _StubDB(skill_rows=rows)
    result = await manifest_trust._resign_skills(db, dry_run=False)
    assert result["skipped"] == 1
    assert result["updated"] == 0


# -- _resign_widgets ------------------------------------------------------


@pytest.mark.asyncio
async def test_resign_widgets_covers_python_code(signing_key):
    rows = [_widget(yaml="yaml: 1", python="code", signature=None)]
    db = _StubDB(widget_rows=rows)
    result = await manifest_trust._resign_widgets(db, dry_run=False)
    assert result["updated"] == 1
    assert ms.verify_widget_row(rows[0])


# -- Endpoint shape -------------------------------------------------------


@pytest.mark.asyncio
async def test_endpoint_rejects_invalid_target(signing_key):
    from fastapi import HTTPException

    db = _StubDB()
    with pytest.raises(HTTPException) as exc_info:
        await manifest_trust.trust_current_state(
            payload={"target": "everything"}, db=db, _auth=None,
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_endpoint_dry_run_without_confirm(signing_key):
    """Without confirm=true the endpoint must NOT commit and must NOT
    mutate rows — it returns the would_change count for preview."""
    rows = [_skill(content="body", signature=None)]
    db = _StubDB(skill_rows=rows, widget_rows=[])
    result = await manifest_trust.trust_current_state(
        payload={"target": "skills"}, db=db, _auth=None,
    )
    assert result["dry_run"] is True
    assert result["confirm"] is False
    assert result["skills"]["would_change"] == 1
    assert result["skills"]["updated"] == 0
    assert db.committed is False
    assert rows[0].signature is None  # untouched


@pytest.mark.asyncio
async def test_endpoint_commits_when_confirmed(signing_key):
    rows = [_skill(content="body", signature=None)]
    db = _StubDB(skill_rows=rows, widget_rows=[])
    result = await manifest_trust.trust_current_state(
        payload={"target": "skills", "confirm": True}, db=db, _auth=None,
    )
    assert result["dry_run"] is False
    assert result["skills"]["updated"] == 1
    assert db.committed is True
    assert rows[0].signature is not None


@pytest.mark.asyncio
async def test_endpoint_target_all_covers_both_tables(signing_key):
    skill_rows = [_skill(content="body", signature=None)]
    widget_rows = [_widget(yaml="y", signature=None)]
    db = _StubDB(skill_rows=skill_rows, widget_rows=widget_rows)
    result = await manifest_trust.trust_current_state(
        payload={"target": "all", "confirm": True}, db=db, _auth=None,
    )
    assert result["skills"]["updated"] == 1
    assert result["widgets"]["updated"] == 1
