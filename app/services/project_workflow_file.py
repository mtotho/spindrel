"""Read and parse the per-Project repo-resident workflow contract.

Phase 4BE of the Project Factory cohesion pass. ``.spindrel/WORKFLOW.md`` is
the single repo-owned file that carries everything Project-specific - branch /
test / PR policy, intake schema, run hook commands, dependency-stack
references. The generic ``skills/project/*`` cluster reads this file and only
falls back to its own defaults when the relevant section is absent.

Parsing is permissive (4BE.0). The starter writer (4BE.4) refuses to
overwrite an existing file - the runtime never silently mutates a WORKFLOW.md
that the user/repo authored. Only ``write_workflow_starter`` is allowed to
create the file, and only when it is absent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.services.projects import (
    normalize_project_path,
    project_canonical_repo_host_path,
    project_directory_from_project,
)

WORKFLOW_RELATIVE_PATH = ".spindrel/WORKFLOW.md"

# The sections every consumer of the parsed file is allowed to assume
# *may* exist. Authors can add more; consumers should not error on extras.
# Surface code (4BE.1) iterates this tuple to emit a stable key set.
STANDARD_SECTIONS: tuple[str, ...] = (
    "policy",
    "artifacts",
    "intake",
    "runs",
    "hooks",
    "dependencies",
)

_SECTION_HEADING_RE = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_SECTION_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug_section(name: str) -> str:
    return _SECTION_SLUG_RE.sub("-", name.strip().lower()).strip("-")


@dataclass(frozen=True)
class WorkflowFile:
    """Parsed view of a Project's ``.spindrel/WORKFLOW.md``."""

    relative_path: str
    host_path: str | None
    present: bool
    frontmatter: dict[str, Any] = field(default_factory=dict)
    sections: dict[str, str] = field(default_factory=dict)
    raw: str | None = None

    def section(self, name: str) -> str | None:
        """Return the body text of a named section, or ``None`` if absent.

        Caller input is normalized the same way author headings are, so
        ``section("Run Hooks")`` matches ``## run-hooks`` and vice versa.
        """
        return self.sections.get(_slug_section(name))


def parse_workflow_file(text: str) -> tuple[dict[str, Any], dict[str, str]]:
    """Split a WORKFLOW.md document into ``(frontmatter, sections)``.

    Frontmatter is a YAML block delimited by ``---`` lines at the very top.
    Sections are level-2 headings (``## Name``); the body of each section is
    every line up to the next level-2 heading (or EOF), stripped. Section
    keys are normalized to a kebab-slug so authors can write ``## Run Hooks``
    or ``## run-hooks`` interchangeably.

    The function is permissive: bad YAML returns an empty frontmatter dict
    rather than raising. The point is to surface the file to skills, not to
    enforce a schema.
    """
    if not text:
        return {}, {}

    body = text
    frontmatter: dict[str, Any] = {}

    if body.startswith("---"):
        end = body.find("\n---", 3)
        if end != -1:
            yaml_block = body[3:end].lstrip("\n")
            try:
                parsed = yaml.safe_load(yaml_block) if yaml_block.strip() else {}
                if isinstance(parsed, dict):
                    frontmatter = parsed
            except yaml.YAMLError:
                frontmatter = {}
            after_close = end + len("\n---")
            if after_close < len(body) and body[after_close] == "\n":
                after_close += 1
            body = body[after_close:]

    sections: dict[str, str] = {}
    matches = list(_SECTION_HEADING_RE.finditer(body))
    for idx, match in enumerate(matches):
        slug = _slug_section(match.group(1))
        if not slug:
            continue
        body_start = match.end()
        body_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
        section_body = body[body_start:body_end].strip("\n").rstrip()
        sections[slug] = section_body

    return frontmatter, sections


def _candidate_workflow_paths(
    project: Any,
    snapshot: dict[str, Any] | None,
) -> list[tuple[str, Path]]:
    """Return workflow-file candidates in resolution order.

    The canonical repo remains the normal home. Projects that predate
    canonical-repo snapshots may still carry an explicit prompt_file_path such
    as ``spindrel/.spindrel/WORKFLOW.md`` under a multi-repo Project root; use
    that as a compatibility fallback so factory-state and skills see the same
    workflow that prompt injection already reads.
    """
    candidates: list[tuple[str, Path]] = []
    seen: set[str] = set()

    def _add(relative_path: str | None, host_path: Path | None) -> None:
        if not relative_path or host_path is None:
            return
        key = str(host_path)
        if key in seen:
            return
        seen.add(key)
        candidates.append((relative_path, host_path))

    host_root = project_canonical_repo_host_path(project, snapshot)
    if host_root is not None:
        _add(WORKFLOW_RELATIVE_PATH, Path(host_root) / WORKFLOW_RELATIVE_PATH)

    prompt_file = normalize_project_path(getattr(project, "prompt_file_path", None))
    if prompt_file and prompt_file.endswith(WORKFLOW_RELATIVE_PATH):
        try:
            project_dir = project_directory_from_project(project)
            _add(prompt_file, Path(project_dir.host_path) / prompt_file)
        except Exception:
            pass

    return candidates


def project_workflow_file(
    project: Any,
    snapshot: dict[str, Any] | None = None,
) -> WorkflowFile:
    """Resolve and parse ``.spindrel/WORKFLOW.md`` for a Project.

    Returns a ``WorkflowFile`` whose ``present`` flag is ``False`` when the
    Project has no canonical repo/prompt-file workflow or when the file does
    not exist on disk. Parsing failures surface an empty ``sections`` dict so
    callers can still report the path.
    """
    candidates = _candidate_workflow_paths(project, snapshot)
    if not candidates:
        return WorkflowFile(
            relative_path=WORKFLOW_RELATIVE_PATH,
            host_path=None,
            present=False,
        )

    first_relative, first_host_path = candidates[0]
    for relative_path, host_path in candidates:
        if not host_path.is_file():
            continue
        raw = host_path.read_text(encoding="utf-8")
        frontmatter, sections = parse_workflow_file(raw)
        return WorkflowFile(
            relative_path=relative_path,
            host_path=str(host_path),
            present=True,
            frontmatter=frontmatter,
            sections=sections,
            raw=raw,
        )

    return WorkflowFile(
        relative_path=first_relative,
        host_path=str(first_host_path),
        present=False,
    )

_STARTER_TEMPLATE = """\
---
name: {project_name}
spindrel_workflow_version: 1
---

# {project_name} Workflow

This file is the single repo-owned contract Spindrel reads to know how to
work in this Project. Edit it directly. Spindrel never silently mutates this
file - the only write that ever lands here is the explicit starter at
Project setup, and only when this file did not already exist.

The generic `skills/project/*` cluster is the fallback for any section left
empty. Whatever you write below wins.

## Policy

Branch policy, base branch, repo-local test command, screenshot evidence
location, PR conventions go here. Example:

> Branch from `master`. Open PRs via `gh`. Repo-local tests:
> `pytest tests/unit -q`. Screenshots land in `tests/screenshots/`.

## Artifacts

Where durable Project state belongs. Example:

> Rough notes go to `docs/inbox.md`; multi-session work goes to
> `docs/tracks/<slug>.md`; implementation plans go to `docs/plans/`;
> audits and evidence history go to `docs/audits/`; run-local receipts and
> scratch artifacts go to `.spindrel/runs/`.

## Intake

Where rough bugs / ideas / tech-debt notes get captured. Default schema:

    ## YYYY-MM-DD HH:MM <kebab-slug>
    **kind:** bug | idea | tech-debt | question · **area:** <subsystem> · **status:** open
    Body. 1-10 lines.

Default path: `docs/inbox.md` in the canonical repo. Replace this section if
your repo uses GitHub Issues, Linear, a folder of files, or any other
convention - whatever you write here is what Spindrel does.

## Runs

Branch / test / PR conventions for Project coding runs. Spindrel reads this
section before launching or implementing a run.

## Hooks

Optional shell commands keyed by phase:

    before_run: <command>
    after_run: <command>

## Dependencies

Notes on backing services, dev targets, and secrets the Project expects.
"""


@dataclass(frozen=True)
class WorkflowStarterResult:
    """Outcome of a ``write_workflow_starter`` call."""

    ok: bool
    host_path: str | None
    relative_path: str
    error: str | None = None


def write_workflow_starter(
    project: Any,
    snapshot: dict[str, Any] | None = None,
    *,
    project_name: str | None = None,
) -> WorkflowStarterResult:
    """Write a starter ``.spindrel/WORKFLOW.md`` only when absent.

    Refuses to overwrite an existing file - the file is repo-owned and the
    runtime is not allowed to silently rewrite it. Returns a structured
    failure when the Project has no canonical repo or when the file already
    exists, so the calling tool/skill can report the blocker without
    raising.
    """
    host_root = project_canonical_repo_host_path(project, snapshot)
    if host_root is None:
        return WorkflowStarterResult(
            ok=False,
            host_path=None,
            relative_path=WORKFLOW_RELATIVE_PATH,
            error="project has no canonical repo configured",
        )

    host_path = Path(host_root) / WORKFLOW_RELATIVE_PATH
    if host_path.exists():
        return WorkflowStarterResult(
            ok=False,
            host_path=str(host_path),
            relative_path=WORKFLOW_RELATIVE_PATH,
            error="workflow file already exists; refusing to overwrite",
        )

    name = project_name or getattr(project, "name", None) or "Project"
    host_path.parent.mkdir(parents=True, exist_ok=True)
    host_path.write_text(_STARTER_TEMPLATE.format(project_name=name), encoding="utf-8")
    return WorkflowStarterResult(
        ok=True,
        host_path=str(host_path),
        relative_path=WORKFLOW_RELATIVE_PATH,
    )
