import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";
import { useAuthStore } from "../../stores/auth";

export interface AdminUserSummary {
  id: string;
  email: string;
  display_name: string;
  avatar_url?: string | null;
  is_admin: boolean;
  is_active: boolean;
}

export interface UserActivityLatestSession {
  session_id: string;
  channel_id: string;
  channel_name: string;
  label: string | null;
  preview: string | null;
  last_active: string | null;
  message_count: number;
  section_count: number;
}

export interface UserActivitySummary extends AdminUserSummary {
  today_message_count: number;
  today_session_count: number;
  today_channel_count: number;
  latest_activity_at: string | null;
  latest_session: UserActivityLatestSession | null;
}

export interface AdminUserActivitySummaryResponse {
  users: UserActivitySummary[];
}

export function useAdminUsers(enabled: boolean = true) {
  const isAdmin = !!useAuthStore((s) => s.user?.is_admin);
  return useQuery({
    queryKey: ["admin-users"],
    queryFn: () => apiFetch<AdminUserSummary[]>("/api/v1/admin/users"),
    enabled: enabled && isAdmin,
    staleTime: 60_000,
  });
}

export function useAdminUserActivitySummary(limit: number = 6, enabled: boolean = true) {
  const isAdmin = !!useAuthStore((s) => s.user?.is_admin);
  return useQuery({
    queryKey: ["admin-users", "activity-summary", limit],
    queryFn: () => apiFetch<AdminUserActivitySummaryResponse>(`/api/v1/admin/users/activity-summary?limit=${limit}`),
    enabled: enabled && isAdmin,
    staleTime: 30_000,
  });
}
