from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_head_revision_resolves() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "migrations"))

    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    revision = script.get_revision(head)

    assert revision is not None
