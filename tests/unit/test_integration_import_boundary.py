"""Integration boundary guard.

Integrations should consume app-owned behavior through ``integrations.sdk``.
Only integration infrastructure shims may import ``app.*`` directly.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATIONS_ROOT = REPO_ROOT / "integrations"

_INFRASTRUCTURE_SHIMS = {
    "__init__.py",
    "discovery.py",
    "manifest_setup.py",
    "sdk.py",
    "utils.py",
}


def _direct_app_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "app" or node.module.startswith("app."):
                imports.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "app" or alias.name.startswith("app."):
                    imports.append(alias.name)
    return imports


def test_no_new_direct_app_imports_under_integrations() -> None:
    offenders: list[str] = []
    for path in sorted(INTEGRATIONS_ROOT.rglob("*.py")):
        rel = path.relative_to(INTEGRATIONS_ROOT).as_posix()
        if rel in _INFRASTRUCTURE_SHIMS or "/tests/" in f"/{rel}":
            continue
        imports = _direct_app_imports(path)
        if imports:
            offenders.append(f"{rel}: {sorted(set(imports))}")

    assert not offenders, (
        "New direct app.* imports under integrations must go through "
        "integrations.sdk. Only integration infrastructure shims "
        "(__init__.py, discovery.py, manifest_setup.py, sdk.py, utils.py) "
        "may import app.* directly:\n"
        + "\n".join(offenders)
    )
