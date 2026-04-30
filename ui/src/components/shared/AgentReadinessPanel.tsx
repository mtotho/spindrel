import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Activity, AlertCircle, CheckCircle2, CircleAlert, ExternalLink, Gauge, History, Plug, Sparkles, Wrench } from "lucide-react";

import { createExecutionReceipt, fetchAgentCapabilities, preflightAgentRepair, useAgentCapabilities, type AgentCapabilityAction, type AgentCapabilityManifest, type AgentDoctorFinding, type AgentRepairPreflight, type ExecutionReceipt } from "@/src/api/hooks/useAgentCapabilities";
import { useUpdateBot } from "@/src/api/hooks/useBots";
import { ApiError } from "@/src/api/client";
import type { BotConfig } from "@/src/types/api";
import { ActionButton, EmptyState, InfoBanner, QuietPill, SettingsControlRow, SettingsStatGrid, StatusBadge } from "./SettingsControls";
import { Spinner } from "./Spinner";

function statusVariant(status?: string): "success" | "warning" | "danger" | "neutral" {
  if (status === "ok") return "success";
  if (status === "error") return "danger";
  if (status === "needs_attention") return "warning";
  return "neutral";
}

function severityTone(severity?: string): "danger" | "warning" | "info" | "neutral" {
  if (severity === "error") return "danger";
  if (severity === "warning") return "warning";
  if (severity === "info") return "info";
  return "neutral";
}

function statusIcon(status?: string) {
  if (status === "ok") return <CheckCircle2 size={15} className="text-success" />;
  if (status === "error") return <AlertCircle size={15} className="text-danger" />;
  return <CircleAlert size={15} className="text-warning-muted" />;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.detail ?? error.message;
  if (error instanceof Error) return error.message;
  return "Agent readiness is unavailable.";
}

function TopFinding({ finding }: { finding: AgentDoctorFinding }) {
  return (
    <SettingsControlRow
      leading={<CircleAlert size={14} />}
      title={finding.message}
      description={finding.next_action}
      meta={<QuietPill label={finding.severity} tone={severityTone(finding.severity)} />}
      compact
    />
  );
}

function ActionMeta({ action }: { action: AgentCapabilityAction }) {
  if (action.apply.type === "bot_patch") {
    return <QuietPill label="staged patch" tone="info" />;
  }
  return <QuietPill label="open settings" />;
}

function ProposedActionRow({
  action,
  onApply,
  onOpen,
  pending,
}: {
  action: AgentCapabilityAction;
  onApply: (action: AgentCapabilityAction) => void;
  onOpen: (href: string) => void;
  pending: boolean;
}) {
  const isPatch = action.apply.type === "bot_patch";
  return (
    <SettingsControlRow
      leading={<Sparkles size={14} />}
      title={action.title}
      description={`${action.description} ${action.impact}`}
      meta={<ActionMeta action={action} />}
      action={
        <ActionButton
          label={pending ? "Applying" : isPatch ? "Apply" : "Open"}
          size="small"
          disabled={pending}
          icon={isPatch ? <Sparkles size={12} /> : <ExternalLink size={12} />}
          onPress={() => {
            if (action.apply.type === "bot_patch") onApply(action);
            else onOpen(action.apply.href);
          }}
        />
      }
      compact
    />
  );
}

function CapabilityStats({ manifest }: { manifest: AgentCapabilityManifest }) {
  return (
    <SettingsStatGrid
      items={[
        { label: "API scopes", value: manifest.api.scopes?.length ?? 0, tone: (manifest.api.scopes?.length ?? 0) ? "accent" : "warning" },
        { label: "Endpoints", value: manifest.api.endpoint_count ?? 0 },
        { label: "Tools", value: manifest.tools.working_set_count ?? 0 },
        { label: "Skills", value: manifest.skills.working_set_count ?? 0 },
      ]}
    />
  );
}

function SurfaceSummary({ manifest }: { manifest: AgentCapabilityManifest }) {
  const project = manifest.project.attached ? (manifest.project.name || "Project attached") : "No Project";
  const runtimeReady = manifest.project.runtime_env?.ready;
  const harness = manifest.harness.runtime || "Spindrel loop";
  const widgets = manifest.widgets.health_loop === "available" ? "Health loop" : "No health loop";
  return (
    <div className="grid gap-2 md:grid-cols-2">
      <SettingsControlRow
        leading={<Gauge size={14} />}
        title={project}
        description={manifest.project.root_path || (manifest.project.attached ? "Project root configured" : "Channel has no Project attachment")}
        meta={manifest.project.attached && runtimeReady === false ? <QuietPill label="runtime" tone="warning" /> : undefined}
        compact
      />
      <SettingsControlRow
        leading={<Wrench size={14} />}
        title={harness}
        description={`${widgets} - ${manifest.tools.catalog_count ?? 0} catalog tools`}
        meta={<QuietPill label={manifest.harness.bridge_status || "loop"} />}
        compact
      />
    </div>
  );
}

function widgetReadinessLabel(readiness?: string | null): string {
  if (readiness === "ready") return "Widget authoring ready";
  if (readiness === "blocked") return "Widget authoring blocked";
  if (readiness === "needs_skills") return "Widget skills on demand";
  return "Widget authoring";
}

function widgetReadinessTone(readiness?: string | null): "success" | "warning" | "danger" | "neutral" {
  if (readiness === "ready") return "success";
  if (readiness === "blocked") return "danger";
  if (readiness === "needs_skills") return "warning";
  return "neutral";
}

function WidgetAuthoringSummary({ manifest }: { manifest: AgentCapabilityManifest }) {
  const widgets = manifest.widgets;
  const missingTools = widgets.missing_authoring_tools?.length ?? 0;
  const missingSkills = widgets.missing_skills?.length ?? 0;
  const description = missingTools > 0
    ? `${missingTools} authoring tool${missingTools === 1 ? "" : "s"} missing`
    : missingSkills > 0
      ? `${missingSkills} widget skill${missingSkills === 1 ? "" : "s"} will be loaded on demand`
      : `${widgets.authoring_tools?.length ?? 0} authoring tools available`;
  return (
    <div data-testid="agent-readiness-widget-authoring">
      <SettingsControlRow
        leading={<Wrench size={14} />}
        title={widgetReadinessLabel(widgets.readiness)}
        description={description}
        meta={<QuietPill label={widgets.html_authoring_check === "available" ? "HTML full check" : "HTML check missing"} tone={widgetReadinessTone(widgets.readiness)} />}
        compact
      />
    </div>
  );
}

function IntegrationReadinessSummary({ manifest }: { manifest: AgentCapabilityManifest }) {
  const summary = manifest.integrations?.summary;
  if (!summary) return null;

  const setupGaps = summary.needs_setup_count ?? 0;
  const dependencyGaps = summary.dependency_gap_count ?? 0;
  const processGaps = summary.process_gap_count ?? 0;
  const stubBindings = summary.channel_stub_binding_count ?? 0;
  const issueCount = setupGaps + dependencyGaps + processGaps + stubBindings;
  const channelBits: string[] = [];
  if ((summary.channel_activation_count ?? 0) > 0) {
    channelBits.push(`${summary.channel_activation_count} active`);
  }
  if ((summary.channel_binding_count ?? 0) > 0) {
    channelBits.push(`${summary.channel_binding_count} bound`);
  }
  const description = issueCount > 0
    ? `${issueCount} integration issue${issueCount === 1 ? "" : "s"} need routing`
    : channelBits.length > 0
      ? `Channel integrations: ${channelBits.join(", ")}`
      : `${summary.enabled_count ?? 0} enabled integrations`;

  return (
    <div data-testid="agent-readiness-integrations">
      <SettingsControlRow
        leading={<Plug size={14} />}
        title="Integration readiness"
        description={description}
        meta={<QuietPill label={issueCount > 0 ? "review" : "ready"} tone={issueCount > 0 ? "warning" : "success"} />}
        compact
      />
    </div>
  );
}

function ActivityLogSummary({ manifest }: { manifest: AgentCapabilityManifest }) {
  const activity = manifest.activity_log;
  if (!activity?.available) return null;
  const recentCount = activity.recent_count ?? 0;
  const counts = activity.recent_counts ?? {};
  const topKinds = Object.entries(counts)
    .filter(([, count]) => count > 0)
    .slice(0, 3)
    .map(([kind, count]) => `${count} ${kind.replaceAll("_", " ")}`);
  const latest = activity.recent?.[0];
  const description = recentCount > 0
    ? (latest?.summary || topKinds.join(", ") || `${recentCount} recent events`)
    : "No replayable activity yet";
  return (
    <div data-testid="agent-readiness-activity-log">
      <SettingsControlRow
        leading={<History size={14} />}
        title="Recent agent activity"
        description={description}
        meta={<QuietPill label={`${recentCount} replayable`} tone={recentCount > 0 ? "info" : "neutral"} />}
        compact
      />
    </div>
  );
}

function receiptTone(status?: string): "success" | "warning" | "danger" | "neutral" {
  if (status === "succeeded") return "success";
  if (status === "failed" || status === "blocked") return "danger";
  if (status === "needs_review") return "warning";
  return "neutral";
}

function LastRepairSummary({ manifest }: { manifest: AgentCapabilityManifest }) {
  const receipt = manifest.doctor.recent_receipts?.find(
    (item) => !(item.status === "needs_review" && item.result?.requested_repair === true),
  );
  if (!receipt) return null;
  const result = receipt.result || {};
  const resolved = result.finding_resolved === true;
  const description = resolved
    ? receipt.after_summary || "Repair was verified after apply"
    : receipt.status === "needs_review"
      ? receipt.rollback_hint || receipt.after_summary || "Repair was applied but still needs review"
      : receipt.summary;
  return (
    <div data-testid="agent-readiness-last-repair">
      <SettingsControlRow
        leading={<History size={14} />}
        title="Last repair"
        description={description}
        meta={<QuietPill label={receipt.status || "reported"} tone={receiptTone(receipt.status)} />}
        compact
      />
    </div>
  );
}

function actorLabel(actor: Record<string, unknown> | undefined): string {
  if (!actor) return "unknown actor";
  if (typeof actor.name === "string" && actor.name) return actor.name;
  if (typeof actor.kind === "string" && actor.kind) return actor.kind.replaceAll("_", " ");
  return "unknown actor";
}

function PendingRepairRequests({
  manifest,
  proposedActions,
  onApply,
  pendingActionId,
}: {
  manifest: AgentCapabilityManifest;
  proposedActions: AgentCapabilityAction[];
  onApply: (action: AgentCapabilityAction) => void;
  pendingActionId: string | null;
}) {
  const requests = manifest.doctor.pending_repair_requests || [];
  if (requests.length === 0) return null;

  return (
    <div className="flex flex-col gap-1" data-testid="agent-readiness-pending-requests">
      <div className="px-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">
        Pending repair request
      </div>
      {requests.slice(0, 3).map((receipt) => {
        const actionId = typeof receipt.target?.action_id === "string" ? receipt.target.action_id : undefined;
        const findingCode = typeof receipt.target?.finding_code === "string" ? receipt.target.finding_code : undefined;
        const action = proposedActions.find((candidate) => candidate.id === actionId);
        return (
          <SettingsControlRow
            key={receipt.id}
            leading={<History size={14} />}
            title={receipt.summary || "Requested readiness repair"}
            description={`${findingCode || "readiness"} - requested by ${actorLabel(receipt.actor)}`}
            meta={action ? <QuietPill label="needs review" tone="warning" /> : <QuietPill label="stale" tone="neutral" />}
            action={action ? (
              <ActionButton
                label={pendingActionId === action.id ? "Applying" : "Apply"}
                size="small"
                disabled={pendingActionId === action.id}
                icon={<Sparkles size={12} />}
                onPress={() => onApply(action)}
              />
            ) : undefined}
            compact
          />
        );
      })}
    </div>
  );
}

function statusTone(state?: string): "danger" | "warning" | "info" | "success" | "neutral" {
  if (state === "error") return "danger";
  if (state === "blocked") return "warning";
  if (state === "working" || state === "scheduled") return "info";
  if (state === "idle") return "success";
  return "neutral";
}

function AgentStatusSummary({ manifest }: { manifest: AgentCapabilityManifest }) {
  const status = manifest.agent_status;
  if (!status?.available) return null;
  const state = status.state || "unknown";
  const latestRun = status.recent_runs?.[0];
  let description = "No autonomous status signal yet";
  if (status.current?.stale) {
    description = status.current.summary || "Current run appears stale";
  } else if (status.current) {
    description = status.current.summary || `${status.current.type || "Agent"} is running`;
  } else if (latestRun?.status === "failed" || latestRun?.status === "error") {
    description = latestRun.error?.message || latestRun.summary || "Latest run failed";
  } else if (status.heartbeat?.next_run_at) {
    description = `Next heartbeat ${new Date(status.heartbeat.next_run_at).toLocaleString()}`;
  } else if (status.heartbeat?.configured === false) {
    description = "No channel heartbeat configured";
  } else if (latestRun?.summary) {
    description = latestRun.summary;
  }
  return (
    <div data-testid="agent-readiness-agent-status">
      <SettingsControlRow
        leading={<Activity size={14} />}
        title="Agent status"
        description={description}
        meta={<QuietPill label={state.replaceAll("_", " ")} tone={statusTone(state)} />}
        compact
      />
    </div>
  );
}

export function AgentReadinessPanel({
  botId,
  channelId,
  sessionId,
  compact = false,
  maxTools = 40,
}: {
  botId?: string | null;
  channelId?: string | null;
  sessionId?: string | null;
  compact?: boolean;
  maxTools?: number;
}) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const updateBot = useUpdateBot(botId || undefined);
  const [pendingActionId, setPendingActionId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [lastReceipt, setLastReceipt] = useState<ExecutionReceipt | null>(null);
  const { data, isLoading, error } = useAgentCapabilities({
    botId,
    channelId,
    sessionId,
    includeEndpoints: false,
    includeSchemas: false,
    maxTools,
  });

  if (!botId && !channelId && !sessionId) {
    return <EmptyState message="Agent readiness appears after this bot or channel exists." />;
  }
  if (isLoading) {
    return (
      <div className="flex min-h-[84px] items-center justify-center rounded-md bg-surface-overlay/25">
        <Spinner size={16} />
      </div>
    );
  }
  if (error || !data) {
    return (
      <InfoBanner variant="warning" icon={<AlertCircle size={14} />}>
        {errorMessage(error)}
      </InfoBanner>
    );
  }

  const findings = data.doctor.findings || [];
  const proposedActions = data.doctor.proposed_actions || [];
  const topFinding = findings[0];
  const label = data.doctor.status.replace(/_/g, " ");

  async function applyAction(action: AgentCapabilityAction) {
    if (action.apply.type !== "bot_patch") return;
    setActionError(null);
    setLastReceipt(null);
    setPendingActionId(action.id);
    const beforeDoctorStatus = data?.doctor.status ?? "unknown";
    try {
      let preflight: AgentRepairPreflight;
      try {
        preflight = await preflightAgentRepair({
          action_id: action.id,
          bot_id: botId,
          channel_id: channelId,
          session_id: sessionId,
        });
      } catch (err) {
        setActionError(`Preflight failed: ${errorMessage(err)}`);
        return;
      }

      if (preflight.status === "blocked" || preflight.status === "stale") {
        setActionError(preflight.reason);
        return;
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
          actor: { kind: "human_ui", surface: "agent_readiness_panel" },
          target: {
            bot_id: botId ?? undefined,
            channel_id: channelId ?? undefined,
            session_id: sessionId ?? undefined,
            finding_code: action.finding_code,
            action_id: action.id,
          },
          before_summary: action.description,
          after_summary: preflight.reason,
          approval_required: true,
          approval_ref: "agent_readiness_panel",
          result: {
            applied: false,
            patch: action.apply.patch,
            preflight,
            doctor_status_before: beforeDoctorStatus,
            finding_resolved: !stillFinding,
            remaining_findings: preflight.current_findings,
          },
          rollback_hint: "No configuration changed.",
          bot_id: botId ?? undefined,
          channel_id: channelId ?? undefined,
          session_id: sessionId ?? undefined,
          idempotency_key: `agent_readiness:${botId ?? "none"}:${action.id}:preflight`,
          metadata: { finding_code: action.finding_code, preflight_status: preflight.status },
        });
        setLastReceipt(receipt);
        void qc.invalidateQueries({ queryKey: ["agent-capabilities"] });
        return;
      }

      if (!preflight.can_apply) {
        setActionError(preflight.reason || "Preflight did not approve this repair.");
        return;
      }

      await updateBot.mutateAsync(action.apply.patch as Partial<BotConfig>);
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
      } catch (err) {
        verificationError = errorMessage(err);
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
      try {
        const receipt = await createExecutionReceipt({
          scope: "agent_readiness",
          action_type: action.kind || "bot_patch",
          status: receiptStatus,
          summary: receiptSummary,
          actor: { kind: "human_ui", surface: "agent_readiness_panel" },
          target: {
            bot_id: botId ?? undefined,
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
          approval_ref: "agent_readiness_panel",
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
          bot_id: botId ?? undefined,
          channel_id: channelId ?? undefined,
          session_id: sessionId ?? undefined,
          idempotency_key: `agent_readiness:${botId ?? "none"}:${action.id}`,
          metadata: { finding_code: action.finding_code },
        });
        setLastReceipt(receipt);
      } catch (err) {
        setActionError(`Repair applied, but the execution receipt was not recorded: ${errorMessage(err)}`);
      }
      void qc.invalidateQueries({ queryKey: ["agent-capabilities"] });
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setPendingActionId(null);
    }
  }

  if (compact) {
    return (
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            {statusIcon(data.doctor.status)}
            <div className="min-w-0">
              <div className="truncate text-[12px] font-semibold text-text">Agent readiness</div>
              <div className="truncate text-[10px] text-text-dim">
                {topFinding ? topFinding.message : "Ready to act with current grants"}
              </div>
            </div>
          </div>
          <StatusBadge label={label} variant={statusVariant(data.doctor.status)} />
        </div>
        {!topFinding && (
          <div className="flex flex-wrap gap-1">
            <QuietPill label={`${data.api.scopes?.length ?? 0} scopes`} tone="info" />
            <QuietPill label={`${data.tools.working_set_count ?? 0} tools`} />
            <QuietPill label={`${data.skills.working_set_count ?? 0} skills`} />
          </div>
        )}
      </div>
    );
  }

  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          {statusIcon(data.doctor.status)}
          <div className="min-w-0">
            <h2 className="text-[14px] font-semibold text-text">Agent readiness</h2>
            <p className="mt-0.5 text-[12px] leading-relaxed text-text-dim">
              Current grants, working set, Project, harness, and widget status.
            </p>
          </div>
        </div>
        <StatusBadge label={label} variant={statusVariant(data.doctor.status)} />
      </div>
      <CapabilityStats manifest={data} />
      <SurfaceSummary manifest={data} />
      <AgentStatusSummary manifest={data} />
      <ActivityLogSummary manifest={data} />
      <PendingRepairRequests
        manifest={data}
        proposedActions={proposedActions}
        pendingActionId={pendingActionId}
        onApply={applyAction}
      />
      <LastRepairSummary manifest={data} />
      <WidgetAuthoringSummary manifest={data} />
      <IntegrationReadinessSummary manifest={data} />
      {findings.length > 0 ? (
        <div className="flex flex-col gap-1">
          {findings.slice(0, 4).map((finding) => (
            <TopFinding key={finding.code} finding={finding} />
          ))}
        </div>
      ) : (
        <InfoBanner variant="success" icon={<CheckCircle2 size={14} />}>
          Ready to act with current API grants, tools, skills, and runtime context.
        </InfoBanner>
      )}
      {proposedActions.length > 0 && (
        <div className="flex flex-col gap-1">
          <div className="px-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">
            Suggested repairs
          </div>
          {proposedActions.slice(0, 4).map((action) => (
            <ProposedActionRow
              key={action.id}
              action={action}
              pending={pendingActionId === action.id}
              onApply={applyAction}
              onOpen={(href) => navigate(href)}
            />
          ))}
          {actionError && (
            <InfoBanner variant="danger" icon={<AlertCircle size={14} />}>
              {actionError}
            </InfoBanner>
          )}
          {lastReceipt && (
            <InfoBanner
              variant={lastReceipt.status === "succeeded" ? "success" : "warning"}
              icon={<CheckCircle2 size={14} />}
            >
              {lastReceipt.summary}
            </InfoBanner>
          )}
        </div>
      )}
    </section>
  );
}
