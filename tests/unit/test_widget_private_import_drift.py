"""Cluster 4B guardrail — widget_*.py service modules must not import
underscore-prefixed names from each other.

`feedback_no_legacy_framing.md`-adjacent reasoning: when one widget
service reaches across the module boundary to grab a `_substitute` or
`_widget_templates` from a sibling, the sibling's "private" marker
loses meaning. Either the helper is a real cross-module public
(promote it, as 4B.1 did for `substitute` / `substitute_string` /
`apply_code_transform` / `build_html_widget_body` /
`resolve_html_template_paths`), or the call site belongs inside the
owning module.

This test walks every ``app/services/widget_*.py`` file, inspects
``ast.ImportFrom`` nodes whose module is another ``app.services.widget_*``,
and fails if any imported name starts with an underscore.

Scope intentionally stops at ``app/services/`` — test files legitimately
poke private cache dicts (e.g. ``tests/unit/test_widget_actions_state_poll.py``
manipulates ``_widget_templates`` for deterministic fixture state).
"""
from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SERVICES_DIR = _REPO_ROOT / "app" / "services"


def _widget_service_files() -> list[Path]:
    return sorted(
        p for p in _SERVICES_DIR.glob("widget_*.py") if "__pycache__" not in p.parts
    )


def _offending_private_widget_imports(py_file: Path) -> list[tuple[int, str, str]]:
    """Return ``(lineno, source_module, name)`` for each cross-widget_*
    private import. Underscore imports are OK within the same file; this
    check only flags cross-module reach-ins."""
    tree = ast.parse(py_file.read_text())
    hits: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module or ""
        # Only cross-module widget_*.py → widget_*.py imports.
        if not module.startswith("app.services.widget_"):
            continue
        source_module_name = module.rsplit(".", 1)[-1]
        if source_module_name == py_file.stem:
            # Self-import would be weird, but not a drift violation.
            continue
        for alias in node.names:
            if alias.name.startswith("_"):
                hits.append((node.lineno, module, alias.name))
    return hits


def test_no_private_imports_across_widget_service_modules() -> None:
    offenders: list[tuple[Path, int, str, str]] = []
    for py_file in _widget_service_files():
        for lineno, module, name in _offending_private_widget_imports(py_file):
            offenders.append((py_file, lineno, module, name))

    if offenders:
        rendered = "\n".join(
            f"  {p.relative_to(_REPO_ROOT)}:{line}: "
            f"from {mod} import {name}"
            for p, line, mod, name in offenders
        )
        raise AssertionError(
            "widget_*.py service modules must not import underscore-prefixed "
            "names from each other. Either promote the helper to a public "
            "alias (see app/services/widget_templates.py `substitute`, "
            "`substitute_string`, `apply_code_transform`, "
            "`build_html_widget_body`, `resolve_html_template_paths` at the "
            "bottom of the file for the pattern) or move the call site into "
            "the owning module.\n\nOffending imports:\n" + rendered
        )
