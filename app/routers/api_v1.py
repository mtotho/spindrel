"""Public integration API — /api/v1/"""
from fastapi import APIRouter

from app.routers.api_v1_admin import router as admin_router
from app.routers.api_v1_admin_terminal import router as admin_terminal_router
from app.routers.api_v1_attachments import router as attachments_router
from app.routers.api_v1_channels import router as channels_router
from app.routers.api_v1_documents import router as documents_router
from app.routers.api_v1_sessions import router as sessions_router
from app.routers.api_v1_tasks import router as tasks_router
from app.routers.api_v1_todos import router as todos_router
from app.routers.api_v1_users import router as users_router
from app.routers.api_v1_prompt_templates import router as prompt_templates_router
from app.routers.api_v1_discover import router as discover_router
from app.routers.api_v1_workspaces import router as workspaces_router
from app.routers.api_v1_channel_workspace import router as channel_workspace_router
from app.routers.api_v1_tool_calls import router as tool_calls_router
from app.routers.api_v1_tool_policies import router as tool_policies_router
from app.routers.api_v1_bot_hooks import router as bot_hooks_router
from app.routers.api_v1_approvals import router as approvals_router
from app.routers.api_v1_llm import router as llm_router
from app.routers.api_v1_modals import router as modals_router
from app.routers.api_v1_search import router as search_router
from app.routers.api_v1_widget_actions import router as widget_actions_router
from app.routers.api_v1_widget_auth import router as widget_auth_router
from app.routers.api_v1_widget_debug import router as widget_debug_router
from app.routers.api_v1_tools import router as tools_router
from app.routers.api_v1_widgets import router as dashboard_router
from app.routers.api_v1_workspace_attention import router as workspace_attention_router
from app.routers.api_v1_workspace_command_center import router as workspace_command_center_router
from app.routers.api_v1_workspace_spatial import router as workspace_spatial_router
from app.routers.api_v1_system_health import router as system_health_router
from app.routers.api_v1_push import router as push_router, presence_router
from app.routers.api_v1_favicon import router as favicon_router
from app.routers.api_v1_internal_tools import router as internal_tools_router
from app.routers.api_v1_messages import router as messages_router
from app.routers.api_v1_runtimes import router as runtimes_router
from app.routers.api_v1_slash_commands import router as slash_commands_router
from app.routers.api_v1_unread import router as unread_router

router = APIRouter(prefix="/api/v1")
router.include_router(admin_router)
router.include_router(admin_terminal_router)
router.include_router(approvals_router)
router.include_router(attachments_router)
router.include_router(channels_router)
router.include_router(discover_router)
router.include_router(documents_router)
router.include_router(prompt_templates_router)
router.include_router(sessions_router)
router.include_router(tasks_router)
router.include_router(todos_router)
router.include_router(tool_calls_router)
router.include_router(tool_policies_router)
router.include_router(bot_hooks_router)
router.include_router(users_router)
router.include_router(workspaces_router)
router.include_router(channel_workspace_router)
router.include_router(llm_router)
router.include_router(modals_router)
router.include_router(search_router)
router.include_router(widget_actions_router)
router.include_router(widget_auth_router)
router.include_router(widget_debug_router)
router.include_router(tools_router)
router.include_router(dashboard_router)
router.include_router(workspace_attention_router)
router.include_router(workspace_command_center_router)
router.include_router(workspace_spatial_router)
router.include_router(system_health_router)
router.include_router(push_router)
router.include_router(presence_router)
router.include_router(favicon_router)
router.include_router(internal_tools_router)
router.include_router(messages_router)
router.include_router(runtimes_router)
router.include_router(slash_commands_router)
router.include_router(unread_router)
