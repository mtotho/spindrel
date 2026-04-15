/**
 * Docker Stacks list page — view all agent-managed Docker Compose stacks.
 */
import { useState, useMemo } from "react";
import { Spinner } from "@/src/components/shared/Spinner";
import { useNavigate } from "react-router-dom";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useDockerStacks, useStartDockerStack, useStopDockerStack, useDestroyDockerStack } from "@/src/api/hooks/useDockerStacks";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import {
  Boxes, Search, Play, Square, Trash2,
  CheckCircle2, XCircle, Loader2, AlertTriangle, Minus, Plug,
} from "lucide-react";
import type { DockerStack } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

function getStatusStyle(status: string, t: ThemeTokens) {
  switch (status) {
    case "running":
      return { color: t.success, bg: t.successSubtle, border: t.successBorder, icon: CheckCircle2, label: "running" };
    case "starting":
      return { color: t.accent, bg: t.accentSubtle, border: t.accentBorder, icon: Loader2, label: "starting" };
    case "stopped":
      return { color: t.textDim, bg: t.surfaceRaised, border: t.surfaceBorder, icon: Minus, label: "stopped" };
    case "error":
      return { color: t.danger, bg: t.dangerSubtle, border: t.dangerBorder, icon: XCircle, label: "error" };
    case "removing":
      return { color: t.warning, bg: t.warningSubtle, border: t.warningBorder, icon: Loader2, label: "removing" };
    default:
      return { color: t.textDim, bg: t.surfaceRaised, border: t.surfaceBorder, icon: AlertTriangle, label: status };
  }
}

function StatusBadge({ status, t }: { status: string; t: ThemeTokens }) {
  const style = getStatusStyle(status, t);
  const Icon = style.icon;
  return (
    <div
      className="flex-row items-center gap-1 rounded-full px-2 py-0.5"
      style={{ backgroundColor: style.bg, border: `1px solid ${style.border}` }}
    >
      <Icon size={12} color={style.color} />
      <span className="text-xs font-medium" style={{ color: style.color }}>
        {style.label}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stack Card
// ---------------------------------------------------------------------------

function StackCard({
  stack,
  t,
  onStart,
  onStop,
  onDestroy,
}: {
  stack: DockerStack;
  t: ThemeTokens;
  onStart: (id: string) => void;
  onStop: (id: string) => void;
  onDestroy: (id: string) => void;
}) {
  const navigate = useNavigate();
  const serviceCount = Object.keys(stack.container_ids || {}).length;
  const isIntegration = stack.source === "integration";

  return (
    <button
      type="button"
      onClick={() => navigate(`/admin/docker-stacks/${stack.id}`)}
      className="rounded-lg p-4 hover:bg-surface-overlay active:bg-surface-overlay"
      style={{
        backgroundColor: t.surfaceRaised,
        border: `1px solid ${t.surfaceBorder}`,
        textAlign: "left",
        width: "100%",
        cursor: "pointer",
      }}
    >
      <div className="flex-row items-start justify-between">
        <div className="flex-1 gap-1">
          <div className="flex-row items-center gap-2">
            <Boxes size={16} color={t.accent} />
            <span className="text-base font-semibold" style={{ color: t.text }}>
              {stack.name}
            </span>
            {isIntegration && (
              <div
                className="flex-row items-center gap-1 rounded-full px-2 py-0.5"
                style={{ backgroundColor: t.accentSubtle, border: `1px solid ${t.accentBorder}` }}
              >
                <Plug size={10} color={t.accent} />
                <span className="text-xs font-medium" style={{ color: t.accent }}>
                  Integration
                </span>
              </div>
            )}
          </div>
          {stack.description ? (
            <span className="text-sm" style={{ color: t.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "block" }}>
              {stack.description}
            </span>
          ) : null}
          <div className="flex-row items-center gap-3 mt-1">
            <span className="text-xs" style={{ color: t.textDim }}>
              {isIntegration ? `Integration: ${stack.integration_id}` : `Bot: ${stack.created_by_bot}`}
            </span>
            {serviceCount > 0 && (
              <span className="text-xs" style={{ color: t.textDim }}>
                {serviceCount} service{serviceCount !== 1 ? "s" : ""}
              </span>
            )}
            {stack.created_at && (
              <span className="text-xs" style={{ color: t.textDim }}>
                {new Date(stack.created_at).toLocaleDateString()}
              </span>
            )}
          </div>
        </div>
        <div className="items-end gap-2">
          <StatusBadge status={stack.status} t={t} />
          <div className="flex-row gap-1">
            {stack.status === "stopped" && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onStart(stack.id);
                }}
                className="rounded p-1.5 hover:bg-surface-overlay"
                style={{ border: `1px solid ${t.surfaceBorder}`, background: "none", cursor: "pointer" }}
              >
                <Play size={14} color={t.success} />
              </button>
            )}
            {stack.status === "running" && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onStop(stack.id);
                }}
                className="rounded p-1.5 hover:bg-surface-overlay"
                style={{ border: `1px solid ${t.surfaceBorder}`, background: "none", cursor: "pointer" }}
              >
                <Square size={14} color={t.warning} />
              </button>
            )}
            {!isIntegration && stack.status === "stopped" && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onDestroy(stack.id);
                }}
                className="rounded p-1.5 hover:bg-surface-overlay"
                style={{ border: `1px solid ${t.surfaceBorder}`, background: "none", cursor: "pointer" }}
              >
                <Trash2 size={14} color={t.danger} />
              </button>
            )}
          </div>
        </div>
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function DockerStacksPage() {
  const t = useThemeTokens();
  const { data: stacks, isLoading } = useDockerStacks();
  const { refreshing, onRefresh } = usePageRefresh([["docker-stacks"]]);
  const [search, setSearch] = useState("");
  const startMutation = useStartDockerStack();
  const stopMutation = useStopDockerStack();
  const destroyMutation = useDestroyDockerStack();
  const { confirm, ConfirmDialogSlot } = useConfirm();

  const filtered = useMemo(() => {
    if (!stacks) return [];
    if (!search) return stacks;
    const q = search.toLowerCase();
    return stacks.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        s.created_by_bot.toLowerCase().includes(q) ||
        s.status.toLowerCase().includes(q)
    );
  }, [stacks, search]);

  const running = filtered.filter((s) => s.status === "running");
  const stopped = filtered.filter((s) => s.status === "stopped");
  const other = filtered.filter((s) => !["running", "stopped"].includes(s.status));

  const handleStart = (id: string) => startMutation.mutate(id);
  const handleStop = (id: string) => stopMutation.mutate(id);
  const handleDestroy = async (id: string) => {
    const ok = await confirm(
      "This will permanently destroy the stack and all its data volumes. This cannot be undone.",
      { title: "Destroy Stack?", confirmLabel: "Destroy", variant: "danger" },
    );
    if (ok) destroyMutation.mutate(id);
  };

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list" title="Docker Stacks" />
      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        contentContainerStyle={{ padding: 16, paddingBottom: 80, gap: 16 }}
      >
        {/* Header */}
        <div className="flex-row items-center justify-between">
          <div className="flex-row items-center gap-2">
            <Boxes size={22} color={t.accent} />
            <span className="text-xl font-bold" style={{ color: t.text }}>
              Docker Stacks
            </span>
            {stacks && (
              <div
                className="rounded-full px-2 py-0.5"
                style={{ backgroundColor: t.accentSubtle }}
              >
                <span className="text-xs font-medium" style={{ color: t.accent }}>
                  {stacks.length}
                </span>
              </div>
            )}
          </div>
        </div>

        {/* Search */}
        <div
          className="flex-row items-center gap-2 rounded-lg px-3 py-2"
          style={{
            backgroundColor: t.surfaceRaised,
            border: `1px solid ${t.surfaceBorder}`,
          }}
        >
          <Search size={16} color={t.textDim} />
          <input
            type="text"
            placeholder="Search stacks..."
            value={search}
            onChange={(e: any) => setSearch(e.target.value)}
            style={{
              flex: 1,
              background: "transparent",
              border: "none",
              outline: "none",
              color: t.text,
              fontSize: 14,
            }}
          />
        </div>

        {isLoading ? (
          <div className="items-center py-12">
            <Spinner />
          </div>
        ) : filtered.length === 0 ? (
          <div className="items-center py-12 gap-2">
            <Boxes size={40} color={t.textDim} />
            <span className="text-base" style={{ color: t.textMuted }}>
              {search ? "No stacks match your search" : "No Docker stacks yet"}
            </span>
            <span className="text-sm" style={{ color: t.textDim }}>
              Bots with docker_stacks.enabled can create stacks via the manage_docker_stack tool.
            </span>
          </div>
        ) : (
          <>
            {running.length > 0 && (
              <Section title="Running" count={running.length} t={t}>
                {running.map((s) => (
                  <StackCard key={s.id} stack={s} t={t} onStart={handleStart} onStop={handleStop} onDestroy={handleDestroy} />
                ))}
              </Section>
            )}
            {other.length > 0 && (
              <Section title="Starting / Error / Removing" count={other.length} t={t}>
                {other.map((s) => (
                  <StackCard key={s.id} stack={s} t={t} onStart={handleStart} onStop={handleStop} onDestroy={handleDestroy} />
                ))}
              </Section>
            )}
            {stopped.length > 0 && (
              <Section title="Stopped" count={stopped.length} t={t}>
                {stopped.map((s) => (
                  <StackCard key={s.id} stack={s} t={t} onStart={handleStart} onStop={handleStop} onDestroy={handleDestroy} />
                ))}
              </Section>
            )}
          </>
        )}
      </RefreshableScrollView>
      <ConfirmDialogSlot />
    </div>
  );
}

function Section({
  title,
  count,
  t,
  children,
}: {
  title: string;
  count: number;
  t: ThemeTokens;
  children: React.ReactNode;
}) {
  return (
    <div className="gap-2">
      <div className="flex-row items-center gap-2">
        <span className="text-sm font-semibold" style={{ color: t.textMuted }}>
          {title}
        </span>
        <span className="text-xs" style={{ color: t.textDim }}>
          ({count})
        </span>
      </div>
      {children}
    </div>
  );
}
