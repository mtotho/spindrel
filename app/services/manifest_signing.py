"""Manifest signing for skills + widget template packages — Phase 1.

Phase 1 (this module today): canonical-payload + content-hash + HMAC
primitive plus a read-only audit helper that surfaces ``content_hash``
drift between the live row and a freshly recomputed hash. Drift means
some writer mutated ``content`` / ``yaml_template`` without updating
``content_hash`` (a writer bug or, less benignly, direct DB tampering
that bypassed the writer entirely).

Phase 2 (follow-up, captured in `docs/tracks/security.md`):
- Persist a `signature` field per row, written via ``compute_signature``.
- Verify-on-read at the loader entrypoints (`app/agent/skills.py`,
  `app/services/widget_packages_seeder.py`) — refuse to load tampered
  rows from autonomous-origin paths; surface in chat for interactive.
- Operator "trust current state" admin action that recomputes signatures.
- UI badge of signed/unsigned/tampered next to each skill / widget.

Design choices:
- Canonical payload is a stable byte-serialization of the user-visible
  body fields (skill: ``content``; widget: ``yaml_template`` plus
  ``python_code`` if present). Metadata fields like timestamps and
  ``surface_count`` are excluded — they change with no integrity loss.
- Content hash is plain SHA-256 hex (matches the existing
  ``content_hash`` column shape in both ``skills`` and
  ``widget_template_packages``). Phase 1 is a drift detector — it does
  not need a key.
- Signature is HMAC-SHA256 over the canonical payload. Hex encoded.
  Key is ``MANIFEST_SIGNING_KEY`` if set, else falls back to
  ``ENCRYPTION_KEY``. Empty key raises — the primitive is not callable
  without operator opt-in.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

from app.config import settings

__all__ = [
    "ManifestDriftFinding",
    "canonical_skill_payload",
    "canonical_widget_payload",
    "compute_content_hash",
    "compute_signature",
    "get_manifest_signing_key",
    "verify_signature",
]


def get_manifest_signing_key() -> str:
    """Return the configured manifest signing key.

    Prefers ``MANIFEST_SIGNING_KEY`` so admins can rotate the manifest
    key without rotating the live data-encryption key. Falls back to
    ``ENCRYPTION_KEY`` so existing deployments don't need a second key
    to use the primitive.
    """
    explicit = getattr(settings, "MANIFEST_SIGNING_KEY", "") or ""
    if explicit:
        return explicit
    return getattr(settings, "ENCRYPTION_KEY", "") or ""


def canonical_skill_payload(content: str, scripts: list[dict] | None) -> bytes:
    """Stable byte-serialization of a Skill row.

    Includes ``content`` (markdown body) and the script bodies that affect
    runtime behavior. Excludes timestamps, ``surface_count``, and
    embedding metadata — those rotate without changing what the agent
    will do.
    """
    parts: list[str] = []
    parts.append("content:")
    parts.append(content or "")
    parts.append("\nscripts:")
    for script in sorted(scripts or [], key=lambda s: s.get("name", "")):
        if not isinstance(script, dict):
            continue
        parts.append("\n  - name=")
        parts.append(str(script.get("name", "")))
        parts.append("\n    description=")
        parts.append(str(script.get("description", "")))
        parts.append("\n    timeout_s=")
        parts.append(str(script.get("timeout_s", "")))
        parts.append("\n    allowed_tools=")
        allowed = script.get("allowed_tools")
        if isinstance(allowed, list):
            parts.append(",".join(sorted(str(t) for t in allowed)))
        else:
            parts.append("")
        parts.append("\n    body=")
        parts.append(str(script.get("script", "")))
    return "".join(parts).encode("utf-8")


def canonical_widget_payload(yaml_template: str, python_code: str | None) -> bytes:
    """Stable byte-serialization of a WidgetTemplatePackage row.

    Includes the YAML template body and the optional Python code that
    will execute on widget runs.
    """
    parts: list[str] = []
    parts.append("yaml_template:\n")
    parts.append(yaml_template or "")
    parts.append("\npython_code:\n")
    parts.append(python_code or "")
    return "".join(parts).encode("utf-8")


def compute_content_hash(payload: bytes) -> str:
    """Plain SHA-256 hex digest of a canonical payload — matches the
    ``content_hash`` column shape used by both ``skills`` and
    ``widget_template_packages`` writers."""
    return hashlib.sha256(payload).hexdigest()


def compute_signature(payload: bytes, *, key: str | None = None) -> str:
    """HMAC-SHA256 hex digest of a canonical payload.

    Phase 2 will write this to a per-row ``signature`` column and admin
    actions will sign / re-sign known-good rows.
    """
    effective = key if key is not None else get_manifest_signing_key()
    if not effective:
        raise ValueError(
            "manifest_signing: no key configured. Set MANIFEST_SIGNING_KEY or "
            "ENCRYPTION_KEY before computing manifest signatures."
        )
    return hmac.new(
        effective.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()


def verify_signature(payload: bytes, signature: str, *, key: str | None = None) -> bool:
    """Constant-time HMAC verification."""
    if not signature:
        return False
    expected = compute_signature(payload, key=key)
    return hmac.compare_digest(expected, signature)


@dataclass(frozen=True)
class ManifestDriftFinding:
    """One row whose stored ``content_hash`` no longer matches its body.

    A drift finding means the body (skill ``content`` / widget
    ``yaml_template``) was modified without updating ``content_hash``.
    That is either a writer bug (forgot to recompute) or direct DB
    tampering by something that bypassed the writer.
    """

    kind: str  # "skill" or "widget_template_package"
    target_id: str
    stored_hash: str
    recomputed_hash: str
    name: str | None = None


def detect_skill_drift(rows: list[Any]) -> list[ManifestDriftFinding]:
    """Recompute the canonical hash for each Skill row and report drift.

    Pass in already-loaded rows so the caller controls the DB session.
    """
    findings: list[ManifestDriftFinding] = []
    for row in rows:
        content = getattr(row, "content", "") or ""
        scripts = getattr(row, "scripts", None) or []
        payload = canonical_skill_payload(content, scripts)
        recomputed = compute_content_hash(payload)
        # The existing column is sha256(content_only). For Phase 1 we
        # mirror that shape so drift reflects current behavior; the
        # canonical-payload hash above is reserved for Phase 2 when we
        # add a separate ``manifest_hash`` / ``signature`` column.
        plain = hashlib.sha256((content or "").encode("utf-8")).hexdigest()
        stored = getattr(row, "content_hash", "") or ""
        if stored and stored != plain:
            findings.append(
                ManifestDriftFinding(
                    kind="skill",
                    target_id=str(getattr(row, "id", "")),
                    stored_hash=stored,
                    recomputed_hash=plain,
                    name=getattr(row, "name", None),
                )
            )
        # Note: ``recomputed`` is intentionally unused in Phase 1 — it
        # will become the source of truth in Phase 2.
        _ = recomputed
    return findings


def detect_widget_drift(rows: list[Any]) -> list[ManifestDriftFinding]:
    """Recompute the canonical hash for each WidgetTemplatePackage row
    and report drift relative to the stored ``content_hash``."""
    findings: list[ManifestDriftFinding] = []
    for row in rows:
        yaml_template = getattr(row, "yaml_template", "") or ""
        # Mirror the widget seeder's existing hash shape (sha256 over
        # yaml body only — python_code is not yet folded in). Phase 2
        # will switch to the canonical payload that also covers
        # python_code so a code-only edit cannot ride past the hash.
        plain = hashlib.sha256(yaml_template.encode("utf-8")).hexdigest()
        stored = getattr(row, "content_hash", "") or ""
        if stored and stored != plain:
            findings.append(
                ManifestDriftFinding(
                    kind="widget_template_package",
                    target_id=str(getattr(row, "id", "")),
                    stored_hash=stored,
                    recomputed_hash=plain,
                    name=getattr(row, "name", None) or getattr(row, "tool_name", None),
                )
            )
    return findings
