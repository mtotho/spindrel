import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";

export type AgentReadinessStatus = "ok" | "needs_attention" | "error" | string;
export type AgentFindingSeverity = "info" | "warning" | "error" | string;

export interface AgentDoctorFinding {
  severity: AgentFindingSeverity;
  code: string;
  message: string;
  next_action?: string;
}

export interface AgentCapabilityAction {
  id: string;
  finding_code: string;
  kind: string;
  title: string;
  description: string;
  impact: string;
  required_actor_scopes?: string[];
  grants_scopes?: string[];
  apply:
    | { type: "bot_patch"; patch: Record<string, unknown> }
    | { type: "navigate"; href: string };
}

export interface AgentToolDetail {
  name: string;
  profile?: string | null;
  description?: string | null;
  safety_tier?: string | null;
  execution_policy?: string | null;
  source_integration?: string | null;
  source_file?: string | null;
  requires_bot_context?: boolean;
  requires_channel_context?: boolean;
  enrolled?: boolean;
  pinned?: boolean;
  configured?: boolean;
  has_return_schema?: boolean;
}

export interface AgentIntegrationGlobal {
  id: string;
  name: string;
  lifecycle_status: string;
  status: string;
  missing_required_settings?: string[];
  dependency_gaps?: {
    python?: string[];
    npm?: string[];
    system?: string[];
  };
  process?: {
    declared?: boolean;
    running?: boolean;
    exit_code?: number | null;
    restart_count?: number | null;
  };
  webhook_declared?: boolean;
  oauth_declared?: boolean;
  api_permissions_declared?: boolean;
  capabilities?: string[];
  rich_tool_results?: boolean;
  href?: string;
}

export interface AgentIntegrationBinding {
  id: string;
  integration_type: string;
  client_id: string;
  display_name?: string | null;
  activated?: boolean;
  stub_binding?: boolean;
  dispatch_config_keys?: string[];
  href?: string | null;
}

export interface AgentIntegrationActivationOption {
  integration_type: string;
  activated?: boolean;
  tools?: string[];
  includes?: string[];
  requires_workspace?: boolean;
  missing_config_fields?: string[];
  href?: string | null;
}

export interface AgentIntegrationReadiness {
  summary?: {
    enabled_count?: number;
    needs_setup_count?: number;
    dependency_gap_count?: number;
    process_gap_count?: number;
    channel_binding_count?: number;
    channel_activation_count?: number;
    channel_stub_binding_count?: number;
  };
  global?: AgentIntegrationGlobal[];
  channel?: {
    channel_id?: string;
    bindings?: AgentIntegrationBinding[];
    activation_options?: AgentIntegrationActivationOption[];
  } | null;
}

export interface AgentRuntimeContext {
  available?: boolean;
  channel_id?: string | null;
  session_id?: string | null;
  recommendation?: "continue" | "summarize" | "handoff" | "unknown" | string;
  reason?: string | null;
  budget?: {
    tokens_used?: number | null;
    tokens_remaining?: number | null;
    total_tokens?: number | null;
    percent_full?: number | null;
    source?: string | null;
    context_profile?: string | null;
  };
  details?: Record<string, unknown>;
}

export interface AgentWorkState {
  available?: boolean;
  bot_id?: string | null;
  channel_id?: string | null;
  session_id?: string | null;
  reason?: string | null;
  summary?: {
    assigned_mission_count?: number;
    assigned_attention_count?: number;
    has_current_work?: boolean;
    recommended_next_action?: "idle" | "advance_mission" | "review_attention" | string;
  };
  missions?: Array<{
    id: string;
    title: string;
    status: string;
    scope: string;
    channel_id?: string | null;
    channel_name?: string | null;
    assignment_id: string;
    role: string;
    target_channel_id?: string | null;
    target_channel_name?: string | null;
    next_run_at?: string | null;
    last_update_at?: string | null;
    last_task_id?: string | null;
    last_correlation_id?: string | null;
    latest_update?: {
      kind?: string;
      summary?: string;
      next_actions?: string[];
      created_at?: string | null;
    } | null;
  }>;
  attention?: Array<{
    id: string;
    title: string;
    severity: string;
    status: string;
    assignment_status?: string | null;
    assignment_mode?: string | null;
    channel_id?: string | null;
    channel_name?: string | null;
    target_kind: string;
    target_id: string;
    assignment_instructions?: string | null;
    next_steps?: string[];
    latest_correlation_id?: string | null;
    assigned_at?: string | null;
    assignment_task_id?: string | null;
    last_seen_at?: string | null;
  }>;
}

export interface AgentActivityItem {
  id: string;
  kind: "tool_call" | "attention" | "mission_update" | "project_receipt" | "widget_receipt" | string;
  actor: {
    bot_id?: string | null;
    session_id?: string | null;
    task_id?: string | null;
  };
  target: {
    channel_id?: string | null;
    project_id?: string | null;
    widget_pin_ids?: string[];
  };
  status: "succeeded" | "failed" | "warning" | "reported" | "needs_review" | "unknown" | string;
  summary: string;
  next_action?: string | null;
  trace?: {
    correlation_id?: string | null;
    tool_call_id?: string | null;
  };
  error?: {
    error_code?: string | null;
    error_kind?: string | null;
    retryable?: boolean | null;
  };
  created_at?: string | null;
  source?: Record<string, unknown>;
}

export interface AgentActivityLogSummary {
  available?: boolean;
  supported_kinds?: string[];
  supported_filters?: string[];
  recent_count?: number;
  recent_counts?: Record<string, number>;
  recent?: AgentActivityItem[];
}

export interface AgentToolErrorContract {
  version?: string;
  fields?: string[];
  retryable_kinds?: string[];
  benign_review_kinds?: string[];
  error_kind_descriptions?: Record<string, string>;
  backward_compatibility?: string;
}

export interface AgentCapabilityManifest {
  schema_version: string;
  context: {
    bot_id?: string | null;
    bot_name?: string | null;
    channel_id?: string | null;
    channel_name?: string | null;
    session_id?: string | null;
  };
  api: {
    scopes?: string[];
    endpoint_count?: number;
    endpoints?: unknown[];
  };
  tool_error_contract?: AgentToolErrorContract;
  tools: {
    catalog_count?: number;
    working_set_count?: number;
    configured?: string[];
    pinned?: string[];
    enrolled?: Array<{ name: string; source?: string; enrolled_at?: string | null; fetch_count?: number }>;
    profiles?: Record<string, number>;
    safety_tiers?: Record<string, number>;
    recommended_core?: string[];
    details?: AgentToolDetail[];
    details_truncated?: boolean;
  };
  skills: {
    working_set_count?: number;
    bot_enrolled?: Array<{ id: string; name?: string | null; source?: string; scope?: string }>;
    channel_enrolled?: Array<{ id: string; name?: string | null; source?: string; scope?: string }>;
  };
  project: {
    attached?: boolean;
    id?: string;
    name?: string | null;
    root_path?: string | null;
    runtime_env?: { ready?: boolean; missing_secrets?: string[]; invalid_env_keys?: string[]; reserved_env_keys?: string[]; error?: string };
  };
  harness: {
    runtime?: string | null;
    workdir?: string | null;
    bridge_status?: string | null;
  };
  runtime_context?: AgentRuntimeContext;
  work_state?: AgentWorkState;
  activity_log?: AgentActivityLogSummary;
  widgets: {
    authoring_tools?: string[];
    required_authoring_tools?: string[];
    missing_authoring_tools?: string[];
    recommended_skills?: string[];
    available_skills?: string[];
    missing_skills?: string[];
    health_loop?: string | null;
    html_authoring_check?: string | null;
    tool_widget_authoring_check?: string | null;
    authoring_flow?: string[];
    readiness?: string | null;
    findings?: AgentDoctorFinding[];
  };
  integrations?: AgentIntegrationReadiness;
  doctor: {
    status: AgentReadinessStatus;
    findings: AgentDoctorFinding[];
    proposed_actions?: AgentCapabilityAction[];
  };
}

export interface AgentCapabilitiesArgs {
  botId?: string | null;
  channelId?: string | null;
  sessionId?: string | null;
  includeSchemas?: boolean;
  includeEndpoints?: boolean;
  maxTools?: number;
  enabled?: boolean;
}

export function useAgentCapabilities({
  botId,
  channelId,
  sessionId,
  includeSchemas = false,
  includeEndpoints = false,
  maxTools = 40,
  enabled = true,
}: AgentCapabilitiesArgs) {
  return useQuery({
    queryKey: [
      "agent-capabilities",
      botId ?? "",
      channelId ?? "",
      sessionId ?? "",
      includeSchemas,
      includeEndpoints,
      maxTools,
    ],
    queryFn: () => {
      const params = new URLSearchParams();
      if (botId) params.set("bot_id", botId);
      if (channelId) params.set("channel_id", channelId);
      if (sessionId) params.set("session_id", sessionId);
      params.set("include_schemas", includeSchemas ? "true" : "false");
      params.set("include_endpoints", includeEndpoints ? "true" : "false");
      params.set("max_tools", String(maxTools));
      return apiFetch<AgentCapabilityManifest>(`/api/v1/agent-capabilities?${params.toString()}`);
    },
    enabled: enabled && Boolean(botId || channelId || sessionId),
    staleTime: 30_000,
  });
}
