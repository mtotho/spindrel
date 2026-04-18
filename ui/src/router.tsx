import { createBrowserRouter, Navigate, Outlet } from "react-router-dom";
import { lazy } from "react";
import { RootLayout } from "./layouts/RootLayout";
import { AppShell } from "./components/layout/AppShell";

// ---------------------------------------------------------------------------
// Lazy-loaded pages — keeps initial bundle small
// ---------------------------------------------------------------------------

// Auth
const LoginPage = lazy(() => import("@/app/(auth)/login"));
const SetupPage = lazy(() => import("@/app/(auth)/setup"));

// App root
const HomePage = lazy(() => import("@/app/(app)/index"));
const SettingsPage = lazy(() => import("@/app/(app)/settings"));
const ProfilePage = lazy(() => import("@/app/(app)/profile"));

// Channels
const NewChannelPage = lazy(() => import("@/app/(app)/channels/new"));
const ChannelPage = lazy(() => import("@/app/(app)/channels/[channelId]/index"));
const ChannelSettings = lazy(() => import("@/app/(app)/channels/[channelId]/settings"));

// Channel tabs / sub-components used as pages

// Integration
const IntegrationIndex = lazy(() => import("@/app/(app)/integration/[integrationId]/index"));
const IntegrationCatchAll = lazy(() => import("@/app/(app)/integration/[integrationId]/[...path]"));

// Admin
const AdminApiDocs = lazy(() => import("@/app/(app)/admin/api-docs"));
const AdminApiKeysIndex = lazy(() => import("@/app/(app)/admin/api-keys/index"));
const AdminApiKeyDetail = lazy(() => import("@/app/(app)/admin/api-keys/[keyId]/index"));
const AdminApprovals = lazy(() => import("@/app/(app)/admin/approvals/index"));
const AdminAttachments = lazy(() => import("@/app/(app)/admin/attachments/index"));
const AdminBotsIndex = lazy(() => import("@/app/(app)/admin/bots/index"));
const AdminBotDetail = lazy(() => import("@/app/(app)/admin/bots/[botId]/index"));
const AdminCaparacesIndex = lazy(() => import("@/app/(app)/admin/carapaces/index"));
const AdminCaparaceDetail = lazy(() => import("@/app/(app)/admin/carapaces/[carapaceId]"));
const AdminConfigState = lazy(() => import("@/app/(app)/admin/config-state"));
const AdminDelegations = lazy(() => import("@/app/(app)/admin/delegations"));
const AdminDiagnostics = lazy(() => import("@/app/(app)/admin/diagnostics/index"));
const AdminDockerStacks = lazy(() => import("@/app/(app)/admin/docker-stacks/index"));
const AdminDockerStackDetail = lazy(() => import("@/app/(app)/admin/docker-stacks/[stackId]"));
const AdminIntegrationsIndex = lazy(() => import("@/app/(app)/admin/integrations/index"));
const AdminIntegrationDetail = lazy(() => import("@/app/(app)/admin/integrations/[integrationId]/index"));
const AdminLearning = lazy(() => import("@/app/(app)/admin/learning/index"));
const AdminLogsIndex = lazy(() => import("@/app/(app)/admin/logs/index"));
const AdminLogsFallbacks = lazy(() => import("@/app/(app)/admin/logs/fallbacks"));
const AdminLogsServer = lazy(() => import("@/app/(app)/admin/logs/server"));
const AdminLogsTraces = lazy(() => import("@/app/(app)/admin/logs/traces"));
const AdminLogDetail = lazy(() => import("@/app/(app)/admin/logs/[correlationId]/index"));
const AdminMcpServers = lazy(() => import("@/app/(app)/admin/mcp-servers/index"));
const AdminMcpServerDetail = lazy(() => import("@/app/(app)/admin/mcp-servers/[serverId]/index"));
const AdminMemories = lazy(() => import("@/app/(app)/admin/memories"));
const AdminPromptTemplates = lazy(() => import("@/app/(app)/admin/prompt-templates/index"));
const AdminPromptTemplateDetail = lazy(() => import("@/app/(app)/admin/prompt-templates/[templateId]/index"));
const AdminProviders = lazy(() => import("@/app/(app)/admin/providers/index"));
const AdminProviderDetail = lazy(() => import("@/app/(app)/admin/providers/[providerId]/index"));
const AdminSandboxes = lazy(() => import("@/app/(app)/admin/sandboxes"));
const AdminSecretValues = lazy(() => import("@/app/(app)/admin/secret-values/index"));
const AdminSessions = lazy(() => import("@/app/(app)/admin/sessions/index"));
const AdminSkillsIndex = lazy(() => import("@/app/(app)/admin/skills/index"));
const AdminSkillDetail = lazy(() => import("@/app/(app)/admin/skills/[...skillId]/index"));
const AdminTasksIndex = lazy(() => import("@/app/(app)/admin/tasks/index"));
const AdminTaskDetail = lazy(() => import("@/app/(app)/admin/tasks/[taskId]/index"));
const AdminToolCalls = lazy(() => import("@/app/(app)/admin/tool-calls/index"));
const AdminToolPolicies = lazy(() => import("@/app/(app)/admin/tool-policies/index"));
const AdminToolPolicyDetail = lazy(() => import("@/app/(app)/admin/tool-policies/[ruleId]/index"));
const AdminToolsIndex = lazy(() => import("@/app/(app)/admin/tools/index"));
const AdminToolDetail = lazy(() => import("@/app/(app)/admin/tools/[toolId]/index"));
const AdminWidgetPackageEditor = lazy(() => import("@/app/(app)/admin/widget-packages/[packageId]/index"));

// Widgets (dashboard + developer panel)
const WidgetsDashboard = lazy(() => import("@/app/(app)/widgets/index"));
const WidgetsDevPanel = lazy(() => import("@/app/(app)/widgets/dev/index"));
const AdminUsage = lazy(() => import("@/app/(app)/admin/usage/index"));
const AdminUsers = lazy(() => import("@/app/(app)/admin/users"));
const AdminWebhooksIndex = lazy(() => import("@/app/(app)/admin/webhooks/index"));
const AdminWebhookDetail = lazy(() => import("@/app/(app)/admin/webhooks/[webhookId]/index"));
const AdminWorkflowsIndex = lazy(() => import("@/app/(app)/admin/workflows/index"));
const AdminWorkflowDetail = lazy(() => import("@/app/(app)/admin/workflows/[workflowId]"));
const AdminWorkspacesIndex = lazy(() => import("@/app/(app)/admin/workspaces/index"));
const AdminWorkspaceDetail = lazy(() => import("@/app/(app)/admin/workspaces/[workspaceId]/index"));
const AdminWorkspaceFiles = lazy(() => import("@/app/(app)/admin/workspaces/[workspaceId]/files"));

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

export const router = createBrowserRouter([
  {
    element: <RootLayout />,
    children: [
      // Auth routes (no AppShell)
      { path: "login", element: <LoginPage /> },
      { path: "setup", element: <SetupPage /> },

      // Authenticated routes (wrapped in AppShell)
      {
        element: <AppShell />,
        children: [
          { index: true, element: <HomePage /> },
          { path: "settings", element: <SettingsPage /> },
          { path: "profile", element: <ProfilePage /> },

          // Channels
          { path: "channels", element: <Navigate to="/" replace /> },
          { path: "channels/new", element: <NewChannelPage /> },
          {
            path: "channels/:channelId",
            element: <Outlet />,
            children: [
              { index: true, element: <ChannelPage /> },
              { path: "settings", element: <ChannelSettings /> },
              // Sub-routes for the pipeline run-view modal. The ChannelPage
              // detects these via useMatch and layers the modal on top —
              // the URL is the source of truth, but the chat subscription
              // stays mounted so closing the modal is instant.
              { path: "pipelines/:pipelineId", element: <ChannelPage /> },
              { path: "runs/:taskId", element: <ChannelPage /> },
            ],
          },

          // Integration embed
          {
            path: "integration/:integrationId",
            element: <Outlet />,
            children: [
              { index: true, element: <IntegrationIndex /> },
              { path: "*", element: <IntegrationCatchAll /> },
            ],
          },

          // Widgets — chat-less dashboard + developer panel
          { path: "widgets", element: <WidgetsDashboard /> },
          { path: "widgets/dev", element: <WidgetsDevPanel /> },

          // Admin
          {
            path: "admin",
            element: <Outlet />,
            children: [
              { path: "api-docs", element: <AdminApiDocs /> },
              { path: "api-keys", element: <AdminApiKeysIndex /> },
              { path: "api-keys/:keyId", element: <AdminApiKeyDetail /> },
              { path: "approvals", element: <AdminApprovals /> },
              { path: "attachments", element: <AdminAttachments /> },
              { path: "bots", element: <AdminBotsIndex /> },
              { path: "bots/:botId", element: <AdminBotDetail /> },
              { path: "carapaces", element: <AdminCaparacesIndex /> },
              { path: "carapaces/:carapaceId", element: <AdminCaparaceDetail /> },
              { path: "config-state", element: <AdminConfigState /> },
              { path: "delegations", element: <AdminDelegations /> },
              { path: "diagnostics", element: <AdminDiagnostics /> },
              { path: "docker-stacks", element: <AdminDockerStacks /> },
              { path: "docker-stacks/:stackId", element: <AdminDockerStackDetail /> },
              { path: "integrations", element: <AdminIntegrationsIndex /> },
              { path: "integrations/:integrationId", element: <AdminIntegrationDetail /> },
              { path: "learning", element: <AdminLearning /> },
              { path: "logs", element: <AdminLogsIndex /> },
              { path: "logs/fallbacks", element: <AdminLogsFallbacks /> },
              { path: "logs/server", element: <AdminLogsServer /> },
              { path: "logs/traces", element: <AdminLogsTraces /> },
              { path: "logs/:correlationId", element: <AdminLogDetail /> },
              { path: "mcp-servers", element: <AdminMcpServers /> },
              { path: "mcp-servers/:serverId", element: <AdminMcpServerDetail /> },
              { path: "memories", element: <AdminMemories /> },
              { path: "prompt-templates", element: <AdminPromptTemplates /> },
              { path: "prompt-templates/:templateId", element: <AdminPromptTemplateDetail /> },
              { path: "providers", element: <AdminProviders /> },
              { path: "providers/:providerId", element: <AdminProviderDetail /> },
              { path: "sandboxes", element: <AdminSandboxes /> },
              { path: "secret-values", element: <AdminSecretValues /> },
              { path: "sessions", element: <AdminSessions /> },
              { path: "skills", element: <AdminSkillsIndex /> },
              { path: "skills/*", element: <AdminSkillDetail /> },
              { path: "tasks", element: <AdminTasksIndex /> },
              { path: "tasks/:taskId", element: <AdminTaskDetail /> },
              { path: "tool-calls", element: <AdminToolCalls /> },
              { path: "tool-policies", element: <AdminToolPolicies /> },
              { path: "tool-policies/:ruleId", element: <AdminToolPolicyDetail /> },
              { path: "tools", element: <AdminToolsIndex /> },
              { path: "tools/:toolId", element: <AdminToolDetail /> },
              { path: "widget-packages/:packageId", element: <AdminWidgetPackageEditor /> },
              { path: "widget-packages", element: <Navigate to="/admin/tools?tab=library" replace /> },
              { path: "upcoming", element: <Navigate to="/admin/tasks?view=list" replace /> },
              { path: "usage", element: <AdminUsage /> },
              { path: "users", element: <AdminUsers /> },
              { path: "webhooks", element: <AdminWebhooksIndex /> },
              { path: "webhooks/:webhookId", element: <AdminWebhookDetail /> },
              { path: "workflows", element: <AdminWorkflowsIndex /> },
              { path: "workflows/:workflowId", element: <AdminWorkflowDetail /> },
              { path: "workspaces", element: <AdminWorkspacesIndex /> },
              { path: "workspaces/:workspaceId", element: <AdminWorkspaceDetail /> },
              { path: "workspaces/:workspaceId/files", element: <AdminWorkspaceFiles /> },
            ],
          },
        ],
      },
    ],
  },
]);
