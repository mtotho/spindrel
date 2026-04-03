"""Test that TOOL_DIRS paths get tilde-expanded and resolved."""
from pathlib import Path
from unittest.mock import patch


def _build_tool_dirs(tool_dirs_value: str) -> list[Path]:
    """Replicate the path construction logic from app/main.py."""
    return [
        Path(p.strip()).expanduser().resolve()
        for p in tool_dirs_value.split(":")
        if p.strip()
    ]


class TestToolDirsExpansion:
    def test_tilde_expanded(self):
        dirs = _build_tool_dirs("~/my-tools")
        assert len(dirs) == 1
        assert "~" not in str(dirs[0])
        assert dirs[0].is_absolute()

    def test_multiple_dirs(self):
        dirs = _build_tool_dirs("~/a:~/b:/absolute/c")
        assert len(dirs) == 3
        for d in dirs:
            assert d.is_absolute()
            assert "~" not in str(d)

    def test_empty_string(self):
        dirs = _build_tool_dirs("")
        assert dirs == []

    def test_whitespace_stripped(self):
        dirs = _build_tool_dirs("  ~/tools  :  /other  ")
        assert len(dirs) == 2
        assert "~" not in str(dirs[0])

    def test_relative_path_resolved(self):
        dirs = _build_tool_dirs("relative/path")
        assert len(dirs) == 1
        assert dirs[0].is_absolute()
