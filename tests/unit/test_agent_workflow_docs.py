"""Guards for the repo-local agent workflow contract."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_agent_startup_docs_do_not_depend_on_private_vault_or_runbook():
    """Portable agents should need only source-controlled repo artifacts."""

    forbidden = (
        "personal/vault",
        "Sessions/spindrel",
        "Ideas & Investigations",
        "Test Server Operations",
        ".spindrel/project-runbook.md",
    )
    checked = {
        "AGENTS.md": _read("AGENTS.md"),
        ".spindrel/WORKFLOW.md": _read(".spindrel/WORKFLOW.md"),
        "docs/guides/projects.md": _read("docs/guides/projects.md"),
        "skills/project/setup/init.md": _read("skills/project/setup/init.md"),
    }

    offenders: list[str] = []
    for path, text in checked.items():
        for needle in forbidden:
            if needle in text:
                offenders.append(f"{path}: {needle}")

    assert offenders == []


def test_project_runbook_pointer_file_is_not_maintained():
    assert not (ROOT / ".spindrel/project-runbook.md").exists()


def test_track_status_values_match_track_contract():
    allowed = {"active", "complete", "superseded"}
    offenders: list[str] = []

    for path in sorted((ROOT / "docs/tracks").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        match = re.search(r"^status:\s*([^\n]+)", text, re.MULTILINE)
        if not match:
            offenders.append(f"{path.relative_to(ROOT)}: missing status")
            continue
        status = match.group(1).strip().split()[0]
        if status not in allowed:
            offenders.append(f"{path.relative_to(ROOT)}: {status}")

    assert offenders == []
