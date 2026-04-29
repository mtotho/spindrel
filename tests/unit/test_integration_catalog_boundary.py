"""Architecture guards for the integration catalog/discovery boundary."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(), filename=str(path))


def test_integrations_package_root_stays_facade_sized() -> None:
    tree = _tree(ROOT / "integrations" / "__init__.py")
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]

    assert [node.name for node in functions] == ["_get_setup_vars"]
    assert len(functions[0].body) <= 3


def test_app_code_does_not_import_integration_private_helpers_from_root() -> None:
    offenders: list[str] = []
    for base in ("app",):
        for path in sorted((ROOT / base).rglob("*.py")):
            tree = _tree(path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.module != "integrations":
                    continue
                private_names = [
                    alias.name for alias in node.names
                    if alias.name.startswith("_")
                ]
                if private_names:
                    rel = path.relative_to(ROOT).as_posix()
                    offenders.append(f"{rel}: {private_names}")

    assert not offenders, (
        "app code should import private integration helpers from their owner "
        "modules, not from the package-root facade:\n" + "\n".join(offenders)
    )


def test_bindable_integrations_does_not_load_runtime_modules() -> None:
    tree = _tree(ROOT / "app" / "services" / "channel_integrations.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "discover_integrations":
            raise AssertionError(
                "list_bindable_integrations must use side-effect-free catalog "
                "metadata, not runtime integration loading"
            )
