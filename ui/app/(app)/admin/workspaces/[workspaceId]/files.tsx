import { useEffect } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { useWorkspace } from "@/src/api/hooks/useWorkspaces";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { Spinner } from "@/src/components/shared/Spinner";
import { WorkspaceFileBrowserSurface } from "@/src/components/workspace/WorkspaceFileBrowserSurface";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { useFileBrowserStore } from "@/src/stores/fileBrowser";
import { useThemeTokens } from "@/src/theme/tokens";

const MOBILE_BREAKPOINT = 768;

export default function WorkspaceFileBrowser() {
  const t = useThemeTokens();
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const [searchParams] = useSearchParams();
  const { data: workspace, isLoading } = useWorkspace(workspaceId);
  const expandDir = useFileBrowserStore((s) => s.expandDir);
  const { width: windowWidth } = useWindowSize();
  const isMobile = windowWidth < MOBILE_BREAKPOINT;

  useEffect(() => {
    const requestedPath = searchParams.get("path");
    if (!requestedPath) return;
    const normalized = requestedPath.replace(/^\/+|\/+$/g, "");
    if (!normalized) return;
    const parts = normalized.split("/");
    for (let i = 1; i <= parts.length; i += 1) {
      expandDir(parts.slice(0, i).join("/"));
    }
  }, [expandDir, searchParams]);

  if (isLoading || !workspace) {
    return (
      <div style={{ display: "flex", flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: t.surface }}>
        <Spinner />
      </div>
    );
  }

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", background: t.surface, height: "100%" }}>
      {isMobile && <PageHeader variant="detail" title="Workspace" backTo={`/admin/workspaces/${workspaceId}`} />}
      <WorkspaceFileBrowserSurface workspace={workspace} settingsHref={`/admin/workspaces/${workspace.id}`} />
    </div>
  );
}
