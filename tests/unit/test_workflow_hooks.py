"""Tests for workflow_hooks.register_workflow_hooks."""
from unittest.mock import patch

import pytest

from app.services.workflow_hooks import _on_task_complete, register_workflow_hooks


class TestRegisterWorkflowHooks:
    def test_when_called_then_registers_after_task_complete_hook(self):
        with patch("app.agent.hooks.register_hook") as mock_register:
            register_workflow_hooks()

        mock_register.assert_called_once_with("after_task_complete", _on_task_complete)


@pytest.mark.asyncio
class TestOnTaskComplete:
    async def test_when_called_then_is_no_op(self):
        result = await _on_task_complete({}, task=None, status=None)

        assert result is None
