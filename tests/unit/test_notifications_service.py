from unittest.mock import MagicMock

from app.services.notifications import bot_can_use_target, normalize_slug


def test_bot_can_use_target_requires_enabled_allowlist():
    target = MagicMock()
    target.enabled = True
    target.allowed_bot_ids = ["ops-bot"]

    assert bot_can_use_target(target, "ops-bot") is True
    assert bot_can_use_target(target, "other-bot") is False
    assert bot_can_use_target(target, None) is False

    target.enabled = False
    assert bot_can_use_target(target, "ops-bot") is False


def test_normalize_slug_falls_back_for_blank_input():
    assert normalize_slug("Ops Alerts!") == "ops-alerts"
    assert normalize_slug("   ").startswith("target-")
