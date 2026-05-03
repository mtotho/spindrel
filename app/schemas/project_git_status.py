from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ProjectGitRepoStatusOut(BaseModel):
    path: str
    display_path: str | None = None
    branch: str | None = None
    head: str | None = None
    dirty: bool
    staged_count: int
    unstaged_count: int
    untracked_count: int
    ahead: int | None = None
    behind: int | None = None
    status_lines: list[str]
    diff_stat: str | None = None
    patch: str | None = None
    error: str | None = None


class ProjectGitStatusOut(BaseModel):
    scope: dict[str, Any]
    repo_count: int
    dirty_count: int
    repos: list[ProjectGitRepoStatusOut]
    generated_at: str | None = None
