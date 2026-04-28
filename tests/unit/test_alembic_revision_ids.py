from __future__ import annotations

import ast
from pathlib import Path


MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"
ALEMBIC_VERSION_NUM_LIMIT = 32


def _revision_id(path: Path) -> str | None:
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        if not any(isinstance(target, ast.Name) and target.id == "revision" for target in targets):
            continue
        revision = ast.literal_eval(value)
        return revision if isinstance(revision, str) else None
    return None


def test_alembic_revision_ids_fit_version_table():
    overlong = []
    for path in sorted(MIGRATIONS_DIR.glob("*.py")):
        revision = _revision_id(path)
        if revision and len(revision) > ALEMBIC_VERSION_NUM_LIMIT:
            overlong.append((path.name, revision, len(revision)))

    assert overlong == []
