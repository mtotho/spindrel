"""Folder-layout skill-loader coverage for file_sync + list_available_skills.

Convention:
  - `skills/<name>.md`                → skill_id = "<name>"
  - `skills/<name>/index.md`          → skill_id = "<name>"   (folder entry)
  - `skills/<name>/<sub>.md`          → skill_id = "<name>/<sub>"
  - `skills/<name>/<sub>/<child>.md`  → skill_id = "<name>/<sub>/<child>"
"""
import os
from unittest.mock import patch

from app.agent.skills import list_available_skills
from app.services.file_sync import SOURCE_FILE, _collect_skill_files


def _chdir_collect(tmp_path):
    """Run _collect_skill_files under tmp_path as cwd."""
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with patch("app.services.file_sync._integration_dirs", return_value=[]):
            return _collect_skill_files()
    finally:
        os.chdir(old_cwd)


class TestCollectSkillFilesFolderLayout:
    def test_flat_layout_still_works(self, tmp_path):
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "alpha.md").write_text("# alpha")
        (skills / "beta.md").write_text("# beta")

        items = _chdir_collect(tmp_path)
        ids = sorted(sid for _p, sid, src in items if src == SOURCE_FILE)
        assert ids == ["alpha", "beta"]

    def test_folder_layout_with_index(self, tmp_path):
        skills = tmp_path / "skills"
        (skills / "configurator").mkdir(parents=True)
        (skills / "configurator" / "index.md").write_text("# entry")
        (skills / "configurator" / "bot.md").write_text("# bot")
        (skills / "configurator" / "channel.md").write_text("# channel")

        items = _chdir_collect(tmp_path)
        ids = sorted(sid for _p, sid, _src in items)
        assert ids == ["configurator", "configurator/bot", "configurator/channel"]

    def test_readme_counts_as_entry(self, tmp_path):
        skills = tmp_path / "skills"
        (skills / "widgets").mkdir(parents=True)
        (skills / "widgets" / "README.md").write_text("# entry")
        (skills / "widgets" / "chips.md").write_text("# chips")

        items = _chdir_collect(tmp_path)
        ids = sorted(sid for _p, sid, _src in items)
        assert ids == ["widgets", "widgets/chips"]

    def test_folder_without_entry_yields_only_children(self, tmp_path):
        skills = tmp_path / "skills"
        (skills / "tools_only").mkdir(parents=True)
        (skills / "tools_only" / "a.md").write_text("# a")
        (skills / "tools_only" / "b.md").write_text("# b")

        items = _chdir_collect(tmp_path)
        ids = sorted(sid for _p, sid, _src in items)
        # No parent "tools_only" because no index.md / README.md
        assert ids == ["tools_only/a", "tools_only/b"]

    def test_nested_subfolders(self, tmp_path):
        skills = tmp_path / "skills"
        (skills / "a" / "b").mkdir(parents=True)
        (skills / "a" / "index.md").write_text("# a")
        (skills / "a" / "b" / "c.md").write_text("# c")

        items = _chdir_collect(tmp_path)
        ids = sorted(sid for _p, sid, _src in items)
        assert ids == ["a", "a/b/c"]

    def test_flat_and_folder_coexist(self, tmp_path):
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "old.md").write_text("# flat")
        (skills / "new").mkdir()
        (skills / "new" / "index.md").write_text("# entry")
        (skills / "new" / "sub.md").write_text("# sub")

        items = _chdir_collect(tmp_path)
        ids = sorted(sid for _p, sid, _src in items)
        assert ids == ["new", "new/sub", "old"]


class TestListAvailableSkills:
    def test_mirrors_folder_layout(self, tmp_path):
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "flat.md").write_text("# flat")
        (skills / "cfg").mkdir()
        (skills / "cfg" / "index.md").write_text("# entry")
        (skills / "cfg" / "bot.md").write_text("# bot")

        ids = sorted(list_available_skills(skills))
        assert ids == ["cfg", "cfg/bot", "flat"]

    def test_empty_dir_returns_empty_list(self, tmp_path):
        skills = tmp_path / "skills"
        skills.mkdir()
        assert list_available_skills(skills) == []

    def test_missing_dir_returns_empty_list(self, tmp_path):
        assert list_available_skills(tmp_path / "does_not_exist") == []
