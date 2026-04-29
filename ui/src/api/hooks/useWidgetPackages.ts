import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface WidgetPackageListItem {
  id: string;
  tool_name: string;
  name: string;
  description: string | null;
  source: "seed" | "user";
  is_readonly: boolean;
  is_active: boolean;
  is_orphaned: boolean;
  is_invalid: boolean;
  has_python_code: boolean;
  source_integration: string | null;
  group_kind?: "suite" | "package" | null;
  group_ref?: string | null;
  version: number;
  updated_at: string;
}

export interface WidgetPackage extends WidgetPackageListItem {
  yaml_template: string | null;
  python_code: string | null;
  sample_payload: Record<string, unknown> | null;
  invalid_reason: string | null;
  source_file: string | null;
  created_by: string | null;
  created_at: string;
}

export interface WidgetPackageCreateBody {
  tool_name: string;
  name: string;
  description?: string | null;
  yaml_template: string;
  python_code?: string | null;
  sample_payload?: Record<string, unknown> | null;
}

export interface WidgetPackageUpdateBody {
  name?: string;
  description?: string | null;
  yaml_template?: string;
  python_code?: string | null;
  sample_payload?: Record<string, unknown> | null;
}

export interface ValidationIssue {
  phase: "yaml" | "python" | "schema";
  message: string;
  line?: number | null;
  severity?: "error" | "warning";
}

export interface ValidateResponse {
  ok: boolean;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
}

export interface PreviewEnvelope {
  content_type: string;
  body: string;
  display: string;
  display_label?: string | null;
  refreshable: boolean;
  refresh_interval_seconds?: number | null;
  source_bot_id?: string | null;
  source_channel_id?: string | null;
}

export interface PreviewResponse {
  ok: boolean;
  envelope: PreviewEnvelope | null;
  errors: ValidationIssue[];
}

export interface AuthoringCheckPhase {
  name: string;
  status: "healthy" | "warning" | "failing" | "unknown" | string;
  message: string;
  duration_ms?: number | null;
}

export interface AuthoringCheckIssue extends Omit<ValidationIssue, "phase"> {
  phase: string;
  kind?: string;
  evidence?: Record<string, unknown> | null;
}

export interface AuthoringCheckResponse {
  ok: boolean;
  readiness: "ready" | "blocked" | "needs_attention" | "needs_runtime" | string;
  summary: string;
  phases: AuthoringCheckPhase[];
  issues: AuthoringCheckIssue[];
  envelope: PreviewEnvelope | null;
  artifacts?: {
    screenshot?: {
      mime_type: string;
      data_url: string;
    };
    bounds?: {
      width: number;
      height: number;
      top: number;
      left: number;
    };
  };
}

interface ListFilter {
  tool_name?: string;
  source?: "seed" | "user";
  include_orphaned?: boolean;
}

export function useWidgetPackages(filter?: ListFilter) {
  const params = new URLSearchParams();
  if (filter?.tool_name) params.set("tool_name", filter.tool_name);
  if (filter?.source) params.set("source", filter.source);
  if (filter?.include_orphaned) params.set("include_orphaned", "true");
  const qs = params.toString();
  return useQuery({
    queryKey: ["admin-widget-packages", filter ?? {}],
    queryFn: () =>
      apiFetch<WidgetPackageListItem[]>(
        qs ? `/api/v1/admin/widget-packages?${qs}` : "/api/v1/admin/widget-packages",
      ),
  });
}

export function useWidgetPackage(id: string | undefined) {
  return useQuery({
    queryKey: ["admin-widget-packages", id],
    queryFn: () => apiFetch<WidgetPackage>(`/api/v1/admin/widget-packages/${id}`),
    enabled: !!id,
  });
}

function invalidatePackageQueries(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["admin-widget-packages"] });
  qc.invalidateQueries({ queryKey: ["admin-tools"] });
  qc.invalidateQueries({ queryKey: ["admin-tool"] });
}

export function useCreateWidgetPackage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: WidgetPackageCreateBody) =>
      apiFetch<WidgetPackage>("/api/v1/admin/widget-packages", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => invalidatePackageQueries(qc),
  });
}

export function useUpdateWidgetPackage(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: WidgetPackageUpdateBody) =>
      apiFetch<WidgetPackage>(`/api/v1/admin/widget-packages/${id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: () => invalidatePackageQueries(qc),
  });
}

export function useDeleteWidgetPackage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<void>(`/api/v1/admin/widget-packages/${id}`, { method: "DELETE" }),
    onSuccess: () => invalidatePackageQueries(qc),
  });
}

export function useActivateWidgetPackage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<WidgetPackage>(`/api/v1/admin/widget-packages/${id}/activate`, {
        method: "POST",
      }),
    onSuccess: () => invalidatePackageQueries(qc),
  });
}

export function useForkWidgetPackage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name?: string }) =>
      apiFetch<WidgetPackage>(`/api/v1/admin/widget-packages/${id}/fork`, {
        method: "POST",
        body: JSON.stringify({ name }),
      }),
    onSuccess: () => invalidatePackageQueries(qc),
  });
}

export function validateWidgetPackage(body: {
  yaml_template: string;
  python_code?: string | null;
}): Promise<ValidateResponse> {
  return apiFetch<ValidateResponse>("/api/v1/admin/widget-packages/validate", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function previewWidgetPackage(
  id: string,
  body: {
    yaml_template?: string;
    python_code?: string | null;
    sample_payload?: Record<string, unknown> | null;
    widget_config?: Record<string, unknown> | null;
  },
): Promise<PreviewResponse> {
  return apiFetch<PreviewResponse>(
    `/api/v1/admin/widget-packages/${id}/preview`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function previewWidgetInline(body: {
  yaml_template: string;
  python_code?: string | null;
  sample_payload?: Record<string, unknown> | null;
  widget_config?: Record<string, unknown> | null;
  tool_name?: string | null;
  source_bot_id?: string | null;
  source_channel_id?: string | null;
}): Promise<PreviewResponse> {
  return apiFetch<PreviewResponse>(
    "/api/v1/admin/widget-packages/preview-inline",
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function checkWidgetAuthoring(body: {
  yaml_template: string;
  python_code?: string | null;
  sample_payload?: Record<string, unknown> | null;
  widget_config?: Record<string, unknown> | null;
  tool_name?: string | null;
  source_bot_id?: string | null;
  source_channel_id?: string | null;
  include_runtime?: boolean;
  include_screenshot?: boolean;
}): Promise<AuthoringCheckResponse> {
  return apiFetch<AuthoringCheckResponse>(
    "/api/v1/admin/widget-packages/authoring-check",
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function previewWidgetForTool(body: {
  tool_name: string;
  sample_payload?: Record<string, unknown> | null;
  widget_config?: Record<string, unknown> | null;
  source_bot_id?: string | null;
  source_channel_id?: string | null;
}): Promise<PreviewResponse> {
  return apiFetch<PreviewResponse>(
    "/api/v1/admin/widget-packages/preview-for-tool",
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function previewDashboardWidgetForTool(body: {
  tool_name: string;
  tool_args?: Record<string, unknown> | null;
  widget_config?: Record<string, unknown> | null;
  source_bot_id?: string | null;
  source_channel_id?: string | null;
}): Promise<PreviewResponse> {
  return apiFetch<PreviewResponse>(
    "/api/v1/widgets/preview-for-tool",
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function genericRenderWidget(body: {
  tool_name: string;
  raw_result: unknown;
  config?: Record<string, unknown> | null;
}): Promise<PreviewResponse> {
  return apiFetch<PreviewResponse>(
    "/api/v1/admin/widget-packages/generic-render",
    { method: "POST", body: JSON.stringify(body) },
  );
}
