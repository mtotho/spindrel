import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";
import { useAuthStore } from "../../stores/auth";

export interface AdminUserSummary {
  id: string;
  email: string;
  display_name: string;
  is_admin: boolean;
  is_active: boolean;
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
