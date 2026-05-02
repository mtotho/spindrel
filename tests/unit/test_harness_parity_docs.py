from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PARITY_DOC = REPO_ROOT / "docs" / "guides" / "harness-parity.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_harness_parity_guide_is_linked_from_public_docs() -> None:
    harness_guide = _read(REPO_ROOT / "docs" / "guides" / "agent-harnesses.md")
    integration_status = _read(REPO_ROOT / "docs" / "guides" / "integration-status.md")

    assert "harness-parity.md" in harness_guide
    assert "harness-parity.md" in integration_status


def test_harness_parity_matrix_covers_critical_native_surfaces() -> None:
    body = _read(PARITY_DOC)

    required_terms = [
        "Native turn loop",
        "Native slash commands",
        "`/context`",
        "`/compact`",
        "Model and effort",
        "Permissions and approvals",
        "Todo/progress tools",
        "Tool discovery",
        "Subagents/background agents",
        "Skills",
        "Plugins and marketplaces",
        "MCP",
        "Hooks",
        "Images and attachments",
        "Project instruction discovery",
        "Native CLI mirror",
        "Usage, context, latency",
        "Spindrel bridge tools",
    ]

    missing = [term for term in required_terms if term not in body]
    assert not missing, f"harness parity guide is missing rows: {missing}"

    assert "https://code.claude.com/docs/en/agent-sdk/overview" in body
    assert "https://developers.openai.com/codex/" in body
    assert "Terminal handoff" in body
    assert "Missing" in body


def test_harness_parity_guide_references_existing_screenshots() -> None:
    body = _read(PARITY_DOC)
    image_refs = set(re.findall(r"`?([A-Za-z0-9_./-]*harness[A-Za-z0-9_./-]*\.png)`?", body))

    assert image_refs, "parity guide should cite existing harness screenshot evidence"
    missing = [
        ref
        for ref in image_refs
        if not (REPO_ROOT / "docs" / "images" / ref).exists()
    ]
    assert not missing, f"parity guide references missing screenshots: {missing}"


def test_integration_status_no_longer_marks_codex_harness_untested() -> None:
    body = _read(REPO_ROOT / "docs" / "guides" / "integration-status.md")
    codex_row = next(line for line in body.splitlines() if line.startswith("| Codex |"))

    assert "`working (beta)`" in codex_row
    assert "`untested`" not in codex_row
