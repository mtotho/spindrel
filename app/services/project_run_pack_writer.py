"""Render Run Pack proposals into a repo-resident markdown section.

Phase 4BD.4 of the Project Factory issue substrate. Replaces the bespoke
``IssueWorkPack`` DB row substrate with file-resident artifacts under the
Project's canonical repo. The ``propose_run_packs`` tool calls these helpers
with the canonical repo host path, a relative artifact path, a section name,
and the list of pack dicts.

Each pack renders as a ``###`` block under a single ``## <section>`` heading.
The section is idempotent: if the named section already exists in the file,
its body is replaced; otherwise the section is appended to the end of the
file. Other sections in the file are preserved verbatim.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


VALID_CATEGORIES: tuple[str, ...] = (
    "code_bug",
    "test_failure",
    "config_issue",
    "environment_issue",
    "user_decision",
    "not_code_work",
    "needs_info",
    "other",
)
VALID_CONFIDENCE: tuple[str, ...] = ("low", "medium", "high")

DEFAULT_SECTION = "Proposed Run Packs"


@dataclass(frozen=True)
class RunPackProposal:
    """One rendered Run Pack proposal."""

    title: str
    summary: str = ""
    category: str = "other"
    confidence: str = "medium"
    launch_prompt: str = ""
    blueprint_impact: bool = False
    source_item_ids: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RunPackProposal":
        category = str(payload.get("category") or "other").strip().lower()
        if category not in VALID_CATEGORIES:
            category = "other"
        confidence = str(payload.get("confidence") or "medium").strip().lower()
        if confidence not in VALID_CONFIDENCE:
            confidence = "medium"
        source_ids = payload.get("source_item_ids") or ()
        return cls(
            title=str(payload.get("title") or "untitled").strip() or "untitled",
            summary=str(payload.get("summary") or "").strip(),
            category=category,
            confidence=confidence,
            launch_prompt=str(payload.get("launch_prompt") or "").strip(),
            blueprint_impact=bool(payload.get("blueprint_impact")),
            source_item_ids=tuple(str(item).strip() for item in source_ids if str(item).strip()),
        )


def render_pack(pack: RunPackProposal) -> str:
    """Render one pack as a ``### <title>`` block."""
    lines: list[str] = [f"### {pack.title}"]
    tag_line_parts = [
        f"**category:** {pack.category}",
        f"**confidence:** {pack.confidence}",
        "**status:** proposed",
    ]
    if pack.blueprint_impact:
        tag_line_parts.append("**blueprint_impact:** yes")
    lines.append(" · ".join(tag_line_parts))
    if pack.summary:
        lines.append("")
        lines.append(pack.summary)
    if pack.launch_prompt:
        lines.append("")
        lines.append("**launch_prompt:**")
        lines.append("```")
        lines.append(pack.launch_prompt)
        lines.append("```")
    if pack.source_item_ids:
        lines.append("")
        lines.append(f"**source_item_ids:** {', '.join(pack.source_item_ids)}")
    return "\n".join(lines) + "\n"


def render_section(section: str, packs: Iterable[RunPackProposal]) -> str:
    """Render a ``## <section>`` heading followed by all packs."""
    body = "\n".join(render_pack(pack) for pack in packs)
    return f"## {section}\n\n{body}".rstrip() + "\n"


_SECTION_RE = re.compile(r"^## (?P<title>.+?)\s*$", re.MULTILINE)


def replace_or_append_section(existing: str, section: str, rendered_section: str) -> str:
    """Replace the named ``## section`` block in ``existing`` or append it.

    A section block runs from its ``## <title>`` line up to (but not
    including) the next ``## `` heading or end of file. When no matching
    section is found, the rendered block is appended after a single blank
    line so the file stays scannable. If the file is empty, the rendered
    section becomes the entire content.
    """
    if not existing.strip():
        return rendered_section

    matches: list[tuple[int, int, str]] = []  # (start, end_of_heading_line, title)
    for match in _SECTION_RE.finditer(existing):
        matches.append((match.start(), match.end(), match.group("title").strip()))

    if not matches:
        sep = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
        return existing + sep + rendered_section

    target_index: int | None = None
    for idx, (_, _, title) in enumerate(matches):
        if title == section:
            target_index = idx
            break

    if target_index is None:
        sep = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
        return existing + sep + rendered_section

    block_start = matches[target_index][0]
    block_end = matches[target_index + 1][0] if target_index + 1 < len(matches) else len(existing)

    before = existing[:block_start]
    after = existing[block_end:]
    # Preserve a single blank-line separator between sections.
    if before and not before.endswith("\n"):
        before = before + "\n"
    if before and not before.endswith("\n\n"):
        before = before + "\n"
    if after and not after.startswith("\n"):
        after = "\n" + after
    return before + rendered_section + after


@dataclass(frozen=True)
class RunPackWriteResult:
    """Outcome of a ``propose_run_packs`` write."""

    host_path: str
    relative_path: str
    section: str
    pack_count: int
    created_file: bool


def write_run_pack_proposals(
    canonical_repo_host_path: str,
    artifact_relative_path: str,
    section: str,
    packs: list[dict[str, Any]],
) -> RunPackWriteResult:
    """Persist the rendered packs into ``<canonical_repo>/<artifact_relative_path>``.

    Idempotent: replaces the named section in place when it already exists,
    appends it when missing, creates the file (and parents) when missing.
    """
    proposals = [RunPackProposal.from_dict(item) for item in packs]
    rendered_section = render_section(section, proposals)

    relative = artifact_relative_path.lstrip("/")
    abs_path = Path(canonical_repo_host_path) / relative
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    created = not abs_path.exists()

    if created:
        abs_path.write_text(rendered_section, encoding="utf-8")
    else:
        existing = abs_path.read_text(encoding="utf-8")
        new_content = replace_or_append_section(existing, section, rendered_section)
        abs_path.write_text(new_content, encoding="utf-8")

    return RunPackWriteResult(
        host_path=str(abs_path),
        relative_path=relative,
        section=section,
        pack_count=len(proposals),
        created_file=created,
    )
