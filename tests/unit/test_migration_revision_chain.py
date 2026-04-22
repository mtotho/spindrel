from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def _load_script_directory() -> ScriptDirectory:
    repo_root = Path(__file__).resolve().parents[2]
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "migrations"))
    return ScriptDirectory.from_config(config)


def test_alembic_head_revision_resolves() -> None:
    script = _load_script_directory()
    head = script.get_current_head()
    revision = script.get_revision(head)

    assert revision is not None


def test_alembic_revision_ids_fit_version_table() -> None:
    script = _load_script_directory()
    too_long = [
        revision.revision
        for revision in script.walk_revisions()
        if revision.revision is not None and len(revision.revision) > 32
    ]

    assert too_long == []
