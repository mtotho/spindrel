import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type {
  ResolvedWidgetThemeResponse,
  WidgetTheme,
  WidgetThemeDefaultResponse,
} from "../../types/api";

export interface WidgetThemeDraft {
  name: string;
  slug?: string | null;
  light_tokens?: Record<string, string> | null;
  dark_tokens?: Record<string, string> | null;
  custom_css?: string | null;
}

export function useWidgetThemes() {
  return useQuery({
    queryKey: ["widget-themes"],
    queryFn: () => apiFetch<WidgetTheme[]>("/api/v1/admin/widget-themes"),
  });
}

export function useWidgetTheme(themeRef: string | undefined) {
  return useQuery({
    queryKey: ["widget-themes", themeRef],
    queryFn: () => apiFetch<WidgetTheme>(`/api/v1/admin/widget-themes/${encodeURIComponent(themeRef!)}`),
    enabled: !!themeRef,
  });
}

export function useWidgetThemeDefault() {
  return useQuery({
    queryKey: ["widget-theme-default"],
    queryFn: () => apiFetch<WidgetThemeDefaultResponse>("/api/v1/admin/widget-theme-default"),
  });
}

export function useResolvedWidgetTheme(channelId?: string | null) {
  return useQuery({
    queryKey: ["resolved-widget-theme", channelId ?? null],
    queryFn: () => apiFetch<ResolvedWidgetThemeResponse>(
      `/api/v1/widgets/themes/resolve${channelId ? `?channel_id=${encodeURIComponent(channelId)}` : ""}`,
    ),
  });
}

export function useCreateWidgetTheme() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (draft: WidgetThemeDraft) =>
      apiFetch<WidgetTheme>("/api/v1/admin/widget-themes", {
        method: "POST",
        body: JSON.stringify(draft),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["widget-themes"] });
    },
  });
}

export function useUpdateWidgetTheme(themeRef: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (draft: Partial<WidgetThemeDraft>) =>
      apiFetch<WidgetTheme>(`/api/v1/admin/widget-themes/${encodeURIComponent(themeRef)}`, {
        method: "PUT",
        body: JSON.stringify(draft),
      }),
    onSuccess: (_data, _vars) => {
      qc.invalidateQueries({ queryKey: ["widget-themes"] });
      qc.invalidateQueries({ queryKey: ["widget-themes", themeRef] });
      qc.invalidateQueries({ queryKey: ["resolved-widget-theme"] });
    },
  });
}

export function useDeleteWidgetTheme() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (themeRef: string) =>
      apiFetch(`/api/v1/admin/widget-themes/${encodeURIComponent(themeRef)}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["widget-themes"] });
      qc.invalidateQueries({ queryKey: ["resolved-widget-theme"] });
    },
  });
}

export function useForkWidgetTheme(sourceRef: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, slug }: { name: string; slug?: string | null }) =>
      apiFetch<WidgetTheme>(`/api/v1/admin/widget-themes/${encodeURIComponent(sourceRef)}/fork`, {
        method: "POST",
        body: JSON.stringify({ name, slug }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["widget-themes"] });
    },
  });
}

export function useSetWidgetThemeDefault() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ref: string) =>
      apiFetch<WidgetThemeDefaultResponse>("/api/v1/admin/widget-theme-default", {
        method: "PUT",
        body: JSON.stringify({ ref }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["widget-theme-default"] });
      qc.invalidateQueries({ queryKey: ["resolved-widget-theme"] });
    },
  });
}
