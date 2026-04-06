import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface SecurityCheck {
  id: string;
  category: string;
  severity: "critical" | "warning" | "info";
  status: "pass" | "fail" | "warning";
  message: string;
  recommendation?: string | null;
  details?: Record<string, any> | null;
}

export interface SecurityAuditResponse {
  checks: SecurityCheck[];
  summary: Record<string, number>;
  score: number;
}

export function useSecurityAudit() {
  return useQuery({
    queryKey: ["admin-security-audit"],
    queryFn: () =>
      apiFetch<SecurityAuditResponse>("/api/v1/admin/security-audit"),
    staleTime: 30_000,
  });
}
