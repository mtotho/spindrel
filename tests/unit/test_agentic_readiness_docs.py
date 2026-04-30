from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
LLMS_PATH = ROOT / "llms.txt"
README_PATH = ROOT / "README.md"


def test_llms_txt_exists_with_agentic_readiness_sections() -> None:
    assert LLMS_PATH.exists()
    text = LLMS_PATH.read_text(encoding="utf-8")

    for heading in (
        "## What this is",
        "## Quickstart",
        "## First API calls",
        "## Key concepts",
        "## Links",
    ):
        assert heading in text

    for endpoint in (
        "/openapi.json",
        "/api/v1/discover",
        "/api/v1/agent-capabilities",
        "/health",
    ):
        assert endpoint in text

    lowered = text.lower()
    assert "outside/dev agents" in lowered
    assert "in-app runtime agents" in lowered
    assert "repo-local `.agents/skills`" in lowered
    assert "not imported into runtime skill tables" in lowered


def test_readme_first_50_lines_are_agent_parseable() -> None:
    first_50 = "\n".join(README_PATH.read_text(encoding="utf-8").splitlines()[:50])

    for marker in (
        "### What it is",
        "### Problem it solves",
        "### Install",
        "### First call",
        "Expected output:",
    ):
        assert marker in first_50

    for required in (
        "bash setup.sh",
        "curl http://localhost:8000/health",
        "/llms.txt",
        "/openapi.json",
        "/api/v1/discover",
        "/api/v1/agent-capabilities",
    ):
        assert required in first_50


@pytest.mark.asyncio
async def test_llms_txt_route_serves_repo_file() -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/llms.txt")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == LLMS_PATH.read_text(encoding="utf-8")
