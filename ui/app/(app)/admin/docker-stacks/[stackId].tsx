/**
 * Docker Stack detail page — stack info, services, logs, and actions.
 */
import { useState } from "react";
import { Spinner } from "@/src/components/shared/Spinner";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import {
  useDockerStack,
  useDockerStackStatus,
  useDockerStackLogs,
  useStartDockerStack,
  useStopDockerStack,
  useDestroyDockerStack,
} from "@/src/api/hooks/useDockerStacks";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import {
  Boxes, ArrowLeft, Play, Square, Trash2,
  CheckCircle2, XCircle, Loader2, AlertTriangle, Minus,
  Server, FileCode, ScrollText, Plug,
} from "lucide-react";
import { useParams, useNavigate } from "react-router-dom";
import type { DockerStackServiceStatus } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Status badge (reusable)
// ---------------------------------------------------------------------------

function getStatusStyle(status: string, t: ThemeTokens) {
  switch (status) {
    case "running":
      return { color: t.success, bg: t.successSubtle, border: t.successBorder, icon: CheckCircle2 };
    case "starting":
      return { color: t.accent, bg: t.accentSubtle, border: t.accentBorder, icon: Loader2 };
    case "stopped":
      return { color: t.textDim, bg: t.surfaceRaised, border: t.surfaceBorder, icon: Minus };
    case "error":
      return { color: t.danger, bg: t.dangerSubtle, border: t.dangerBorder, icon: XCircle };
    case "removing":
      return { color: t.warning, bg: t.warningSubtle, border: t.warningBorder, icon: Loader2 };
    default:
      return { color: t.textDim, bg: t.surfaceRaised, border: t.surfaceBorder, icon: AlertTriangle };
  }
}

function StatusBadge({ status, t }: { status: string; t: ThemeTokens }) {
  const style = getStatusStyle(status, t);
  const Icon = style.icon;
  return (
    <div
      className="flex flex-row items-center gap-1 rounded-full px-2.5 py-1"
      style={{ backgroundColor: style.bg, border: `1px solid ${style.border }`}}
    >
      <Icon size={14} color={style.color} />
      <span className="text-sm font-medium" style={{ color: style.color }}>
        {status}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

type Tab = "services" | "compose" | "logs";

function TabButton({
  label,
  icon: Icon,
  active,
  onClick,
  t,
}: {
  label: string;
  icon: React.ComponentType<{ size: number; color: string }>;
  active: boolean;
  onClick: () => void;
  t: ThemeTokens;
}) {
  return (
    <button type="button"
      onClick={onClick}
      className={`flex flex-row items-center gap-1.5 px-3 py-2 rounded-lg ${
        active ? "bg-accent/15" : "hover:bg-surface-overlay"
      }`}
    >
      <Icon size={14} color={active ? t.accent : t.textDim} />
      <span
        className="text-sm font-medium"
        style={{ color: active ? t.accent : t.textMuted }}
      >
        {label}
      </span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Services Tab
// ---------------------------------------------------------------------------

function ServicesTab({
  services,
  isLoading,
  t,
}: {
  services: DockerStackServiceStatus[] | undefined;
  isLoading: boolean;
  t: ThemeTokens;
}) {
  if (isLoading) {
    return (
      <div className="flex flex-col items-center py-8">
        <Spinner color={t.accent} />
      </div>
    );
  }
  if (!services || services.length === 0) {
    return (
      <div className="flex flex-col items-center py-8">
        <span className="text-sm" style={{ color: t.textDim }}>
          No services running
        </span>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      {services.map((svc) => {
        const stStyle = getStatusStyle(svc.state, t);
        return (
          <div
            key={svc.name}
            className="flex rounded-lg p-3 flex-row items-center justify-between"
            style={{
              backgroundColor: t.surfaceRaised,
              border: `1px solid ${t.surfaceBorder}`,
            }}
          >
            <div className="flex flex-row items-center gap-2">
              <Server size={14} color={t.accent} />
              <span className="text-sm font-medium" style={{ color: t.text }}>
                {svc.name}
              </span>
            </div>
            <div className="flex flex-row items-center gap-3">
              {svc.ports.length > 0 && (
                <span className="text-xs" style={{ color: t.textDim }}>
                  {svc.ports.map((p) => `${p.host_port}:${p.container_port}`).join(", ")}
                </span>
              )}
              {svc.health && (
                <span className="text-xs" style={{ color: t.textDim }}>
                  {svc.health}
                </span>
              )}
              <div
                className="rounded-full px-2 py-0.5"
                style={{ backgroundColor: stStyle.bg, border: `1px solid ${stStyle.border }`}}
              >
                <span className="text-xs font-medium" style={{ color: stStyle.color }}>
                  {svc.state}
                </span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Compose Tab
// ---------------------------------------------------------------------------

function ComposeTab({ definition, t }: { definition: string; t: ThemeTokens }) {
  return (
    <div
      className="rounded-lg p-4"
      style={{
        backgroundColor: t.surfaceRaised,
        border: `1px solid ${t.surfaceBorder}`,
      }}
    >
      <div className="overflow-x-auto">
        <span
          className="text-xs font-mono"
          style={{ color: t.text, whiteSpace: "pre" } as any}
        >
          {definition}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Logs Tab
// ---------------------------------------------------------------------------

function LogsTab({
  stackId,
  services,
  t,
}: {
  stackId: string;
  services: DockerStackServiceStatus[] | undefined;
  t: ThemeTokens;
}) {
  const [selectedService, setSelectedService] = useState<string | undefined>();
  const { data: logsData, isLoading } = useDockerStackLogs(stackId, selectedService);

  return (
    <div className="flex flex-col gap-3">
      {/* Service filter */}
      {services && services.length > 0 && (
        <div className="flex flex-row flex-wrap gap-1.5">
          <button type="button"
            onClick={() => setSelectedService(undefined)}
            className={`rounded-full px-3 py-1 ${!selectedService ? "bg-accent/15" : ""}`}
            style={{
              border: `1px solid ${!selectedService ? t.accentBorder : t.surfaceBorder}`,
            }}
          >
            <span
              className="text-xs font-medium"
              style={{ color: !selectedService ? t.accent : t.textMuted }}
            >
              All
            </span>
          </button>
          {services.map((svc) => (
            <button type="button"
              key={svc.name}
              onClick={() => setSelectedService(svc.name)}
              className={`rounded-full px-3 py-1 ${selectedService === svc.name ? "bg-accent/15" : ""}`}
              style={{
                border: `1px solid ${selectedService === svc.name ? t.accentBorder : t.surfaceBorder}`,
              }}
            >
              <span
                className="text-xs font-medium"
                style={{ color: selectedService === svc.name ? t.accent : t.textMuted }}
              >
                {svc.name}
              </span>
            </button>
          ))}
        </div>
      )}

      {/* Logs output */}
      <div
        className="rounded-lg p-3"
        style={{
          backgroundColor: t.surfaceRaised,
          border: `1px solid ${t.surfaceBorder}`,
          maxHeight: 500,
        }}
      >
        {isLoading ? (
          <Spinner color={t.accent} />
        ) : (
          <div className="overflow-auto">
            <span
              className="text-xs font-mono"
              style={{ color: t.text, whiteSpace: "pre-wrap" } as any}
                >
              {logsData?.logs || "No logs available"}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function DockerStackDetailPage() {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const { stackId } = useParams<{ stackId: string }>();
  const { data: stack, isLoading } = useDockerStack(stackId);
  const { data: services } = useDockerStackStatus(
    stackId,
    stack?.status === "running" || stack?.status === "starting"
  );
  const { refreshing, onRefresh } = usePageRefresh([["docker-stacks", stackId ?? ""]]);
  const startMutation = useStartDockerStack();
  const stopMutation = useStopDockerStack();
  const destroyMutation = useDestroyDockerStack();
  const { confirm, ConfirmDialogSlot } = useConfirm();
  const [activeTab, setActiveTab] = useState<Tab>("services");

  if (isLoading) {
    return (
      <div className="flex flex-1 bg-surface items-center justify-center">
        <Spinner color={t.accent} />
      </div>
    );
  }

  if (!stack) {
    return (
      <div className="flex flex-col flex-1 bg-surface items-center justify-center gap-2">
        <span className="text-base" style={{ color: t.textMuted }}>
          Stack not found
        </span>
        <button type="button" onClick={() => navigate(-1)}>
          <span className="text-sm" style={{ color: t.accent }}>
            Go back
          </span>
        </button>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="detail" title={stack.name} backTo="/admin/docker-stacks" />
      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        contentContainerStyle={{ padding: 16, paddingBottom: 80, gap: 16 }}
      >
        {/* Back + Title */}
        <div className="flex flex-row items-center gap-3">
          <button type="button" onClick={() => navigate("/admin/docker-stacks")} className="p-1">
            <ArrowLeft size={20} color={t.textMuted} />
          </button>
          <Boxes size={22} color={t.accent} />
          <span className="text-xl font-bold flex-1" style={{ color: t.text }}>
            {stack.name}
          </span>
          <StatusBadge status={stack.status} t={t} />
        </div>

        {/* Info bar */}
        <div
          className="flex flex-col rounded-lg p-4 gap-2"
          style={{
            backgroundColor: t.surfaceRaised,
            border: `1px solid ${t.surfaceBorder}`,
          }}
        >
          <div className="flex flex-row flex-wrap gap-4">
            {stack.source === "integration" ? (
              <div className="flex flex-row items-center gap-1.5">
                <div>
                  <span className="text-xs" style={{ color: t.textDim }}>Integration</span>
                  <div className="flex flex-row items-center gap-1">
                    <Plug size={12} color={t.accent} />
                    <span className="text-sm font-medium" style={{ color: t.text }}>
                      {stack.integration_id}
                    </span>
                  </div>
                </div>
              </div>
            ) : (
              <InfoItem label="Bot" value={stack.created_by_bot} t={t} />
            )}
            <InfoItem label="Project" value={stack.project_name} t={t} />
            {stack.network_name && <InfoItem label="Network" value={stack.network_name} t={t} />}
            {stack.last_started_at && (
              <InfoItem
                label="Last Started"
                value={new Date(stack.last_started_at).toLocaleString()}
                t={t}
              />
            )}
          </div>
          {stack.error_message && (
            <div className="rounded p-2 mt-1" style={{ backgroundColor: t.dangerSubtle }}>
              <span className="text-xs" style={{ color: t.danger }}>
                {stack.error_message}
              </span>
            </div>
          )}
          {stack.description && (
            <span className="text-sm" style={{ color: t.textMuted }}>
              {stack.description}
            </span>
          )}
        </div>

        {/* Actions */}
        <div className="flex flex-row gap-2">
          {(stack.status === "stopped" || stack.status === "error") && (
            <ActionButton
              label="Start"
              icon={Play}
              color={t.success}
              onClick={() => startMutation.mutate(stack.id)}
              loading={startMutation.isPending}
              t={t}
            />
          )}
          {stack.status === "running" && (
            <ActionButton
              label="Stop"
              icon={Square}
              color={t.warning}
              onClick={() => stopMutation.mutate(stack.id)}
              loading={stopMutation.isPending}
              t={t}
            />
          )}
          {stack.source !== "integration" && (stack.status === "stopped" || stack.status === "error") && (
            <ActionButton
              label="Destroy"
              icon={Trash2}
              color={t.danger}
              onClick={async () => {
                const ok = await confirm(
                  "This will permanently destroy the stack and all its data volumes. This cannot be undone.",
                  { title: "Destroy Stack?", confirmLabel: "Destroy", variant: "danger" },
                );
                if (ok) {
                  destroyMutation.mutate(stack.id, {
                    onSuccess: () => navigate("/admin/docker-stacks"),
                  });
                }
              }}
              loading={destroyMutation.isPending}
              t={t}
            />
          )}
        </div>

        {/* Tabs */}
        <div className="flex flex-row gap-1">
          <TabButton
            label="Services"
            icon={Server}
            active={activeTab === "services"}
            onClick={() => setActiveTab("services")}
            t={t}
          />
          <TabButton
            label="Compose"
            icon={FileCode}
            active={activeTab === "compose"}
            onClick={() => setActiveTab("compose")}
            t={t}
          />
          <TabButton
            label="Logs"
            icon={ScrollText}
            active={activeTab === "logs"}
            onClick={() => setActiveTab("logs")}
            t={t}
          />
        </div>

        {/* Tab content */}
        {activeTab === "services" && (
          <ServicesTab services={services} isLoading={false} t={t} />
        )}
        {activeTab === "compose" && (
          <ComposeTab definition={stack.compose_definition} t={t} />
        )}
        {activeTab === "logs" && (
          <LogsTab stackId={stack.id} services={services} t={t} />
        )}
      </RefreshableScrollView>
      <ConfirmDialogSlot />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared sub-components
// ---------------------------------------------------------------------------

function InfoItem({ label, value, t }: { label: string; value: string; t: ThemeTokens }) {
  return (
    <div>
      <span className="text-xs" style={{ color: t.textDim }}>
        {label}
      </span>
      <span className="text-sm font-medium" style={{ color: t.text }}>
        {value}
      </span>
    </div>
  );
}

function ActionButton({
  label,
  icon: Icon,
  color,
  onClick,
  loading,
  t,
}: {
  label: string;
  icon: React.ComponentType<{ size: number; color: string }>;
  color: string;
  onClick: () => void;
  loading?: boolean;
  t: ThemeTokens;
}) {
  return (
    <button type="button"
      onClick={onClick}
      disabled={loading}
      className="flex flex-row items-center gap-1.5 rounded-lg px-3 py-2 hover:opacity-80"
      style={{
        border: `1px solid ${color}`,
        opacity: loading ? 0.6 : 1,
      }}
    >
      {loading ? (
        <Spinner color={color} />
      ) : (
        <Icon size={14} color={color} />
      )}
      <span className="text-sm font-medium" style={{ color }}>
        {label}
      </span>
    </button>
  );
}
