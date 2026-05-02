"""Tests for :mod:`app.services.manifest_signing` — the Phase 1
canonical-payload + content-hash + HMAC primitive plus the
``content_hash`` drift detector used by the security audit.

Phase 2 (persisted signature column, verify-on-read at the loader) is
captured in ``docs/tracks/security.md`` and will land in a follow-up
pass.
"""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from app.services.manifest_signing import (
    ManifestDriftFinding,
    canonical_skill_payload,
    canonical_widget_payload,
    compute_content_hash,
    compute_signature,
    detect_skill_drift,
    detect_widget_drift,
    get_manifest_signing_key,
    sign_skill_payload,
    sign_widget_payload,
    verify_signature,
    verify_skill_row,
    verify_widget_row,
)


# -- canonical payload ------------------------------------------------------


def test_skill_payload_stable_across_script_order():
    """Reordering the scripts list must not change the canonical hash —
    otherwise an innocuous re-save would look like tampering."""
    a = canonical_skill_payload(
        "body",
        [
            {"name": "a", "description": "A", "script": "print(1)"},
            {"name": "b", "description": "B", "script": "print(2)"},
        ],
    )
    b = canonical_skill_payload(
        "body",
        [
            {"name": "b", "description": "B", "script": "print(2)"},
            {"name": "a", "description": "A", "script": "print(1)"},
        ],
    )
    assert a == b


def test_skill_payload_changes_when_body_changes():
    a = canonical_skill_payload("hello", [])
    b = canonical_skill_payload("hello world", [])
    assert a != b


def test_skill_payload_changes_when_script_body_changes():
    a = canonical_skill_payload("body", [{"name": "x", "script": "print(1)"}])
    b = canonical_skill_payload("body", [{"name": "x", "script": "print(2)"}])
    assert a != b


def test_skill_payload_changes_when_allowed_tools_change():
    """Allowed_tools is part of the script's security envelope; a body
    diff that adds a tool to the allowlist must move the hash."""
    a = canonical_skill_payload(
        "body",
        [{"name": "x", "script": "print(1)", "allowed_tools": ["a"]}],
    )
    b = canonical_skill_payload(
        "body",
        [{"name": "x", "script": "print(1)", "allowed_tools": ["a", "b"]}],
    )
    assert a != b


def test_widget_payload_changes_when_python_code_changes():
    """Widget python_code is executable — a code-only edit must move
    the canonical hash even if YAML is unchanged."""
    a = canonical_widget_payload("yaml: 1", "print('a')")
    b = canonical_widget_payload("yaml: 1", "print('b')")
    assert a != b


# -- content hash + signature ----------------------------------------------


def test_compute_content_hash_matches_sha256():
    payload = b"hello world"
    assert compute_content_hash(payload) == hashlib.sha256(payload).hexdigest()


def test_compute_signature_requires_key(monkeypatch):
    """Without a configured key, compute_signature raises rather than
    silently returning a hash. Operators must opt in to the primitive."""
    monkeypatch.setattr("app.services.manifest_signing.settings.MANIFEST_SIGNING_KEY", "")
    monkeypatch.setattr("app.services.manifest_signing.settings.ENCRYPTION_KEY", "")
    with pytest.raises(ValueError, match="no key configured"):
        compute_signature(b"payload")


def test_compute_signature_falls_back_to_encryption_key(monkeypatch):
    monkeypatch.setattr("app.services.manifest_signing.settings.MANIFEST_SIGNING_KEY", "")
    monkeypatch.setattr("app.services.manifest_signing.settings.ENCRYPTION_KEY", "fallback-key")
    sig = compute_signature(b"payload")
    assert sig
    assert verify_signature(b"payload", sig)


def test_compute_signature_prefers_explicit_manifest_key(monkeypatch):
    monkeypatch.setattr(
        "app.services.manifest_signing.settings.MANIFEST_SIGNING_KEY", "manifest-only",
    )
    monkeypatch.setattr(
        "app.services.manifest_signing.settings.ENCRYPTION_KEY", "different-data-key",
    )
    sig_with_explicit = compute_signature(b"payload")
    sig_with_data_key = compute_signature(b"payload", key="different-data-key")
    assert sig_with_explicit != sig_with_data_key, (
        "Explicit MANIFEST_SIGNING_KEY must take precedence"
    )


def test_verify_signature_constant_time_pass(monkeypatch):
    monkeypatch.setattr("app.services.manifest_signing.settings.ENCRYPTION_KEY", "k")
    sig = compute_signature(b"payload")
    assert verify_signature(b"payload", sig) is True


def test_verify_signature_rejects_wrong_signature(monkeypatch):
    monkeypatch.setattr("app.services.manifest_signing.settings.ENCRYPTION_KEY", "k")
    assert verify_signature(b"payload", "0" * 64) is False


def test_verify_signature_rejects_empty_signature(monkeypatch):
    monkeypatch.setattr("app.services.manifest_signing.settings.ENCRYPTION_KEY", "k")
    assert verify_signature(b"payload", "") is False


def test_get_manifest_signing_key_prefers_explicit(monkeypatch):
    monkeypatch.setattr(
        "app.services.manifest_signing.settings.MANIFEST_SIGNING_KEY", "explicit",
    )
    monkeypatch.setattr(
        "app.services.manifest_signing.settings.ENCRYPTION_KEY", "fallback",
    )
    assert get_manifest_signing_key() == "explicit"


def test_get_manifest_signing_key_falls_back(monkeypatch):
    monkeypatch.setattr("app.services.manifest_signing.settings.MANIFEST_SIGNING_KEY", "")
    monkeypatch.setattr(
        "app.services.manifest_signing.settings.ENCRYPTION_KEY", "fallback",
    )
    assert get_manifest_signing_key() == "fallback"


# -- drift detection -------------------------------------------------------


def _skill_row(skill_id: str, content: str, stored_hash: str | None = None, scripts=None):
    return SimpleNamespace(
        id=skill_id,
        name=skill_id,
        content=content,
        scripts=scripts or [],
        content_hash=stored_hash if stored_hash is not None else hashlib.sha256(content.encode()).hexdigest(),
    )


def _widget_row(widget_id: str, yaml_template: str, stored_hash: str | None = None, python_code: str | None = None):
    return SimpleNamespace(
        id=widget_id,
        tool_name=widget_id,
        name=widget_id,
        yaml_template=yaml_template,
        python_code=python_code,
        content_hash=stored_hash if stored_hash is not None else hashlib.sha256(yaml_template.encode()).hexdigest(),
    )


def test_skill_drift_returns_empty_when_clean():
    row = _skill_row("a", "body")
    assert detect_skill_drift([row]) == []


def test_skill_drift_flags_mismatched_hash():
    row = _skill_row("a", "real body", stored_hash="0" * 64)
    findings = detect_skill_drift([row])
    assert len(findings) == 1
    f = findings[0]
    assert isinstance(f, ManifestDriftFinding)
    assert f.kind == "skill"
    assert f.target_id == "a"
    assert f.stored_hash == "0" * 64
    assert f.recomputed_hash == hashlib.sha256(b"real body").hexdigest()


def test_skill_drift_skips_rows_with_empty_stored_hash():
    """A skill that was never hashed at all (legacy seed) is not drift —
    drift means hash WAS recorded and no longer matches. Empty stored
    hash is a different finding (Phase 2 will surface it as `unsigned`)."""
    row = _skill_row("a", "body", stored_hash="")
    assert detect_skill_drift([row]) == []


def test_widget_drift_returns_empty_when_clean():
    row = _widget_row("w1", "yaml: 1")
    assert detect_widget_drift([row]) == []


def test_widget_drift_flags_mismatched_hash():
    row = _widget_row("w1", "yaml: real", stored_hash="0" * 64)
    findings = detect_widget_drift([row])
    assert len(findings) == 1
    assert findings[0].kind == "widget_template_package"
    assert findings[0].target_id == "w1"


def test_widget_drift_uses_yaml_only_for_phase_one_match():
    """Phase 1 mirrors the existing seeder hash shape (yaml only) so a
    change to ``python_code`` does NOT register as drift in Phase 1.
    Phase 2 will switch to the canonical payload that covers code too."""
    row = _widget_row("w1", "yaml: 1", python_code="anything")
    assert detect_widget_drift([row]) == []


# -- Phase 2: sign_*_payload helpers + verify_*_row -----------------------


def test_sign_skill_payload_returns_signature_when_key_present(monkeypatch):
    monkeypatch.setattr("app.services.manifest_signing.settings.ENCRYPTION_KEY", "k")
    sig = sign_skill_payload("body", [])
    assert sig
    # Signature is HMAC over canonical payload, NOT sha256(content).
    assert sig != hashlib.sha256(b"body").hexdigest()


def test_sign_skill_payload_returns_none_when_no_key(monkeypatch):
    """Seed paths run before key configuration in dev — they must
    persist NULL rather than raising. Audit surfaces it as unsigned."""
    monkeypatch.setattr("app.services.manifest_signing.settings.MANIFEST_SIGNING_KEY", "")
    monkeypatch.setattr("app.services.manifest_signing.settings.ENCRYPTION_KEY", "")
    assert sign_skill_payload("body", []) is None


def test_sign_widget_payload_covers_python_code(monkeypatch):
    """A widget python_code edit must move the signature, even if YAML
    is unchanged — Phase 1 hashed yaml only, so this is a Phase 2 win."""
    monkeypatch.setattr("app.services.manifest_signing.settings.ENCRYPTION_KEY", "k")
    sig_a = sign_widget_payload("yaml: 1", "print('a')")
    sig_b = sign_widget_payload("yaml: 1", "print('b')")
    assert sig_a != sig_b


def test_verify_skill_row_passes_when_signature_matches(monkeypatch):
    monkeypatch.setattr("app.services.manifest_signing.settings.ENCRYPTION_KEY", "k")
    row = SimpleNamespace(
        content="body",
        scripts=[],
        signature=sign_skill_payload("body", []),
    )
    assert verify_skill_row(row) is True


def test_verify_skill_row_passes_when_signature_is_null():
    """NULL signature = Phase-1 unsigned. Drift-only surface, not
    fail-closed — verify_skill_row returns True."""
    row = SimpleNamespace(content="body", scripts=[], signature=None)
    assert verify_skill_row(row) is True


def test_verify_skill_row_fails_when_content_tampered(monkeypatch):
    """Persisted signature stays put while content gets edited under
    the writer — verify_skill_row catches the mismatch."""
    monkeypatch.setattr("app.services.manifest_signing.settings.ENCRYPTION_KEY", "k")
    sig = sign_skill_payload("original", [])
    row = SimpleNamespace(content="tampered", scripts=[], signature=sig)
    assert verify_skill_row(row) is False


def test_verify_widget_row_fails_when_python_code_tampered(monkeypatch):
    monkeypatch.setattr("app.services.manifest_signing.settings.ENCRYPTION_KEY", "k")
    sig = sign_widget_payload("yaml: 1", "print('safe')")
    row = SimpleNamespace(
        yaml_template="yaml: 1",
        python_code="print('exfil')",
        signature=sig,
    )
    assert verify_widget_row(row) is False


def test_verify_skill_row_treats_missing_key_as_unverifiable(monkeypatch):
    """If MANIFEST_SIGNING_KEY rotates and is no longer configured,
    verify_*_row returns True (un-verifiable rather than tampered) —
    operator must restore the key or run trust-current-state."""
    monkeypatch.setattr("app.services.manifest_signing.settings.ENCRYPTION_KEY", "k")
    sig = sign_skill_payload("body", [])
    monkeypatch.setattr("app.services.manifest_signing.settings.MANIFEST_SIGNING_KEY", "")
    monkeypatch.setattr("app.services.manifest_signing.settings.ENCRYPTION_KEY", "")
    row = SimpleNamespace(content="body", scripts=[], signature=sig)
    assert verify_skill_row(row) is True
