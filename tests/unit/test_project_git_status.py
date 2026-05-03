from pathlib import Path
import subprocess

from app.services.project_git_status import _repo_summary


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def test_repo_summary_exposes_ui_git_status_contract(tmp_path: Path):
    _git(tmp_path, "init")
    (tmp_path / "tracked.txt").write_text("initial\n")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "-c", "user.email=test@example.com", "-c", "user.name=Test User", "commit", "-m", "initial")

    (tmp_path / "tracked.txt").write_text("changed\n")
    (tmp_path / "new.txt").write_text("new\n")

    summary = _repo_summary(tmp_path, include_patch=True)

    assert summary["dirty"] is True
    assert summary["changed_count"] == 2
    assert summary["unstaged_count"] == 1
    assert summary["untracked_count"] == 1
    assert summary["staged_count"] == 0
    assert summary["status_lines"] == summary["files"]
    assert summary["error"] is None
    assert isinstance(summary["head"], str)
    assert summary["patch"]
