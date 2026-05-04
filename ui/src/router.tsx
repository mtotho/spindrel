import { createBrowserRouter, Navigate, Outlet, useLocation, useParams } from "react-router-dom";
import { lazy } from "react";
import { RootLayout } from "./layouts/RootLayout";
import { AppShell } from "./components/layout/AppShell";
import { AdminRoute } from "./components/routing/AdminRoute";
import { useIsAdmin } from "./hooks/useScope";

/** Legacy redirect: `/admin/widget-packages/:packageId` → `/widgets/dev?id=...#templates`.
 *  The editor now lives inside the Widget dev panel as the Templates tab. */
function AdminWidgetPackageRedirect() {
  const { packageId } = useParams<{ packageId: string }>();
  if (!packageId) return <Navigate to="/widgets/dev#library" replace />;
  return <Navigate to={`/widgets/dev?id=${packageId}#templates`} replace />;
}

function ChannelDashboardSettingsRedirect() {
  const { channelId } = useParams<{ channelId: string }>();
  if (!channelId) return <Navigate to="/widgets" replace />;
  return <Navigate to={`/channels/${channelId}/settings?from=dashboard#dashboard`} replace />;
}

function RedirectToAutomation() {
  const { taskId } = useParams<{ taskId: string }>();
  if (!taskId) return <Navigate to="/admin/automations" replace />;
  return <Navigate to={`/admin/automations/${taskId}`} replace />;
}

function SettingsIndexRedirect() {
  const isAdmin = useIsAdmin();
  const { hash } = useLocation();
  return <Navigate to={`${isAdmin ? "/settings/system" : "/settings/account"}${hash}`} replace />;
}

// ---------------------------------------------------------------------------
// Lazy-loaded pages — keeps initial bundle small
// ---------------------------------------------------------------------------

// Auth
const LoginPage = lazy(() => import("@/app/(auth)/login"));
const SetupPage = lazy(() => import("@/app/(auth)/setup"));

// App root
const HomePage = lazy(() => import("@/app/(app)/index"));
const CanvasPage = lazy(() => import("@/app/(app)/canvas"));
const SpatialPage = lazy(() => import("@/app/(app)/spatial"));
const HubCommandCenterPage = lazy(() => import("@/app/(app)/hub/command-center"));
const HubAttentionPage = lazy(() => import("@/app/(app)/hub/attention"));
const HubDailyHealthPage = lazy(() => import("@/app/(app)/hub/daily-health"));
const HubContextBloatPage = lazy(() => import("@/app/(app)/hub/context-bloat"));
const SettingsShell = lazy(() =>
  import("@/app/(app)/settings/SettingsShell").then((m) => ({
    default: m.SettingsShell,
  })),
);
const SettingsAccountPage = lazy(() => import("@/app/(app)/settings/account"));
const SettingsChannelsPage = lazy(() => import("@/app/(app)/settings/channels"));
const SettingsBotsPage = lazy(() => import("@/app/(app)/settings/bots"));
const SettingsSystemPage = lazy(() => import("@/app/(app)/settings/system"));

// Channels
const NewChannelPage = lazy(() => import("@/app/(app)/channels/new"));
const ChannelPage = lazy(() => import("@/app/(app)/channels/[channelId]/index"));
const ChannelSettings = lazy(() => import("@/app/(app)/channels/[channelId]/settings"));
const NoteWorkspacePage = lazy(() => import("@/app/(app)/channels/[channelId]/NoteWorkspacePage"));

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
const AdminConfigState = lazy(() => import("@/app/(app)/admin/config-state"));
const AdminDelegations = lazy(() => import("@/app/(app)/admin/delegations"));
const AdminDiagnostics = lazy(() => import("@/app/(app)/admin/diagnostics/index"));
const AdminDockerStacks = lazy(() => import("@/app/(app)/admin/docker-stacks/index"));
const AdminDockerStackDetail = lazy(() => import("@/app/(app)/admin/docker-stacks/[stackId]"));
const AdminFeedback = lazy(() => import("@/app/(app)/admin/feedback"));
const AdminHarnesses = lazy(() => import("@/app/(app)/admin/harnesses/index"));
const AdminIntegrationsIndex = lazy(() => import("@/app/(app)/admin/integrations/index"));
const AdminIntegrationDetail = lazy(() => import("@/app/(app)/admin/integrations/[integrationId]/index"));
const AdminLearning = lazy(() => import("@/app/(app)/admin/learning/index"));
const AdminLogsIndex = lazy(() => import("@/app/(app)/admin/logs/index"));
const AdminLogsFallbacks = lazy(() => import("@/app/(app)/admin/logs/fallbacks"));
const AdminLogsServer = lazy(() => import("@/app/(app)/admin/logs/server"));
const AdminLogsTraces = lazy(() => import("@/app/(app)/admin/logs/traces"));
const AdminLogDetail = lazy(() => import("@/app/(app)/admin/logs/[correlationId]/index"));
const AdminMachines = lazy(() => import("@/app/(app)/admin/machines/index"));
const AdminMcpServers = lazy(() => import("@/app/(app)/admin/mcp-servers/index"));
const AdminMcpServerDetail = lazy(() => import("@/app/(app)/admin/mcp-servers/[serverId]/index"));
const AdminMemories = lazy(() => import("@/app/(app)/admin/memories"));
const AdminNotifications = lazy(() => import("@/app/(app)/admin/notifications/index"));
const AdminPromptTemplates = lazy(() => import("@/app/(app)/admin/prompt-templates/index"));
const AdminPromptTemplateDetail = lazy(() => import("@/app/(app)/admin/prompt-templates/[templateId]/index"));
const AdminProjectsIndex = lazy(() => import("@/app/(app)/admin/projects/index"));
const AdminProjectBlueprintsIndex = lazy(() => import("@/app/(app)/admin/projects/blueprints/index"));
const AdminProjectBlueprintDetail = lazy(() => import("@/app/(app)/admin/projects/blueprints/[blueprintId]/index"));
const AdminProjectDetail = lazy(() => import("@/app/(app)/admin/projects/[projectId]/index"));
const AdminProjectRunDetail = lazy(() => import("@/app/(app)/admin/projects/[projectId]/runs/[taskId]/index"));
const AdminProjectRunLive = lazy(() => import("@/app/(app)/admin/projects/[projectId]/runs/[taskId]/live"));
const AdminProviders = lazy(() => import("@/app/(app)/admin/providers/index"));
const AdminProviderDetail = lazy(() => import("@/app/(app)/admin/providers/[providerId]/index"));
const AdminSandboxes = lazy(() => import("@/app/(app)/admin/sandboxes"));
const AdminSecretValues = lazy(() => import("@/app/(app)/admin/secret-values/index"));
const AdminSessions = lazy(() => import("@/app/(app)/admin/sessions/index"));
const AdminSkillsIndex = lazy(() => import("@/app/(app)/admin/skills/index"));
const AdminTerminal = lazy(() => import("@/app/(app)/admin/terminal/index"));
const AdminSkillDetail = lazy(() => import("@/app/(app)/admin/skills/[...skillId]/index"));
const AdminTasksIndex = lazy(() => import("@/app/(app)/admin/tasks/index"));
const AdminTaskDetail = lazy(() => import("@/app/(app)/admin/tasks/[taskId]/index"));
const AdminToolCalls = lazy(() => import("@/app/(app)/admin/tool-calls/index"));
const AdminToolPolicies = lazy(() => import("@/app/(app)/admin/tool-policies/index"));
const AdminToolPolicyDetail = lazy(() => import("@/app/(app)/admin/tool-policies/[ruleId]/index"));
const AdminToolsIndex = lazy(() => import("@/app/(app)/admin/tools/index"));
const AdminToolDetail = lazy(() => import("@/app/(app)/admin/tools/[toolId]/index"));
// Widgets (dashboard + developer panel)
const WidgetsDashboard = lazy(() => import("@/app/(app)/widgets/index"));
const WidgetPinPage = lazy(() => import("@/app/(app)/widgets/pins/[pinId]"));
const WidgetsDevPanel = lazy(() => import("@/app/(app)/widgets/dev/index"));
const WidgetAuthoringRuntimePreview = lazy(() => import("@/app/(app)/widgets/dev/runtime-preview"));
const WidgetsRedirect = lazy(() => import("@/app/(app)/widgets/WidgetsRedirect"));
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
      // Routes without AppShell. Runtime preview stays isolated so browser
      // smoke checks do not pick up sidebar/background polling noise.
      { path: "login", element: <LoginPage /> },
      { path: "setup", element: <SetupPage /> },
      { path: "widgets/dev/runtime-preview", element: <WidgetAuthoringRuntimePreview /> },

      // Authenticated routes (wrapped in AppShell)
      {
        element: <AppShell />,
        children: [
          { index: true, element: <HomePage /> },
          { path: "spatial", element: <SpatialPage /> },
          { path: "canvas", element: <CanvasPage /> },
          { path: "hub/mission-control", element: <HubCommandCenterPage /> },
          { path: "hub/command-center", element: <HubCommandCenterPage /> },
          { path: "hub/attention", element: <HubAttentionPage /> },
          { path: "hub/daily-health", element: <HubDailyHealthPage /> },
          { path: "hub/context-bloat", element: <HubContextBloatPage /> },
          {
            path: "settings",
            element: <SettingsShell />,
            children: [
              { index: true, element: <SettingsIndexRedirect /> },
              { path: "account", element: <SettingsAccountPage /> },
              { path: "channels", element: <SettingsChannelsPage /> },
              { path: "bots", element: <SettingsBotsPage /> },
              { path: "system", element: <AdminRoute><SettingsSystemPage /></AdminRoute> },
            ],
          },
          { path: "profile", element: <Navigate to="/settings/account" replace /> },

          // Channels
          { path: "channels", element: <Navigate to="/" replace /> },
          { path: "channels/new", element: <NewChannelPage /> },
          {
            path: "channels/:channelId",
            element: <Outlet />,
            children: [
              { index: true, element: <ChannelPage /> },
              { path: "settings", element: <ChannelSettings /> },
              { path: "notes/:slug", element: <NoteWorkspacePage /> },
              // Sub-routes for the pipeline run-view modal. The ChannelPage
              // detects these via useMatch and layers the modal on top —
              // the URL is the source of truth, but the chat subscription
              // stays mounted so closing the modal is instant.
              { path: "pipelines/:pipelineId", element: <ChannelPage /> },
              { path: "runs/:taskId", element: <ChannelPage /> },
              // Full-screen thread view — renders a channel-chat-shaped
              // screen against the thread session with a "Replying to …"
              // header + close-X that returns to the channel.
              { path: "threads/:threadSessionId", element: <ChannelPage /> },
              // Session sub-view. `?scratch=true` = scratch-session full-page.
              // Path is deliberately generic so future session-switching
              // (non-scratch) flavors can share this route.
              { path: "session/:sessionId", element: <ChannelPage /> },
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

          // Widgets — chat-less dashboard + developer panel.
          // `widgets/channel/:channelId` is a friendly alias for the implicit
          // channel dashboard (slug `channel:<channelId>`) — keeps the URL
          // readable while the underlying row is the same.
          { path: "widgets", element: <WidgetsRedirect /> },
          { path: "widgets/dev", element: <WidgetsDevPanel /> },
          { path: "widgets/channel/:channelId/settings", element: <ChannelDashboardSettingsRedirect /> },
          { path: "widgets/channel/:channelId", element: <WidgetsDashboard /> },
          { path: "widgets/pins/:pinId", element: <WidgetPinPage /> },
          { path: "widgets/:slug", element: <WidgetsDashboard /> },

          // Admin — gated to is_admin users. Non-admins see UnauthorizedCard
          // regardless of which sub-route they land on. Backend also 403s via
          // `verify_admin_auth` on every `/api/v1/admin/*` endpoint.
          {
            path: "admin",
            element: <AdminRoute><Outlet /></AdminRoute>,
            children: [
              { path: "api-docs", element: <AdminApiDocs /> },
              { path: "api-keys", element: <AdminApiKeysIndex /> },
              { path: "api-keys/:keyId", element: <AdminApiKeyDetail /> },
              { path: "approvals", element: <AdminApprovals /> },
              { path: "attachments", element: <AdminAttachments /> },
              { path: "bots", element: <AdminBotsIndex /> },
              { path: "bots/:botId", element: <AdminBotDetail /> },
              { path: "config-state", element: <AdminConfigState /> },
              { path: "system-health", element: <Navigate to="/hub/daily-health" replace /> },
              { path: "delegations", element: <AdminDelegations /> },
              { path: "diagnostics", element: <AdminDiagnostics /> },
              { path: "docker-stacks", element: <AdminDockerStacks /> },
              { path: "docker-stacks/:stackId", element: <AdminDockerStackDetail /> },
              { path: "feedback", element: <AdminFeedback /> },
              { path: "harnesses", element: <AdminHarnesses /> },
              { path: "integrations", element: <AdminIntegrationsIndex /> },
              { path: "integrations/:integrationId", element: <AdminIntegrationDetail /> },
              { path: "learning", element: <AdminLearning /> },
              { path: "logs", element: <AdminLogsIndex /> },
              { path: "logs/fallbacks", element: <AdminLogsFallbacks /> },
              { path: "logs/server", element: <AdminLogsServer /> },
              { path: "logs/traces", element: <AdminLogsTraces /> },
              { path: "logs/:correlationId", element: <AdminLogDetail /> },
              { path: "machines", element: <AdminMachines /> },
              { path: "mcp-servers", element: <AdminMcpServers /> },
              { path: "mcp-servers/:serverId", element: <AdminMcpServerDetail /> },
              { path: "memories", element: <AdminMemories /> },
              { path: "notifications", element: <AdminNotifications /> },
              { path: "prompt-templates", element: <AdminPromptTemplates /> },
              { path: "prompt-templates/:templateId", element: <AdminPromptTemplateDetail /> },
              { path: "projects", element: <AdminProjectsIndex /> },
              { path: "projects/blueprints", element: <AdminProjectBlueprintsIndex /> },
              { path: "projects/blueprints/:blueprintId", element: <AdminProjectBlueprintDetail /> },
              { path: "projects/:projectId/runs/:taskId", element: <AdminProjectRunDetail /> },
              { path: "projects/:projectId/runs/:taskId/live", element: <AdminProjectRunLive /> },
              { path: "projects/:projectId", element: <AdminProjectDetail /> },
              { path: "providers", element: <AdminProviders /> },
              { path: "providers/:providerId", element: <AdminProviderDetail /> },
              { path: "sandboxes", element: <AdminSandboxes /> },
              { path: "secret-values", element: <AdminSecretValues /> },
              { path: "sessions", element: <AdminSessions /> },
              { path: "skills", element: <AdminSkillsIndex /> },
              { path: "skills/*", element: <AdminSkillDetail /> },
              { path: "automations", element: <AdminTasksIndex /> },
              { path: "automations/:taskId", element: <AdminTaskDetail /> },
              { path: "tasks", element: <Navigate to="/admin/automations" replace /> },
              { path: "tasks/:taskId", element: <RedirectToAutomation /> },
              { path: "terminal", element: <AdminTerminal /> },
              { path: "tool-calls", element: <AdminToolCalls /> },
              { path: "tool-policies", element: <AdminToolPolicies /> },
              { path: "tool-policies/:ruleId", element: <AdminToolPolicyDetail /> },
              { path: "tools", element: <AdminToolsIndex /> },
              { path: "tools/:toolId", element: <AdminToolDetail /> },
              { path: "widget-packages/:packageId", element: <AdminWidgetPackageRedirect /> },
              { path: "widget-packages", element: <Navigate to="/widgets/dev#library" replace /> },
              { path: "upcoming", element: <Navigate to="/admin/automations?view=list" replace /> },
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
