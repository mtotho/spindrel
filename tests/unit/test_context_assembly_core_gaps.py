"""Phase B.7 targeted sweep of context_assembly.py core gaps (#24, #25).

Covers:
  #24  invalidate_bot_skill_cache — per-bot vs all-clear branches
  #25  invalidate_skill_auto_enroll_cache — core/integration cache clear + silent exception swallow

No DB surface. Uses monkeypatch to manipulate module-level cache dicts and
restore them cleanly between tests (B.28).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

import app.agent.tool_surface.enrollment as ca


# ---------------------------------------------------------------------------
# Cache reset fixture — B.28: leaking cache state breaks subsequent tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_caches():
    """Clear all three module-level caches before and after each test."""
    ca._bot_skill_cache.clear()
    ca._core_skill_cache = None
    ca._integration_skill_cache.clear()
    yield
    ca._bot_skill_cache.clear()
    ca._core_skill_cache = None
    ca._integration_skill_cache.clear()


# ===========================================================================
# #24 — invalidate_bot_skill_cache
# ===========================================================================

class TestInvalidateBotSkillCache:
    def test_when_invalidate_by_bot_id_then_only_that_entry_removed(self):
        ca._bot_skill_cache["bot-a"] = (1.0, ["skills/s1"])
        ca._bot_skill_cache["bot-b"] = (1.0, ["skills/s2"])

        ca.invalidate_bot_skill_cache("bot-a")

        assert "bot-a" not in ca._bot_skill_cache
        assert "bot-b" in ca._bot_skill_cache

    def test_when_invalidate_by_bot_id_then_sibling_values_unchanged(self):
        ca._bot_skill_cache["bot-x"] = (9.9, ["skills/keep"])
        ca._bot_skill_cache["bot-target"] = (1.0, ["skills/remove"])

        ca.invalidate_bot_skill_cache("bot-target")

        assert ca._bot_skill_cache["bot-x"] == (9.9, ["skills/keep"])

    def test_when_invalidate_with_no_bot_id_then_all_entries_cleared(self):
        ca._bot_skill_cache["bot-a"] = (1.0, ["skills/s1"])
        ca._bot_skill_cache["bot-b"] = (1.0, ["skills/s2"])

        ca.invalidate_bot_skill_cache()

        assert ca._bot_skill_cache == {}

    def test_when_invalidate_missing_bot_id_then_no_error(self):
        ca._bot_skill_cache["bot-other"] = (1.0, ["skills/s1"])

        ca.invalidate_bot_skill_cache("bot-not-present")  # should not raise

        assert "bot-other" in ca._bot_skill_cache

    def test_when_cache_empty_and_invalidate_all_then_no_error(self):
        ca.invalidate_bot_skill_cache()  # must not raise on empty dict


# ===========================================================================
# #25 — invalidate_skill_auto_enroll_cache
# ===========================================================================

class TestInvalidateSkillAutoEnrollCache:
    def test_when_called_then_core_skill_cache_reset_to_none(self):
        ca._core_skill_cache = (1.0, ["skills/core"])

        ca.invalidate_skill_auto_enroll_cache()

        assert ca._core_skill_cache is None

    def test_when_called_then_integration_skill_cache_cleared(self):
        ca._integration_skill_cache["slack"] = (1.0, ["integrations/slack/s1"])

        ca.invalidate_skill_auto_enroll_cache()

        assert ca._integration_skill_cache == {}

    def test_when_called_then_enrolled_cache_also_invalidated(self):
        invalidated = []
        with patch(
            "app.services.skill_enrollment.invalidate_enrolled_cache",
            side_effect=lambda: invalidated.append(True),
        ):
            ca.invalidate_skill_auto_enroll_cache()

        assert invalidated  # ensure the call actually happened

    def test_when_invalidate_enrolled_cache_raises_then_exception_swallowed(self):
        with patch(
            "app.services.skill_enrollment.invalidate_enrolled_cache",
            side_effect=RuntimeError("enrollment service unavailable"),
        ):
            ca.invalidate_skill_auto_enroll_cache()  # must not propagate

        # Core/integration caches were still cleared despite the exception
        assert ca._core_skill_cache is None
        assert ca._integration_skill_cache == {}

    def test_when_import_fails_then_exception_swallowed(self):
        with patch.dict("sys.modules", {"app.services.skill_enrollment": None}):
            ca.invalidate_skill_auto_enroll_cache()  # must not raise

        assert ca._core_skill_cache is None
