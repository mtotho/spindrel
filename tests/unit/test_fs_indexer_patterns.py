"""Unit tests for pattern splitting and exclusion glob support in fs_indexer."""
import pytest
from pathlib import Path

from app.agent.fs_indexer import _split_patterns, _glob_with_exclusions


class TestSplitPatterns:
    """Test _split_patterns separates include/exclude correctly."""

    def test_all_include(self):
        include, exclude = _split_patterns(["**/*.py", "**/*.md"])
        assert include == ["**/*.py", "**/*.md"]
        assert exclude == []

    def test_all_exclude(self):
        include, exclude = _split_patterns(["!**/*.pyc", "!**/test/**"])
        assert include == []
        assert exclude == ["**/*.pyc", "**/test/**"]

    def test_mixed(self):
        include, exclude = _split_patterns(["**/*.py", "!**/test/**", "**/*.md"])
        assert include == ["**/*.py", "**/*.md"]
        assert exclude == ["**/test/**"]

    def test_whitespace_stripped(self):
        include, exclude = _split_patterns(["  **/*.py  ", "  !**/test/**  "])
        assert include == ["**/*.py"]
        assert exclude == ["**/test/**"]

    def test_empty_list(self):
        include, exclude = _split_patterns([])
        assert include == []
        assert exclude == []


class TestGlobWithExclusions:
    """Test _glob_with_exclusions honours negation patterns."""

    @pytest.fixture()
    def tree(self, tmp_path: Path):
        """Create a file tree for testing."""
        # src/main.py, src/utils.py, src/test/test_main.py
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("main")
        (tmp_path / "src" / "utils.py").write_text("utils")
        (tmp_path / "src" / "test").mkdir()
        (tmp_path / "src" / "test" / "test_main.py").write_text("test")
        # docs/readme.md
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "readme.md").write_text("readme")
        # node_modules/pkg/index.js (should be ignored by _accept but test pattern exclusion)
        (tmp_path / "vendor").mkdir()
        (tmp_path / "vendor" / "lib.py").write_text("vendor")
        return tmp_path

    def _accept_all(self, p: Path) -> bool:
        return p.is_file()

    def test_include_only(self, tree: Path):
        result = _glob_with_exclusions(tree, ["**/*.py"], self._accept_all, tree)
        names = {p.name for p in result}
        assert "main.py" in names
        assert "utils.py" in names
        assert "test_main.py" in names
        assert "lib.py" in names

    def test_exclude_directory(self, tree: Path):
        result = _glob_with_exclusions(
            tree, ["**/*.py", "!vendor/**"], self._accept_all, tree,
        )
        names = {p.name for p in result}
        assert "main.py" in names
        assert "utils.py" in names
        assert "lib.py" not in names

    def test_exclude_pattern(self, tree: Path):
        result = _glob_with_exclusions(
            tree, ["**/*.py", "!**/test/**"], self._accept_all, tree,
        )
        names = {p.name for p in result}
        assert "main.py" in names
        assert "utils.py" in names
        assert "test_main.py" not in names

    def test_exclude_by_extension(self, tree: Path):
        result = _glob_with_exclusions(
            tree, ["**/*", "!**/*.md"], self._accept_all, tree,
        )
        names = {p.name for p in result}
        assert "main.py" in names
        assert "readme.md" not in names

    def test_multiple_excludes(self, tree: Path):
        result = _glob_with_exclusions(
            tree, ["**/*", "!**/*.md", "!vendor/**"], self._accept_all, tree,
        )
        names = {p.name for p in result}
        assert "main.py" in names
        assert "readme.md" not in names
        assert "lib.py" not in names

    def test_no_patterns(self, tree: Path):
        result = _glob_with_exclusions(tree, [], self._accept_all, tree)
        assert result == set()

    def test_only_exclude_patterns(self, tree: Path):
        """If only exclusion patterns given, no files are included."""
        result = _glob_with_exclusions(
            tree, ["!**/*.py"], self._accept_all, tree,
        )
        assert result == set()
