"""Cluster 3 guardrail — services, agent, and tool layers must not import
``fastapi``.

The refactor moved router-layer concerns (HTTPException, Request) out of
the business layers behind ``app/domain/errors.py`` + a router-boundary
exception handler (see ``app/main.py``). This test is the drift guard.

If it fails, someone reintroduced a ``from fastapi import ...`` (or
``import fastapi``) inside a service / agent / tool file. Re-route the
raise through a ``DomainError`` subclass or the router-adapter instead.

Allowlist:
- ``app/services/endpoint_catalog.py`` — purpose-built FastAPI route
  introspection. It imports ``FastAPI``/``Depends``/``APIRoute`` to walk
  ``app.routes``; it has no HTTP-error-handling concern and sits at the
  router-adjacent boundary.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Scoped to business-logic directories. Router files legitimately use
# fastapi; the wall is at the services/agent/tool boundary.
SCOPED_DIRS = [
    REPO_ROOT / "app" / "services",
    REPO_ROOT / "app" / "agent",
    REPO_ROOT / "app" / "tools",
]

# Files that legitimately need fastapi. Keep this list tight — every
# new entry should come with a comment explaining why the rule doesn't
# apply.
ALLOWLIST = {
    # Route introspection for the discovery surface. Reads FastAPI routes;
    # does not raise HTTP errors.
    REPO_ROOT / "app" / "services" / "endpoint_catalog.py",
}

def _imports_fastapi(py_file: Path) -> tuple[int, str] | None:
    """Return ``(lineno, text)`` for the first real fastapi import, else None.

    Uses ``ast`` so string literals that happen to contain ``from fastapi …``
    (e.g. scaffolded code written to disk by integration tooling) are ignored.
    """
    tree = ast.parse(py_file.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "fastapi":
            return node.lineno, f"from {node.module} import ..."
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "fastapi":
                    return node.lineno, f"import {alias.name}"
    return None


def _offending_files() -> list[tuple[Path, int, str]]:
    hits: list[tuple[Path, int, str]] = []
    for root in SCOPED_DIRS:
        for py_file in root.rglob("*.py"):
            if py_file in ALLOWLIST:
                continue
            if "__pycache__" in py_file.parts:
                continue
            hit = _imports_fastapi(py_file)
            if hit is not None:
                lineno, text = hit
                hits.append((py_file, lineno, text))
    return hits


def test_no_fastapi_imports_in_services_agent_or_tools():
    """Business-layer modules must not import from ``fastapi``."""
    offenders = _offending_files()
    if offenders:
        rendered = "\n".join(
            f"  {p.relative_to(REPO_ROOT)}:{line}: {text}"
            for p, line, text in offenders
        )
        raise AssertionError(
            "Services/agent/tool layer must not import fastapi.\n"
            "Raise ``DomainError`` from ``app.domain.errors`` instead; the "
            "router boundary converts to ``HTTPException``.\n\n"
            "Offending files:\n" + rendered
        )
