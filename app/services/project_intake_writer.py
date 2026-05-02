"""Write captured intake notes to a repo-resident file or folder.

Phase 4BD.3 of the Project Factory issue substrate. The generic intake skill
calls these helpers via the ``capture_project_intake`` tool; they format the
note in the documented inbox schema and append (for ``repo_file``) or write a
new file (for ``repo_folder``) under the canonical repo path resolved by the
caller.

The schema is intentionally minimal so it greps cleanly:

    ## YYYY-MM-DD HH:MM <kebab-slug>
    **kind:** <kind> · **area:** <area> · **status:** <status>
    Body. 1-10 lines.

Repos that want a richer schema should ship their own
``.agents/skills/<repo>-issues/SKILL.md`` and reach for ``file_ops`` directly;
this helper is the convention-free default.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

VALID_KINDS: tuple[str, ...] = ("bug", "idea", "tech-debt", "question")
VALID_STATUSES: tuple[str, ...] = ("open", "stale")


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def kebab_slug(value: str, *, max_len: int = 60) -> str:
    """Normalize free-form text into a kebab-case slug suitable for headings.

    Keeps the slug grep-friendly: lowercase, hyphens only, no leading/trailing
    separators, capped at ``max_len`` characters so the inbox heading stays
    scannable.
    """
    cleaned = _SLUG_RE.sub("-", value.lower()).strip("-")
    if not cleaned:
        cleaned = "note"
    return cleaned[:max_len].rstrip("-") or "note"


@dataclass(frozen=True)
class CapturedIntakeNote:
    """A captured intake note in the generic Spindrel schema."""

    title: str
    kind: str = "idea"
    area: str | None = None
    status: str = "open"
    body: str | None = None
    captured_at: datetime | None = None

    def normalized(self) -> "CapturedIntakeNote":
        """Return a copy with timestamps + defaults filled in."""
        return CapturedIntakeNote(
            title=self.title.strip() or "untitled",
            kind=(self.kind or "idea").strip().lower() or "idea",
            area=(self.area or None) and self.area.strip() or None,
            status=(self.status or "open").strip().lower() or "open",
            body=(self.body or "").strip() or None,
            captured_at=self.captured_at or datetime.utcnow(),
        )


def render_inbox_entry(note: CapturedIntakeNote) -> str:
    """Render one note as a level-2 heading + tag line + optional body."""
    n = note.normalized()
    timestamp = n.captured_at.strftime("%Y-%m-%d %H:%M")
    slug = kebab_slug(n.title)
    heading = f"## {timestamp} {slug}"
    tag_line = (
        f"**kind:** {n.kind} · "
        f"**area:** {n.area or '-'} · "
        f"**status:** {n.status}"
    )
    parts: list[str] = [heading, tag_line]
    if n.body:
        parts.append(n.body)
    return "\n".join(parts) + "\n"


@dataclass(frozen=True)
class IntakeWriteResult:
    """Outcome of an intake write."""

    host_path: str
    relative_path: str
    appended: bool
    created_file: bool
    slug: str
    timestamp: str


def append_to_repo_file(
    canonical_repo_host_path: str,
    intake_target: str,
    note: CapturedIntakeNote,
) -> IntakeWriteResult:
    """Append the formatted note to ``<canonical_repo>/<intake_target>``.

    Creates the file (and any parent directories) when missing. The file's
    pre-existing content is preserved verbatim and the new entry is appended
    after a single blank line so the inbox stays scannable.
    """
    rendered = render_inbox_entry(note)
    relative = intake_target.lstrip("/")
    abs_path = Path(canonical_repo_host_path) / relative
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    created = not abs_path.exists()

    if created:
        abs_path.write_text(rendered, encoding="utf-8")
    else:
        existing = abs_path.read_text(encoding="utf-8")
        separator = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
        abs_path.write_text(existing + separator + rendered, encoding="utf-8")

    n = note.normalized()
    return IntakeWriteResult(
        host_path=str(abs_path),
        relative_path=relative,
        appended=not created,
        created_file=created,
        slug=kebab_slug(n.title),
        timestamp=n.captured_at.strftime("%Y-%m-%d %H:%M"),
    )


def write_to_repo_folder(
    canonical_repo_host_path: str,
    intake_target: str,
    note: CapturedIntakeNote,
    existing_filenames: Iterable[str] | None = None,
) -> IntakeWriteResult:
    """Write the formatted note as a new file under the intake folder.

    Filename pattern is ``<YYYYMMDD-HHMM>-<slug>.md``. Collisions append a
    monotonic suffix (``-2``, ``-3``...) so two captures within the same
    minute do not overwrite each other.
    """
    n = note.normalized()
    folder_rel = intake_target.lstrip("/").rstrip("/")
    folder_abs = Path(canonical_repo_host_path) / folder_rel
    folder_abs.mkdir(parents=True, exist_ok=True)

    base_slug = kebab_slug(n.title)
    base_name = f"{n.captured_at.strftime('%Y%m%d-%H%M')}-{base_slug}"

    taken = set(existing_filenames or ()) | {p.name for p in folder_abs.glob("*.md")}
    candidate = f"{base_name}.md"
    counter = 2
    while candidate in taken:
        candidate = f"{base_name}-{counter}.md"
        counter += 1

    abs_path = folder_abs / candidate
    abs_path.write_text(render_inbox_entry(n), encoding="utf-8")

    return IntakeWriteResult(
        host_path=str(abs_path),
        relative_path=f"{folder_rel}/{candidate}",
        appended=False,
        created_file=True,
        slug=base_slug,
        timestamp=n.captured_at.strftime("%Y-%m-%d %H:%M"),
    )
