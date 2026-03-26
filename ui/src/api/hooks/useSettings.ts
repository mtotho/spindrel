import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface SettingItem {
  key: string;
  label: string;
  description: string;
  type: "string" | "int" | "float" | "bool";
  value: any;
  default: any;
  overridden: boolean;
  read_only: boolean;
  options?: string[];
  min?: number;
  max?: number;
  nullable?: boolean;
  widget?: "model";
}

export interface SettingsGroup {
  group: string;
  settings: SettingItem[];
}

export interface SettingsResponse {
  groups: SettingsGroup[];
}

export function useSettings() {
  return useQuery({
    queryKey: ["admin-settings"],
    queryFn: () => apiFetch<SettingsResponse>("/api/v1/admin/settings"),
  });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (updates: Record<string, any>) =>
      apiFetch("/api/v1/admin/settings", {
        method: "PUT",
        body: JSON.stringify({ settings: updates }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-settings"] });
    },
  });
}

export function useResetSetting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (key: string) =>
      apiFetch(`/api/v1/admin/settings/${key}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-settings"] });
    },
  });
}
