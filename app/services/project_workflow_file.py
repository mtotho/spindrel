"""Read and parse the per-Project repo-resident workflow contract.

Phase 4BE of the Project Factory cohesion pass. ``.spindrel/WORKFLOW.md`` is
the single repo-owned file that carries everything Project-specific - branch /
test / PR policy, intake schema, run hook commands, dependency-stack
references. The generic ``skills/project/*`` cluster reads this file and only
falls back to its own defaults when the relevant section is absent.

This module is read-only: parsing only. The starter writer ships in 4BE.4.
The runtime never silently mutates an existing WORKFLOW.md - the file is
repo-owned and reviewable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.services.projects import project_canonical_repo_host_path

WORKFLOW_RELATIVE_PATH = ".spindrel/WORKFLOW.md"

# The five sections every consumer of the parsed file is allowed to assume
# *may* exist. Authors can add more; consumers should not error on extras.
# Surface code (4BE.1) iterates this tuple to emit a stable key set.
STANDARD_SECTIONS: tuple[str, ...] = (
    "policy",
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


def project_workflow_file(
    project: Any,
    snapshot: dict[str, Any] | None = None,
) -> WorkflowFile:
    """Resolve and parse ``.spindrel/WORKFLOW.md`` for a Project.

    Returns a ``WorkflowFile`` whose ``present`` flag is ``False`` when the
    Project has no canonical repo or when the file does not exist on disk.
    Parsing failures surface an empty ``sections`` dict so callers can still
    report the path.
    """
    host_root = project_canonical_repo_host_path(project, snapshot)
    if host_root is None:
        return WorkflowFile(
            relative_path=WORKFLOW_RELATIVE_PATH,
            host_path=None,
            present=False,
        )

    host_path = Path(host_root) / WORKFLOW_RELATIVE_PATH
    if not host_path.is_file():
        return WorkflowFile(
            relative_path=WORKFLOW_RELATIVE_PATH,
            host_path=str(host_path),
            present=False,
        )

    raw = host_path.read_text(encoding="utf-8")
    frontmatter, sections = parse_workflow_file(raw)
    return WorkflowFile(
        relative_path=WORKFLOW_RELATIVE_PATH,
        host_path=str(host_path),
        present=True,
        frontmatter=frontmatter,
        sections=sections,
        raw=raw,
    )
