import { AlertCircle, CheckCircle2, CircleAlert, Gauge, Wrench } from "lucide-react";

import { useAgentCapabilities, type AgentCapabilityManifest, type AgentDoctorFinding } from "@/src/api/hooks/useAgentCapabilities";
import { ApiError } from "@/src/api/client";
import { EmptyState, InfoBanner, QuietPill, SettingsControlRow, SettingsStatGrid, StatusBadge } from "./SettingsControls";
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
  const topFinding = findings[0];
  const label = data.doctor.status.replace(/_/g, " ");

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
    </section>
  );
}
