"""Test data factories.

Every factory returns a real ORM model instance with sensible defaults and
accepts field overrides via kwargs. Use these instead of constructing models
inline with 10 kwargs, and instead of ``MagicMock()`` stand-ins.

See ``~/.claude/skills/testing-python/SKILL.md`` sections C and G.
"""
from tests.factories.bots import build_bot
from tests.factories.channels import build_channel, build_channel_bot_member
from tests.factories.prompt_templates import build_prompt_template
from tests.factories.skills import build_bot_skill_enrollment, build_skill
from tests.factories.tasks import build_task
from tests.factories.workflows import build_workflow, build_workflow_run

__all__ = [
    "build_bot",
    "build_bot_skill_enrollment",
    "build_channel",
    "build_channel_bot_member",
    "build_prompt_template",
    "build_skill",
    "build_task",
    "build_workflow",
    "build_workflow_run",
]
