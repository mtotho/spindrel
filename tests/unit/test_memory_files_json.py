from __future__ import annotations

from decimal import Decimal
import json
from types import SimpleNamespace

from app.tools.local.memory_files import _format_search_results


def test_format_search_results_serializes_decimal_scores():
    payload = _format_search_results([
        SimpleNamespace(
            file_path="memory/MEMORY.md",
            score=Decimal("0.87654"),
            content="# Memory\nBennie Loggins notes",
        )
    ])

    data = json.loads(payload)
    assert data["count"] == 1
    assert data["results"][0]["score"] == 0.877
    assert data["results"][0]["snippet"] == "Bennie Loggins notes"
