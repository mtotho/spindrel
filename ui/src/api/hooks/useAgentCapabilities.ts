import { useQuery } from "@tanstack/react-query";
import { ApiError, apiFetch } from "../client";
import type { BotConfig } from "../../types/api";

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
  kind: "tool_call" | "attention" | "mission_update" | "project_receipt" | "widget_receipt" | "execution_receipt" | string;
  actor: {
    bot_id?: string | null;
    session_id?: string | null;
    task_id?: string | null;
  };
  target: {
    bot_id?: string | null;
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

export interface AgentStatusSnapshot {
  schema_version?: string;
  available?: boolean;
  state?: "idle" | "scheduled" | "working" | "blocked" | "error" | "unknown" | string;
  recommendation?: "continue" | "wait_for_run" | "review_failure" | "review_stale_run" | "enable_heartbeat" | "unknown" | string;
  reason?: string | null;
  current?: {
    type?: "task" | "heartbeat" | string;
    id?: string;
    task_id?: string | null;
    heartbeat_id?: string | null;
    task_type?: string | null;
    channel_id?: string | null;
    session_id?: string | null;
    status?: string;
    started_at?: string | null;
    elapsed_seconds?: number | null;
    max_run_seconds?: number | null;
    stale?: boolean;
    summary?: string | null;
    trace?: { correlation_id?: string | null };
  } | null;
  heartbeat?: {
    configured?: boolean;
    configured_count?: number;
    enabled?: boolean;
    heartbeat_id?: string | null;
    channel_id?: string | null;
    interval_minutes?: number | null;
    next_run_at?: string | null;
    last_run_at?: string | null;
    last_status?: string | null;
    last_error?: string | null;
    repetition_detected?: boolean | null;
    run_count?: number | null;
    max_run_seconds?: number | null;
  };
  recent_runs?: Array<{
    type?: "task" | "heartbeat" | string;
    id?: string;
    task_id?: string | null;
    heartbeat_id?: string | null;
    task_type?: string | null;
    channel_id?: string | null;
    session_id?: string | null;
    status?: string;
    started_at?: string | null;
    completed_at?: string | null;
    duration_ms?: number | null;
    summary?: string | null;
    trace?: { correlation_id?: string | null };
    error?: {
      message?: string | null;
      error_code?: string | null;
      error_kind?: string | null;
      retryable?: boolean | null;
    };
    repetition_detected?: boolean | null;
  }>;
}

export interface AgentToolErrorContract {
  version?: string;
  fields?: string[];
  retryable_kinds?: string[];
  benign_review_kinds?: string[];
  error_kind_descriptions?: Record<string, string>;
  backward_compatibility?: string;
}

export interface AgentSkillRecommendation {
  feature_id: string;
  feature_label: string;
  skill_ids: string[];
  missing_skill_ids?: string[];
  reason: string;
  when_to_load: string;
  first_action?: string | null;
  model_support?: "recommended_for_small_models" | string;
  labels?: Record<string, string>;
}

export interface AgentSkillCreationCandidate {
  feature_id: string;
  feature_label: string;
  reason: string;
  suggested_skill_id: string;
  first_outline?: string[];
  model_support?: "recommended_for_small_models" | string;
}

export interface ExecutionReceiptWrite {
  scope?: string;
  action_type: string;
  status?: "reported" | "succeeded" | "failed" | "blocked" | "needs_review" | string;
  summary: string;
  actor?: Record<string, unknown>;
  target?: Record<string, unknown>;
  before_summary?: string | null;
  after_summary?: string | null;
  approval_required?: boolean;
  approval_ref?: string | null;
  result?: Record<string, unknown>;
  rollback_hint?: string | null;
  bot_id?: string | null;
  channel_id?: string | null;
  session_id?: string | null;
  task_id?: string | null;
  correlation_id?: string | null;
  idempotency_key?: string | null;
  metadata?: Record<string, unknown>;
}

export interface ExecutionReceipt extends ExecutionReceiptWrite {
  schema_version: "execution-receipt.v1" | string;
  id: string;
  scope: string;
  status: string;
  actor: Record<string, unknown>;
  target: Record<string, unknown>;
  approval_required: boolean;
  result: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at?: string | null;
}

export interface AgentRepairPreflight {
  schema_version: "agent-action-preflight.v1" | string;
  action_id: string;
  status: "ready" | "blocked" | "stale" | "noop" | string;
  can_apply: boolean;
  reason: string;
  action?: {
    id?: string | null;
    finding_code?: string | null;
    kind?: string | null;
    title?: string | null;
    apply_type?: string | null;
  } | null;
  required_actor_scopes: string[];
  missing_actor_scopes: string[];
  would_change: Array<{
    field: string;
    current?: unknown;
    next?: unknown;
    changes?: boolean;
    reason?: string;
  }>;
  current_findings: string[];
  warnings: string[];
}

export interface AgentRepairRequest {
  schema_version: "agent-repair-request.v1" | string;
  ok: boolean;
  status: "queued" | "ready" | "blocked" | "stale" | "noop" | string;
  reason: string;
  receipt?: ExecutionReceipt;
  receipt_id?: string;
  created?: boolean;
  updated?: boolean;
  preflight: AgentRepairPreflight;
  requester_missing_actor_scopes: string[];
}

function agentRepairErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.detail ?? error.message;
  if (error instanceof Error) return error.message;
  return "Agent readiness repair failed.";
}

export function createExecutionReceipt(payload: ExecutionReceiptWrite) {
  return apiFetch<ExecutionReceipt>("/api/v1/execution-receipts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function preflightAgentRepair(payload: {
  action_id: string;
  bot_id?: string | null;
  channel_id?: string | null;
  session_id?: string | null;
}) {
  return apiFetch<AgentRepairPreflight>("/api/v1/agent-capabilities/actions/preflight", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      action_id: payload.action_id,
      bot_id: payload.bot_id ?? null,
      channel_id: payload.channel_id ?? null,
      session_id: payload.session_id ?? null,
    }),
  });
}

export function requestAgentRepair(payload: {
  action_id: string;
  bot_id?: string | null;
  channel_id?: string | null;
  session_id?: string | null;
  rationale?: string | null;
}) {
  return apiFetch<AgentRepairRequest>("/api/v1/agent-capabilities/actions/request", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      action_id: payload.action_id,
      bot_id: payload.bot_id ?? null,
      channel_id: payload.channel_id ?? null,
      session_id: payload.session_id ?? null,
      rationale: payload.rationale ?? null,
    }),
  });
}

export interface ApplyAgentReadinessRepairInput {
  action: AgentCapabilityAction;
  botId?: string | null;
  channelId?: string | null;
  sessionId?: string | null;
  maxTools?: number;
  actor?: Record<string, unknown>;
  approvalRef?: string;
  beforeDoctorStatus?: string | null;
}

export interface ApplyAgentReadinessRepairResult {
  status: "succeeded" | "needs_review" | "blocked" | "stale";
  receipt?: ExecutionReceipt;
  preflight: AgentRepairPreflight;
  refreshed?: AgentCapabilityManifest | null;
  findingResolved?: boolean;
  verificationError?: string | null;
}

export async function updateBotConfig(botId: string, data: Partial<BotConfig>) {
  return apiFetch<BotConfig>(`/api/v1/admin/bots/${botId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function applyAgentReadinessRepair({
  action,
  botId,
  channelId,
  sessionId,
  maxTools = 40,
  actor = { kind: "human_ui", surface: "agent_readiness_panel" },
  approvalRef = "agent_readiness_panel",
  beforeDoctorStatus = "unknown",
}: ApplyAgentReadinessRepairInput): Promise<ApplyAgentReadinessRepairResult> {
  if (action.apply.type !== "bot_patch") {
    throw new Error("Only bot patch readiness repairs can be applied.");
  }
  if (!botId) {
    throw new Error("A bot id is required to apply this readiness repair.");
  }

  const preflight = await preflightAgentRepair({
    action_id: action.id,
    bot_id: botId,
    channel_id: channelId,
    session_id: sessionId,
  });

  if (preflight.status === "blocked" || preflight.status === "stale") {
    return { status: preflight.status, preflight };
  }

  if (preflight.status === "noop") {
    const stillFinding = preflight.current_findings.includes(action.finding_code);
    const receipt = await createExecutionReceipt({
      scope: "agent_readiness",
      action_type: action.kind || "bot_patch",
      status: stillFinding ? "needs_review" : "succeeded",
      summary: stillFinding
        ? `Preflight skipped, still needs review: ${action.title}`
        : `Preflight skipped, already resolved: ${action.title}`,
      actor,
      target: {
        bot_id: botId,
        channel_id: channelId ?? undefined,
        session_id: sessionId ?? undefined,
        finding_code: action.finding_code,
        action_id: action.id,
      },
      before_summary: action.description,
      after_summary: preflight.reason,
      approval_required: true,
      approval_ref: approvalRef,
      result: {
        applied: false,
        patch: action.apply.patch,
        preflight,
        doctor_status_before: beforeDoctorStatus,
        finding_resolved: !stillFinding,
        remaining_findings: preflight.current_findings,
      },
      rollback_hint: "No configuration changed.",
      bot_id: botId,
      channel_id: channelId ?? undefined,
      session_id: sessionId ?? undefined,
      idempotency_key: `agent_readiness:${botId ?? "none"}:${action.id}:preflight`,
      metadata: { finding_code: action.finding_code, preflight_status: preflight.status },
    });
    return {
      status: stillFinding ? "needs_review" : "succeeded",
      receipt,
      preflight,
      findingResolved: !stillFinding,
    };
  }

  if (!preflight.can_apply) {
    return { status: "blocked", preflight };
  }

  await updateBotConfig(botId, action.apply.patch as Partial<BotConfig>);
  let refreshed: AgentCapabilityManifest | null = null;
  let verificationError: string | null = null;
  try {
    refreshed = await fetchAgentCapabilities({
      botId,
      channelId,
      sessionId,
      includeEndpoints: false,
      includeSchemas: false,
      maxTools,
    });
  } catch (error) {
    verificationError = agentRepairErrorMessage(error);
  }

  const remainingFindings = refreshed?.doctor.findings ?? [];
  const remainingCodes = remainingFindings.map((finding) => finding.code);
  const findingResolved = Boolean(refreshed && !remainingCodes.includes(action.finding_code));
  const receiptStatus = findingResolved ? "succeeded" : "needs_review";
  const receiptSummary = verificationError
    ? `Applied readiness repair, verification failed: ${action.title}`
    : findingResolved
      ? `Verified resolved: ${action.title}`
      : `Applied, still needs review: ${action.title}`;
  const receipt = await createExecutionReceipt({
    scope: "agent_readiness",
    action_type: action.kind || "bot_patch",
    status: receiptStatus,
    summary: receiptSummary,
    actor,
    target: {
      bot_id: botId,
      channel_id: channelId ?? undefined,
      session_id: sessionId ?? undefined,
      finding_code: action.finding_code,
      action_id: action.id,
    },
    before_summary: action.description,
    after_summary: findingResolved
      ? "The original readiness finding no longer appears after refetching the capability manifest."
      : action.impact,
    approval_required: true,
    approval_ref: approvalRef,
    result: {
      applied: true,
      patch: action.apply.patch,
      preflight,
      required_actor_scopes: action.required_actor_scopes ?? [],
      grants_scopes: action.grants_scopes ?? [],
      doctor_status_before: beforeDoctorStatus,
      doctor_status_after: refreshed?.doctor.status ?? null,
      finding_resolved: findingResolved,
      remaining_findings: remainingCodes,
      verification_error: verificationError,
    },
    rollback_hint: "Open Bot settings and remove the added API scopes or tool enrollments if this repair was not intended.",
    bot_id: botId,
    channel_id: channelId ?? undefined,
    session_id: sessionId ?? undefined,
    idempotency_key: `agent_readiness:${botId ?? "none"}:${action.id}`,
    metadata: { finding_code: action.finding_code },
  });
  return {
    status: receiptStatus,
    receipt,
    preflight,
    refreshed,
    findingResolved,
    verificationError,
  };
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
    recommended_now?: AgentSkillRecommendation[];
    creation_candidates?: AgentSkillCreationCandidate[];
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
  agent_status?: AgentStatusSnapshot;
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
    recent_receipts?: ExecutionReceipt[];
    pending_repair_requests?: ExecutionReceipt[];
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

export function fetchAgentCapabilities({
  botId,
  channelId,
  sessionId,
  includeSchemas = false,
  includeEndpoints = false,
  maxTools = 40,
}: AgentCapabilitiesArgs) {
  const params = new URLSearchParams();
  if (botId) params.set("bot_id", botId);
  if (channelId) params.set("channel_id", channelId);
  if (sessionId) params.set("session_id", sessionId);
  params.set("include_schemas", includeSchemas ? "true" : "false");
  params.set("include_endpoints", includeEndpoints ? "true" : "false");
  params.set("max_tools", String(maxTools));
  return apiFetch<AgentCapabilityManifest>(`/api/v1/agent-capabilities?${params.toString()}`);
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
    queryFn: () => fetchAgentCapabilities({ botId, channelId, sessionId, includeSchemas, includeEndpoints, maxTools }),
    enabled: enabled && Boolean(botId || channelId || sessionId),
    staleTime: 30_000,
  });
}
