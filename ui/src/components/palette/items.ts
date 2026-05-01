import { useMemo } from "react";
import { useChannels } from "../../api/hooks/useChannels";
import { useBots } from "../../api/hooks/useBots";
import { useSidebarSections, useIntegrations } from "../../api/hooks/useIntegrations";
import { useProviders } from "../../api/hooks/useProviders";
import { useMCPServers } from "../../api/hooks/useMCPServers";
import { useTools } from "../../api/hooks/useTools";
import { usePromptTemplates } from "../../api/hooks/usePromptTemplates";
import { useWebhooks } from "../../api/hooks/useWebhooks";
import { useApiKeys } from "../../api/hooks/useApiKeys";
import { useToolPolicies } from "../../api/hooks/useToolPolicies";
import { useDockerStacks } from "../../api/hooks/useDockerStacks";
import { useWorkflows } from "../../api/hooks/useWorkflows";
import { useWorkspaces } from "../../api/hooks/useWorkspaces";
import { useProjectBlueprints, useProjects } from "../../api/hooks/useProjects";
import { useTraces } from "../../api/hooks/useLogs";
import { useIsAdmin } from "../../hooks/useScope";
import { useDashboards } from "../../stores/dashboards";
import type { PaletteItem } from "./types";
import { buildPaletteItems } from "./catalog.js";

/**
 * Build the flat list of palette items from live data + static catalogs.
 * Consumed by both the Ctrl+K command palette overlay and the home-page grid.
 */
export function usePaletteItems(): PaletteItem[] {
  const isAdmin = useIsAdmin();
  const { data: channels } = useChannels();
  const { data: bots } = useBots();
  const { data: sidebarData } = useSidebarSections(isAdmin);
  const { data: integrationsData } = useIntegrations(isAdmin);
  const { data: providersData } = useProviders(isAdmin);
  const { data: mcpServers } = useMCPServers(isAdmin);
  const { data: tools } = useTools(isAdmin);
  const { data: promptTemplates } = usePromptTemplates(undefined, undefined, isAdmin);
  const { data: webhooks } = useWebhooks(isAdmin);
  const { data: apiKeys } = useApiKeys(isAdmin);
  const { data: toolPolicies } = useToolPolicies(undefined, undefined, isAdmin);
  const { data: dockerStacks } = useDockerStacks(undefined, isAdmin);
  const { data: workflows } = useWorkflows(isAdmin);
  const { data: workspaces } = useWorkspaces(isAdmin);
  const { data: projects } = useProjects(isAdmin);
  const { data: projectBlueprints } = useProjectBlueprints(isAdmin);
  const { data: tracesData } = useTraces({ count: 20 }, isAdmin);
  const { list: dashboards, channelDashboards } = useDashboards();

  return useMemo(
    () =>
      buildPaletteItems({
        isAdmin,
        channels,
        bots,
        providers: providersData?.providers,
        mcpServers,
        tools,
        promptTemplates,
        webhooks,
        apiKeys,
        toolPolicies,
        dockerStacks,
        workflows,
        workspaces,
        projects: isAdmin ? projects : undefined,
        projectBlueprints: isAdmin ? projectBlueprints : undefined,
        dashboards: [...dashboards, ...channelDashboards],
        integrations: integrationsData?.integrations,
        sidebarSections: sidebarData?.sections,
        traces: tracesData?.traces,
      }),
    [
      apiKeys,
      bots,
      channelDashboards,
      channels,
      dashboards,
      dockerStacks,
      integrationsData?.integrations,
      isAdmin,
      mcpServers,
      promptTemplates,
      projectBlueprints,
      projects,
      providersData?.providers,
      sidebarData?.sections,
      toolPolicies,
      tools,
      tracesData?.traces,
      webhooks,
      workflows,
      workspaces,
    ],
  );
}

export { buildPaletteItems } from "./catalog.js";
