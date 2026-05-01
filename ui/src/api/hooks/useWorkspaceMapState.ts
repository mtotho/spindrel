import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";
export type {
  WorkspaceMapObjectKind,
  WorkspaceMapObjectState,
  WorkspaceMapObjectStatus,
  WorkspaceMapSeverity,
  WorkspaceMapSignal,
  WorkspaceMapState,
} from "../types/workspaceMapState";
import type { WorkspaceMapState } from "../types/workspaceMapState";

export const WORKSPACE_MAP_STATE_KEY = ["workspace-map-state"] as const;

export function useWorkspaceMapState(options?: { enabled?: boolean }) {
  const enabled = options?.enabled ?? true;
  return useQuery({
    queryKey: WORKSPACE_MAP_STATE_KEY,
    queryFn: () => apiFetch<WorkspaceMapState>("/api/v1/workspace/spatial/map-state"),
    enabled,
    refetchInterval: enabled ? 20_000 : false,
    staleTime: 8_000,
    refetchOnWindowFocus: false,
  });
}
