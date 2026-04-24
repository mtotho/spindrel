"""Test data factories.

Every factory returns a real ORM model instance with sensible defaults and
accepts field overrides via kwargs. Use these instead of constructing models
inline with 10 kwargs, and instead of ``MagicMock()`` stand-ins.
"""
from tests.factories.attachments import build_attachment
from tests.factories.bot_hooks import build_bot_hook
from tests.factories.bot_skills import build_bot_skill
from tests.factories.bots import build_bot
from tests.factories.channels import build_channel, build_channel_bot_member
from tests.factories.docker_stacks import build_docker_stack
from tests.factories.integration_manifests import build_integration_manifest
from tests.factories.mcp_servers import build_mcp_server
from tests.factories.prompt_templates import build_prompt_template
from tests.factories.providers import build_provider_config, build_provider_model
from tests.factories.secret_values import build_secret_value
from tests.factories.skills import build_bot_skill_enrollment, build_skill
from tests.factories.tasks import build_task
from tests.factories.usage_limits import build_usage_limit
from tests.factories.webhooks import build_webhook_endpoint
from tests.factories.workflows import build_workflow, build_workflow_run

__all__ = [
    "build_attachment",
    "build_bot",
    "build_bot_hook",
    "build_bot_skill",
    "build_bot_skill_enrollment",
    "build_channel",
    "build_channel_bot_member",
    "build_docker_stack",
    "build_integration_manifest",
    "build_mcp_server",
    "build_prompt_template",
    "build_provider_config",
    "build_provider_model",
    "build_secret_value",
    "build_skill",
    "build_task",
    "build_usage_limit",
    "build_webhook_endpoint",
    "build_workflow",
    "build_workflow_run",
]
